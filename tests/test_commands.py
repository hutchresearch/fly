import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("fly", os.path.join(HERE, "..", "fly.py"))
fly = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fly)

# A stand-in "python" that prints the argv it receives, one repr per line.
FAKE_PYTHON = "#!/usr/bin/env python3\nimport sys\nprint(sys.argv[1:])\n"


def parse(*argv):
    with mock.patch.object(sys, "argv", ["fly.py"] + list(argv)):
        return fly.parse_all_args()


def validate(*argv, on_head=True):
    out = io.StringIO()
    with mock.patch.object(fly, "on_cluster_head", return_value=on_head), redirect_stdout(out):
        valid = fly.valid_args(parse(*argv))
    return valid, out.getvalue()


class Workspace(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.bin = os.path.join(self.tmp, "bin")
        os.mkdir(self.bin)
        self.write(os.path.join(self.bin, "python"), FAKE_PYTHON, mode=0o755)
        self.cwd = os.path.join(self.tmp, "cwd")
        os.mkdir(self.cwd)

    def write(self, path, text, mode=None):
        with open(path, "w") as f:
            f.write(text)
        if mode:
            os.chmod(path, mode)
        return path

    def generate(self, *argv, commands_text=None):
        if commands_text is not None:
            fn = self.write(os.path.join(self.tmp, "commands.txt"), commands_text)
            argv = argv + ("--commands_fn", fn)
        args = parse(*argv)
        job_dir = tempfile.mkdtemp(dir=self.tmp)
        submit_fn = fly.make_job_files(job_dir, args, fly.read_commands(args))
        with open(submit_fn) as f:
            return job_dir, f.read()

    def run_jobs(self, job_dir, submit_text):
        """Runs every job the way condor would: the wrapper with the submit file's
        arguments, once per queued process, in the submit directory."""
        arguments = re.search(r"^arguments = (.*)$", submit_text, re.M).group(1)
        count = int(re.search(r"^queue (\d+)$", submit_text, re.M).group(1))
        env = dict(os.environ, PATH=self.bin + os.pathsep + os.environ["PATH"], HOME="/home/student")
        results = []
        for process in range(count):
            arg = arguments.replace("$(Process)", str(process))
            results.append(subprocess.run([os.path.join(job_dir, "wrapper.sh"), arg], cwd=self.cwd, env=env,
                                          capture_output=True, text=True))
        return results


class CommandSemanticsTest(Workspace):
    """The #26 behavior table: commands run exactly as typed at a bash prompt."""

    def run_command(self, command):
        job_dir, submit = self.generate("--command", command)
        (result,) = self.run_jobs(job_dir, submit)
        return result

    def argv(self, command):
        result = self.run_command(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        return [eval(line) for line in result.stdout.splitlines()]

    def test_redirect(self):
        self.argv("python train.py --lr 0.1 > log.txt")
        with open(os.path.join(self.cwd, "log.txt")) as f:
            self.assertEqual(f.read(), "['train.py', '--lr', '0.1']\n")

    def test_quotes(self):
        self.assertEqual(self.argv('python train.py --name "my run"'), [["train.py", "--name", "my run"]])
        self.assertEqual(self.argv("python train.py --name 'my run'"), [["train.py", "--name", "my run"]])
        self.assertEqual(self.argv("python t.py --q 'it'\"'\"'s'"), [["t.py", "--q", "it's"]])

    def test_expansions(self):
        self.assertEqual(self.argv("python t.py --out $HOME/results"), [["t.py", "--out", "/home/student/results"]])
        self.assertEqual(self.argv("python t.py --x $(echo 2026)"), [["t.py", "--x", "2026"]])

    def test_condor_macros_are_not_expanded(self):
        self.assertEqual(self.argv("python t.py --tag '$(Process)'"), [["t.py", "--tag", "$(Process)"]])

    def test_and_and_multiple_commands(self):
        self.assertEqual(self.argv("python prep.py && python train.py"), [["prep.py"], ["train.py"]])

    def test_glob_expands_in_working_directory(self):
        for name in ("a.csv", "b.csv"):
            self.write(os.path.join(self.cwd, name), "")
        self.assertEqual(self.argv("python t.py --glob *.csv"), [["t.py", "--glob", "a.csv", "b.csv"]])

    def test_escaped_and_unescaped_pipe(self):
        self.assertEqual(self.argv("python t.py --regex a\\|b"), [["t.py", "--regex", "a|b"]])
        result = self.run_command("python t.py --regex a|b")
        self.assertIn("b: command not found", result.stderr)

    def test_backslashes_preserved(self):
        self.assertEqual(self.argv("python t.py 'C:\\new\\table'"), [["t.py", "C:\\new\\table"]])

    def test_exit_status_propagates(self):
        self.assertEqual(self.run_command("exit 3").returncode, 3)


class BatchTest(Workspace):
    def test_commands_file_one_job_per_line(self):
        job_dir, submit = self.generate(
            commands_text="# comment\npython a.py 1\n\n   \npython a.py 'two words'\r\n  # indented comment\npython a.py 3")
        self.assertIn("arguments = $(Process)", submit)
        self.assertIn("queue 3", submit)
        outputs = [r.stdout for r in self.run_jobs(job_dir, submit)]
        self.assertEqual(outputs, ["['a.py', '1']\n", "['a.py', 'two words']\n", "['a.py', '3']\n"])

    def test_command_text_written_verbatim(self):
        job_dir, _ = self.generate(commands_text="python a.py  --x 'y  z' \\\\ \n")
        with open(os.path.join(job_dir, "cmd", "0.sh")) as f:
            self.assertEqual(f.read(), "python a.py  --x 'y  z' \\\\ \n")

    def test_queue_count_repeats_command_zero(self):
        job_dir, submit = self.generate("--command", "python a.py", "--queue_count", "5")
        self.assertIn("arguments = 0", submit)
        self.assertIn("queue 5", submit)
        self.assertEqual(os.listdir(os.path.join(job_dir, "cmd")), ["0.sh"])
        results = self.run_jobs(job_dir, submit)
        self.assertEqual([r.stdout for r in results], ["['a.py']\n"] * 5)

    def test_max_materialize(self):
        _, submit = self.generate("--J", "2", commands_text="python a.py\npython b.py\n")
        self.assertIn("max_materialize = 2", submit)
        self.assertNotIn("dag", submit.lower())
        _, submit = self.generate("--command", "python a.py", "--queue_count", "4", "--J", "1")
        self.assertIn("max_materialize = 1", submit)

    def test_submit_file_settings(self):
        job_dir, submit = self.generate("--command", "python a.py")
        for line in ("universe = vanilla", "should_transfer_files = NO",
                     "executable = " + os.path.join(job_dir, "wrapper.sh"),
                     "output = " + os.path.join(job_dir, "$(Process).out"),
                     "log    = " + os.path.join(job_dir, "condor.log")):
            self.assertIn(line + "\n", submit)
        self.assertNotIn("python a.py", submit)

    def test_interactive(self):
        _, submit = self.generate("--interactive")
        self.assertTrue(submit.endswith("queue\n"))
        self.assertNotIn("arguments", submit)


class EnvironmentTest(Workspace):
    def make_venv(self, activate_text):
        venv = os.path.join(self.tmp, "my venv")
        os.makedirs(os.path.join(venv, "bin"))
        self.write(os.path.join(venv, "bin", "activate"), activate_text)
        return venv

    def test_venv_activated_before_command(self):
        venv = self.make_venv("export FLY_TEST_ENV=on\n")
        job_dir, submit = self.generate("--venv", venv, "--command", "echo $FLY_TEST_ENV")
        (result,) = self.run_jobs(job_dir, submit)
        self.assertEqual(result.stdout, "on\n")

    def test_failed_activation_stops_the_job(self):
        venv = self.make_venv("return 1\n")
        job_dir, submit = self.generate("--venv", venv, "--command", "echo SHOULD-NOT-RUN")
        (result,) = self.run_jobs(job_dir, submit)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("SHOULD-NOT-RUN", result.stdout)
        self.assertIn("fly: could not activate venv", result.stderr)

    def test_conda(self):
        conda = os.path.join(self.tmp, "conda's dir")
        os.makedirs(os.path.join(conda, "etc", "profile.d"))
        self.write(os.path.join(conda, "etc", "profile.d", "conda.sh"),
                   'conda() { [ "$2" = "good env" ] && export ACTIVE="$2"; }\n')
        job_dir, submit = self.generate("--conda", conda, "--conda_name", "good env", "--command", "echo $ACTIVE")
        (result,) = self.run_jobs(job_dir, submit)
        self.assertEqual(result.stdout, "good env\n")
        job_dir, submit = self.generate("--conda", conda, "--conda_name", "bad", "--command", "echo RAN")
        (result,) = self.run_jobs(job_dir, submit)
        self.assertEqual((result.returncode, result.stdout), (1, ""))
        self.assertIn("could not activate conda env bad", result.stderr)


class ValidationTest(Workspace):
    def commands_file(self, text):
        return self.write(tempfile.mktemp(dir=self.tmp, suffix=".txt"), text)

    def test_valid(self):
        self.assertTrue(validate("--command", "python a.py")[0])
        self.assertTrue(validate("--commands_fn", self.commands_file("a\nb\n"), "--J", "1")[0])
        self.assertTrue(validate("--command", "a", "--queue_count", "3", "--J", "2")[0])

    def test_invalid(self):
        cases = [
            (("--command", "   "), "--command is empty"),
            (("--commands_fn", self.tmp), "Unable to find"),
            (("--commands_fn", self.commands_file("# only\n\n")), "No commands"),
            (("--command", "a", "--J", "1"), "--J limits"),
            (("--interactive", "--J", "2"), "--J limits"),
            (("--interactive", "--queue_count", "2"), "--queue_count only works with --command"),
            (("--commands_fn", self.commands_file("a\n"), "--queue_count", "2"), "--queue_count only works"),
            (("--command", "a", "--conda_name", "x"), "--conda_name requires --conda"),
            (("--command", "a", "--venv", self.tmp), "activation script not found"),
        ]
        for argv, message in cases:
            valid, out = validate(*argv)
            self.assertFalse(valid, argv)
            self.assertIn(message, out, argv)

    def test_env_paths_only_warn_off_head_node(self):
        valid, out = validate("--command", "a", "--venv", "/cluster/home/x/venv", on_head=False)
        self.assertTrue(valid)
        self.assertIn("Warning", out)


if __name__ == "__main__":
    unittest.main()
