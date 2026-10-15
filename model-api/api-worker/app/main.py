import os
from contextlib import asynccontextmanager
from typing import Any
from pathlib import Path
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    status,
)
from fastapi.responses import JSONResponse

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from datetime import datetime, timedelta, timezone
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

import logging
from app.database import engine, get_db
from app.models import (
    ModelJob,
    ModelRun,
    WorkerHeartbeat,
)
from app.schemas import (
    ExecutionModelResponse,
    ExecutionResponse,
    InputDatasetResponse,
    JobCreate,
    JobCreateResponse,
    JobErrorResponse,
    JobListResponse,
    JobResponse,
    JobResultResponse,
    JobStatus,
    ModelErrorDetail,
    ModelRunResponse,
    Paging,
    ReadyResponse,
    ResultAssetResponse,
    ResultDownloadResponse,
)

logger = logging.getLogger(__name__)

JOB_HOST_ROOT = Path(
    os.getenv(
        "JOB_HOST_ROOT",
        "/Data/model-jobs",
    )
)

JOB_WORKER_ROOT = Path(
    os.getenv(
        "JOB_WORKER_ROOT",
        "/jobs",
    )
)

RESULT_PUBLIC_ROOT = Path(
    os.getenv(
        "RESULT_PUBLIC_ROOT",
        str(JOB_HOST_ROOT),
    )
)

WORKER_READY_MAX_AGE_SECONDS = int(
    os.getenv(
        "WORKER_READY_MAX_AGE_SECONDS",
        "30",
    )
)

class CallbackConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    url: AnyHttpUrl | None

    @model_validator(mode="after")
    def validate_enabled_url(self) -> "CallbackConfig":
        if self.enabled and self.url is None:
            raise ValueError(
                "callback.url is required when callback.enabled is true"
            )

        return self


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=1, max_length=150)
    input: dict[str, Any]
    callback: CallbackConfig


class JobCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID

PUBLIC_STATUS = {
    "QUEUED": "queued",
    "RUNNING": "running",
    "SUCCEEDED": "success",
    "PARTIAL_SUCCESS": "partial_success",
    "FAILED": "failed",
    "CANCEL_REQUESTED": "running",
    "CANCELED": "cancelled",
}

PUBLIC_TO_DB_STATUSES = {
    "queued": ["QUEUED"],
    "running": [
        "RUNNING",
        "CANCEL_REQUESTED",
    ],
    "success": ["SUCCEEDED"],
    "partial_success": ["PARTIAL_SUCCESS"],
    "failed": ["FAILED"],
    "cancelled": ["CANCELED"],
}

def to_public_status(value: str) -> str:
    return PUBLIC_STATUS.get(
        value,
        value.lower(),
    )

def get_job(
    db: Session,
    job_id: UUID,
) -> ModelJob:
    query = (
        select(ModelJob)
        .options(selectinload(ModelJob.runs))
        .where(ModelJob.id == job_id)
    )

    job = db.scalar(query)

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    return job

def get_job_by_request_id(
    db: Session,
    model_id: str,
    request_id: str,
) -> ModelJob:
    job = db.scalar(
        select(ModelJob)
        .options(
            selectinload(ModelJob.runs)
        )
        .where(
            ModelJob.model_id == model_id,
            ModelJob.request_id == request_id,
        )
    )

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    return job

def get_queue_position(
    db: Session,
    job: ModelJob,
) -> int | None:
    if job.status != "QUEUED":
        return None

    query = (
        select(func.count())
        .select_from(ModelJob)
        .where(
            ModelJob.status == "QUEUED",
            or_(
                ModelJob.priority > job.priority,
                and_(
                    ModelJob.priority == job.priority,
                    ModelJob.created_at <= job.created_at,
                ),
            ),
        )
    )

    return int(db.scalar(query) or 0)

def build_job_response(
    db: Session,
    job: ModelJob,
) -> JobResponse:
    return JobResponse(
        job_id=job.id,
        model_id=job.model_id,
        request_id=job.request_id,
        scenario_id=job.scenario_id,
        requested_by=job.requested_by,
        status=to_public_status(job.status),
        priority=job.priority,
        queue_position=get_queue_position(db, job),
        request_data=job.request_data,
        callback_enabled=job.callback_enabled,
        callback_url=job.callback_url,
        error_message=job.error_message,

        created_at=job.created_at,
        submitted_at=job.created_at,
        updated_at=job.updated_at,

        started_at=job.started_at,
        finished_at=job.finished_at,
        models=[
            ModelRunResponse(
                model_type=run.model_type,
                status=to_public_status(run.status),
                container_name=run.container_name,
                exit_code=run.exit_code,
                result_path=run.result_path,
                log_path=run.log_path,
                result_data=run.result_data,
                error_message=run.error_message,
                started_at=run.started_at,
                finished_at=run.finished_at,
            )
            for run in job.runs
        ],
    )

