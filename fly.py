#! /usr/bin/env python3
"""
Authors:
    - Ryan Lingg
    - Brian Hutchinson
"""

import argparse
from datetime import datetime
import getpass
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile

CLUSTER_HEAD = "csci-head.cluster.cs.wwu.edu"
LAB_HEAD = "csci-lab-head.cs.wwu.edu"
# fly submits to the pool of the machine it runs on, identified by the
# central manager (COLLECTOR_HOST) in its HTCondor configuration.
SUBMIT_POOLS = {CLUSTER_HEAD: "cluster", LAB_HEAD: "lab"}
POOL_HEADS = {"cluster": CLUSTER_HEAD, "lab": LAB_HEAD}
# PoolName advertised by each pool's machines. The pools flock to each
# other, so jobs are pinned to the pool they were submitted to.
POOL_NAMES = {"cluster": "CSCI Cluster", "lab": "CSCI Lab Cluster"}

# Nominal GPU memory sizes (GB) of the cards in the CSCI pools. A --gpu_mem
# request snaps up to the smallest of these, and each size is matched as
# at least size * GPU_MIB_PER_NOMINAL_GB MiB, because cards advertise a bit
# less than their nominal size (an "11 GB" RTX 2080 Ti advertises 10835 MiB).
GPU_MEM_TIERS = (4, 6, 8, 11, 12, 16, 24, 80)
GPU_MIB_PER_NOMINAL_GB = 950
# Larger cards are reserved for jobs that need them: a job may only use cards
# below the next reserved size above its request.
RESERVED_GPU_TIERS = (16, 24, 80)
# Nominal GPU sizes fly can schedule onto in each pool (the cluster's H100s
# require preemption opt-in and are not available through fly).
POOL_GPU_TIERS = {"cluster": (11,), "lab": (4, 6, 8, 11, 12, 16, 24)}


def main():
    """ Main Function:
            Performs the heavy lifting for the submission of jobs to condor.
    """
    # Parse args
    args = parse_all_args()
    detected = detect_pool()

    # Confirm proper run location (previews work anywhere)
    if not args.pretend and detected is None:
        sys.exit("EXITING: Jobs must be submitted from %s (cluster) or from %s or a CS lab machine (lab)"
                 % (CLUSTER_HEAD, LAB_HEAD))
    pool = args.pool or detected or "cluster"
    if not valid_args(args, pool, detected is not None):
        sys.exit("EXITING: Invalid arguments")

    # Create and launch the job(s)
    if args.pretend:
        job_dir = tempfile.mkdtemp(prefix="fly_pretend_")
    else:
        job_dir = make_job_dir(args.condor_dir)

    submit_fn = make_job_files(job_dir, args, read_commands(args), pool)
    if args.interactive:
        if args.venv or args.conda:
            print("Note: interactive jobs start a plain shell, so fly's environment setup does not run. "
                  "Activate it yourself once the shell starts.", file=sys.stderr)
        if pool == "lab":
            print("Note: lab machines suspend jobs while someone is using them, and end the session "
                  "if that lasts 10 minutes.", file=sys.stderr)
        cmd = ["condor_submit", "-interactive", submit_fn]
    else:
        cmd = ["condor_submit", submit_fn]

    if args.pretend:
        show_pretend(job_dir, cmd, pool)
        return 0
    return submit(cmd, pool)


def submit(cmd, pool):
    """ Runs a condor submit command, passing its output through.

        Returns:
            int: the command's exit status
    """
    interactive = "-interactive" in cmd
    try:
        # Interactive sessions keep the terminal; otherwise watch stderr for
        # authentication failures to give lab users the fix.
        result = subprocess.run(cmd, stderr=None if interactive else subprocess.PIPE, universal_newlines=True)
    except FileNotFoundError:
        print("EXITING: %s not found. Is HTCondor installed here?" % cmd[0], file=sys.stderr)
        return 1
    if not interactive:
        sys.stderr.write(result.stderr)
        if result.returncode != 0 and pool == "lab" and re.search("authenticat", result.stderr, re.I):
            print("\nIf you are on a lab machine, you may need a token for %s. Fetch one with:\n"
                  "  ssh -p 922 %s condor_token_fetch -token csci-lab-head" % (LAB_HEAD, LAB_HEAD),
                  file=sys.stderr)
    return result.returncode


