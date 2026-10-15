BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS uq_model_jobs_single_running
    ON model_jobs ((1))
    WHERE status IN ('RUNNING', 'CANCEL_REQUESTED');

COMMIT;
