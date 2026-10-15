BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;


-- 통합 작업
CREATE TABLE IF NOT EXISTS model_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 외부 시스템이 전달하는 중복 방지용 요청 ID
    request_id VARCHAR(150) NOT NULL UNIQUE,

    status VARCHAR(30) NOT NULL DEFAULT 'QUEUED'
        CHECK (
            status IN (
                'QUEUED',
                'RUNNING',
                'SUCCEEDED',
                'PARTIAL_FAILED',
                'FAILED',
                'CANCEL_REQUESTED',
                'CANCELED'
            )
        ),

    priority INTEGER NOT NULL DEFAULT 0,

    -- 공통/CFD/HYSPLIT 요청값 전체
    request_data JSONB NOT NULL,

    callback_url TEXT NOT NULL,

    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,

    -- 재실행한 작업이면 원본 작업 ID
    retry_of UUID REFERENCES model_jobs(id),

    -- Worker 장애 복구용
    worker_id VARCHAR(100),
    heartbeat_at TIMESTAMPTZ,

    error_message TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);


-- 통합 작업에 속한 CFD/HYSPLIT 개별 실행
CREATE TABLE IF NOT EXISTS model_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    job_id UUID NOT NULL
        REFERENCES model_jobs(id)
        ON DELETE CASCADE,

    model_type VARCHAR(20) NOT NULL
        CHECK (model_type IN ('CFD', 'HYSPLIT')),

    status VARCHAR(30) NOT NULL DEFAULT 'QUEUED'
        CHECK (
            status IN (
                'QUEUED',
                'RUNNING',
                'SUCCEEDED',
                'FAILED',
                'CANCEL_REQUESTED',
                'CANCELED'
            )
        ),

    container_id VARCHAR(100),
    container_name VARCHAR(200),

    exit_code INTEGER,

    result_path TEXT,
    log_path TEXT,
    result_data JSONB,

    error_message TEXT,

    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- 한 작업에 CFD와 HYSPLIT이 각각 하나씩만 존재
    UNIQUE (job_id, model_type)
);


-- 모델별 완료 콜백
CREATE TABLE IF NOT EXISTS callback_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    job_id UUID NOT NULL,
    model_type VARCHAR(20) NOT NULL,

    event_type VARCHAR(50) NOT NULL DEFAULT 'MODEL_COMPLETED',

    status VARCHAR(20) NOT NULL DEFAULT 'PENDING'
        CHECK (
            status IN (
                'PENDING',
                'SENDING',
                'DELIVERED',
                'FAILED'
            )
        ),

    payload JSONB NOT NULL,

    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    last_http_status INTEGER,
    last_error TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at TIMESTAMPTZ,

    -- 해당 모델 실행이 존재해야 콜백을 만들 수 있음
    CONSTRAINT fk_callback_model_run
        FOREIGN KEY (job_id, model_type)
        REFERENCES model_runs(job_id, model_type)
        ON DELETE CASCADE,

    -- CFD/HYSPLIT별 논리 콜백 하나만 생성
    UNIQUE (job_id, model_type)
);


-- 대기 작업을 빠르게 가져오기 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_model_jobs_queue
    ON model_jobs (
        status,
        priority DESC,
        created_at ASC
    );


CREATE INDEX IF NOT EXISTS idx_model_runs_job
    ON model_runs (job_id);


CREATE INDEX IF NOT EXISTS idx_model_runs_status
    ON model_runs (status);


-- 전송 또는 재시도할 콜백 조회용
CREATE INDEX IF NOT EXISTS idx_callback_events_pending
    ON callback_events (
        status,
        next_attempt_at
    )
    WHERE status IN ('PENDING', 'FAILED');


COMMIT;
