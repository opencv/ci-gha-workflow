# ci_priority — score-driven CI priority dispatch

Orders opencv 5.x PR builds so that, when self-hosted runner pools are contended,
the most valuable runs go **first** — instead of plain FIFO. Additive and
**fail-open**: if anything goes wrong (or it isn't configured yet), builds run
exactly as before.

## How it works

Each PR triggers opencv's `PR:5.x` workflow, which calls one reusable workflow per
platform (`Windows`, `Linux`, `Ubuntu2404-ARM64`, `macOS-ARM64`, …). A lightweight
`priority-gate` job is added to the front of each reusable workflow; the heavy
self-hosted jobs `needs:` it:

```
PR run ──▶ priority-gate (ubuntu-latest, cheap)
              1. score this (branch, platform) from history
              2. enrol in a per-pool queue on the ci-priority-data branch
              3. block until: running_in_pool < max-concurrent
                              AND this run is the top-scored waiter
              4. release  (fail-open after a timeout — never blocks a build)
           ──▶ heavy build jobs (self-hosted)   ← only grab a scarce runner once released
           ──▶ release-priority-slot            ← frees the slot for the next waiter
```

The scarce runner is never held while waiting — only the cheap gate job waits.

## Scoring — `(branch, platform)`

Fork PRs have no PR number, so runs are identified by **`head_branch`**. Each
platform is scored independently. Higher score = sooner:

| factor | weight | meaning |
|--------|:------:|---------|
| `failed_on_prev_run` | 10 | this branch's last run on this platform **failed** (fast feedback on fixes) |
| `flake_penalty`      | 2  | de-prioritise platforms with known flaky signatures |
| `short_job_first`    | 1  | quicker platforms first |
| `branch_stability`   | 1  | tiebreaker |

`cancelled` is **not** a failure (opencv cancels superseded runs), so it never
triggers the priority boost.

## Storage — zero infrastructure

History and the live queue live as plain files on a dedicated **`ci-priority-data`**
git branch (`data/runs.ndjson`, `data/queue.json`), updated with a clone→append→push
retry loop. No database, no external service. The queue is partitioned by pool and
keyed on `(run_id, platform)` — all platforms of one PR share a `run_id`.

`seed/runs.ndjson` is a committed 90-day baseline (per-platform, metadata) so scoring
works on day one; live data accumulates on top and the seed ages out of the 90-day
window on its own.

## Layout

```
ci_priority/
  scheduler/   score.py, gate.py, queue_store.py   # scoring + the gate
  store/       ndjson_store.py                      # git-branch NDJSON store (+ seed)
  seed/        runs.ndjson                           # committed 90-day baseline
priority-gate/action.yml                             # the composite action workflows call
```

The runtime path uses only the Python standard library plus `git` — no external
packages, no `pip install`.

## Seed + automated updates

`seed/runs.ndjson` is a committed 90-day, per-platform baseline generated from opencv's
`PR:5.x` run history, so scoring works on day one.

The store then **keeps itself fresh automatically** — no separate ingest workflow. Every
gated platform run ends in its `release-priority-slot` job, which (besides freeing the
slot) records one fact `{run_id, branch, platform, conclusion, created_at}` to the
history via `gate release --conclusion`. So `failed_on_prev_run`, `branch_stability`, and
`flake` inputs stay current on their own; the seed simply ages out of the 90-day window.

Deferred to a later data-pipeline PR (not required for this to work): failure
*classification* (error signatures / categories, which sharpen the flake factor) and
precise per-platform durations, plus the offline seed-generation tooling.

## Activation (maintainer)

Merging this changes **nothing** on its own — the gate fails open until:

1. A `CI_PRIORITY_PAT` secret (contents:write on `opencv/ci-gha-workflow`) is added to
   `opencv/opencv` and passed to the reusable workflows via `secrets: inherit` in
   `PR-5.x.yaml`.
2. **`max-concurrent`** in each gated workflow is set to that pool's runner capacity
   (÷ heavy jobs per run). It defaults to `1` (safe, but serialising) — set it to real
   capacity so no runner is left idle; the gate then only reorders the *overflow* beyond
   capacity, with zero throughput loss.
