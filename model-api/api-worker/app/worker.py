import logging
import os
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Thread
from uuid import UUID
from app.callback import run_callback_dispatcher
from app.docker_runner import run_model_container
from app.recovery import ensure_job_stopped, recover_incomplete_jobs
from app.job_service import (
    WORKER_ID,
    claim_next_job,
    fail_entire_job,
    update_job_heartbeat,
)

import socket
from datetime import datetime, timezone
from pathlib import Path

import docker
from sqlalchemy.dialects.postgresql import insert

from app.database import SessionLocal
from app.models import WorkerHeartbeat


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format=(
        "%(asctime)s "
        "%(levelname)s "
        "%(name)s "
        "%(message)s"
    ),
)

logger = logging.getLogger(__name__)

shutdown_event = Event()

POLL_INTERVAL = float(
    os.getenv("WORKER_POLL_INTERVAL_SECONDS", "2")
)

CFD_SIMULATION_SECONDS = float(
    os.getenv("CFD_SIMULATION_SECONDS", "8")
)

HYSPLIT_SIMULATION_SECONDS = float(
    os.getenv("HYSPLIT_SIMULATION_SECONDS", "4")
)

WORKER_HEARTBEAT_INTERVAL_SECONDS = float(
    os.getenv("WORKER_HEARTBEAT_INTERVAL_SECONDS", "5")
)

JOB_WORKER_ROOT = Path(
    os.getenv("JOB_WORKER_ROOT", "/jobs")
)

CFD_IMAGE = os.getenv("CFD_IMAGE", "cfd-model:1.0")
HYSPLIT_IMAGE = os.getenv("HYSPLIT_IMAGE", "hysplit-model:1.0")


def handle_shutdown(
    signum: int,
    frame: object,
) -> None:
    logger.info("Shutdown requested: signal=%s", signum)
    shutdown_event.set()


def wait_with_heartbeat(
    job_id: UUID,
    duration_seconds: float,
) -> None:
    """
    모의 실행 중 2초마다 heartbeat를 갱신한다.
    실제 모델 연결 단계에서는 Docker 상태 감시로 교체한다.
    """

    remaining = duration_seconds

    while remaining > 0:
        if shutdown_event.is_set():
            raise RuntimeError("Worker shutdown requested")

        sleep_seconds = min(2.0, remaining)

        time.sleep(sleep_seconds)
        remaining -= sleep_seconds

        update_job_heartbeat(job_id)

def process_job(job_id: UUID) -> None:
    """
    한 통합 작업 안에서 CFD와 HYSPLIT을 동시에 실행한다.
    """

    logger.info("Processing job: job_id=%s", job_id)

    try:
        with ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="model",
        ) as executor:
            cfd_future = executor.submit(
                run_model_container,
                job_id,
                "CFD"
            )

            hysplit_future = executor.submit(
                run_model_container,
                job_id,
                "HYSPLIT"
            )

            # 두 모델이 모두 끝날 때까지 대기
            cfd_future.result()
            hysplit_future.result()

        logger.info(
            "Finished processing job: job_id=%s",
            job_id,
        )

    except Exception as exc:
        logger.exception(
            "Unexpected job processing error: job_id=%s",
            job_id,
        )

        ensure_job_stopped(job_id)

        fail_entire_job(
            job_id=job_id,
            error_message=str(exc),
        )

def update_worker_readiness() -> None:
    now = datetime.now(timezone.utc)

    details = {
        "docker": False,
        "storage": False,
        "cfd_image": False,
        "hysplit_image": False,
    }

    try:
        JOB_WORKER_ROOT.mkdir(parents=True, exist_ok=True)

        test_path = (
            JOB_WORKER_ROOT
            / f".readiness-{WORKER_ID}"
        )

        test_path.write_text("ok", encoding="utf-8")
        test_path.unlink()

        details["storage"] = True
    except OSError:
        logger.exception("Storage readiness check failed")

    client = None

    try:
        client = docker.from_env()
        client.ping()
        details["docker"] = True

        client.images.get(CFD_IMAGE)
        details["cfd_image"] = True

        client.images.get(HYSPLIT_IMAGE)
        details["hysplit_image"] = True
    except Exception:
        logger.exception("Docker readiness check failed")
    finally:
        if client is not None:
            client.close()

    ready = all(details.values())

    with SessionLocal() as db:
        with db.begin():
            statement = (
                insert(WorkerHeartbeat)
                .values(
                    worker_id=WORKER_ID,
                    ready=ready,
                    details=details,
                    heartbeat_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[
                        WorkerHeartbeat.worker_id
                    ],
                    set_={
                        "ready": ready,
                        "details": details,
                        "heartbeat_at": now,
                    },
                )
            )

            db.execute(statement)


def run_worker_heartbeat() -> None:
    while not shutdown_event.is_set():
        try:
            update_worker_readiness()
        except Exception:
            logger.exception(
                "Worker heartbeat update failed"
            )

        shutdown_event.wait(
            WORKER_HEARTBEAT_INTERVAL_SECONDS
        )


def run_worker() -> None:
    logger.info(
        "Worker started: poll_interval=%s",
        POLL_INTERVAL,
    )

    recover_incomplete_jobs()

    callback_thread = Thread(
        target=run_callback_dispatcher,
        args=(shutdown_event,),
        name="callback-dispatcher",
        daemon=True,
    )
    callback_thread.start()

    heartbeat_thread = Thread(
        target=run_worker_heartbeat,
        name="worker-heartbeat",
        daemon=True,
    )
    heartbeat_thread.start()

    try:
        while not shutdown_event.is_set():
            job_id = claim_next_job()

            if job_id is None:
                shutdown_event.wait(POLL_INTERVAL)
                continue

            process_job(job_id)

    finally:
        shutdown_event.set()
        callback_thread.join(timeout=10)
        heartbeat_thread.join(timeout=10)

    logger.info("Worker stopped")

if __name__ == "__main__":
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    run_worker()
