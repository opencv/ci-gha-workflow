"""
NDJSON-based persistent store backed by a dedicated git branch (ci-intel-data).

Each CI fact is one JSON line appended to data/runs.ndjson on that branch.
Concurrent writes are handled with a push-retry loop: clone → append → push;
if the push is rejected (another ingest already pushed), retry from a fresh clone.

This is intentionally zero-infrastructure — no external services, no secrets
beyond the GITHUB_TOKEN already available in GitHub Actions.

To migrate to a real database (Phase 2), replace the upsert_fact / _load_all_runs
methods; all query methods (last_run_for_pr, flake_count, …) stay unchanged.
"""
import json
import os
import statistics
import subprocess
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_BRANCH = "ci-intel-data"
DATA_FILE = "data/runs.ndjson"
# Committed dataset shipped in the repo (ci_intel/seed/runs.ndjson). Read as the
# day-one baseline so a freshly-merged repo scores before any live ingest runs.
SEED_FILE = Path(__file__).resolve().parent.parent / "seed" / "runs.ndjson"
MAX_RETRIES = 5
GIT_ENV_BASE = {
    "GIT_AUTHOR_NAME": "ci-intel",
    "GIT_AUTHOR_EMAIL": "ci-intel@noreply.github.com",
    "GIT_COMMITTER_NAME": "ci-intel",
    "GIT_COMMITTER_EMAIL": "ci-intel@noreply.github.com",
    "GIT_TERMINAL_PROMPT": "0",
}


