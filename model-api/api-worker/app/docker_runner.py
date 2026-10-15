from __future__ import annotations

import glob
import json
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import docker
from docker.errors import DockerException
from docker.types import Ulimit
from sqlalchemy import select

from app.database import SessionLocal
from app.job_service import (
    complete_model_run,
    mark_model_running,
    update_job_heartbeat,
)
from app.models import ModelJob, ModelRun
from app.recovery import ensure_job_stopped

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer: {raw_value}") from exc

    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero: {value}")

    return value


JOB_HOST_ROOT = Path(os.getenv("JOB_HOST_ROOT", "/Data/model-jobs"))
JOB_WORKER_ROOT = Path(os.getenv("JOB_WORKER_ROOT", "/jobs"))

CFD_IMAGE = os.getenv("CFD_IMAGE", "cfd-model:1.0")
CFD_MPI_NP = _env_int("CFD_MPI_NP", 16)
CFD_COMMON_FILE_ROOT = Path(
    os.getenv("CFD_COMMON_FILE_ROOT", "/Data/CFD/common/file")
)
CFD_RDAPS_ROOT = Path(
    os.getenv("CFD_RDAPS_ROOT", "/Data/CFD/input/RDAPS-KIM")
)
CFD_FIRELINE_HOST_ROOT = Path(
    os.getenv("CFD_FIRELINE_SOURCE_ROOT", "/Data/CFD/input/fireline")
)
CFD_FIRELINE_WORKER_ROOT = Path(
    os.getenv("CFD_FIRELINE_WORKER_ROOT", "/cfd-fireline-source")
)
CFD_DATA_TEMPLATE_WORKER_ROOT = Path(
    os.getenv("CFD_DATA_TEMPLATE_WORKER_ROOT", "/cfd-data-template")
)

HYSPLIT_IMAGE = os.getenv("HYSPLIT_IMAGE", "hysplit-model:1.0")
HYSPLIT_MPI_NP = _env_int("HYSPLIT_MPI_NP", 6)
HYSPLIT_GFS_ROOT = Path(
    os.getenv("HYSPLIT_GFS_ROOT", "/Data/Hysplit/INPUT/gfs0p25")
)
HYSPLIT_SOURCE_WORKER_ROOT = Path(
    os.getenv("HYSPLIT_SOURCE_WORKER_ROOT", "/hysplit-source")
)
HYSPLIT_TEMPLATE_SUBDIR = os.getenv(
    "HYSPLIT_TEMPLATE_SUBDIR",
    "2026/20260801",
)

MODEL_UID = _env_int("MODEL_UID", 1000)
MODEL_GID = _env_int("MODEL_GID", 1000)
MODEL_POLL_INTERVAL_SECONDS = float(
    os.getenv("MODEL_POLL_INTERVAL_SECONDS", "2")
)
MODEL_CANCEL_GRACE_SECONDS = _env_int("MODEL_CANCEL_GRACE_SECONDS", 30)

HYSPLIT_INPUT_FILES = (
    "ASCDATA.CFG",
    "CONC.CFG",
    "CONTROL",
    "EMITIMES",
    "SETUP.CFG",
)

DEFAULT_DOMAIN_CONFIG: dict[str, int | float] = {
    "resolution_m": 200,
    "vertical_resolution_m": 50,
    "kmax": 40,
    "time_step_s": 2.0,
    "output_interval_s": 600,
    "domain_size_m": 20000,
}

DOMAIN_CONFIG_ALIASES = {
    "resolutionM": "resolution_m",
    "verticalResolutionM": "vertical_resolution_m",
    "timeStepS": "time_step_s",
    "outputIntervalS": "output_interval_s",
    "domainSizeM": "domain_size_m",
}


@dataclass(frozen=True)
class ModelSpec:
    image: str
    name: str
    working_dir: str
    environment: dict[str, str]
    volumes: dict[str, dict[str, str]]
    labels: dict[str, str]
    log_worker_path: Path
    log_host_path: Path
    result_worker_path: Path
    result_host_path: Path
    expected_result_worker_path: Path | None
    run_kwargs: dict[str, Any]


