"""
Priority gate — the runtime that turns a score into real job ordering.

Runs as a lightweight job at the front of a gated workflow (on a cheap
ubuntu-latest runner).  The expensive jobs declare `needs: priority-gate`, so
they do not grab a scarce self-hosted runner until this gate releases them.

Flow:
    enter   — score this (PR, workflow) from the store and enroll in the queue
    wait    — poll until fewer than MAX_CONCURRENT runs are active AND this run
              is the highest-scored waiter, then release (exit 0)
    release — called when the run finishes, freeing its slot for the next waiter

The gate is deadlock-safe: if it cannot get a slot within --timeout seconds it
fails open (releases anyway), so a stuck queue can never block CI indefinitely.

Two subcommands, both driven entirely by env + flags so the composite action
can call them with no glue code:

    python -m ci_priority.scheduler.gate enter   --run-id 123 --workflow "OCV PR:5.x ARM64" --pr 42
    python -m ci_priority.scheduler.gate release --run-id 123

Env vars:
    GITHUB_TOKEN          token with contents:write on the store repo
    CI_PRIORITY_REPO         repo whose ci-priority-data branch holds queue + history
                          (defaults to GITHUB_REPOSITORY, set by Actions)
"""
import argparse
import os
import sys
import time
from datetime import datetime, timezone

from ci_priority.scheduler.score import compute_score
from ci_priority.store.ndjson_store import NdjsonStore
from ci_priority.scheduler.queue_store import QueueStore

# Defaults — overridable per workflow via the composite action inputs.
DEFAULT_MAX_CONCURRENT = 1     # active runs allowed at once (model the runner pool)
DEFAULT_TIMEOUT = 1800         # seconds before failing open (never deadlock CI)
DEFAULT_POLL_INTERVAL = 30     # seconds between queue checks
STALE_TTL = 900               # drop a queue entry whose heartbeat is this old

DEFAULT_WEIGHTS = {
    "failed_on_prev_run": 10.0,
    "flake_penalty": 2.0,
    "short_job_first": 1.0,
    "branch_stability": 1.0,
}


def _stores(now_fn=time.time):
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("CI_PRIORITY_REPO") or os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        # Raise (not exit) so main() can fail OPEN — a misconfigured gate must
        # never block the build.
        raise RuntimeError("GITHUB_TOKEN and CI_PRIORITY_REPO (or GITHUB_REPOSITORY) must be set")
    return NdjsonStore(repo, token), QueueStore(repo, token)


def cmd_enter(args, history, queue, now_fn=time.time, sleep_fn=time.sleep):
    """Score this run, enroll it, and block until released. Always exits 0."""
    # platform = scoring key (per-platform history: fail rate, duration, flake).
    # pool     = queue partition = the RUNNER LABEL, so platforms that share the
    #            same self-hosted runners contend in ONE queue (correct capacity).
    #            Defaults to platform when --pool is omitted.
    platform = args.platform
    pool = getattr(args, "pool", None) or platform
    branch = args.branch or ""
    job = {"branch": branch, "platform": platform}
    score = compute_score(job, history, DEFAULT_WEIGHTS)
    print(f"[gate] run {args.run_id} platform={platform!r} pool={pool!r} branch={branch!r} score={score:.3f}")

    queue.enter(args.run_id, platform, None, score, now_fn(), group=pool)

    start = now_fn()
    while True:
        if queue.try_claim(args.run_id, args.max_concurrent, STALE_TTL, now_fn(), group=pool):
            waited = int(now_fn() - start)
            print(f"[gate] RELEASED run {args.run_id} pool={pool} after {waited}s (score={score:.3f})")
            return 0

        elapsed = now_fn() - start
        if elapsed >= args.timeout:
            print(f"[gate] TIMEOUT after {int(elapsed)}s — failing open, releasing run {args.run_id} pool={pool}")
            queue.force_claim(args.run_id, now_fn(), group=pool)
            return 0

        waiting = [e for e in queue.snapshot()
                   if e["state"] == "waiting" and e.get("group") == pool]
        ahead = sum(1 for e in waiting if (-e["score"], e["run_id"]) < (-score, args.run_id))
        print(f"[gate] run {args.run_id} waiting in pool {pool} — "
              f"{ahead} higher-priority run(s) ahead; re-check in {args.poll_interval}s")
        sleep_fn(args.poll_interval)


def cmd_release(args, history, queue, **_):
    """
    Free this (run, platform) slot and — when --conclusion is given — record the
    run's outcome to history. This is the automated, zero-infra update path: every
    gated platform run appends one fact here at completion, so the store stays
    fresh with no separate ingest workflow. Always exits 0.
    """
    pool = getattr(args, "pool", None) or args.platform
    queue.release(args.run_id, group=pool)
    print(f"[gate] released slot for run {args.run_id} pool={pool}")

    if getattr(args, "conclusion", None):
        fact = {
            "run_id": args.run_id,
            "branch": args.branch or "",
            "platform": args.platform,
            "conclusion": args.conclusion,
            "error_signature": None,   # classification is a later enhancement
            "category": None,
            "duration_sec": args.duration,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        history.append_many([fact])
        print(f"[gate] recorded outcome: {args.platform} = {args.conclusion}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(description="CI priority gate")
    sub = p.add_subparsers(dest="command", required=True)

    enter = sub.add_parser("enter", help="enroll and wait for release")
    enter.add_argument("--run-id", type=int, required=True)
    enter.add_argument("--platform", required=True,
                       help="opencv platform name (e.g. 'Windows', 'macOS-ARM64') — the scoring key")
    enter.add_argument("--pool", default=None,
                       help="runner-label queue partition (e.g. 'opencv-cn-lin-x86-64'). "
                            "Platforms sharing runners share a pool. Defaults to --platform.")
    enter.add_argument("--branch", default=None, help="head_branch (PR source branch) — identity key")
    enter.add_argument("--max-concurrent", type=int, default=DEFAULT_MAX_CONCURRENT)
    enter.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    enter.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL)
    enter.set_defaults(func=cmd_enter)

    release = sub.add_parser("release", help="free this (run, platform) slot; optionally record outcome")
    release.add_argument("--run-id", type=int, required=True)
    release.add_argument("--platform", required=True)
    release.add_argument("--pool", default=None, help="runner-label queue partition (defaults to --platform)")
    release.add_argument("--branch", default=None, help="head_branch — identity key for the recorded fact")
    release.add_argument("--conclusion", default=None,
                         help="success|failure|cancelled — records a history fact when set")
    release.add_argument("--duration", type=int, default=None, help="platform duration in seconds (optional)")
    release.set_defaults(func=cmd_release)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    # Fail OPEN: any internal error (missing token, git/network failure, read-only
    # token on a fork PR, …) must let the build proceed UNORDERED rather than block
    # or skip it. The gate is an optimization, never a gate on correctness.
    try:
        history, queue = _stores()
        return args.func(args, history, queue)
    except Exception as e:
        print(f"[gate] ERROR: {e} — failing OPEN, build proceeds unordered", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
