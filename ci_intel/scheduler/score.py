"""
Priority scoring for CI dispatch ordering, keyed by (branch, platform).

opencv PR runs come from forks, so there is no PR number — runs are identified
by head_branch.  One PR run contains many platform jobs (Windows, Linux,
macOS-ARM64, …); each platform is scored independently against the history of
that same platform.

Higher score = runs sooner.  Four weighted factors:
  1. failed_on_prev_run  — dominant; this branch's last run on this platform FAILED
  2. flake_penalty       — penalize platforms with known flaky signatures
  3. short_job_first     — faster feedback from shorter platforms
  4. branch_stability    — tiebreaker; branches that rarely fail get slight preference

"failure" is counted strictly — cancelled runs (superseded by a new push) are
NOT failures and never trigger the failed_on_prev_run boost.
"""


def compute_score(job_config, history, weights):
    """
    Return a numeric priority score for one (branch, platform) unit.

    job_config keys: branch, platform
    history: NdjsonStore instance (or any object with the same query API)
    weights: dict (failed_on_prev_run, flake_penalty, short_job_first, branch_stability)
    """
    branch = job_config["branch"]
    platform = job_config["platform"]

    # Factor 1: did this branch's last run on this platform FAIL? (binary 0/1)
    last_run = history.last_run_for_branch(branch, platform)
    failed_prev = 1 if last_run and last_run.get("conclusion") == "failure" else 0

    # Factor 2: flake penalty — more flaky signatures on this platform → lower score
    flakes = history.flake_count(platform, lookback_days=30)
    flake_score = 1 / max(flakes, 1)

    # Factor 3: shortest-job-first — shorter median duration → higher score
    median_dur = history.median_duration(platform) or 600
    duration_score = 1 / median_dur

    # Factor 4: branch stability — lower fail rate across this branch → higher score
    runs = history.recent_runs(branch, limit=50)
    fail_count = sum(1 for r in runs if r.get("conclusion") == "failure")
    fail_rate = fail_count / max(len(runs), 1)
    stability = 1 / max(fail_rate, 0.01)

    return (
        weights.get("failed_on_prev_run", 10.0) * failed_prev
        + weights.get("flake_penalty", 2.0) * flake_score
        + weights.get("short_job_first", 1.0) * duration_score
        + weights.get("branch_stability", 1.0) * stability
    )