def _load_job(job_id: UUID) -> tuple[dict[str, Any], str]:
    with SessionLocal() as db:
        job = db.scalar(
            select(ModelJob).where(ModelJob.id == job_id)
        )

        if job is None:
            raise RuntimeError(f"Job not found: job_id={job_id}")

        return dict(job.request_data), job.request_id


def _is_cancel_requested(job_id: UUID) -> bool:
    with SessionLocal() as db:
        value = db.scalar(
            select(ModelJob.cancel_requested).where(ModelJob.id == job_id)
        )

    return bool(value)


def _save_container_info(
    job_id: UUID,
    model_type: str,
    container_id: str,
    container_name: str,
    log_path: Path,
) -> None:
    with SessionLocal() as db:
        with db.begin():
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
                    f"Model run not found: job_id={job_id}, model={model_type}"
                )

            run.container_id = container_id
            run.container_name = container_name
            run.log_path = str(log_path)

def _extract_input(
    request_data: dict[str, Any],
) -> dict[str, Any]:
    model_input = request_data.get("input")

    if isinstance(model_input, dict):
        merged_input = dict(model_input)

        parameters = model_input.get("parameters")
        if isinstance(parameters, dict):
            merged_input.update(parameters)

        return merged_input

    # 이전에 생성된 작업 호환
    parameters = request_data.get(
        "parameters"
    )

    if isinstance(parameters, dict):
        return parameters

    merged: dict[str, Any] = {}

    for key in (
        "commonParameters",
        "cfdParameters",
        "hysplitParameters",
    ):
        value = request_data.get(key)

        if isinstance(value, dict):
            merged.update(value)

    return merged

def _build_domain_config(
    model_input: dict[str, Any],
) -> dict[str, int | float]:
    supplied = model_input.get(
        "domain_config"
    )

    # 이전 요청 호환
    if supplied is None:
        supplied = model_input.get(
            "domainConfig",
            {},
        )

    if not isinstance(supplied, dict):
        raise ValueError(
            "input.domain_config "
            "must be an object"
        )

    normalized: dict[str, Any] = {}

    for key, value in supplied.items():
        normalized[
            DOMAIN_CONFIG_ALIASES.get(
                key,
                key,
            )
        ] = value

    unknown_keys = (
        set(normalized)
        - set(DEFAULT_DOMAIN_CONFIG)
    )

    if unknown_keys:
        names = ", ".join(
            sorted(unknown_keys)
        )

        raise ValueError(
            "Unknown input.domain_config "
            f"fields: {names}"
        )

    result = {
        **DEFAULT_DOMAIN_CONFIG,
        **normalized,
    }

    integer_fields = (
        "resolution_m",
        "vertical_resolution_m",
        "kmax",
        "output_interval_s",
        "domain_size_m",
    )

    for key in integer_fields:
        value = result[key]

        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
        ):
            raise ValueError(
                "input.domain_config."
                f"{key} must be a "
                "positive integer"
            )

    time_step = result["time_step_s"]

    if (
        isinstance(time_step, bool)
        or not isinstance(
            time_step,
            (int, float),
        )
        or time_step <= 0
    ):
        raise ValueError(
            "input.domain_config.time_step_s "
            "must be a positive number"
        )

    result["time_step_s"] = float(
        time_step
    )

    return result

