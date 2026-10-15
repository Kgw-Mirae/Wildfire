BEGIN;

ALTER TABLE model_jobs
    ADD COLUMN IF NOT EXISTS
        model_id VARCHAR(100);

UPDATE model_jobs
SET model_id = 'smoke-spread'
WHERE model_id IS NULL;

ALTER TABLE model_jobs
    ALTER COLUMN model_id SET NOT NULL;


ALTER TABLE model_jobs
    ADD COLUMN IF NOT EXISTS
        scenario_id VARCHAR(150);

ALTER TABLE model_jobs
    ADD COLUMN IF NOT EXISTS
        requested_by VARCHAR(150);

ALTER TABLE model_jobs
    ADD COLUMN IF NOT EXISTS
        callback_enabled BOOLEAN
        NOT NULL DEFAULT FALSE;

UPDATE model_jobs
SET callback_enabled = TRUE
WHERE callback_url IS NOT NULL;

ALTER TABLE model_jobs
    ALTER COLUMN callback_url
    DROP NOT NULL;


ALTER TABLE model_jobs
    DROP CONSTRAINT IF EXISTS
        model_jobs_request_id_key;

ALTER TABLE model_jobs
    DROP CONSTRAINT IF EXISTS
        model_jobs_model_id_request_id_key;

ALTER TABLE model_jobs
    ADD CONSTRAINT
        model_jobs_model_id_request_id_key
        UNIQUE (
            model_id,
            request_id
        );


ALTER TABLE model_jobs
    DROP CONSTRAINT IF EXISTS
        model_jobs_status_check;

UPDATE model_jobs
SET status = 'PARTIAL_SUCCESS'
WHERE status = 'PARTIAL_FAILED';

ALTER TABLE model_jobs
    ADD CONSTRAINT model_jobs_status_check
        CHECK (
            status IN (
                'QUEUED',
                'RUNNING',
                'SUCCEEDED',
                'PARTIAL_SUCCESS',
                'FAILED',
                'CANCEL_REQUESTED',
                'CANCELED'
            )
        );


ALTER TABLE callback_events
    DROP CONSTRAINT IF EXISTS
        callback_events_job_id_model_type_key;

ALTER TABLE callback_events
    DROP CONSTRAINT IF EXISTS
        callback_events_job_model_event_key;

ALTER TABLE callback_events
    ADD CONSTRAINT
        callback_events_job_model_event_key
        UNIQUE (
            job_id,
            model_type,
            event_type
        );


DROP INDEX IF EXISTS
    idx_callback_events_pending;

CREATE INDEX
    idx_callback_events_pending
    ON callback_events (
        status,
        next_attempt_at
    )
    WHERE status = 'PENDING';

COMMIT;
