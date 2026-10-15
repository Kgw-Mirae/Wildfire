from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ModelJob(Base):
    __tablename__ = "model_jobs"

    __table_args__ = (
        UniqueConstraint(
            "model_id",
            "request_id",
            name="model_jobs_model_id_request_id_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    model_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    request_id: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    scenario_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    requested_by: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="QUEUED",
        server_default=text("'QUEUED'"),
    )

    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    request_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )

    callback_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    callback_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    cancel_requested: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    retry_of: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("model_jobs.id"),
        nullable=True,
    )

    target_worker: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    worker_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    runs: Mapped[list["ModelRun"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="ModelRun.model_type",
    )


class ModelRun(Base):
    __tablename__ = "model_runs"

    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "model_type",
            name="model_runs_job_id_model_type_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    job_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("model_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )

    model_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="QUEUED",
        server_default=text("'QUEUED'"),
    )

    container_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    container_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    exit_code: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    result_path: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    log_path: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    result_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    job: Mapped[ModelJob] = relationship(
        back_populates="runs",
    )

class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )

    ready: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )

    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

class CallbackEvent(Base):
    __tablename__ = "callback_events"

    __table_args__ = (
        ForeignKeyConstraint(
            ["job_id", "model_type"],
            ["model_runs.job_id", "model_runs.model_type"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "job_id",
            "model_type",
            "event_type",
            name="callback_events_job_model_event_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    job_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
    )

    model_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="MODEL_COMPLETED",
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING",
    )

    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )

    attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    last_http_status: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
