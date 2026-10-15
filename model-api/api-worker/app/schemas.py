from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

JobStatus = Literal[
    "queued", "running", "success", "partial_success", "failed", "cancelled",
]

class ApiSchema(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
    )

class RequestSchema(ApiSchema):
    model_config = ConfigDict(extra="forbid")

class DomainConfig(RequestSchema):
    resolution_m: int = Field(default=200, gt=0)
    vertical_resolution_m: int = Field(default=50, gt=0)
    kmax: int = Field(default=40, gt=0)
    time_step_s: float = Field(default=2.0, gt=0)
    output_interval_s: int = Field(default=600, gt=0)
    domain_size_m: int = Field(default=20000, gt=0)

class SmokeModelParameters(RequestSchema):
    forecast_hours: int = Field(
        default=10,
        gt=0,
    )


class SmokeModelInput(RequestSchema):
    base_time: datetime

    parameters: SmokeModelParameters = Field(
        default_factory=SmokeModelParameters,
    )

    fireline_path: str = Field(
        min_length=1,
    )

    domain_config: DomainConfig = Field(
        default_factory=DomainConfig,
    )

class ModelRunResponse(ApiSchema):
    model_type: Literal["CFD", "HYSPLIT"]
    status: JobStatus
    container_name: str | None = None
    exit_code: int | None = None
    result_path: str | None = None
    log_path: str | None = None
    result_data: dict[str, Any] | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

class JobResponse(ApiSchema):
    job_id: UUID
    model_id: str
    request_id: str
    scenario_id: str | None = None
    requested_by: str | None = None
    status: JobStatus
    priority: int
    queue_position: int | None = None
    request_data: dict[str, Any]
    callback_enabled: bool
    callback_url: str | None = None
    error_message: str | None = None
    created_at: datetime
    submitted_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    models: list[ModelRunResponse] = Field(default_factory=list)

class Paging(ApiSchema):
    limit: int
    next_cursor: str | None = None

class JobListResponse(ApiSchema):
    items: list[JobResponse]
    paging: Paging    

class CallbackConfig(RequestSchema):
    enabled: bool
    url: AnyHttpUrl | None = None

    @model_validator(mode="after")
    def validate_callback_url(self):
        if self.enabled and self.url is None:
            raise ValueError(
                "callback.url is required "
                "when callback.enabled is true"
            )

        return self

class JobCreate(RequestSchema):
    model_id: Literal["smoke-spread"]

    request_id: str = Field(
        min_length=1,
        max_length=150,
    )

    input: SmokeModelInput
    callback: CallbackConfig

class JobCreateResponse(ApiSchema):
    job_id: UUID

class ReadyResponse(ApiSchema):
    status: Literal[
        "ready",
        "not_ready",
    ]
    checks: dict[str, str]


class InputDatasetResponse(ApiSchema):
    dataset_id: str
    dataset_version: str
    source_uri: str
    checksum: str | None = None


class ExecutionModelResponse(ApiSchema):
    model_type: Literal[
        "CFD",
        "HYSPLIT",
    ]
    status: JobStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ExecutionResponse(ApiSchema):
    started_at: datetime | None = None
    finished_at: datetime | None = None
    models: list[ExecutionModelResponse] = Field(
        default_factory=list,
    )


class ResultAssetResponse(ApiSchema):
    asset_id: str
    name: str
    model_type: Literal[
        "CFD",
        "HYSPLIT",
    ]
    media_type: str
    size_bytes: int | None = None
    checksum: str | None = None


class JobResultResponse(ApiSchema):
    job_id: UUID
    status: Literal[
        "available",
        "partial",
        "not_available",
    ]
    execution: ExecutionResponse
    input_parameters: dict[str, Any]
    input_datasets: list[
        InputDatasetResponse
    ] = Field(default_factory=list)
    provenance: dict[str, Any]
    assets: list[
        ResultAssetResponse
    ] = Field(default_factory=list)


class ResultDownloadResponse(ApiSchema):
    asset_id: str
    method: Literal["LOCAL_FILE"]
    local_path: str
    source_uri: str
    media_type: str
    size_bytes: int | None = None
    checksum: str | None = None


class ModelErrorDetail(ApiSchema):
    model_type: Literal[
        "CFD",
        "HYSPLIT",
    ]
    exit_code: int | None = None
    message: str
    log_path: str | None = None


class JobErrorResponse(ApiSchema):
    job_id: UUID
    error_code: str
    error_message: str
    retryable: bool
    occurred_at: datetime | None = None
    details: list[
        ModelErrorDetail
    ] = Field(default_factory=list)
