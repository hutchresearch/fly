# **Overview:**
fly.py is a command-line tool that simplifies dispatching condor jobs to the
WWU CSCI department cluster.

# **Usage Examples**
```sh
fly.py --command "/bin/echo test"
fly.py --command "/path/to/train_cool_model.py train.npy dev.npy" --gpus 1 --gpu_mem 11 --cores 2
fly.py --commands_fn commands.txt --venv /cluster/home/$(whoami)/venv --J 10
fly.py --commands_fn commands.txt --conda /cluster/home/$(whoami)/anaconda3 --conda_name CondaEnvName
```
Call ``fly.py -h`` to see all of the options available.

# **Tips:**
* Condor must be able to run the commands on the remote machine, so please
  * Make sure you have a proper ``#!`` at the top of any scripts you wish to run
    via condor.
    * E.g. ``#! /usr/bin/env python3``
  * Make sure you have given the execute permission to your user for any binary
    or script you wish to run via condor.
  * Please provide the absolute path for the command you wish to run
    * You may use ``which command`` to find the absolute path for command


# **Helpful Condor Commands**
* condor_q -> check current queue
  * You can watch your status with ``watch condor_q``
* condor_q -hold -> check what error caused your job to be placed into the holding queue
* condor_q -better-analyze -> see how many machines can run the job you submitted and why
* condor_status -> check which computers are being used
* condor_ssh_to_job (job_id_number) -> ssh to the machine a given job is on (e.g. to check top or nvidia-smi)

# **fly Output Files**
In the condor directory (defaults to .condor_jobs), fly will create an output directory with the format USER_YYYYMMDD_HHmmss_ff (USER is your username, ff is microseconds sections).  Within that, it will produce a set of files of the format NUM.EXT.
* NUM is the job number.  If you only submit one job, it will be 0.  If you submit N jobs, you will have sets of files for NUM=0,...,N-1.
* EXT is one of the following
  * err - the contents of your command's standard out and any condor error output
  * job - the job file automatically created for you 
  * log - condor's logging
  * out - the contents of your command's standard out
  * sh - the wrapper script that actually calls your command(s)
* The *.out files are buffered and may only be written once the job has completed.

### Condor Documentation:
* [Condor: General](https://htcondor.readthedocs.io/en/stable/)
* [Condor: Job Files](https://htcondor.readthedocs.io/en/stable/classad-attributes/job-classad-attributes.html)
