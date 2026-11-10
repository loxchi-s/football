# Anvil + Gemini Agent Architecture

## Scope

This PR introduces the durable PostgreSQL queue contract only. It does not provision a database, add credentials, enable billing, or activate scheduled workflows. Apply the migration only to a dedicated non-production database after review.

## State model

- `pending`: eligible for claim when `scheduled_at <= now()`.
- `running`: held by a worker lease; only the matching `lease_owner` may heartbeat or finish it.
- `done`: successful terminal state.
- `dead`: retry budget exhausted.
- `cancelled`: explicitly cancelled.

The queue uses `FOR UPDATE SKIP LOCKED` so concurrent workers claim distinct jobs. `idempotency_key` prevents duplicate event delivery from creating duplicate jobs. Expired leases can be reclaimed, and attempts are bounded by `max_attempts`.

## Components planned

1. Trigger: validate trusted event metadata and enqueue a job.
2. Worker: claim one job, run bounded Gemini work, heartbeat, and finish with owner fencing.
3. Publisher: read the outbox and create a branch/PR. It must never push to `main`.
4. Reconciler: compare GitHub HEAD with `processed_sha`; do not mark a SHA processed merely because it was observed or enqueued.
5. Cleanup: delete only expired workflow artifacts; preserve ledger/evidence required by audit policy.
6. Security gate: fork PR code never receives secrets or write tokens. A label alone is not an approval boundary.

## Operational limits

- GitHub Actions hosted runner; no personal GPU or local machine.
- Gemini Developer API Free Tier only; stop on quota/access errors, with no paid fallback.
- Start with worker concurrency 1–2; raise only after measuring API quota and database load.
- Use GitHub Actions artifacts for short-lived handoff. Keep durable audit metadata in PostgreSQL.
- No Redis or S3 is required for the first iteration.
- Never send API keys, database URLs, PATs, or production data to Gemini.

## Activation gate

Before adding scheduled Trigger/Worker/Publisher workflows:
- Provision a dedicated database and apply the migration.
- Add `ANVIL_DATABASE_URL` as a GitHub Actions secret.
- Verify the database role can access only the Anvil schema/tables.
- Verify GitHub Actions token permissions and PR creation settings.
- Run concurrent-claim, duplicate-enqueue, expired-lease, retry, and stale-worker tests against a disposable database.
- Keep all publishing limited to branch + PR; human review and merge remain mandatory.

## Status

- Designed: queue schema, idempotent enqueue, atomic claim, lease heartbeat, bounded retry, and outbox table.
- Implemented: SQL migration only.
- Tested: not yet tested against PostgreSQL.
- Validated: not production-validated; activation is blocked until integration tests pass.