TERMINAL_JOB_STATUSES = {
    "SUCCEEDED",
    "PARTIAL_SUCCESS",
    "FAILED",
    "CANCELED",
}

def request_job_cancel(
    db: Session,
    job: ModelJob,
) -> None:
    if job.status in TERMINAL_JOB_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "INVALID_JOB_STATE",
                "error_message": (
                    "Cancel is not allowed "
                    "because the job is already completed."
                ),
                "job_id": str(job.id),
                "current_status": to_public_status(
                    job.status
                ),
            },
        )

    job.cancel_requested = True
    job.updated_at = func.now()

    if job.status == "QUEUED":
        now = datetime.now(timezone.utc)

        job.status = "CANCELED"
        job.finished_at = now

        for run in job.runs:
            run.status = "CANCELED"
            run.error_message = (
                "Job was cancelled before execution"
            )
            run.finished_at = now
            run.updated_at = now
    else:
        job.status = "CANCEL_REQUESTED"

    db.commit()

@asynccontextmanager
async def lifespan(app: FastAPI):
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    yield

    engine.dispose()


app = FastAPI(
    title="CFD/HYSPLIT Model API",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "UP"}

@app.get(
    "/v1/ready",
    response_model=ReadyResponse,
    responses={
        503: {
            "model": ReadyResponse,
        },
    },
)
def ready(
    db: Session = Depends(get_db),
):
    checks: dict[str, str] = {
        "database": "down",
        "storage": "down",
        "worker": "down",
        "docker": "down",
        "cfd_image": "down",
        "hysplit_image": "down",
    }

    worker = None

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "up"

        heartbeat_limit = (
            datetime.now(timezone.utc)
            - timedelta(
                seconds=WORKER_READY_MAX_AGE_SECONDS
            )
        )

        worker = db.scalar(
            select(WorkerHeartbeat)
            .where(
                WorkerHeartbeat.ready.is_(True),
                WorkerHeartbeat.heartbeat_at >= heartbeat_limit,
            )
            .order_by(WorkerHeartbeat.heartbeat_at.desc())
            .limit(1)
        )

    except Exception:
        logger.exception(
            "Worker readiness query failed"
        )
        db.rollback()

    try:
        if (
            JOB_WORKER_ROOT.is_dir()
            and os.access(
                JOB_WORKER_ROOT,
                os.R_OK | os.W_OK,
            )
        ):
            checks["storage"] = "up"
    except OSError:
        pass

    if worker is not None:
        checks["worker"] = "up"

        details = worker.details or {}

        checks["docker"] = (
            "up"
            if details.get("docker")
            else "down"
        )
        checks["cfd_image"] = (
            "up"
            if details.get("cfd_image")
            else "down"
        )
        checks["hysplit_image"] = (
            "up"
            if details.get("hysplit_image")
            else "down"
        )

    is_ready = all(
        value == "up"
        for value in checks.values()
    )

    response = ReadyResponse(
        status=(
            "ready"
            if is_ready
            else "not_ready"
        ),
        checks=checks,
    )

    if not is_ready:
        return JSONResponse(
            status_code=503,
            content=response.model_dump(
                mode="json",
            ),
        )

    return response

def build_result_asset(
    run: ModelRun,
) -> ResultAssetResponse | None:
    if not run.result_path:
        return None

    result_data = run.result_data or {}

    return ResultAssetResponse(
        asset_id=result_data.get(
            "asset_id",
            f"{run.model_type.lower()}-result",
        ),
        name=result_data.get(
            "name",
            f"{run.model_type} result",
        ),
        model_type=run.model_type,
        media_type=result_data.get(
            "media_type",
            (
                "application/x-directory"
                if run.model_type == "CFD"
                else "application/octet-stream"
            ),
        ),
        size_bytes=result_data.get(
            "size_bytes"
        ),
        checksum=result_data.get(
            "checksum"
        ),
    )

def to_public_result_path(
    result_path: str,
) -> str:
    path = Path(result_path)

    try:
        relative_path = path.relative_to(
            JOB_HOST_ROOT
        )
    except ValueError:
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": (
                    "INVALID_RESULT_PATH"
                ),
                "error_message": (
                    "Stored result path is outside "
                    "JOB_HOST_ROOT"
                ),
                "retryable": False,
            },
        )

    return str(
        RESULT_PUBLIC_ROOT
        / relative_path
    )

router = APIRouter(
    prefix="/jobs",
    tags=["jobs"],
)