def _resolve_fireline_files(
    fireline_path: str,
) -> list[Path]:
    if not fireline_path:
        raise ValueError(
            "input.fireline_path is required"
        )

    if not os.path.isabs(fireline_path):
        raise ValueError(
            "input.fireline_path must be "
            "an absolute host path"
        )

    host_root = Path(
        os.path.abspath(
            os.path.normpath(
                CFD_FIRELINE_HOST_ROOT
            )
        )
    )

    normalized_path = Path(
        os.path.abspath(
            os.path.normpath(
                fireline_path
            )
        )
    )

    try:
        relative_path = (
            normalized_path.relative_to(
                host_root
            )
        )
    except ValueError as exc:
        raise ValueError(
            "input.fireline_path must be "
            f"under {host_root}: "
            f"{fireline_path}"
        ) from exc

    worker_path = (
        CFD_FIRELINE_WORKER_ROOT
        / relative_path
    )

    if glob.has_magic(str(worker_path)):
        candidates = [
            Path(value)
            for value in glob.glob(
                str(worker_path)
            )
        ]
    elif worker_path.is_dir():
        candidates = list(
            worker_path.glob(
                "*.geojson"
            )
        )
    elif worker_path.is_file():
        candidates = [worker_path]
    else:
        candidates = []

    allowed_root = (
        CFD_FIRELINE_WORKER_ROOT.resolve()
    )

    resolved_files: list[Path] = []

    for candidate in candidates:
        if (
            not candidate.is_file()
            or candidate.suffix.lower()
            != ".geojson"
        ):
            continue

        resolved = candidate.resolve()

        try:
            resolved.relative_to(
                allowed_root
            )
        except ValueError as exc:
            raise ValueError(
                "Fireline path escapes "
                "allowed directory: "
                f"{candidate}"
            ) from exc

        resolved_files.append(resolved)

    resolved_files = sorted(
        set(resolved_files)
    )

    if not resolved_files:
        raise FileNotFoundError(
            "No GeoJSON files matched "
            "input.fireline_path: "
            f"{fireline_path}"
        )

    return resolved_files

def _copy_tree_contents(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(f"Template directory not found: {source}")

    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        symlinks=False,
    )


def _chown_tree(path: Path, uid: int, gid: int) -> None:
    try:
        os.chown(path, uid, gid)

        for root, directories, files in os.walk(path):
            for name in directories:
                os.chown(Path(root) / name, uid, gid)

            for name in files:
                os.chown(Path(root) / name, uid, gid)

    except PermissionError:
        logger.warning(
            "Could not change ownership: path=%s uid=%s gid=%s",
            path,
            uid,
            gid,
        )


