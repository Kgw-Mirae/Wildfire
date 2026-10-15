import logging
import os
import socket
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.callback import enqueue_model_callback
from app.database import SessionLocal
from app.models import ModelJob, ModelRun


logger = logging.getLogger(__name__)

WORKER_ID = os.getenv(
    "WORKER_ID",
    f"{socket.gethostname()}-{os.getpid()}",
)

MODEL_TERMINAL_STATUSES = {
    "SUCCEEDED",
    "FAILED",
    "CANCELED",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def claim_next_job() -> UUID | None:
    """
    현재 Worker가 비어 있을 때
    QUEUED 작업 하나를 가져와 RUNNING으로 변경한다.

    여러 Worker가 동시에 접근해도
    FOR UPDATE SKIP LOCKED로 중복 선점을 방지한다.
    """

    try:
        with SessionLocal() as db:
            with db.begin():

                # 이 Worker가 이미 실행 중인 작업을 가지고 있으면
                # 추가 작업을 가져오지 않는다.
                active_job_id = db.scalar(
                    select(ModelJob.id)
                    .where(
                        ModelJob.worker_id == WORKER_ID,
                        ModelJob.status.in_(
                            ["RUNNING", "CANCEL_REQUESTED"]
                        ),
                    )
                    .limit(1)
                )

                if active_job_id is not None:
                    return None

                # 전체 공용 Queue에서 다음 작업 하나 선택
                job = db.scalar(
                    select(ModelJob)
                    .where(
                        ModelJob.status == "QUEUED",
                        ModelJob.cancel_requested.is_(False),
                    )
                    .order_by(
                        ModelJob.priority.desc(),
                        ModelJob.created_at.asc(),
                    )
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )

                if job is None:
                    return None

                now = utc_now()

                job.status = "RUNNING"
                job.worker_id = WORKER_ID
                job.started_at = now
                job.heartbeat_at = now
                job.updated_at = now

                job_id = job.id

            logger.info(
                "Claimed job: job_id=%s worker_id=%s",
                job_id,
                WORKER_ID,
            )

            return job_id

    except IntegrityError:
        logger.debug(
            "Worker already has an active job: worker_id=%s",
            WORKER_ID,
        )
        return None


def update_job_heartbeat(job_id: UUID) -> None:
    with SessionLocal() as db:
        with db.begin():
            db.execute(
                update(ModelJob)
                .where(
                    ModelJob.id == job_id,
                    ModelJob.status == "RUNNING",
                    ModelJob.worker_id == WORKER_ID,
                )
                .values(
                    heartbeat_at=utc_now(),
                    updated_at=utc_now(),
                )
            )


def mark_model_running(
    job_id: UUID,
    model_type: str,
) -> bool:
    now = utc_now()

    with SessionLocal() as db:
        with db.begin():
            job = db.scalar(
                select(ModelJob)
                .where(
                    ModelJob.id == job_id,
                    ModelJob.status == "RUNNING",
                    ModelJob.worker_id == WORKER_ID,
                )
                .with_for_update()
            )
            if job is None:
                raise RuntimeError(
                    f"Job not found or not owned by this worker: "
                    f"job_id={job_id}, worker_id={WORKER_ID}"
                )

            run = db.scalar(
                select(ModelRun)
                .where(
                    ModelRun.job_id == job_id,
                    ModelRun.model_type == model_type,
                )
                .with_for_update()
            )

            if run is None:
                raise RuntimeError(
                    f"Model run not found: "
                    f"job_id={job_id}, model={model_type}"
                )

            if run.status != "QUEUED":
                raise RuntimeError(
                    f"Cannot start model from status {run.status}: "
                    f"job_id={job_id}, model={model_type}"
                )

            if job.cancel_requested or job.status in {
                "SUCCEEDED", "PARTIAL_SUCCESS", "FAILED", "CANCELED",
            }:
                return False

            run.status = "RUNNING"
            run.started_at = now
            run.updated_at = now

            enqueue_model_callback(
                db=db,
                job=job,
                run=run,
                event_type="MODEL_RUNNING",
            )

    logger.info(
        "Model started: job_id=%s model=%s",
        job_id,
        model_type,
    )

    return True


def complete_model_run(
    job_id: UUID,
    model_type: str,
    model_status: str,
    *,
    exit_code: int | None = None,
    result_path: str | None = None,
    log_path: str | None = None,
    error_message: str | None = None,
) -> None:
    if model_status not in MODEL_TERMINAL_STATUSES:
        raise ValueError(
            f"Invalid terminal model status: {model_status}"
        )

    now = utc_now()

    with SessionLocal() as db:
        with db.begin():
            job = db.scalar(
                select(ModelJob)
                .where(ModelJob.id == job_id)
                .with_for_update()
            )
            if job is None:
                raise RuntimeError(f"Job not found: job_id={job_id}")

            run = db.scalar(
                select(ModelRun)
                .where(
                    ModelRun.job_id == job_id,
                    ModelRun.model_type == model_type,
                )
                .with_for_update()
            )

            if run is None:
                raise RuntimeError(
                    f"Model run not found: "
                    f"job_id={job_id}, model={model_type}"
                )

            if run.status in MODEL_TERMINAL_STATUSES:
                return

            if job.cancel_requested:
                model_status = "CANCELED"
                error_message = "Model execution was cancelled"
                result_path = None

            run.status = model_status
            run.exit_code = exit_code
            run.result_path = result_path
            run.log_path = log_path
            run.error_message = error_message
            run.finished_at = now
            run.updated_at = now

            # autoflush=False이므로 상태 조회 전에 명시적으로 DB 반영
            db.flush()

            model_statuses = list(
                db.scalars(
                    select(ModelRun.status)
                    .where(ModelRun.job_id == job_id)
                ).all()
            )

            all_models_finished = (
                len(model_statuses) == 2
                and all(
                    status in MODEL_TERMINAL_STATUSES
                    for status in model_statuses
                )
            )

            if all_models_finished:
                if job.cancel_requested:
                    job.status = "CANCELED"
                elif all(s == "SUCCEEDED" for s in model_statuses):
                    job.status = "SUCCEEDED"
                elif any(s == "SUCCEEDED" for s in model_statuses):
                    job.status = "PARTIAL_SUCCESS"
                else:
                    job.status = "FAILED"

                job.finished_at = now
                job.heartbeat_at = now
                job.updated_at = now

            # 모델 상태와 콜백 이벤트를 같은 트랜잭션으로 저장
            enqueue_model_callback(
                db=db,
                job=job,
                run=run,
                event_type="MODEL_COMPLETED",
            )

    logger.info(
        "Model completed: job_id=%s model=%s status=%s",
        job_id,
        model_type,
        model_status,
    )

def fail_entire_job(job_id: UUID, error_message: str) -> None:
    now = utc_now()
    with SessionLocal() as db:
        with db.begin():
            job = db.scalar(
                select(ModelJob)
                .where(ModelJob.id == job_id)
                .with_for_update()
            )
            if job is None:
                return
            if job.status in {
                "SUCCEEDED", "PARTIAL_SUCCESS", "FAILED", "CANCELED",
            }:
                return

            runs = list(db.scalars(
                select(ModelRun)
                .where(ModelRun.job_id == job_id)
                .order_by(ModelRun.model_type)
                .with_for_update()
            ))
            changed = False
            for run in runs:
                if run.status in MODEL_TERMINAL_STATUSES:
                    continue
                changed = True
                run.status = "CANCELED" if job.cancel_requested else "FAILED"
                run.exit_code = -1
                run.result_path = None
                run.error_message = error_message
                run.finished_at = now
                run.updated_at = now
                enqueue_model_callback(db, job, run, "MODEL_COMPLETED")

            statuses = [run.status for run in runs]
            if job.cancel_requested:
                job.status = "CANCELED"
            elif len(statuses) == 2 and all(s == "SUCCEEDED" for s in statuses):
                job.status = "SUCCEEDED"
            elif any(s == "SUCCEEDED" for s in statuses):
                job.status = "PARTIAL_SUCCESS"
            else:
                job.status = "FAILED"

            if changed or job.status != "SUCCEEDED":
                job.error_message = error_message
            job.finished_at = now
            job.heartbeat_at = now
            job.updated_at = now