@router.get(
    "",
    response_model=JobListResponse,
)
def list_jobs(
    job_status: JobStatus | None = Query(
        default=None,
        alias="status",
    ),
    model_id: str | None = Query(
        default=None,
    ),
    submitted_after: datetime | None = Query(
        default=None,
    ),
    submitted_before: datetime | None = Query(
        default=None,
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
    cursor: str | None = Query(
        default=None,
    ),
    db: Session = Depends(get_db),
) -> JobListResponse:
    query = (
        select(ModelJob)
        .options(
            selectinload(ModelJob.runs)
        )
    )

    if job_status is not None:
        query = query.where(
            ModelJob.status.in_(
                PUBLIC_TO_DB_STATUSES[
                    job_status
                ]
            )
        )

    if model_id is not None:
        query = query.where(
            ModelJob.model_id == model_id
        )

    if submitted_after is not None:
        query = query.where(
            ModelJob.created_at
            >= submitted_after
        )

    if submitted_before is not None:
        query = query.where(
            ModelJob.created_at
            <= submitted_before
        )

    if cursor is not None:
        try:
            cursor_id = UUID(cursor)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "INVALID_CURSOR",
                    "error_message": (
                        "cursor must be a valid job UUID"
                    ),
                },
            ) from exc

        cursor_job = db.scalar(
            select(ModelJob).where(
                ModelJob.id == cursor_id
            )
        )

        if cursor_job is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "INVALID_CURSOR",
                    "error_message": (
                        "The cursor job does not exist"
                    ),
                },
            )

        query = query.where(
            or_(
                ModelJob.created_at
                < cursor_job.created_at,
                and_(
                    ModelJob.created_at
                    == cursor_job.created_at,
                    ModelJob.id
                    < cursor_job.id,
                ),
            )
        )

    query = (
        query
        .order_by(
            ModelJob.created_at.desc(),
            ModelJob.id.desc(),
        )
        .limit(limit + 1)
    )

    jobs = list(
        db.scalars(query).all()
    )

    has_next = len(jobs) > limit

    if has_next:
        jobs = jobs[:limit]

    next_cursor = None

    if has_next and jobs:
        next_cursor = str(
            jobs[-1].id
        )

    return JobListResponse(
        items=[
            build_job_response(db, job)
            for job in jobs
        ],
        paging=Paging(
            limit=limit,
            next_cursor=next_cursor,
        ),
    )


