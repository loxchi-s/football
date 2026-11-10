BEGIN;

DO $$
DECLARE
    first_id UUID;
    duplicate_id UUID;
    claimed anvil_jobs%ROWTYPE;
    ok BOOLEAN;
BEGIN
    first_id := anvil_enqueue_job(
        'ci-idempotency-001', 'ci_test', '{"case":"idempotency"}'::jsonb
    );
    duplicate_id := anvil_enqueue_job(
        'ci-idempotency-001', 'ci_test', '{"case":"duplicate"}'::jsonb
    );
    IF first_id <> duplicate_id THEN
        RAISE EXCEPTION 'idempotent enqueue returned different job IDs';
    END IF;

    SELECT * INTO claimed FROM anvil_claim_job('ci-worker-a', 60);
    IF claimed.job_id IS DISTINCT FROM first_id OR claimed.status <> 'running'
       OR claimed.attempts <> 1 THEN
        RAISE EXCEPTION 'atomic claim did not return expected job';
    END IF;

    ok := anvil_heartbeat_job(first_id, 'stale-worker', 60);
    IF ok THEN
        RAISE EXCEPTION 'stale worker unexpectedly extended lease';
    END IF;
    ok := anvil_heartbeat_job(first_id, 'ci-worker-a', 60);
    IF NOT ok THEN
        RAISE EXCEPTION 'current worker failed to extend lease';
    END IF;

    ok := anvil_finish_job(first_id, 'ci-worker-a', FALSE, 'ci_retry', 'expected test retry');
    IF NOT ok THEN
        RAISE EXCEPTION 'current worker failed to finish job';
    END IF;

    UPDATE anvil_jobs SET scheduled_at = now() - interval '1 second'
    WHERE job_id = first_id;
    SELECT * INTO claimed FROM anvil_claim_job('ci-worker-b', 60);
    IF claimed.job_id IS DISTINCT FROM first_id OR claimed.attempts <> 2 THEN
        RAISE EXCEPTION 'retry claim did not increment attempts';
    END IF;
    ok := anvil_finish_job(first_id, 'ci-worker-b', TRUE);
    IF NOT ok THEN
        RAISE EXCEPTION 'successful finish failed';
    END IF;
    IF (SELECT status FROM anvil_jobs WHERE job_id = first_id) <> 'done' THEN
        RAISE EXCEPTION 'successful job did not reach done state';
    END IF;

    first_id := anvil_enqueue_job(
        'ci-expired-final-lease', 'ci_test', '{}'::jsonb
    );
    UPDATE anvil_jobs SET max_attempts = 1 WHERE job_id = first_id;
    SELECT * INTO claimed FROM anvil_claim_job('crashed-worker', 60);
    UPDATE anvil_jobs SET lease_expires_at = now() - interval '1 second'
    WHERE job_id = first_id;
    IF anvil_reap_exhausted_jobs() <> 1 THEN
        RAISE EXCEPTION 'expired final lease was not reaped';
    END IF;
    IF (SELECT status FROM anvil_jobs WHERE job_id = first_id) <> 'dead' THEN
        RAISE EXCEPTION 'exhausted job did not reach dead state';
    END IF;
END;
$$;

ROLLBACK;
