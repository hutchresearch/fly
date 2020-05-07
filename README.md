# **Overview:**
fly.py is a command-line tool that simplifies dispatching condor jobs to the
WWU CSCI department cluster.

# **Usage Examples**
```sh
fly.py --command "/bin/echo test"
fly.py --command "/path/to/train_cool_model.py train.npy dev.npy" -gpus 1 -gpu_mem 11 -cores 2
fly.py --commands_file commands.txt --conda /cluster/home/$(whoami)/anaconda3 --conda_name CondaEnvName
```

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
