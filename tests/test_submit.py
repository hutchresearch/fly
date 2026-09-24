import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("fly", os.path.join(HERE, "..", "fly.py"))
fly = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fly)


def run_main(*argv, on_head=True, returncode=0, side_effect=None, pool="cluster"):
    """Runs fly.main() with a fake condor_submit. Returns (status, calls, stdout, stderr)."""
    fake = mock.Mock(return_value=subprocess.CompletedProcess([], returncode, stderr=""))
    if side_effect:
        fake.side_effect = side_effect
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(sys, "argv", ["fly.py"] + list(argv)), \
         mock.patch.object(fly, "detect_pool", return_value=pool if on_head else None), \
         mock.patch.object(fly.subprocess, "run", fake), \
         redirect_stdout(out), redirect_stderr(err):
        try:
            status = fly.main()
        except SystemExit as e:
            status = e.code
    return status, [c.args[0] for c in fake.call_args_list], out.getvalue(), err.getvalue()


class SubmitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def condor_dir(self, name="jobs"):
        return os.path.join(self.tmp.name, name)

    def test_submits_with_argument_list(self):
        status, calls, _, _ = run_main("--command", "/bin/true", "--condor_dir", self.condor_dir())
        self.assertEqual(status, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "condor_submit")
        self.assertTrue(os.path.isabs(calls[0][1]) and calls[0][1].endswith("submit.job"), calls[0])

    def test_propagates_submit_failure(self):
        status, _, _, _ = run_main("--command", "/bin/true", "--condor_dir", self.condor_dir(), returncode=1)
        self.assertEqual(status, 1)

    def test_missing_condor_submit(self):
        status, _, _, err = run_main("--command", "/bin/true", "--condor_dir", self.condor_dir(),
                                     side_effect=FileNotFoundError)
        self.assertEqual(status, 1)
        self.assertIn("condor_submit not found", err)

    def test_interactive_flag_is_its_own_argument(self):
        _, calls, _, _ = run_main("--interactive", "--condor_dir", self.condor_dir())
        self.assertEqual(calls[0][:2], ["condor_submit", "-interactive"])
        self.assertTrue(calls[0][2].endswith("submit.job"))

    def test_condor_dir_with_spaces_and_metacharacters(self):
        weird = self.condor_dir("my jobs; `touch pwned` & 'x' \"y\"")
        status, calls, _, _ = run_main("--command", "/bin/true", "--condor_dir", weird)
        self.assertEqual(status, 0)
        self.assertTrue(calls[0][1].startswith(weird))
        self.assertTrue(os.path.exists(calls[0][1]))
        self.assertFalse(os.path.exists("pwned"))

    def test_condor_dir_with_macro_syntax_is_rejected(self):
        status, calls, out, _ = run_main("--command", "/bin/true", "--condor_dir", self.condor_dir("jobs$(Process)"))
        self.assertEqual(status, "EXITING: Invalid arguments")
        self.assertIn("cannot contain '$'", out)
        self.assertEqual(calls, [])

    def test_pretend_with_J_previews_one_submit_file(self):
        commands = os.path.join(self.tmp.name, "commands.txt")
        with open(commands, "w") as f:
            f.write("/bin/true\n/bin/false\n")
        status, calls, out, _ = run_main("--pretend", "--commands_fn", commands, "--J", "1")
        self.assertEqual((status, calls), (0, []))
        self.assertIn("max_materialize = 1", out)
        self.assertRegex(out, r"condor_submit -dry-run - \S+/submit\.job")
        self.assertNotIn("dag", out.lower())

    def test_refuses_to_submit_off_head_node(self):
        status, calls, _, _ = run_main("--command", "/bin/true", "--condor_dir", self.condor_dir(), on_head=False)
        self.assertIn("csci-head", str(status))
        self.assertIn("csci-lab-head", str(status))
        self.assertEqual(calls, [])

    def test_help_works_off_head_node(self):
        status, _, out, _ = run_main("--help", on_head=False)
        self.assertEqual(status, 0)
        self.assertIn("--pretend", out)

    def test_pretend_off_head_node_does_not_submit(self):
        status, calls, out, _ = run_main("--pretend", "--command", "/bin/true", on_head=False)
        self.assertEqual(status, 0)
        self.assertEqual(calls, [])
        self.assertIn("request_cpus = 2", out)
        self.assertIn("condor_submit -dry-run", out)


class LabPoolTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.condor_dir = os.path.join(tmp.name, "jobs")

    def submit_text(self, calls):
        with open(calls[0][-1]) as f:
            return f.read()

    def test_lab_jobs_ask_for_lab_machines(self):
        status, calls, _, _ = run_main("--command", "/bin/true", "--condor_dir", self.condor_dir, pool="lab")
        self.assertEqual(status, 0)
        text = self.submit_text(calls)
        self.assertIn('requirements = TARGET.PoolName == "CSCI Lab Cluster"\n', text)
        self.assertIn("+CSCI_GrpDesktop = True\n", text)
        self.assertIn("should_transfer_files = NO\n", text)

    def test_cluster_jobs_are_pinned_to_cluster(self):
        _, calls, _, _ = run_main("--command", "/bin/true", "--condor_dir", self.condor_dir,
                                  "--requirements", "HasScratchSSD")
        text = self.submit_text(calls)
        self.assertIn('requirements = TARGET.PoolName == "CSCI Cluster" && (HasScratchSSD)\n', text)
        self.assertNotIn("CSCI_GrpDesktop", text)

    def test_lab_gpu_sizes(self):
        status, _, _, _ = run_main("--command", "a", "--gpus", "1", "--gpu_mem", "24", "--condor_dir",
                                   self.condor_dir, pool="lab")
        self.assertEqual(status, 0)
        status, _, out, _ = run_main("--command", "a", "--gpus", "1", "--gpu_mem", "24", "--condor_dir",
                                     self.condor_dir, pool="cluster")
        self.assertEqual(status, "EXITING: Invalid arguments")
        self.assertIn("cluster pool", out)

    def test_auth_failure_hint_in_lab(self):
        fake = subprocess.CompletedProcess([], 1, stderr="ERROR: AUTHENTICATE:1003:Failed to authenticate\n")
        with mock.patch.object(fly.subprocess, "run", return_value=fake), redirect_stderr(io.StringIO()) as err:
            status = fly.submit(["condor_submit", "x.job"], "lab")
        self.assertEqual(status, 1)
        self.assertIn("condor_token_fetch", err.getvalue())
        self.assertIn("AUTHENTICATE", err.getvalue())

    def test_pool_flag_only_for_pretend(self):
        status, _, out, _ = run_main("--command", "a", "--pool", "lab", "--condor_dir", self.condor_dir)
        self.assertEqual(status, "EXITING: Invalid arguments")
        status, calls, out, _ = run_main("--pretend", "--command", "a", "--pool", "lab", on_head=False)
        self.assertEqual((status, calls), (0, []))
        self.assertIn("CSCI_GrpDesktop", out)
        self.assertIn("on csci-lab-head.cs.wwu.edu run", out)


class DetectPoolTest(unittest.TestCase):
    def detect(self, config):
        def fake_run(cmd, **kwargs):
            value = config.get(cmd[1])
            return subprocess.CompletedProcess(cmd, 0 if value is not None else 1, stdout=(value or "") + "\n")
        with mock.patch.object(fly.subprocess, "run", side_effect=fake_run):
            return fly.detect_pool()

    def test_known_pools(self):
        self.assertEqual(self.detect({"COLLECTOR_HOST": "csci-head.cluster.cs.wwu.edu"}), "cluster")
        self.assertEqual(self.detect({"COLLECTOR_HOST": "csci-lab-head.cs.wwu.edu",
                                      "SCHEDD_HOST": "csci-lab-head.cs.wwu.edu"}), "lab")
        self.assertEqual(self.detect({"COLLECTOR_HOST": "CSCI-LAB-HEAD.cs.wwu.edu:9618"}), "lab")

    def test_unknown_or_ambiguous(self):
        self.assertIsNone(self.detect({"COLLECTOR_HOST": "cse-head.cluster.cs.wwu.edu"}))
        self.assertIsNone(self.detect({}))
        self.assertIsNone(self.detect({"COLLECTOR_HOST": "csci-head.cluster.cs.wwu.edu, csci-lab-head.cs.wwu.edu"}))
        self.assertIsNone(self.detect({"COLLECTOR_HOST": "csci-lab-head.cs.wwu.edu",
                                       "SCHEDD_HOST": "csci-head.cluster.cs.wwu.edu"}))

    def test_htcondor_not_installed(self):
        with mock.patch.object(fly.subprocess, "run", side_effect=FileNotFoundError):
            self.assertIsNone(fly.detect_pool())


if __name__ == "__main__":
    unittest.main()