def show_pretend(job_dir, cmd, pool, max_commands=5):
    """ Prints the generated files instead of submitting them. """
    paths = [os.path.join(job_dir, name) for name in sorted(os.listdir(job_dir))]
    cmd_dir = os.path.join(job_dir, "cmd")
    commands = sorted(os.listdir(cmd_dir), key=lambda n: int(n.split(".")[0])) if os.path.isdir(cmd_dir) else []
    paths = [p for p in paths if p != cmd_dir] + [os.path.join(cmd_dir, n) for n in commands[:max_commands]]
    for path in paths:
        print("# ==========\n# %s\n# ==========" % path)
        with open(path) as f:
            print(f.read())
    if len(commands) > max_commands:
        print("# ... and %d more command files in %s\n" % (len(commands) - max_commands, cmd_dir))
    print("# Not submitted. fly would run:\n#   %s" % " ".join(shlex.quote(c) for c in cmd))
    print("# To check the files with HTCondor's own parser, on %s run:" % POOL_HEADS[pool])
    print("#   condor_submit -dry-run - %s" % shlex.quote(cmd[-1]))


def condor_config(name):
    """ Returns an HTCondor configuration value, or None if it's undefined or
        HTCondor isn't installed.
    """
    try:
        result = subprocess.run(["condor_config_val", name], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, universal_newlines=True)
    except FileNotFoundError:
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def detect_pool():
    """ Works out which pool this machine submits to from its HTCondor
        configuration: its central manager, and its schedd if configured.

        Returns:
            str or None: "cluster", "lab", or None if this isn't a known
            submit machine (or the configuration is ambiguous)
    """
    def pool_of(hosts):
        names = {host.split(":")[0].lower() for host in re.split(r"[\s,]+", hosts) if host}
        pools = {SUBMIT_POOLS.get(name) for name in names}
        return pools.pop() if len(pools) == 1 else None

    collector = condor_config("COLLECTOR_HOST")
    if collector is None:
        return None
    pool = pool_of(collector)
    schedd = condor_config("SCHEDD_HOST")
    if schedd is not None and pool_of(schedd) != pool:
        return None
    return pool


def make_job_dir(condor_dir):
    """ Creates the .condor_jobs/job_dir folder

        Returns:
            job_dir: Path to the new dir to hold the generated files
    """
    job_dir = None
    while True:
        job_name = getpass.getuser() + "_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        job_dir  = os.path.join(os.path.abspath(condor_dir), job_name)
        if not os.path.exists(job_dir):
            break

    if not os.path.isdir(job_dir):
        os.makedirs(job_dir)

    return job_dir


