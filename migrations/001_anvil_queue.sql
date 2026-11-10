-- Durable queue contract for the Anvil/Gemini agent.
-- Apply manually to a dedicated project database; never point this at production.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS anvil_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key TEXT NOT NULL UNIQUE,
    job_type TEXT NOT NULL CHECK (length(job_type) BETWEEN 1 AND 100),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    priority INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'done', 'dead', 'cancelled')),
    scheduled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 10),
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (status = 'running' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR status <> 'running'
    )
);

CREATE INDEX IF NOT EXISTS anvil_jobs_ready_idx
    ON anvil_jobs (priority DESC, scheduled_at, created_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS anvil_jobs_expired_lease_idx
    ON anvil_jobs (lease_expires_at)
    WHERE status = 'running';

CREATE TABLE IF NOT EXISTS anvil_outbox (
    outbox_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key TEXT NOT NULL UNIQUE,
    job_id UUID REFERENCES anvil_jobs(job_id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'publishing', 'published', 'dead')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    lease_expires_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS anvil_outbox_ready_idx
    ON anvil_outbox (created_at)
    WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS anvil_sync_state (
    repository TEXT PRIMARY KEY,
    observed_sha TEXT NOT NULL,
    processed_sha TEXT,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ
);

-- Enqueue is idempotent: duplicate delivery returns the existing job.
CREATE OR REPLACE FUNCTION anvil_enqueue_job(
    p_idempotency_key TEXT,
    p_job_type TEXT,
    p_payload JSONB,
    p_priority INTEGER DEFAULT 0,
    p_scheduled_at TIMESTAMPTZ DEFAULT now()
) RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_job_id UUID;
BEGIN
    INSERT INTO anvil_jobs (
        idempotency_key, job_type, payload, priority, scheduled_at
    ) VALUES (
        p_idempotency_key, p_job_type, COALESCE(p_payload, '{}'::jsonb),
        COALESCE(p_priority, 0), COALESCE(p_scheduled_at, now())
    )
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING job_id INTO v_job_id;

    IF v_job_id IS NULL THEN
        SELECT job_id INTO v_job_id
        FROM anvil_jobs
        WHERE idempotency_key = p_idempotency_key;
    END IF;

    RETURN v_job_id;
END;
$$;

-- Claim one job atomically. Expired leases are eligible for retry.
CREATE OR REPLACE FUNCTION anvil_claim_job(
    p_worker_id TEXT,
    p_lease_seconds INTEGER DEFAULT 600
) RETURNS SETOF anvil_jobs
LANGUAGE sql
AS $$
    WITH candidate AS (
        SELECT job_id
        FROM anvil_jobs
        WHERE (
            status = 'pending' AND scheduled_at <= now()
        ) OR (
            status = 'running' AND lease_expires_at < now()
            AND attempts < max_attempts
        )
        ORDER BY priority DESC, scheduled_at, created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    UPDATE anvil_jobs AS j
    SET status = 'running',
        attempts = j.attempts + 1,
        lease_owner = p_worker_id,
        lease_expires_at = now() + make_interval(secs => GREATEST(p_lease_seconds, 30)),
        heartbeat_at = now(),
        started_at = COALESCE(j.started_at, now()),
        updated_at = now(),
        error_code = NULL,
        error_message = NULL
    FROM candidate
    WHERE j.job_id = candidate.job_id
    RETURNING j.*;
$$;


-- A worker may disappear during its final attempt. Reap expired exhausted leases.
CREATE OR REPLACE FUNCTION anvil_reap_exhausted_jobs() RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    UPDATE anvil_jobs
    SET status = 'dead',
        finished_at = now(),
        lease_owner = NULL,
        lease_expires_at = NULL,
        heartbeat_at = NULL,
        error_code = COALESCE(error_code, 'lease_expired'),
        error_message = COALESCE(error_message, 'Lease expired after maximum attempts'),
        updated_at = now()
    WHERE status = 'running'
      AND lease_expires_at < now()
      AND attempts >= max_attempts;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;

-- Heartbeat is owner-fenced: a stale worker cannot extend another worker's lease.
CREATE OR REPLACE FUNCTION anvil_heartbeat_job(
    p_job_id UUID,
    p_worker_id TEXT,
    p_lease_seconds INTEGER DEFAULT 600
) RETURNS BOOLEAN
LANGUAGE plpgsql
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    UPDATE anvil_jobs
    SET heartbeat_at = now(),
        lease_expires_at = now() + make_interval(secs => GREATEST(p_lease_seconds, 30)),
        updated_at = now()
    WHERE job_id = p_job_id
      AND status = 'running'
      AND lease_owner = p_worker_id
      AND lease_expires_at > now();

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count = 1;
END;
$$;

-- Finish is also owner-fenced. Failure retries are scheduled with bounded backoff.
CREATE OR REPLACE FUNCTION anvil_finish_job(
    p_job_id UUID,
    p_worker_id TEXT,
    p_success BOOLEAN,
    p_error_code TEXT DEFAULT NULL,
    p_error_message TEXT DEFAULT NULL
) RETURNS BOOLEAN
LANGUAGE plpgsql
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    UPDATE anvil_jobs
    SET status = CASE
            WHEN p_success THEN 'done'
            WHEN attempts >= max_attempts THEN 'dead'
            ELSE 'pending'
        END,
        scheduled_at = CASE
            WHEN p_success OR attempts >= max_attempts THEN scheduled_at
            ELSE now() + make_interval(secs => LEAST(3600, 30 * (2 ^ LEAST(attempts, 6))))
        END,
        finished_at = CASE WHEN p_success OR attempts >= max_attempts THEN now() ELSE NULL END,
        lease_owner = NULL,
        lease_expires_at = NULL,
        heartbeat_at = NULL,
        error_code = CASE WHEN p_success THEN NULL ELSE left(p_error_code, 100) END,
        error_message = CASE WHEN p_success THEN NULL ELSE left(p_error_message, 2000) END,
        updated_at = now()
    WHERE job_id = p_job_id
      AND status = 'running'
      AND lease_owner = p_worker_id;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count = 1;
END;
$$;
