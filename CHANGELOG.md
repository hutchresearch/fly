# Changelog

## Unreleased (2026-09 modernization, PRs #11–#14)

Items marked **Behavior change** may affect existing scripts or habits.

### Fixed
- **fly runs on csci-head again.** Since the 2025 OS reinstall, fly refused to start on the cluster head node ("Jobs must be dispatched from csci-head…"). (#11)
- **GPU jobs can be scheduled again.** fly matched on a GPU attribute the cluster no longer advertises, so every GPU job sat idle forever. Also, `--requirements` used to silently drop the GPU memory constraint; now both apply. (#11)
- **`--J` with a single command no longer crashes.** (#13)
- Failed submissions are reported: fly exits with `condor_submit`'s status instead of always succeeding. (#12)

### Added
- **Lab pool support.** Run fly on `csci-lab-head` or a CS lab machine to use idle lab computers, which have 4–24 GB GPUs. fly detects the pool from the machine's HTCondor configuration. Lab jobs automatically ask for lab machines. A failed lab submission caused by authentication prints the `condor_token_fetch` command to fix it. (#14)
- **`--pretend`** prints the files fly would submit, without submitting, on any machine. It also shows the `condor_submit -dry-run` command for checking them. **`--pool lab`** previews a lab submission from elsewhere. (#12, #14)
- **`--queue_count` works with `--J`.** (#13)
- A test suite (`python3 -m unittest discover -s tests`, 47 tests). It passes on Python 3.8, 3.9 and 3.12. (#11–#14)

### Changed
- **Behavior change: commands run exactly as typed at a bash prompt.** Quotes, `$VARS`, `$(...)`, pipes, `>` redirects and `&&` now work. Previously, double quotes got the job rejected, `> log.txt` was passed to the program as arguments, and `$(date)` silently vanished. Unquoted `* | ; $` are now interpreted by bash, so quote them as you would in a terminal. (#13)
- **Behavior change: `--gpu_mem` means the card's nominal size** (e.g. 11 for an RTX 2080 Ti), rounded up to the next real card size. Cards of 16 GB and up are reserved: small requests, and `--gpus` without `--gpu_mem`, use only smaller cards. Requests no available card can satisfy are rejected up front. (#11)
- **Behavior change: new output layout** in `.condor_jobs/<run>/`: `submit.job`, `wrapper.sh`, `cmd/N.sh`, `N.out`, `N.err`, and a single `condor.log`. The old layout used `0.job`, `0.sh` and `0_N.out`. (#13)
- **Behavior change: `--J` limits how many jobs from the batch are in the queue at once, instead of using DAGMan.** Batches are a single submission. (#13)
- **Environment setup fails loudly.** If venv or conda activation fails, the job stops with a `fly:` error in its `.err` file instead of running with the wrong Python. Paths with spaces work. (#13)
- Commands files skip blank lines and `#` comments, and tolerate Windows line endings. (#13)
- Jobs are pinned to the pool they were submitted from, since the pools share jobs with each other. (#14)
- Clearer validation: empty commands, empty or missing commands files, `--conda_name` without `--conda`, and `$` in `--condor_dir` are all rejected. (#12, #13)
- README rewritten: cluster vs. lab, command rules, GPUs, output files, buffering tips, and `condor_watch_q`. (#11–#14)

### Removed
- DAGMan-based batching (`condor_submit_dag`). (#13)
