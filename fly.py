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
import shlex
import socket
import stat
import subprocess
import sys
import tempfile

CLUSTER_HEAD = "csci-head.cluster.cs.wwu.edu"

# Nominal GPU memory sizes (GB) of the cards in the CSCI pools. A --gpu_mem
# request snaps up to the smallest of these, and each size is matched as
# at least size * GPU_MIB_PER_NOMINAL_GB MiB, because cards advertise a bit
# less than their nominal size (an "11 GB" RTX 2080 Ti advertises 10835 MiB).
GPU_MEM_TIERS = (4, 6, 8, 11, 12, 16, 24, 80)
GPU_MIB_PER_NOMINAL_GB = 950
# Larger cards are reserved for jobs that need them: a job may only use cards
# below the next reserved size above its request.
RESERVED_GPU_TIERS = (16, 24, 80)
# Nominal GPU sizes fly can schedule onto (the H100s require preemption
# opt-in and are not available through fly).
POOL_GPU_TIERS = (11,)


def main():
    """ Main Function:
            Performs the heavy lifting for the submission of jobs to condor.
    """
    # Parse args
    args = parse_all_args()
    if not valid_args(args):
        sys.exit("EXITING: Invalid arguments")

    # Confirm proper run location (previews work anywhere)
    if not args.pretend and not on_cluster_head():
        sys.exit("EXITING: Jobs must be dispatched from " + CLUSTER_HEAD)

    # Create and launch job (or dag of jobs)
    if args.pretend:
        job_dir = tempfile.mkdtemp(prefix="fly_pretend_")
    else:
        job_dir = make_job_dir(args.condor_dir)

    job_options = {
        'job_dir'      : job_dir,
        'job_name'     : args.name,
        'cores'        : args.cores,
        'mem'          : args.mem,
        'gpus'         : args.gpus,
        'gpu_mem'      : args.gpu_mem,
        'low_prio'     : args.low_prio,
        'requirements' : args.requirements,
        'rank'         : args.rank,
        'venv'         : args.venv,
        'conda'        : args.conda,
        'conda_name'   : args.conda_name,
        'commands_fn'  : args.commands_fn,
        'command'      : args.command,
        'interactive'  : args.interactive,
        'queue_count'  : args.queue_count
        }

    if args.J == 0:
        submit_fn = make_job_file(**job_options)
        if args.interactive:
            cmd = ["condor_submit", "-interactive", submit_fn]
        else:
            cmd = ["condor_submit", submit_fn]
    else:
        submit_fn = make_dag_file(args.J,job_options)
        cmd = ["condor_submit_dag", "-maxjobs", str(args.J), submit_fn]

    if args.pretend:
        show_pretend(job_dir, cmd)
        return 0
    return submit(cmd)


def submit(cmd):
    """ Runs a condor submit command, passing its output through.

        Returns:
            int: the command's exit status
    """
    try:
        return subprocess.run(cmd).returncode
    except FileNotFoundError:
        print("EXITING: %s not found. Are you on %s?" % (cmd[0], CLUSTER_HEAD), file=sys.stderr)
        return 1


def show_pretend(job_dir, cmd):
    """ Prints the generated files instead of submitting them. """
    for name in sorted(os.listdir(job_dir)):
        path = os.path.join(job_dir, name)
        print("# ==========\n# %s\n# ==========" % path)
        with open(path) as f:
            print(f.read())
    print("# Not submitted. fly would run:\n#   %s" % " ".join(shlex.quote(c) for c in cmd))
    print("# To check the files with HTCondor's own parser, on %s run:" % CLUSTER_HEAD)
    print("#   condor_submit -dry-run - %s" % shlex.quote(cmd[-1]))


def on_cluster_head():
    """ Checks whether this is the cluster head node. Its nodename has been the
        short "csci-head" since the 2025 OS reinstall, so compare FQDNs too.
    """
    nodename = os.uname().nodename
    return nodename in ("csci-head", CLUSTER_HEAD) or socket.getfqdn() == CLUSTER_HEAD


def make_dag_file(J,job_options):
    """ Make DAG File:
            Creates the dag file
    """
    dag_fn = job_options['job_dir'] + "/dagman.dag"
    with open(dag_fn,"w") as dag_file:
        with open(job_options['commands_fn']) as commands_file:
            for i,line in enumerate(commands_file):
                job_options['commands_fn'] = None
                job_options['command'] = line.rstrip()
                job_options['job_num'] = i
                job_fn  = make_job_file(**job_options)
                print("JOB %d %s" % (i,job_fn),file=dag_file)
                print("CATEGORY %d limited" % i,file=dag_file)
        print("MAXJOBS limited %d" % J,file=dag_file)

    return dag_fn

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


