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


def run_main(*argv, on_head=True, returncode=0, side_effect=None):
    """Runs fly.main() with a fake condor_submit. Returns (status, calls, stdout, stderr)."""
    fake = mock.Mock(return_value=subprocess.CompletedProcess([], returncode))
    if side_effect:
        fake.side_effect = side_effect
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(sys, "argv", ["fly.py"] + list(argv)), \
         mock.patch.object(fly, "on_cluster_head", return_value=on_head), \
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
        self.assertTrue(os.path.isabs(calls[0][1]) and calls[0][1].endswith("0.job"), calls[0])

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
        self.assertTrue(calls[0][2].endswith("0.job"))

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

    def test_pretend_dag_suggests_dag_check(self):
        commands = os.path.join(self.tmp.name, "commands.txt")
        with open(commands, "w") as f:
            f.write("/bin/true\n/bin/false\n")
        status, calls, out, _ = run_main("--pretend", "--commands_fn", commands, "--J", "1")
        self.assertEqual((status, calls), (0, []))
        self.assertIn("condor_submit_dag -no_submit", out)
        self.assertNotIn("condor_submit -dry-run", out)

    def test_refuses_to_submit_off_head_node(self):
        status, calls, _, _ = run_main("--command", "/bin/true", "--condor_dir", self.condor_dir(), on_head=False)
        self.assertIn("csci-head", str(status))
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


if __name__ == "__main__":
    unittest.main()