def _prepare_cfd(
    job_id: UUID,
    request_data: dict[str, Any],
) -> ModelSpec:
    model_input = _extract_input(
        request_data
    )
    
    forecast_hours = model_input.get(
        "forecast_hours",
        10,
    )

    if (
        isinstance(forecast_hours, bool)
        or not isinstance(forecast_hours, (int, float))
        or forecast_hours <= 0
    ):
        raise ValueError(
            "input.parameters.forecast_hours "
            "must be a positive number"
        )


    fireline_path = model_input.get(
        "fireline_path"
    )

    # 이전 요청 호환
    if fireline_path is None:
        fireline_path = model_input.get(
            "firelinePattern"
        )

    if fireline_path is None:
        fireline_path = model_input.get(
            "firelineFile"
        )

    if not isinstance(
        fireline_path,
        str,
    ):
        raise ValueError(
            "input.fireline_path "
            "must be a string"
        )

    fireline_sources = (
        _resolve_fireline_files(
            fireline_path
        )
    )

    domain_config = (
        _build_domain_config(
            model_input
        )
    )

    forecast_total_minutes = int(round(float(forecast_hours) * 60))
    forecast_duration_h, forecast_duration_m = divmod(
        forecast_total_minutes,
        60,
    )

    domain_config["forecast_duration_h"] = forecast_duration_h
    domain_config["forecast_duration_m"] = forecast_duration_m

    worker_root = JOB_WORKER_ROOT / str(job_id)
    host_root = JOB_HOST_ROOT / str(job_id)

    data_dir = worker_root / "cfd" / "data"
    fireline_dir = worker_root / "cfd" / "fireline"
    domain_dir = worker_root / "cfd" / "domain"
    moment_dir = worker_root / "cfd" / "moment-results"
    result_dir = worker_root / "cfd" / "results"
    topo_dir = worker_root / "cfd" / "topo"
    event_dir = worker_root / "events"
    rdaps_result_dir = worker_root / "cfd" / "rdaps-results"
    logs_dir = worker_root / "cfd" / "logs"

    for directory in (
        data_dir,
        fireline_dir,
        domain_dir,
        moment_dir,
        result_dir,
        topo_dir,
        rdaps_result_dir,
        logs_dir,
        event_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    # /app/sh/data bind mount가 이미지 내부 파일을 가리므로 정적 기반 파일을 복사한다.
    _copy_tree_contents(CFD_DATA_TEMPLATE_WORKER_ROOT, data_dir)
    (data_dir / "Domain").mkdir(parents=True, exist_ok=True)

    copied_names: set[str] = set()

    for source in fireline_sources:
        if source.name in copied_names:
            raise ValueError(f"Duplicate fireline filename: {source.name}")

        shutil.copy2(source, fireline_dir / source.name)
        copied_names.add(source.name)

    domain_config_path = domain_dir / "domain_config.json"
    domain_config_path.write_text(
        json.dumps(domain_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    _chown_tree(worker_root / "cfd", MODEL_UID, MODEL_GID)
    _chown_tree(event_dir, MODEL_UID, MODEL_GID)

    host_cfd_root = host_root / "cfd"
    log_worker_path = worker_root / "cfd" / "model.log"
    log_host_path = host_cfd_root / "model.log"
    result_host_path = host_cfd_root / "results"

    volumes = {
        str(CFD_COMMON_FILE_ROOT): {
            "bind": "/app/file",
            "mode": "ro,z",
        },
        str(host_cfd_root / "data"): {
            "bind": "/app/sh/data",
            "mode": "rw,z",
        },
        str(CFD_RDAPS_ROOT): {
            "bind": "/app/sh/data/RDAPS-KIM",
            "mode": "ro,z",
        },
        str(host_cfd_root / "fireline"): {
            "bind": "/app/sh/data/Geojson",
            "mode": "ro,z",
        },
        str(host_cfd_root / "domain" / "domain_config.json"): {
            "bind": "/app/sh/data/Domain/domain_config.json",
            "mode": "ro,z",
        },
        str(host_cfd_root / "moment-results"): {
            "bind": "/app/sh/2_moment/results",
            "mode": "rw,z",
        },
        str(host_cfd_root / "results"): {
            "bind": "/app/sh/3_postproc/results",
            "mode": "rw,z",
        },
        str(host_root / "events"): {
            "bind": "/job-events",
            "mode": "rw,z",
        },
        str(host_cfd_root / "topo"): {
            "bind": "/app/sh/0_TOPO/top",
            "mode": "rw,z",
        },
        str(host_cfd_root / "rdaps-results"): {
            "bind": "/app/sh/1_RDAPS/txt_results",
            "mode": "rw,z",
        },
        str(host_cfd_root / "logs"): {
           "bind": "/app/sh/logs",
           "mode": "rw,z",
        },
    }

    return ModelSpec(
        image=CFD_IMAGE,
        name=f"model-{job_id}-cfd",
        working_dir="/app/sh",
        environment={
            "JOB_ID": str(job_id),
            "EVENT_DIR": "/job-events",
            "PYTHON_BIN": "/usr/bin/python3",

            "FORECAST_HOURS": str(forecast_hours),

            "MPI_NP": str(CFD_MPI_NP),
            "OMP_NUM_THREADS": "1",

            "OMPI_MCA_pml": "ob1",
            "OMPI_MCA_mtl": "^ofi",
            "OMPI_MCA_btl": "self,vader,tcp",

            "CANCEL_GRACE_SECONDS": str(MODEL_CANCEL_GRACE_SECONDS),
            "CFD_UID": str(MODEL_UID),
            "CFD_GID": str(MODEL_GID),
        },
        volumes=volumes,
        labels={
            "model.runner": "true",
            "model.job_id": str(job_id),
            "model.type": "cfd",
        },
        log_worker_path=log_worker_path,
        log_host_path=log_host_path,
        result_worker_path=result_dir,
        result_host_path=result_host_path,
        expected_result_worker_path=None,
        run_kwargs={
            "entrypoint": ["/app/sh/run_cfd_job.sh"],
            "init": True,
            "shm_size": "32g",
        },
    )


def _prepare_hysplit(job_id: UUID) -> ModelSpec:
    worker_root = JOB_WORKER_ROOT / str(job_id)
    host_root = JOB_HOST_ROOT / str(job_id)

    work_dir = worker_root / "hysplit" / "work"
    result_dir = worker_root / "hysplit" / "results"
    template_dir = HYSPLIT_SOURCE_WORKER_ROOT / HYSPLIT_TEMPLATE_SUBDIR

    work_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)

    for filename in HYSPLIT_INPUT_FILES:
        source = template_dir / filename

        if not source.is_file():
            raise FileNotFoundError(f"HYSPLIT input not found: {source}")

        shutil.copy2(source, work_dir / filename)

    _chown_tree(worker_root / "hysplit", MODEL_UID, MODEL_GID)

    host_hysplit_root = host_root / "hysplit"
    log_worker_path = worker_root / "hysplit" / "model.log"
    log_host_path = host_hysplit_root / "model.log"
    result_host_path = host_hysplit_root / "results" / "cdump3"

    volumes = {
        str(host_hysplit_root / "work"): {
            "bind": "/work",
            "mode": "rw,z",
        },
        str(host_hysplit_root / "results"): {
            "bind": "/work/results",
            "mode": "rw,z",
        },
        str(HYSPLIT_GFS_ROOT): {
            "bind": "/home/cfd/hysplit/fire-spark-test/INPUT/gfs0p25",
            "mode": "ro,z",
        },
    }

    return ModelSpec(
        image=HYSPLIT_IMAGE,
        name=f"model-{job_id}-hysplit",
        working_dir="/work",
        environment={
            "JOB_ID": str(job_id),
            "MPI_NP": str(HYSPLIT_MPI_NP),
            "OMP_NUM_THREADS": "1",
            "I_MPI_FABRICS": "shm",
            "HYSPLIT_RUN_DIR": "/work",
            "HOME": "/tmp",
            "CANCEL_GRACE_SECONDS": str(MODEL_CANCEL_GRACE_SECONDS),
            "CFD_UID": str(MODEL_UID),
            "CFD_GID": str(MODEL_GID),
        },
        volumes=volumes,
        labels={
            "model.runner": "true",
            "model.job_id": str(job_id),
            "model.type": "hysplit",
        },
        log_worker_path=log_worker_path,
        log_host_path=log_host_path,
        result_worker_path=result_dir,
        result_host_path=result_host_path,
        expected_result_worker_path=result_dir / "cdump3",
        run_kwargs={
            "user": f"{MODEL_UID}:{MODEL_GID}",
            "init": True,
            "shm_size": "16g",
            "ulimits": [
                Ulimit(name="stack", soft=-1, hard=-1),
                Ulimit(name="memlock", soft=-1, hard=-1),
            ],
        },
    )


def _stream_logs(container_id: str, log_path: Path) -> None:
    client = docker.from_env()

    try:
        container = client.containers.get(container_id)

        with log_path.open("ab", buffering=0) as log_file:
            for chunk in container.logs(
                stream=True,
                follow=True,
                stdout=True,
                stderr=True,
            ):
                log_file.write(chunk)

    except Exception:
        logger.exception(
            "Container log streaming failed: container_id=%s",
            container_id,
        )
    finally:
        client.close()


def _tail_log(path: Path, limit: int = 4000) -> str:
    if not path.is_file():
        return ""

    with path.open("rb") as file:
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(max(0, size - limit))
        data = file.read()

    return data.decode("utf-8", errors="replace").strip()

def _has_cfd_result(result_dir: Path) -> bool:
    if not result_dir.is_dir():
        return False
    files = [p for p in result_dir.rglob("*.nc") if p.is_file()]
    return bool(files) and all(p.stat().st_size > 0 for p in files)

def run_model_container(job_id: UUID, model_type: str) -> None:
    normalized_model_type = model_type.upper()

    container = None
    client = None
    spec: ModelSpec | None = None
    cleanup_required = False
    exit_code = -1
    model_status = "FAILED"
    error_message: str | None = None

    try:
        if not mark_model_running(job_id, normalized_model_type):
            model_status = "CANCELED"
            error_message = "Job was cancelled before model startup"
            return

        request_data, request_id = _load_job(job_id)

        if normalized_model_type == "CFD":
            spec = _prepare_cfd(job_id, request_data)
        elif normalized_model_type == "HYSPLIT":
            spec = _prepare_hysplit(job_id)
        else:
            raise ValueError(f"Unsupported model type: {model_type}")

        spec.log_worker_path.parent.mkdir(parents=True, exist_ok=True)
        spec.log_worker_path.write_bytes(b"")

        client = docker.from_env()
        client.ping()

        cleanup_required = True
        
        container = client.containers.run(
            image=spec.image,
            name=spec.name,
            detach=True,
            working_dir=spec.working_dir,
            environment=spec.environment,
            volumes=spec.volumes,
            labels=spec.labels,
            auto_remove=False,
            **spec.run_kwargs,
        )

        _save_container_info(
            job_id=job_id,
            model_type=normalized_model_type,
            container_id=container.id,
            container_name=spec.name,
            log_path=spec.log_host_path,
        )

        log_thread = threading.Thread(
            target=_stream_logs,
            args=(container.id, spec.log_worker_path),
            name=f"log-{normalized_model_type.lower()}-{job_id}",
            daemon=True,
        )
        log_thread.start()

        stop_sent = False

        while True:
             # Docker SDK의 캐시된 status를 실제 상태로 갱신
            container.reload()

            if container.status in {
                "exited",
                "dead",
            }:
                break

            if (
                _is_cancel_requested(job_id)
                and not stop_sent
            ):
                logger.info(
                    "Stopping model container: "
                    "job_id=%s model=%s",
                    job_id,
                    normalized_model_type,
                )

                stop_sent = True

                container.stop(
                    timeout=(
                        MODEL_CANCEL_GRACE_SECONDS
                    )
                )

            update_job_heartbeat(job_id)

            time.sleep(
                MODEL_POLL_INTERVAL_SECONDS
            )

        wait_result = container.wait()
        exit_code = int(wait_result.get("StatusCode", -1))
        log_thread.join(timeout=10)

        canceled = _is_cancel_requested(job_id) or exit_code == 143

        if canceled:
            model_status = "CANCELED"
            error_message = "Model execution was canceled"
        elif exit_code != 0:
            model_status = "FAILED"
            error_message = (
                f"Model container exited with code {exit_code}"
            )
        elif (
            spec.expected_result_worker_path is not None
            and (
                not spec.expected_result_worker_path.is_file()
                or spec.expected_result_worker_path.stat().st_size == 0
            )
        ):
            model_status = "FAILED"
            error_message = (
                "Expected result file is missing or empty: "
                f"{spec.expected_result_worker_path}"
            )
        elif (
            normalized_model_type == "CFD"
            and not _has_cfd_result(spec.result_worker_path)
        ):
            model_status = "FAILED"
            error_message = (
                f"CFD result directory is empty: {spec.result_worker_path}"
            )
        else:
            model_status = "SUCCEEDED"

        if model_status == "FAILED":
            log_tail = _tail_log(spec.log_worker_path)

            if log_tail:
                error_message = f"{error_message}\n\nLast log output:\n{log_tail}"

    except Exception as exc:
        logger.exception(
            "Model execution failed: job_id=%s model=%s",
            job_id,
            normalized_model_type,
        )
        error_message = str(exc)

        if spec is not None:
            log_tail = _tail_log(spec.log_worker_path)

            if log_tail:
                error_message = f"{error_message}\n\nLast log output:\n{log_tail}"

    finally:
        try:
            if cleanup_required:
                ensure_job_stopped(
                    job_id,
                    model_type=normalized_model_type,
                )
        finally:
            if client is not None:
                client.close()

        # 위 종료 확인에서 예외가 발생하면 아래로 진행하지 않는다.
        result_path = (
            str(spec.result_host_path)
            if spec is not None and model_status == "SUCCEEDED"
            else None
        )

        log_path = str(spec.log_host_path) if spec is not None else None

        try:
            complete_model_run(
                job_id=job_id,
                model_type=(
                    normalized_model_type
                ),
                model_status=model_status,
                exit_code=exit_code,
                result_path=result_path,
                log_path=log_path,
                error_message=error_message,
            )
        except Exception:
            logger.exception(
                "Could not save model completion: "
                "job_id=%s model=%s",
                job_id,
                normalized_model_type,
            )
            raise
