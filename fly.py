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
import stat
import sys

def main():
    """ Main Function:
            Performs the heavy lifting for the submission of jobs to condor.
    """
    # Confirm proper run location
    if os.uname().nodename != "csci-head.cluster.cs.wwu.edu":
        sys.exit("EXITING: Jobs must be dispatched from csci-head.cluster.cs.wwu.edu")

    # Parse args
    args = parse_all_args()
    if not valid_args(args):
        sys.exit("EXITING: Invalid arguments")

    # Create and launch job (or dag of jobs)
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
        'queue_count'  : args.queue_count
        }

    if args.J == 0:
        job_fn  = make_job_file(**job_options)
        os.system("condor_submit " + job_fn)
    elif args.J >= 1:
        dag_fn = make_dag_file(args.J,job_options)
        os.system("condor_submit_dag -maxjobs %d %s" % (args.J,dag_fn))
    return


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
        job_dir  = os.path.join(condor_dir, job_name)
        if not os.path.exists(job_dir):
            break

    if not os.path.isdir(job_dir):
        os.makedirs(job_dir)

    return job_dir


def make_job_file(job_dir,job_name,cores,mem,gpus,gpu_mem,low_prio,requirements,rank,name=None,venv=None,\
    conda=None,conda_name=None,commands_fn=None,command=None,queue_count=1,job_num=0):
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
        job_file.write("requirements = (CUDAGlobalMemoryMb >= " + str(gpu_mem * 1000) + ")\n")
    if requirements is not "":
        job_file.write("requirements = " + requirements + "\n")
    if rank is not "":
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

    job_file.close()
    return job_fn 


def parse_all_args():
    """ Parses all arguments.

        Returns:
            argparse.Namespace: the parsed argument object
    """
    parser = argparse.ArgumentParser()

    # Executable Settings
    command = parser.add_mutually_exclusive_group(required=True)
    command.add_argument("--command",
                        type=str,
                        help="The path to the executable (str)")
    command.add_argument("--commands_fn",
                        type=str,
                        help="The path to a file containing a list of arguments for the executable (str) (optional)")

    # Environment
    run_env = parser.add_mutually_exclusive_group(required=False)
    run_env.add_argument("--venv",
                         help="Path to the virtual environment to be used (str)",
                         type=str)
    run_env.add_argument("--conda",
                         help="Path to the virtual environment to be used (str)",
                         type=str)
    parser.add_argument("--conda_name",
                        help="If using conda, name of the conda environment to activate (str) [default: \"\"]",
                        type=str)

    # Job Priority
    parser.add_argument("--low_prio",
                        action='store_true',
                        help="Jobs will be run after normal priority jobs")

    # Condor Settings
    parser.add_argument("--name",
                        type=str,
                        help="Name for the condor job. (str)")
    parser.add_argument("--condor_dir",
                        type=str,
                        help="Dir to store condor job and log files. [default: .condor_jobs]",
                        default=".condor_jobs")
    parser.add_argument("--J",
                        type=int,
                        help="Maximum number of concurrent jobs (int) [default: 0 --> unlimited]",
                        default=0)
    parser.add_argument("--cores",
                        type=int,
                        help="Number of CPU cores to allocate. (int) [default: 1]",
                        default=1)
    parser.add_argument("--mem",
                        type=int,
                        help="Amount of main memory to allocate, in GB. (int) [default: 8]",
                        default=8)
    parser.add_argument("--gpus",
                        type=int,
                        help="Number of GPUs needed. (int) [default: 0]",
                        default=0)
    parser.add_argument("--gpu_mem",
                        type=int,
                        help="Amount of GPU memory needed, in GB. (int) [default: 0]",
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
        print("\Error: You cannot specify both a virtual environment and a anaconda environment")
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
        print("\tError: Invalid amount of GPU memory specified:", args.gpus)
        is_valid = False
    if args.J < 0:
        print("\tError: Invalid number of concurrent jobs specified:", args.J)
        is_valid = False
    
    return is_valid


if __name__ == "__main__":
    main()
