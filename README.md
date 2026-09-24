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

To see what fly would submit without submitting anything, add ``--pretend``.
It works on any machine and prints the generated condor files; on
csci-head you can then check them with ``condor_submit -dry-run - FILE``.
fly exits with condor_submit's exit status, so scripts can detect failed
submissions.

# **GPUs**
``--gpu_mem`` is the card's nominal memory size in GB, as printed on the box
(e.g. 11 for an RTX 2080 Ti). Requests are rounded up to the next card size
that exists. Larger cards are reserved for jobs that need them, so a small
request, or ``--gpus`` without ``--gpu_mem``, only uses the smaller cards. If
no card fly can use is big enough, fly exits with an error rather than
submitting a job that can never start.

# **Commands**
fly runs each command exactly as if you typed it at a bash prompt, in the
directory you ran fly from, on the cluster's shared filesystem. Quotes,
``$VARIABLES``, ``$(...)``, pipes, ``>`` redirects, and ``&&`` all work:
```sh
fly.py --command "python3 train.py --name 'my run' > train.log 2>&1"
```
Because bash interprets the command, quote any argument containing
characters bash treats specially (``* ? | ; & $ < >``), just as you would
in a terminal: ``--pattern '*.csv'``.

A ``--commands_fn`` file holds one command per line, and each line runs as
its own job. Blank lines and lines starting with ``#`` are skipped.
``--queue_count N`` runs ``--command`` N times. ``--J N`` keeps at most N
jobs from the batch in the queue at once, adding the rest as earlier ones
finish.

With ``--venv`` or ``--conda``, the environment is activated before your
command runs; if activation fails, the job stops with an error in its
``.err`` file instead of running with the wrong Python. Interactive jobs
(``-i``) start a plain shell, so activate your environment yourself there.

# **Tips:**
* If you run a script directly (``./train.py`` rather than
  ``python3 train.py``), give it a ``#!`` line (e.g. ``#! /usr/bin/env python3``)
  and execute permission (``chmod +x train.py``).
* Python buffers standard output when it isn't a terminal, so ``.out`` files
  may stay empty until the job ends. Use ``python3 -u`` or ``print(..., flush=True)``
  to see output as it happens.
* Use ``--pretend`` to check what fly will submit before submitting it.

# **Helpful Condor Commands**
* condor_q -> check current queue
  * ``condor_watch_q`` shows your jobs updating live without loading the scheduler
* condor_q -hold -> check what error caused your job to be placed into the holding queue
* condor_q -better-analyze -> see how many machines can run the job you submitted and why
* condor_status -> check which computers are being used
* condor_ssh_to_job (job_id_number) -> ssh to the machine a given job is on (e.g. to check top or nvidia-smi)
* condor_rm (job_id_number) -> cancel a running job

# **fly Output Files**
In the condor directory (``--condor_dir``, default ``.condor_jobs``), fly
creates a directory named USER_YYYYMMDD_HHMMSS_microseconds containing:
* ``submit.job`` - the condor submit file
* ``wrapper.sh`` - sets up your environment, then runs a command file
* ``cmd/N.sh`` - your commands, one file per line of ``--commands_fn`` (or just ``cmd/0.sh``)
* ``N.out`` / ``N.err`` - standard output / standard error of job N (N = 0, 1, ...)
* ``condor.log`` - condor's log of events (submitted, started, finished) for every job

I recommend you design your scripts to write any output logging directly to
a file that you specify, instead of relying on standard out or standard
error. If you do so, you may not ever need to inspect any of the files
produced for you in the output directory.

### Condor Documentation:
* [WWU cluster documentation](https://cluster.cs.wwu.edu/)
* [HTCondor 25.0 manual](https://htcondor.readthedocs.io/en/25.0/)
* [condor_submit reference](https://htcondor.readthedocs.io/en/25.0/man-pages/condor_submit.html)
