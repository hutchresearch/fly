# **Overview:**
fly.py is a command-line tool that simplifies dispatching condor jobs to the
WWU CSCI department cluster.

# **Usage Examples**
* fly.py --commands_file commands_to_run.txt --gpus 1 --gpu_mem 7 --cores 4 --conda /cluster/home/username/anaconda3 --conda_name CondaEnvName

# **Tips:**
* Condor must be able to run the commands on the remote machine, so please
  * Make sure you have a proper ``#!'' at the top of any scripts you wish to run
    via condor.
    * E.g. ``#! /usr/bin/env python3``
  * Make sure you have given the execute permission to your user for any binary
    or script you wish to run via condor.
  * Please provide the absolute path for the command you wish to run
    * You may use ``which command'' to find the absolute path for command
* When a job submitted to condor prints to stdout, it will be written to the
  condor_jobs/*.out file, but only once the job has completed.
* When a job submitted to condor has an error, it will be written to the
  condor_jobs/*.err file.

# **Helpful Condor Commands**
* condor_q -> check current queue
* condor_status -> check which computers are being used
* condor_submit my.job


# **Current Cluster Status:**
* CF and Hutch Labs: Working
* CSCI Cluster: Working


### Condor Documentation:
* [Condor: General](https://htcondor.readthedocs.io/en/stable/)
* [Condor: Job Files](https://htcondor.readthedocs.io/en/stable/classad-attributes/job-classad-attributes.html)
