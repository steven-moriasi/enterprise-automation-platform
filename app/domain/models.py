import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.domain.enums import (
    ExecutionStatus,
    FailureKind,
    StepStatus,
    TriggerType,
    WorkflowStatus,
)
from app.domain.types import JsonObject


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Workflow(Base):
    __tablename__ = "workflows"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_workflow_name_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[WorkflowStatus] = mapped_column(
        Enum(WorkflowStatus), default=WorkflowStatus.DRAFT
    )
    steps: Mapped[list[JsonObject]] = mapped_column(JSON)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    retry_base_seconds: Mapped[int] = mapped_column(Integer, default=5)
    created_by: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    executions: Mapped[list["Execution"]] = relationship(back_populates="workflow")


class Execution(Base):
    __tablename__ = "executions"
    __table_args__ = (
        UniqueConstraint("workflow_id", "idempotency_key", name="uq_execution_idempotency"),
        Index("ix_execution_status_retry", "status", "next_retry_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), index=True)
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus), default=ExecutionStatus.QUEUED, index=True
    )
    trigger_type: Mapped[TriggerType] = mapped_column(Enum(TriggerType))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    input_payload: Mapped[JsonObject] = mapped_column(JSON, default=dict)
    output_payload: Mapped[JsonObject | None] = mapped_column(JSON, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(160), index=True)
    requested_by: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workflow: Mapped[Workflow] = relationship(back_populates="executions")
    step_executions: Mapped[list["StepExecution"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )


class StepExecution(Base):
    __tablename__ = "step_executions"
    __table_args__ = (
        UniqueConstraint("execution_id", "step_index", name="uq_step_execution_index"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id"), index=True)
    step_index: Mapped[int] = mapped_column(Integer)
    step_name: Mapped[str] = mapped_column(String(120))
    step_kind: Mapped[str] = mapped_column(String(80))
    status: Mapped[StepStatus] = mapped_column(Enum(StepStatus), default=StepStatus.PENDING)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    output_payload: Mapped[JsonObject | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    execution: Mapped[Execution] = relationship(back_populates="step_executions")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_execution_created", "execution_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    execution_id: Mapped[str | None] = mapped_column(
        ForeignKey("executions.id"), nullable=True, index=True
    )
    workflow_id: Mapped[str | None] = mapped_column(
        ForeignKey("workflows.id"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    actor_id: Mapped[str] = mapped_column(String(160))
    correlation_id: Mapped[str] = mapped_column(String(160), index=True)
    details: Mapped[JsonObject] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class FailureRecord(Base):
    __tablename__ = "failure_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id"), index=True)
    step_index: Mapped[int] = mapped_column(Integer)
    kind: Mapped[FailureKind] = mapped_column(Enum(FailureKind))
    code: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DispatchOutbox(Base):
    __tablename__ = "dispatch_outbox"
    __table_args__ = (Index("ix_dispatch_outbox_unpublished", "published_at", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id"), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
