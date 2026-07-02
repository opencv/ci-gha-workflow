"""
Shared priority queue, stored as a single JSON file on the ci-priority-data branch.

This is the coordination point for the priority gate: every gated workflow run
registers one entry here, and the gate releases runs highest-score-first as
slots free up.  It reuses the same git-branch + push-retry storage pattern as
ndjson_store.py, so there is no new infrastructure to operate.

Unlike runs.ndjson (append-only history), the queue is small and mutable — it
only ever holds the runs currently in flight.  Every mutation is a single
clone -> modify -> commit -> push transaction, retried on concurrent-push
conflicts so two gates can never corrupt each other's view.

File layout on the branch (data/queue.json):

    {
      "entries": [
        {"run_id": 123, "workflow": "OCV PR:5.x ARM64", "pr_number": 42,
         "score": 13.0, "state": "waiting", "heartbeat": 1751280000.0}
      ]
    }

states:  "waiting"  — enrolled, not yet released
         "running"  — released; occupies a concurrency slot until removed
"""
import json
import os
import subprocess
import tempfile
from pathlib import Path

DATA_BRANCH = "ci-priority-data"
QUEUE_FILE = "data/queue.json"
MAX_RETRIES = 8
GIT_ENV_BASE = {
    "GIT_AUTHOR_NAME": "ci-priority",
    "GIT_AUTHOR_EMAIL": "ci-priority@noreply.github.com",
    "GIT_COMMITTER_NAME": "ci-priority",
    "GIT_COMMITTER_EMAIL": "ci-priority@noreply.github.com",
    "GIT_TERMINAL_PROMPT": "0",
}


