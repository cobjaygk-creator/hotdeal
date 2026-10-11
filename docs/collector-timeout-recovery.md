# Collector timeout recovery

The October 12 crash log showed a 20-second Dealbada request timeout,
overlapping scheduler jobs being skipped, then a watchdog exit after 324
seconds without a completed collection tick (300-second threshold).

## Recovery behavior

- Community list fetches run outside the shared SQLite writer lock. Each
  source gets a 60-second total fetch budget, including retries/fallbacks.
- Raised fetch failures/timeouts put that source in a 120-second cooldown.
  Failures remain visible in the pipeline's per-source error summary.
- Shared-lock collectors (including manual routes and background enrichment)
  have a 180-second budget for waiting plus work. Cancellation unwinds DB
  contexts and releases the lock. Native SQLite calls may finish before
  cleanup completes; these are cooperative deadlines, not process kills.
- DB initialization closes its connection on failure or cancellation,
  even before the caller has received it.
- The watchdog logs degraded collection after WATCHDOG_STALE_MINUTES
  (default 5). It no longer exits the web process on stale collection alone.
  WATCHDOG_ENABLED and WATCHDOG_CHECK_SECONDS still control this diagnostic.

The 60-second source limit can also affect slow browser-backed sources.
Check per-source errors rather than assuming that a responsive web server
means every upstream source is healthy. Fetchers which internally return an
empty list instead of raising an error do not enter the failure cooldown.

## Validation and rollout

Regression tests cover a stalled upstream, other-tier progress, failure
cooldown/recovery, cancellation propagation, writer-lock cleanup, transaction
rollback, cancelled DB initialization, and nonfatal stale watchdog checks.

After deployment, check the GitHub/Railway deployment commit and status, then
GET /api/stats repeatedly to verify last_collect_at and collect_by_source
timestamps advance. Inspect Railway logs for repeated deadlines and DB locks.
Railway restart settings are not changed by this patch.
