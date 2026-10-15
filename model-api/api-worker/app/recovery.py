import logging
import os
from pathlib import Path
from uuid import UUID

import docker
from docker.errors import NotFound
from sqlalchemy import select

from app.database import SessionLocal
from app.job_service import (
    WORKER_ID,
    fail_entire_job
)
from app.models import ModelJob

logger = logging.getLogger(__name__)

def ensure_job_stopped(
    job_id: UUID,
    *,
    model_type: str | None = None,
) -> None:
    labels = [
        "model.runner=true",
        f"model.job_id={job_id}",
    ]

    if model_type is not None:
        normalized = model_type.lower()

        if normalized not in {
            "cfd",
            "hysplit",
        }:
            raise ValueError(
                f"Unsupported model type: {model_type}"
            )

        labels.append(
            f"model.type={normalized}"
        )

    filters = {
        "label": labels,
    }

    client = docker.from_env()

    grace = int(
        os.getenv(
            "MODEL_CANCEL_GRACE_SECONDS",
            "30",
        )
    )

    try:
        client.ping()

        containers = client.containers.list(
            all=True,
            filters=filters,
        )

        for container in containers:
            try:
                container.reload()

                if container.status == "paused":
                    container.unpause()
                    container.reload()

                if container.status == "created":
                    container.remove()
                    continue

                if container.status not in {
                    "exited",
                    "dead",
                }:
                    container.stop(
                        timeout=grace
                    )

                container.reload()

                if container.status not in {
                    "exited",
                    "dead",
                }:
                    raise RuntimeError(
                        "Model is still active: "
                        f"{container.id}"
                    )

                # 삭제 전에 Docker 로그의 마지막 부분을 보존한다.
                model = container.labels.get(
                    "model.type",
                    "unknown",
                ).lower()

                if model not in {
                    "cfd",
                    "hysplit",
                }:
                    model = "unknown"

                root = Path(
                    os.getenv(
                        "JOB_WORKER_ROOT",
                        "/jobs",
                    )
                )

                log_path = (
                    root
                    / str(job_id)
                    / model
                    / "recovery.log"
                )

                try:
                    log_path.parent.mkdir(
                        parents=True,
                        exist_ok=True,
                    )

                    log_path.write_bytes(
                        container.logs(
                            tail=2000,
                            timestamps=True,
                        )
                    )
                except Exception:
                    logger.exception(
                        "Could not preserve recovery log: %s",
                        container.id,
                    )

                # 결과 및 모델 로그는 bind mount에 저장돼 있으므로
                # 실행 컨테이너만 삭제한다.
                container.remove(v=False)

                logger.info(
                    "Removed model container: "
                    "job_id=%s model=%s container_id=%s",
                    job_id,
                    model,
                    container.id,
                )

            except NotFound:
                # 이미 삭제된 경우 정상 처리한다.
                continue

        remaining = client.containers.list(
            all=True,
            filters=filters,
        )

        if remaining:
            remaining_ids = [
                container.id
                for container in remaining
            ]

            raise RuntimeError(
                "Could not remove model containers: "
                f"job_id={job_id}, "
                f"containers={remaining_ids}"
            )

    finally:
        client.close()


def recover_incomplete_jobs() -> None:
    # 기존 워커 종료 후, 이 단일 워커가 새 작업을 선점하기 전에만 호출한다.
    with SessionLocal() as db:
        job_ids = list(db.scalars(
            select(ModelJob.id).where(
                ModelJob.status.in_(["RUNNING", "CANCEL_REQUESTED"]),
                ModelJob.target_worker == WORKER_ID,
            )
        ))
    for job_id in job_ids:
        ensure_job_stopped(job_id)
        fail_entire_job(
            job_id=job_id,
            error_message=(
                "Worker interrupted; unfinished models "
                f"stopped during recovery: worker={WORKER_ID}"
            ),
        )