class QueueStore:
    def __init__(self, repo, token, remote_url=None):
        self.repo = repo
        self.token = token
        # remote_url lets tests point at a local file:// bare repo
        self._remote = remote_url or f"https://x-access-token:{token}@github.com/{repo}.git"

    # ------------------------------------------------------------------
    # Public operations — each is one atomic transaction on the branch
    # ------------------------------------------------------------------

    def enter(self, run_id, workflow, pr_number, score, now, group=None):
        """
        Register this run as waiting (idempotent — re-entering is a no-op).

        `group` partitions the queue: runs only compete with others in the same
        group (use the runner-pool label, so different hardware pools each get
        their own concurrency limit and ordering).  group=None is a single
        global pool.
        """
        def mutate(queue):
            entries = queue.setdefault("entries", [])
            # keyed by (run_id, group): one opencv PR run has many platform jobs
            # sharing a run_id, so the pool/group is part of the identity.
            if not any(e["run_id"] == run_id and e.get("group") == group for e in entries):
                entries.append({
                    "run_id": run_id,
                    "workflow": workflow,
                    "pr_number": pr_number,
                    "score": score,
                    "group": group,
                    "state": "waiting",
                    "heartbeat": now,
                })
            return queue, None

        self._transaction(mutate, f"gate: enter run {run_id} pool {group}")

    def try_claim(self, run_id, max_concurrent, stale_ttl, now, group=None):
        """
        Atomically decide whether this run may start.

        Returns True (and marks the run "running") iff, within this run's group:
          - fewer than max_concurrent runs are currently "running", AND
          - this run is the highest-scored among all "waiting" runs.

        Slots and ordering are scoped to `group` (the runner pool), so contention
        on one pool never blocks another.  group=None is a single global pool.

        Stale entries (heartbeat older than stale_ttl — a crashed or cancelled
        run that never released its slot) are pruned first so they can't block
        the queue forever.  Also refreshes this run's heartbeat on every call.
        """
        def mutate(queue):
            entries = queue.setdefault("entries", [])

            # Drop dead entries whose heartbeat went stale.
            entries = [e for e in entries if now - e.get("heartbeat", now) <= stale_ttl]

            for e in entries:
                if e["run_id"] == run_id and e.get("group") == group:
                    e["heartbeat"] = now

            in_group = [e for e in entries if e.get("group") == group]
            running = [e for e in in_group if e["state"] == "running"]
            waiting = sorted(
                (e for e in in_group if e["state"] == "waiting"),
                key=lambda e: (-e["score"], e["run_id"]),  # high score first; FIFO tiebreak
            )

            claimed = False
            if (len(running) < max_concurrent and waiting
                    and waiting[0]["run_id"] == run_id and waiting[0].get("group") == group):
                waiting[0]["state"] = "running"
                claimed = True

            queue["entries"] = entries
            return queue, claimed

        return self._transaction(mutate, f"gate: claim run {run_id}")

    def force_claim(self, run_id, now, group=None):
        """Fail-open: mark this (run, pool) running regardless of position (timeout escape)."""
        def mutate(queue):
            entries = queue.setdefault("entries", [])
            found = False
            for e in entries:
                if e["run_id"] == run_id and e.get("group") == group:
                    e["state"] = "running"
                    e["heartbeat"] = now
                    found = True
            if not found:
                entries.append({
                    "run_id": run_id, "workflow": None, "pr_number": None,
                    "score": 0, "group": group, "state": "running", "heartbeat": now,
                })
            return queue, None

        self._transaction(mutate, f"gate: force-claim run {run_id} pool {group}")

    def release(self, run_id, group=None):
        """Remove this (run, pool) entry, freeing its slot for the next waiter."""
        def mutate(queue):
            entries = queue.setdefault("entries", [])
            queue["entries"] = [
                e for e in entries
                if not (e["run_id"] == run_id and (group is None or e.get("group") == group))
            ]
            return queue, None

        self._transaction(mutate, f"gate: release run {run_id} pool {group}")

    def snapshot(self):
        """Return the current queue entries (read-only; for diagnostics/tests)."""
        with tempfile.TemporaryDirectory() as d:
            if not self._clone(d):
                return []
            return self._read_queue(Path(d)).get("entries", [])

    # ------------------------------------------------------------------
    # Transaction core
    # ------------------------------------------------------------------

    def _transaction(self, mutate, commit_msg):
        """
        clone -> mutate(queue) -> write -> commit -> push, retrying on conflict.

        `mutate` takes the parsed queue dict and returns (new_queue, result).
        The branch is created on first use if it does not exist yet.
        """
        for attempt in range(MAX_RETRIES):
            with tempfile.TemporaryDirectory() as d:
                cloned = self._clone(d)
                if not cloned:
                    # Branch does not exist yet — bootstrap it as an orphan branch.
                    self._git("init", "-b", DATA_BRANCH, cwd=d)
                    self._git("remote", "add", "origin", self._remote, cwd=d)

                queue = self._read_queue(Path(d))
                queue, result = mutate(queue)

                path = Path(d) / QUEUE_FILE
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")

                self._git("add", QUEUE_FILE, cwd=d)
                commit = self._git("commit", "-m", commit_msg, cwd=d)
                if commit.returncode != 0 and "nothing to commit" in (commit.stdout + commit.stderr):
                    return result  # no change to push (e.g. idempotent enter)

                push = self._git("push", "origin", DATA_BRANCH, cwd=d)
                if push.returncode == 0:
                    return result
                # Push rejected — another gate pushed first; retry from a fresh clone.

        raise RuntimeError(f"queue transaction failed after {MAX_RETRIES} attempts: {commit_msg}")

    # ------------------------------------------------------------------
    # git helpers
    # ------------------------------------------------------------------

    def _clone(self, dest):
        r = self._git("clone", "--depth=1", "--branch", DATA_BRANCH,
                      self._remote, dest, cwd=dest)
        return r.returncode == 0

    @staticmethod
    def _read_queue(repo_dir):
        path = repo_dir / QUEUE_FILE
        if not path.exists():
            return {"entries": []}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"entries": []}

    def _git(self, *args, cwd):
        env = {**os.environ, **GIT_ENV_BASE}
        return subprocess.run(
            ["git"] + list(args), cwd=cwd, env=env, capture_output=True, text=True,
        )