def make_job_file(job_dir,job_name,cores,mem,gpus,gpu_mem,low_prio,requirements,rank,name=None,venv=None,\
    conda=None,conda_name=None,commands_fn=None,command=None,queue_count=1,job_num=0,interactive=False):
    """ Creates the condor_submit file and shell script wrapper for the job.

        Returns:
            file_name: The string path to the created condor_submit file.
    """
    # Set up job file
    job_path = job_dir + "/" + str(job_num)
    job_fn   = job_path + ".job"
    job_file = open(job_fn, "w")

    # Condor Settings
    if job_name is not None:
        job_file.write("batch_name = \"" + job_name.strip() +"\"\n")
    job_file.write("request_cpus = " + str(cores) + "\n")
    job_file.write("request_memory = " + str(mem) + " GB\n")
    job_file.write("request_gpus = " + str(gpus) + "\n")
    if low_prio:
        job_file.write("priority = -10\n")
    if gpus > 0:
        job_file.write("require_gpus = " + gpu_constraint(gpu_mem) + "\n")
    if requirements:
        job_file.write("requirements = " + requirements + "\n")
    if rank:
        job_file.write("rank = " + rank + "\n")

    # Log Files
    job_file.write("output = " + job_path + "_$(Process).out\n")
    job_file.write("error  = " + job_path + "_$(Process).err\n")
    job_file.write("log    = " + job_path + "_$(Process).log\n")

    # Shell Script Wrapper
    shell_wrapper = os.open(job_path + ".sh", flags=os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode=stat.S_IRWXU)
    shell_wrapper_text = "#!/usr/bin/env bash\n"
    if venv is not None:
        shell_wrapper_text = shell_wrapper_text + "source $PYENV/bin/activate\n"
        job_file.write("environment=\"PYENV=" + venv.strip() + "\"\n")
    elif conda is not None:
        shell_wrapper_text = shell_wrapper_text + "source " + os.path.join(conda.strip(), "etc/profile.d/conda.sh") + "\n"
        if conda_name is not None:
            shell_wrapper_text = shell_wrapper_text + "conda activate " + conda_name.strip() + "\n"
        else:
            shell_wrapper_text = shell_wrapper_text + "conda activate" + "\n"
    shell_wrapper_text += "exec \"$@\"\n"
    os.write(shell_wrapper, bytes(shell_wrapper_text, encoding="utf-8"))
    os.close(shell_wrapper)

    # Assign Executable, Arguments, and Queue Commands
    job_file.write("executable = " + job_path + ".sh\n")
    if commands_fn is not None:
        job_file.write("arguments = $(command)\n")
        job_file.write("queue command from " + commands_fn.strip())
    elif command is not None:
        job_file.write("arguments = " + command.strip() + "\n")
        if queue_count > 1:
            job_file.write("queue " + str(queue_count))
        elif queue_count == 1:
            job_file.write("queue")
    elif interactive:
        job_file.write("queue")

    job_file.close()
    return job_fn


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


def gpu_request_fits(gpu_mem):
    """ Checks that some card fly can use falls within the request's band. """
    if gpu_tier(gpu_mem) is None:
        return False
    lower, upper = gpu_band(gpu_mem)
    return any(lower <= t and (upper is None or t < upper) for t in POOL_GPU_TIERS)


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

    # Executable Settings
    command = parser.add_mutually_exclusive_group(required=True)
    command.add_argument("--command",
                        type=str,
                        help="The path to the executable (str)")
    command.add_argument("--commands_fn",
                        type=str,
                        help="The path to a file containing a list of arguments for the executable (str) (optional)")
    command.add_argument("--interactive", "-i",
                        action="store_true",
                        help="Request job to run an interactive shell job (flag)")

    # Environment
    run_env = parser.add_mutually_exclusive_group(required=False)
    run_env.add_argument("--venv",
                         help="The path to the virtual environment to be used (str)",
                         type=str)
    run_env.add_argument("--conda",
                         help="The path to the virtual environment to be used (str)",
                         type=str)
    parser.add_argument("--conda_name",
                        help="If using conda, the name of the conda environment to activate (str) [default: \"\"]",
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
                        help="Maximum number of concurrent jobs (int) [default: 0 --> unlimited]",
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
                        help="The number of times to queue the command to run. (NOTE: Only works with the '--command' flag) (int) [default: 1]",
                        default=1)
    parser.add_argument("--condor_dir",
                        type=str,
                        help="Directory to store condor job and log files. [default: .condor_jobs]",
                        default=".condor_jobs")

    return parser.parse_args()


def valid_args(args):
    """ Checks if the arguments provided will allow for a successful job dispatching.

    Returns:
        boolean: True if all args were assigned valid values, else false.
    """
    is_valid = True
    # Commands Options
    if args.commands_fn is not None and not os.path.exists(args.commands_fn):
        print("\tError: Unable to find the specified command file:", args.commands_fn)
        is_valid = False
    if args.commands_fn is None and args.J > 1:
        print("\tThe --J flag only works with a commands file")
        is_valid = False
    if args.queue_count < 1:
        print("\tError: Invalid QUEUE_COUNT. You cannot schedule a job to run less than once.")
        is_valid = False
    if args.queue_count > 1 and args.commands_fn is not None:
        print("\tError: You cannot run a commands file multiple times with queue count.")
        is_valid = False
    
    # Virtual Environment
    if args.venv is not None and not os.path.exists(args.venv):
        print("\tError: Failed to find the specified venv directory:", args.venv)
        is_valid = False
    if args.conda is not None and not os.path.exists(args.conda):
        print("\tError: Failed to find the specified venv directory:", args.conda)
        is_valid = False
    if args.conda is not None and args.venv is not None:
        print("\tError: You cannot specify both a virtual environment and a anaconda environment")
        is_valid = False
    
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
    elif args.gpus > 0 and not gpu_request_fits(args.gpu_mem):
        print("\tError: No GPUs available to fly match --gpu_mem %d. Available card sizes (GB): %s"
              % (args.gpu_mem, ", ".join(str(t) for t in POOL_GPU_TIERS)))
        is_valid = False
    if args.J < 0:
        print("\tError: Invalid number of concurrent jobs specified:", args.J)
        is_valid = False
    
    return is_valid


if __name__ == "__main__":
    sys.exit(main())
