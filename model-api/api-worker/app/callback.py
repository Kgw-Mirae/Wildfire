from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import CallbackEvent, ModelJob, ModelRun


logger = logging.getLogger(__name__)


def _positive_float(name: str, default: float) -> float:
    raw_value = os.getenv(name, str(default))

    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number: {raw_value}") from exc

    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero: {value}")

    return value


JOB_HOST_ROOT = os.getenv("JOB_HOST_ROOT", "/Data/model-jobs")

CALLBACK_POLL_INTERVAL_SECONDS = _positive_float(
    "CALLBACK_POLL_INTERVAL_SECONDS",
    2.0,
)
CALLBACK_TIMEOUT_SECONDS = _positive_float(
    "CALLBACK_TIMEOUT_SECONDS",
    10.0,
)
MODEL_TERMINAL_STATUSES = {
    "SUCCEEDED",
    "FAILED",
    "CANCELED",
}

@dataclass(frozen=True)
class ClaimedCallback:
    event_id: UUID
    callback_url: str
    payload: dict[str, Any]
    attempt: int


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def enqueue_model_callback(
    db: Session,
    job: ModelJob,
    run: ModelRun,
    event_type: str,
) -> None:
    if not job.callback_enabled:
        return

    if not job.callback_url:
        logger.warning(
            "Callback URL missing: "
            "job_id=%s",
            job.id,
        )
        return

    existing_id = db.scalar(
        select(CallbackEvent.id).where(
            CallbackEvent.job_id == job.id,
            CallbackEvent.model_type
            == run.model_type,
            CallbackEvent.event_type
            == event_type,
        )
    )

    if existing_id is not None:
        return

    if event_type == "MODEL_RUNNING":
        callback_status = "RUNNING"
        result_path = ""
        message = ""

    elif event_type == "MODEL_COMPLETED":
        if run.status == "SUCCEEDED":
            callback_status = "SUCCESS"
            result_path = (
                run.result_path or ""
            )
            message = ""

        elif run.status == "CANCELED":
            callback_status = "FAILED"
            result_path = ""
            message = (
                run.error_message
                or "Model execution "
                "was cancelled"
            )

        else:
            callback_status = "FAILED"
            result_path = ""
            message = (
                run.error_message
                or f"{run.model_type} "
                   "execution failed"
            )
    else:
        raise ValueError(
            "Unsupported callback event: "
            f"{event_type}"
        )

    payload = {
        "job_id": str(job.id),
        "job_status": callback_status,
        "result_path": result_path,
        "model_type": run.model_type,
        "message": message,
    }

    db.add(
        CallbackEvent(
            job_id=job.id,
            model_type=run.model_type,
            event_type=event_type,
            status="PENDING",
            payload=payload,
            attempts=0,
            next_attempt_at=utc_now(),
        )
    )

def _claim_next_callback() -> ClaimedCallback | None:
    now = utc_now()

    with SessionLocal() as db:
        with db.begin():
            event = db.scalar(
                select(CallbackEvent)
                .where(
                    CallbackEvent.status == "PENDING",
                    CallbackEvent.next_attempt_at <= now,
                )
                .order_by(
                    CallbackEvent.next_attempt_at.asc(),
                    CallbackEvent.created_at.asc(),
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )

            if event is None:
                return None

            callback_url = db.scalar(
                select(ModelJob.callback_url).where(
                    ModelJob.id == event.job_id
                )
            )

            if not callback_url:
                event.status = "FAILED"
                event.attempts += 1
                event.last_error = "Callback URL not found"
                return None

            event.status = "SENDING"
            event.attempts += 1

            stored_payload = dict(event.payload)
            payload = {
                "job_id": str(event.job_id),
                "job_status": str(
                    stored_payload.get("job_status", "FAILED")
                ),
                "result_path": str(
                    stored_payload.get("result_path") or ""
                ),
                "model_type": event.model_type,
                "message": str(
                    stored_payload.get("message") or ""
                ),
            }

            claimed = ClaimedCallback(
                event_id=event.id,
                callback_url=str(callback_url),
                payload=payload,
                attempt=event.attempts,
            )

        return claimed


def _post_json(
    callback_url: str,
    payload: dict[str, Any],
) -> int:
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    request = Request(
        callback_url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "model-api-callback/1.0",
        },
        method="POST",
    )

    with urlopen(
        request,
        timeout=CALLBACK_TIMEOUT_SECONDS,
    ) as response:
        status_code = int(response.status)
        # 연결을 재사용하지 않더라도 응답 본문을 소비한다.
        response.read(65536)

    if not 200 <= status_code < 300:
        raise RuntimeError(
            f"Callback returned HTTP {status_code}"
        )

    return status_code


def _mark_delivered(event_id: UUID, http_status: int) -> None:
    with SessionLocal() as db:
        with db.begin():
            event = db.scalar(
                select(CallbackEvent)
                .where(CallbackEvent.id == event_id)
                .with_for_update()
            )

            if event is None:
                return

            event.status = "DELIVERED"
            event.last_http_status = http_status
            event.last_error = None
            event.delivered_at = utc_now()


def _mark_failed(
    event_id: UUID,
    error_message: str,
    http_status: int | None = None,
) -> None:
    with SessionLocal() as db:
        with db.begin():
            event = db.scalar(
                select(CallbackEvent)
                .where(CallbackEvent.id == event_id)
                .with_for_update()
            )

            if event is None:
                return

            event.status = "FAILED"
            event.last_http_status = http_status
            event.last_error = error_message[:10000]


def deliver_one_callback() -> bool:
    claimed = _claim_next_callback()

    if claimed is None:
        return False

    try:
        http_status = _post_json(
            claimed.callback_url,
            claimed.payload,
        )
    except HTTPError as exc:
        error_message = f"HTTP {exc.code}: {exc.reason}"
        _mark_failed(
            claimed.event_id,
            error_message,
            http_status=exc.code,
        )
        logger.warning(
            "Callback failed: event_id=%s attempt=%s error=%s",
            claimed.event_id,
            claimed.attempt,
            error_message,
        )
    except (URLError, TimeoutError, OSError, RuntimeError) as exc:
        _mark_failed(claimed.event_id, str(exc))
        logger.warning(
            "Callback failed: event_id=%s attempt=%s error=%s",
            claimed.event_id,
            claimed.attempt,
            exc,
        )
    except Exception as exc:
        _mark_failed(claimed.event_id, str(exc))
        logger.exception(
            "Unexpected callback error: event_id=%s attempt=%s",
            claimed.event_id,
            claimed.attempt,
        )
    else:
        _mark_delivered(claimed.event_id, http_status)
        logger.info(
            "Callback delivered: event_id=%s attempt=%s http_status=%s",
            claimed.event_id,
            claimed.attempt,
            http_status,
        )

    return True


def run_callback_dispatcher(shutdown_event: Event) -> None:
    logger.info(
        "Callback dispatcher started: poll_interval=%s retry=false",
        CALLBACK_POLL_INTERVAL_SECONDS,
    )

    while not shutdown_event.is_set():
        delivered_or_failed = deliver_one_callback()

        if not delivered_or_failed:
            shutdown_event.wait(CALLBACK_POLL_INTERVAL_SECONDS)

    logger.info("Callback dispatcher stopped")

