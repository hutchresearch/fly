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


def main():
    """ Main Function:
            Performs the heavy lifting for the submission of jobs to condor.
    """
    args = parse_all_args()
    if not valid_args(args):
        exit(-1)
    if args.commands_file is not None:
        if not os.path.exists(args.commands_file):
            print("Couldn't find the commands file.")
            exit()
    job_submission_file = make_job_file(args)
    os.system("condor_submit " + job_submission_file)
    return


def make_job_file(args):
    """ Creates the condor_submit file and shell script wrapper for the job.

        Returns:
            file_name: The string path to the created condor_submit file.
    """
    # Make Submission File
    job_name = None
    if args.name is not None:
        job_name = getpass.getuser() + "-" + args.name.strip()
    else:
        job_name = getpass.getuser() + "-" + datetime.now().strftime("%Y%m%d-%H%M")
    job_path = os.path.join(args.condor_dir, job_name)
    submission_file_name = job_path + ".job"
    if not os.path.isdir(args.condor_dir):
        os.mkdir(args.condor_dir)
    submission_file_handle = open(submission_file_name, "w")

    # Condor Settings
    if args.name is not None:
        submission_file_handle.write("batch_name = \"" + args.name.strip() +"\"\n")
    submission_file_handle.write("request_cpus = " + str(args.cores) + "\n")
    submission_file_handle.write("request_memory = " + str(args.mem) + " GB\n")
    submission_file_handle.write("request_gpus = " + str(args.gpus) + "\n")
    if args.low_prio:
        submission_file_handle.write("priority = -10\n")
    if args.gpus > 0:
        submission_file_handle.write("requirements = (CUDAGlobalMemoryMb >= " + str(args.gpu_mem * 1000) + ")\n")
    if args.requirements is not "":
        submission_file_handle.write("requirements = " + args.requirements + "\n")
    if args.rank is not "":
        submission_file_handle.write("rank = " + args.rank + "\n")

    # Job Run Location
    if os.uname().nodename != "csci-head.cluster.cs.wwu.edu":
        sys.exit("Jobs must be dispatched from csci-head.cluster.cs.wwu.edu")

    # Log Files
    submission_file_handle.write("output = " + job_path + ".out\n")
    submission_file_handle.write("error  = " + job_path + ".err\n")
    submission_file_handle.write("log    = " + job_path + ".log\n")

    # Shell Script Wrapper
    shell_wrapper = os.open(job_path + ".sh", flags=os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode=stat.S_IRWXU)
    shell_wrapper_text = "#!/usr/bin/env bash\n"
    if args.venv is not None:
        shell_wrapper_text = shell_wrapper_text + "source $PYENV/bin/activate\n"
        submission_file_handle.write("environment=\"PYENV=" + args.venv.strip() + "\"\n")
    elif args.conda is not None:
        shell_wrapper_text = shell_wrapper_text + "source " + os.path.join(args.conda.strip(), "etc/profile.d/conda.sh") + "\n"
        if args.conda_name is not None:
            shell_wrapper_text = shell_wrapper_text + "conda activate " + args.conda_name.strip() + "\n"
        else:
            shell_wrapper_text = shell_wrapper_text + "conda activate" + "\n"
    shell_wrapper_text += "exec \"" + os.getcwd() + "/$@\"\n"
    os.write(shell_wrapper, bytes(shell_wrapper_text, encoding="utf-8"))
    os.close(shell_wrapper)

    # Assign Executable, Arguments, and Queue Commands
    submission_file_handle.write("executable = " + job_path + ".sh\n")
    if args.commands_file is not None:
        submission_file_handle.write("arguments = $(command)\n")
        submission_file_handle.write("queue command from " + args.commands_file.strip())
    elif args.command is not None:
        submission_file_handle.write("arguments = " + args.command.strip() + "\n")
        if args.queue_count > 1:
            submission_file_handle.write("queue " + str(args.queue_count))
        elif args.queue_count == 1:
            submission_file_handle.write("queue")


    submission_file_handle.close()
    return submission_file_name


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
    command.add_argument("--commands_file",
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
    if args.commands_file is not None:
        if not os.path.exists(args.commands_file):
            print("\tERROR: Unable to find the specified command file:", args.commands_file)
            is_valid = False
    if args.queue_count < 1:
        print("\tERROR: Invalid QUEUE_COUNT. You cannot schedule a job to run less than once.")
        is_valid = False
    
    # Virtual Environment
    if args.venv is not None and not os.path.exists(args.venv):
        print("\tERROR: Failed to find the specified venv directory:", args.venv)
        is_valid = False
    if args.conda is not None and not os.path.exists(args.conda):
        print("\tERROR: Failed to find the specified venv directory:", args.conda)
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
        is_valid = false
    if args.gpu_mem < 0:
        print("\tError: Invalid amount of GPU memory specified:", args.gpus)
        is_valid = false
    
    return is_valid


if __name__ == "__main__":
    main()