def read_commands(args):
    """ Returns the commands to run, one per job. A commands file holds one
        command per line; blank lines and lines starting with # are skipped.

        Returns:
            list of str: the commands (empty for an interactive job)
    """
    if args.command is not None:
        return [args.command]
    if args.commands_fn is not None:
        with open(args.commands_fn) as commands_file:
            lines = commands_file.read().splitlines()
        return [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
    return []


def write_wrapper(job_dir, args):
    """ Writes the script condor runs for each job: it sets up the
        environment, stopping if that fails, then runs command file $1 with
        bash, so commands behave exactly as they would typed at a bash prompt.

        Returns:
            str: path to the wrapper script
    """
    def fail(message):
        return " || fail " + shlex.quote(message)

    lines = ["#!/usr/bin/env bash",
             "# Generated by fly: sets up the environment, then runs command file $1.",
             'fail() { echo "fly: $*" >&2; exit 1; }']
    if args.venv is not None:
        activate = os.path.join(os.path.abspath(args.venv), "bin", "activate")
        lines.append("source " + shlex.quote(activate) + fail("could not activate venv " + args.venv))
    elif args.conda is not None:
        conda_sh = os.path.join(os.path.abspath(args.conda), "etc", "profile.d", "conda.sh")
        lines.append("source " + shlex.quote(conda_sh) + fail("could not set up conda from " + args.conda))
        env = args.conda_name if args.conda_name is not None else "base"
        lines.append("conda activate " + shlex.quote(env) + fail("could not activate conda env " + env))
    lines.append("exec bash " + shlex.quote(os.path.join(job_dir, "cmd")) + '/"$1".sh')

    wrapper_fn = os.path.join(job_dir, "wrapper.sh")
    fd = os.open(wrapper_fn, flags=os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode=stat.S_IRWXU)
    with os.fdopen(fd, "w") as wrapper:
        wrapper.write("\n".join(lines) + "\n")
    return wrapper_fn


def make_job_files(job_dir, args, commands, pool="cluster"):
    """ Creates the condor submit file, the wrapper script, and one command
        file per job (cmd/0.sh, cmd/1.sh, ...). Command text is written
        verbatim and never passes through condor's own parser.

        Returns:
            str: path to the submit file
    """
    if commands:
        os.mkdir(os.path.join(job_dir, "cmd"))
    for i, command in enumerate(commands):
        with open(os.path.join(job_dir, "cmd", "%d.sh" % i), "w") as command_file:
            command_file.write(command + "\n")

    lines = []
    if args.name is not None:
        lines.append("batch_name = \"" + args.name.strip() + "\"")
    lines += ["universe = vanilla",
              "request_cpus = " + str(args.cores),
              "request_memory = " + str(args.mem) + " GB",
              "request_gpus = " + str(args.gpus)]
    if args.low_prio:
        lines.append("priority = -10")
    if args.gpus > 0:
        lines.append("require_gpus = " + gpu_constraint(args.gpu_mem))
    requirements = "TARGET.PoolName == \"%s\"" % POOL_NAMES[pool]
    if args.requirements:
        requirements += " && (" + args.requirements + ")"
    lines.append("requirements = " + requirements)
    if args.rank:
        lines.append("rank = " + args.rank)
    if pool == "lab":
        # Lab machines only accept jobs that ask for them.
        lines.append("+CSCI_GrpDesktop = True")
    # Jobs read and write the pool's shared filesystem directly.
    lines.append("should_transfer_files = NO")
    lines += ["executable = " + write_wrapper(job_dir, args),
              "output = " + os.path.join(job_dir, "$(Process).out"),
              "error  = " + os.path.join(job_dir, "$(Process).err"),
              "log    = " + os.path.join(job_dir, "condor.log")]
    if args.J > 0:
        lines.append("max_materialize = " + str(args.J))
    if len(commands) > 1:
        # One job per command file.
        lines += ["arguments = $(Process)", "queue " + str(len(commands))]
    elif commands:
        # Every repeat runs command file 0.
        lines += ["arguments = 0", "queue " + str(args.queue_count)]
    else:
        lines.append("queue")

    submit_fn = os.path.join(job_dir, "submit.job")
    with open(submit_fn, "w") as submit_file:
        submit_file.write("\n".join(lines) + "\n")
    return submit_fn


def gpu_tier(gpu_mem):
    """ Snaps a --gpu_mem request (GB) up to a nominal GPU size.

        Returns:
            int or None: the nominal size, 0 for no request, or None if the
            request is larger than any known card.
    """
    if gpu_mem == 0:
        return 0
    for tier in GPU_MEM_TIERS:
        if tier >= gpu_mem:
            return tier
    return None


def gpu_band(gpu_mem):
    """ Returns the (lowest, next reserved) nominal sizes a request may use.
        The upper bound is exclusive and None when unbounded.
    """
    tier = gpu_tier(gpu_mem)
    upper = next((t for t in RESERVED_GPU_TIERS if t > tier), None)
    return tier, upper


def gpu_request_fits(gpu_mem, pool):
    """ Checks that some card fly can use in the pool falls within the request's band. """
    if gpu_tier(gpu_mem) is None:
        return False
    lower, upper = gpu_band(gpu_mem)
    return any(lower <= t and (upper is None or t < upper) for t in POOL_GPU_TIERS[pool])


def gpu_constraint(gpu_mem):
    """ Builds the per-GPU require_gpus expression for a --gpu_mem request. """
    lower, upper = gpu_band(gpu_mem)
    clauses = []
    if lower:
        clauses.append("GlobalMemoryMb >= %d" % (lower * GPU_MIB_PER_NOMINAL_GB))
    if upper is not None:
        clauses.append("GlobalMemoryMb < %d" % (upper * GPU_MIB_PER_NOMINAL_GB))
    return " && ".join(clauses)


def parse_all_args():
    """ Parses all arguments.

        Returns:
            argparse.Namespace: the parsed argument object
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--pretend",
                        action="store_true",
                        help="Print the generated condor files instead of submitting them. "
                             "Works on any machine. (flag)")
    parser.add_argument("--pool",
                        choices=("cluster", "lab"),
                        help="With --pretend on a machine outside both pools, which pool to preview for "
                             "[default: cluster]")

    # Executable Settings
    command = parser.add_mutually_exclusive_group(required=True)
    command.add_argument("--command",
                        type=str,
                        help="The command to run, exactly as you would type it at a bash prompt (str)")
    command.add_argument("--commands_fn",
                        type=str,
                        help="A file of commands, one per line, each run as its own job. Blank lines and lines "
                             "starting with # are skipped. (str)")
    command.add_argument("--interactive", "-i",
                        action="store_true",
                        help="Request job to run an interactive shell job (flag)")

    # Environment
    run_env = parser.add_mutually_exclusive_group(required=False)
    run_env.add_argument("--venv",
                         help="The path to the virtual environment to be used (str)",
                         type=str)
    run_env.add_argument("--conda",
                         help="The path to the conda installation to be used (str)",
                         type=str)
    parser.add_argument("--conda_name",
                        help="If using conda, the name of the conda environment to activate (str) [default: base]",
                        type=str)

    # Job Priority
    parser.add_argument("--low_prio",
                        action='store_true',
                        help="Jobs will be run after normal priority jobs")

    # Condor Settings
    parser.add_argument("--name",
                        type=str,
                        help="A name for the condor job. (str)")
    parser.add_argument("--J",
                        type=int,
                        help="Maximum number of jobs from this batch in the queue at once; the rest are added as "
                             "earlier ones finish (int) [default: 0 --> unlimited]",
                        default=0)
    parser.add_argument("--cores",
                        type=int,
                        help="The number of CPU cores to allocate. (int) [default: 2]",
                        default=2)
    parser.add_argument("--mem",
                        type=int,
                        help="The amount of main memory to allocate, in GB. (int) [default: 8]",
                        default=8)
    parser.add_argument("--gpus",
                        type=int,
                        help="The number of GPUs needed. (int) [default: 0]",
                        default=0)
    parser.add_argument("--gpu_mem",
                        type=int,
                        help="Nominal GPU memory needed, in GB, as printed on the card (e.g. 11 for an "
                             "RTX 2080 Ti). Rounded up to the next card size; larger cards are reserved "
                             "for jobs that need them. (int) [default: 0 --> smallest cards]",
                        default=0)
    parser.add_argument("--requirements",
                        type=str,
                        help="Condor requirements expression. (str)",
                        default="")
    parser.add_argument("--rank",
                        type=str,
                        help="Condor rank expression. (str)",
                        default="")
    parser.add_argument("--queue_count",
                        type=int,
                        help="The number of times to run --command, each as its own job (int) [default: 1]",
                        default=1)
    parser.add_argument("--condor_dir",
                        type=str,
                        help="Directory to store condor job and log files. [default: .condor_jobs]",
                        default=".condor_jobs")

    return parser.parse_args()


def valid_args(args, pool="cluster", on_submit_host=True):
    """ Checks if the arguments provided will allow for a successful job dispatching.

    Returns:
        boolean: True if all args were assigned valid values, else false.
    """
    is_valid = True
    # Paths are only checked where the job will run (previews work anywhere).
    check_paths = on_submit_host
    if args.pool is not None and not args.pretend:
        print("\tError: --pool only works with --pretend; fly submits to the pool of the machine it runs on")
        is_valid = False
    # Condor expands $(...) macros in submit-file paths
    if "$" in os.path.abspath(args.condor_dir):
        print("\tError: --condor_dir cannot contain '$' (condor would treat it as a macro):", args.condor_dir)
        is_valid = False

    # Commands Options
    if args.command is not None and not args.command.strip():
        print("\tError: --command is empty")
        is_valid = False
    if args.commands_fn is not None:
        if not os.path.isfile(args.commands_fn):
            print("\tError: Unable to find the specified command file:", args.commands_fn)
            is_valid = False
        elif not read_commands(args):
            print("\tError: No commands in", args.commands_fn, "(blank lines and # comments are skipped)")
            is_valid = False
    if args.queue_count < 1:
        print("\tError: Invalid QUEUE_COUNT. You cannot schedule a job to run less than once.")
        is_valid = False
    if args.queue_count > 1 and args.command is None:
        print("\tError: --queue_count only works with --command")
        is_valid = False
    if args.J > 0 and (args.interactive or (args.command is not None and args.queue_count == 1)):
        print("\tError: --J limits how many jobs run at once, so it needs --commands_fn or --queue_count > 1")
        is_valid = False

    # Virtual Environment
    if args.conda_name is not None and args.conda is None:
        print("\tError: --conda_name requires --conda")
        is_valid = False
    env_files = []
    if args.venv is not None:
        env_files.append(os.path.join(args.venv, "bin", "activate"))
    if args.conda is not None:
        env_files.append(os.path.join(args.conda, "etc", "profile.d", "conda.sh"))
    for env_file in env_files:
        if not os.path.isfile(env_file):
            if check_paths:
                print("\tError: Environment activation script not found:", env_file)
                is_valid = False
            else:
                print("\tWarning: Environment activation script not found here (fine if it exists on the cluster):",
                      env_file)

    # System Requirements
    if args.cores < 1:
        print("\tError: Invalid number of cores specified:", args.cores)
        is_valid = False
    if args.mem <= 0:
        print("\tError: Invalid amount of RAM specified:", args.mem)
        is_valid = False
    if args.gpus < 0:
        print("\tError: Invalid number of GPUs specified:", args.gpus)
        is_valid = False
    if args.gpu_mem < 0:
        print("\tError: Invalid amount of GPU memory specified:", args.gpu_mem)
        is_valid = False
    elif args.gpu_mem > 0 and args.gpus == 0:
        print("\tError: --gpu_mem requires --gpus")
        is_valid = False
    elif args.gpus > 0 and not gpu_request_fits(args.gpu_mem, pool):
        print("\tError: No GPUs available to fly in the %s pool match --gpu_mem %d. Card sizes there (GB): %s"
              % (pool, args.gpu_mem, ", ".join(str(t) for t in POOL_GPU_TIERS[pool])))
        is_valid = False
    if args.J < 0:
        print("\tError: Invalid number of jobs to run at once specified:", args.J)
        is_valid = False
    
    return is_valid


if __name__ == "__main__":
    sys.exit(main())