@router.post(
    "",
    response_model=JobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_job(
    payload: JobCreate,
    db: Session = Depends(get_db),
) -> JobCreateResponse:
    existing_job = db.scalar(
        select(ModelJob).where(
            ModelJob.model_id
            == payload.model_id,
            ModelJob.request_id
            == payload.request_id,
        )
    )

    if existing_job is not None:
        return JobCreateResponse(
            job_id=existing_job.id,
        )

    callback_url = None

    if (
        payload.callback.enabled
        and payload.callback.url is not None
    ):
        callback_url = str(
            payload.callback.url
        )

    job = ModelJob(
        model_id=payload.model_id,
        request_id=payload.request_id,
        status="QUEUED",
        priority=0,
        request_data=payload.model_dump(
            mode="json",
        ),
        callback_enabled=payload.callback.enabled,
        callback_url=callback_url,
        runs=[
            ModelRun(
                model_type="CFD",
                status="QUEUED",
            ),
            ModelRun(
                model_type="HYSPLIT",
                status="QUEUED",
            ),
        ],
    )

    db.add(job)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()

        existing_job = db.scalar(
            select(ModelJob).where(
                ModelJob.model_id
                == payload.model_id,
                ModelJob.request_id
                == payload.request_id,
            )
        )

        if existing_job is None:
            raise

        return JobCreateResponse(
            job_id=existing_job.id,
        )

    return JobCreateResponse(
        job_id=job.id,
    )

@router.get(
    "/by-request/{request_id}",
    response_model=JobResponse,
)
def get_job_by_request(
    request_id: str,
    model_id: str = Query(
        default="smoke-hybrid"
    ),
    db: Session = Depends(get_db),
) -> JobResponse:
    job = get_job_by_request_id(
        db=db,
        model_id=model_id,
        request_id=request_id,
    )

    return build_job_response(db, job)

@router.post(
    "/by-request/{request_id}/cancel",
    response_model=JobResponse,
)
def cancel_job_by_request(
    request_id: str,
    model_id: str = Query(
        default="smoke-hybrid"
    ),
    db: Session = Depends(get_db),
) -> JobResponse:
    job = get_job_by_request_id(
        db=db,
        model_id=model_id,
        request_id=request_id,
    )

    request_job_cancel(
        db=db,
        job=job,
    )

    job = get_job(db, job.id)

    return build_job_response(db, job)

@router.get(
    "/{job_id}/result",
    response_model=JobResultResponse,
)
def get_job_result(
    job_id: UUID,
    db: Session = Depends(get_db),
) -> JobResultResponse:
    job = get_job(db, job_id)

    result_status = {
        "SUCCEEDED": "available",
        "PARTIAL_SUCCESS": "partial",
    }.get(
        job.status,
        "not_available",
    )

    assets: list[
        ResultAssetResponse
    ] = []

    for run in job.runs:
        asset = build_result_asset(run)

        if asset is not None:
            assets.append(asset)

    model_input = job.request_data.get(
        "input",
        {},
    )

    input_datasets: list[
        InputDatasetResponse
    ] = []

    fireline_path = model_input.get(
        "fireline_path"
    )

    if isinstance(fireline_path, str):
        input_datasets.append(
            InputDatasetResponse(
                dataset_id="fireline",
                dataset_version=job.request_id,
                source_uri=fireline_path,
                checksum=None,
            )
        )

    return JobResultResponse(
        job_id=job.id,
        status=result_status,
        execution=ExecutionResponse(
            started_at=job.started_at,
            finished_at=job.finished_at,
            models=[
                ExecutionModelResponse(
                    model_type=run.model_type,
                    status=to_public_status(
                        run.status
                    ),
                    started_at=run.started_at,
                    finished_at=run.finished_at,
                )
                for run in job.runs
            ],
        ),
        input_parameters=model_input,
        input_datasets=input_datasets,
        provenance={
            "api_version": "1.0.0",
            "model_id": job.model_id,
            "request_id": job.request_id,
        },
        assets=assets,
    )

@router.get(
    "/{job_id}/result/download",
    response_model=ResultDownloadResponse,
)
def get_result_download(
    job_id: UUID,
    asset_id: str = Query(...),
    db: Session = Depends(get_db),
) -> ResultDownloadResponse:
    job = get_job(db, job_id)

    if job.status not in {
        "SUCCEEDED",
        "PARTIAL_SUCCESS",
    }:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": (
                    "RESULT_NOT_AVAILABLE"
                ),
                "error_message": (
                    "The result is not available"
                ),
                "retryable": True,
            },
        )

    for run in job.runs:
        asset = build_result_asset(run)

        if asset is None:
            continue

        if asset.asset_id != asset_id:
            continue

        public_path = to_public_result_path(
            run.result_path
        )

        source_uri = (
            Path(public_path)
            .absolute()
            .as_uri()
        )

        return ResultDownloadResponse(
            asset_id=asset.asset_id,
            method="LOCAL_FILE",
            local_path=public_path,
            source_uri=source_uri,
            media_type=asset.media_type,
            size_bytes=asset.size_bytes,
            checksum=asset.checksum,
        )

    raise HTTPException(
        status_code=404,
        detail={
            "error_code": "ASSET_NOT_FOUND",
            "error_message": (
                "The requested result asset "
                "was not found"
            ),
            "retryable": False,
        },
    )

@router.get(
    "/{job_id}/error",
    response_model=JobErrorResponse,
)
def get_job_error(
    job_id: UUID,
    db: Session = Depends(get_db),
) -> JobErrorResponse:
    job = get_job(db, job_id)

    failed_runs = [
        run
        for run in job.runs
        if (
            run.status
            in {
                "FAILED",
                "CANCELED",
            }
            or run.error_message
        )
    ]

    if (
        not failed_runs
        and not job.error_message
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": (
                    "ERROR_NOT_AVAILABLE"
                ),
                "error_message": (
                    "No error is available "
                    "for this job"
                ),
                "retryable": False,
            },
        )

    is_cancelled = (
        job.status == "CANCELED"
    )

    return JobErrorResponse(
        job_id=job.id,
        error_code=(
            "JOB_CANCELED"
            if is_cancelled
            else "MODEL_EXECUTION_FAILED"
        ),
        error_message=(
            job.error_message
            or "One or more models failed"
        ),
        retryable=not is_cancelled,
        occurred_at=job.finished_at,
        details=[
            ModelErrorDetail(
                model_type=run.model_type,
                exit_code=run.exit_code,
                message=(
                    run.error_message
                    or "Model execution failed"
                ),
                log_path=run.log_path,
            )
            for run in failed_runs
        ],
    )

@router.get(
    "/{job_id}",
    response_model=JobResponse,
)
def get_job_detail(
    job_id: UUID,
    db: Session = Depends(get_db),
) -> JobResponse:
    job = get_job(db, job_id)

    return build_job_response(db, job)


@router.post(
    "/{job_id}/cancel",
    response_model=JobResponse,
)
def cancel_job(
    job_id: UUID,
    db: Session = Depends(get_db),
) -> JobResponse:
    job = get_job(db, job_id)

    request_job_cancel(
        db=db,
        job=job,
    )

    job = get_job(db, job.id)

    return build_job_response(db, job)

app.include_router(
    router,
    prefix="/v1",
)

# 기존 호출 호환용
app.include_router(
    router,
    prefix="/api/v1",
    include_in_schema=False,
)

