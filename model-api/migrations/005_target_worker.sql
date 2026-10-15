BEGIN;

ALTER TABLE model_jobs
    ADD COLUMN IF NOT EXISTS target_worker VARCHAR(100);

-- 기존 "DB 전체에서 실행 작업 1개" 제한 제거
DROP INDEX IF EXISTS uq_model_jobs_single_running;

-- 서버별로 실행 작업 1개 허용
CREATE UNIQUE INDEX IF NOT EXISTS uq_model_jobs_single_running_per_worker
    ON model_jobs (target_worker)
    WHERE status IN ('RUNNING', 'CANCEL_REQUESTED')
      AND target_worker IS NOT NULL;

-- 각 worker가 자기 queue를 빠르게 찾기 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_model_jobs_target_queue
    ON model_jobs (
        target_worker,
        status,
        priority DESC,
        created_at ASC
    );

COMMIT;