class NdjsonStore:
    def __init__(self, repo, token, remote_url=None, use_seed=True):
        self.repo = repo
        self.token = token
        # remote_url can be overridden in tests with a local file:// path
        self._remote = remote_url or f"https://x-access-token:{token}@github.com/{repo}.git"
        self._use_seed = use_seed  # tests set False to isolate from the shipped seed
        self._cache = None  # lazy-loaded on first query

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def upsert_fact(self, fact):
        """
        Append one fact dict as a NDJSON line to the data branch.
        Retries up to MAX_RETRIES times on concurrent-push conflicts.
        """
        line = json.dumps(fact, separators=(",", ":")) + "\n"

        for attempt in range(MAX_RETRIES):
            with tempfile.TemporaryDirectory() as d:
                r = self._git("clone", "--depth=1", "--branch", DATA_BRANCH,
                              self._remote, d, cwd=d)

                if r.returncode != 0:
                    stderr = r.stderr
                    if ("Remote branch" in stderr and "not found" in stderr) \
                            or "fatal: couldn't find remote ref" in stderr:
                        self._init_branch(line, fact["run_id"])
                        return
                    raise RuntimeError(f"clone failed (attempt {attempt + 1}): {stderr}")

                data_path = Path(d) / DATA_FILE
                data_path.parent.mkdir(parents=True, exist_ok=True)
                with open(data_path, "a", encoding="utf-8") as f:
                    f.write(line)

                self._git("add", DATA_FILE, cwd=d)
                self._git("commit", "-m", f"ingest: run {fact['run_id']}", cwd=d)
                r = self._git("push", "origin", DATA_BRANCH, cwd=d)
                if r.returncode == 0:
                    print(f"[store] fact written (run {fact['run_id']}, attempt {attempt + 1})")
                    return
                # Push rejected — another ingest pushed concurrently; retry
                print(f"[store] push conflict, retrying ({attempt + 1}/{MAX_RETRIES})")

        raise RuntimeError(f"upsert_fact: push failed after {MAX_RETRIES} attempts")

    def append_many(self, facts):
        """
        Append many facts in a SINGLE commit/push (with retry). Used by backfill,
        which produces ~one fact per platform per run — one push per fact would be
        thousands of pushes.
        """
        if not facts:
            return
        blob = "".join(json.dumps(f, separators=(",", ":")) + "\n" for f in facts)

        for attempt in range(MAX_RETRIES):
            with tempfile.TemporaryDirectory() as d:
                r = self._git("clone", "--depth=1", "--branch", DATA_BRANCH,
                              self._remote, d, cwd=d)
                if r.returncode != 0:
                    stderr = r.stderr
                    if ("Remote branch" in stderr and "not found" in stderr) \
                            or "fatal: couldn't find remote ref" in stderr:
                        self._init_branch(blob, f"{len(facts)} facts")
                        return
                    raise RuntimeError(f"clone failed (attempt {attempt + 1}): {stderr}")

                data_path = Path(d) / DATA_FILE
                data_path.parent.mkdir(parents=True, exist_ok=True)
                with open(data_path, "a", encoding="utf-8") as f:
                    f.write(blob)
                self._git("add", DATA_FILE, cwd=d)
                self._git("commit", "-m", f"backfill: {len(facts)} facts", cwd=d)
                r = self._git("push", "origin", DATA_BRANCH, cwd=d)
                if r.returncode == 0:
                    print(f"[store] appended {len(facts)} facts (attempt {attempt + 1})")
                    return
                print(f"[store] push conflict, retrying ({attempt + 1}/{MAX_RETRIES})")

        raise RuntimeError(f"append_many: push failed after {MAX_RETRIES} attempts")

    def _init_branch(self, first_line, run_id):
        """Bootstrap the ci-intel-data orphan branch with the first data line."""
        with tempfile.TemporaryDirectory() as d:
            self._git("init", "-b", DATA_BRANCH, cwd=d)
            self._git("remote", "add", "origin", self._remote, cwd=d)
            data_path = Path(d) / DATA_FILE
            data_path.parent.mkdir(parents=True, exist_ok=True)
            data_path.write_text(first_line, encoding="utf-8")
            self._git("add", DATA_FILE, cwd=d)
            self._git("commit", "-m", f"init: ci-intel data store (run {run_id})", cwd=d)
            r = self._git("push", "origin", DATA_BRANCH, cwd=d)
            if r.returncode != 0:
                raise RuntimeError(f"init_branch: push failed: {r.stderr}")
        print(f"[store] data branch '{DATA_BRANCH}' initialized")

    # ------------------------------------------------------------------
    # Read path — all queries share one lazy-loaded in-memory dataset
    # ------------------------------------------------------------------

    def _load_all_runs(self):
        """
        Return all run facts: the committed seed dataset as a baseline, overlaid
        with live data from the ci-intel-data branch (a live row supersedes a
        seed row with the same run_id).

        The seed lets a freshly-merged repo score on day one, before any live
        ingest has run; live runs then accumulate on top and age it out.
        """
        if self._cache is not None:
            return self._cache

        by_id = {r.get("run_id"): r for r in self._load_seed()}

        with tempfile.TemporaryDirectory() as d:
            r = self._git("clone", "--depth=1", "--branch", DATA_BRANCH,
                          self._remote, d, cwd=d)
            if r.returncode == 0:
                data_path = Path(d) / DATA_FILE
                if data_path.exists():
                    with open(data_path, encoding="utf-8") as f:
                        for lineno, raw in enumerate(f, 1):
                            raw = raw.strip()
                            if not raw:
                                continue
                            try:
                                rec = json.loads(raw)
                                by_id[rec.get("run_id")] = rec  # live supersedes seed
                            except json.JSONDecodeError as exc:
                                print(f"[store] warn: bad JSON on line {lineno}: {exc}")

        self._cache = list(by_id.values())
        return self._cache

    def _load_seed(self):
        """Load the committed baseline seed (ci_intel/seed/runs.ndjson), if present."""
        if not self._use_seed or not SEED_FILE.exists():
            return []
        runs = []
        for raw in SEED_FILE.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                runs.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
        return runs

    def _runs_since(self, days):
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = []
        for r in self._load_all_runs():
            raw_ts = r.get("created_at", "")
            try:
                ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            if ts >= cutoff:
                result.append(r)
        return result

    # ------------------------------------------------------------------
    # Query API (called by scheduler/score.py)
    # ------------------------------------------------------------------

    def last_run_for_branch(self, branch, platform):
        """Return the most recent run dict for this branch + platform, or None."""
        candidates = [
            r for r in self._runs_since(90)
            if r.get("branch") == branch and r.get("platform") == platform
        ]
        return max(candidates, key=lambda r: r["run_id"]) if candidates else None

    def flake_count(self, platform, lookback_days=30):
        """
        Count distinct error signatures that look like flakes for this platform.

        Detection: same branch, same platform — run A fails with signature X,
        a later run B succeeds. Signature X is a flake (it passed on retry
        without a code change in between).
        """
        runs = [
            r for r in self._runs_since(lookback_days)
            if r.get("platform") == platform
        ]
        by_branch = {}
        for r in runs:
            br = r.get("branch")
            if br:
                by_branch.setdefault(br, []).append(r)

        flaky_sigs = set()
        for branch_runs in by_branch.values():
            ordered = sorted(branch_runs, key=lambda r: r["run_id"])
            pending_sigs = set()
            for r in ordered:
                if r.get("conclusion") == "failure" and r.get("error_signature"):
                    pending_sigs.add(r["error_signature"])
                elif r.get("conclusion") == "success" and pending_sigs:
                    # This branch succeeded after previous failures → those sigs are flakes
                    flaky_sigs.update(pending_sigs)
                    pending_sigs.clear()
        return len(flaky_sigs)

    def existing_keys(self):
        """Return the set of (run_id, platform) already stored (backfill skip key)."""
        return {(r["run_id"], r.get("platform")) for r in self._load_all_runs()}

    def median_duration(self, platform):
        """Return median duration in seconds for this platform, or None."""
        durations = [
            r["duration_sec"] for r in self._runs_since(90)
            if r.get("platform") == platform and r.get("duration_sec")
        ]
        return statistics.median(durations) if durations else None

    def recent_runs(self, branch, limit=50):
        """Return the most recent N runs for a branch (any platform), newest first."""
        runs = [r for r in self._runs_since(90) if r.get("branch") == branch]
        return sorted(runs, key=lambda r: r["run_id"], reverse=True)[:limit]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _git(self, *args, cwd):
        env = {**os.environ, **GIT_ENV_BASE}
        return subprocess.run(
            ["git"] + list(args),
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
        )
