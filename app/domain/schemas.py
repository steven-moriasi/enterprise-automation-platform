from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import ExecutionStatus, TriggerType, WorkflowStatus
from app.domain.types import JsonObject


class StepDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["assign", "condition", "emit_event"]
    config: JsonObject = Field(default_factory=dict)

    @field_validator("config")
    @classmethod
    def reject_secret_like_keys(cls, config: JsonObject) -> JsonObject:
        forbidden = {"password", "secret", "token", "api_key", "private_key"}
        present = forbidden.intersection(key.lower() for key in config)
        if present:
            raise ValueError("workflow definitions must reference managed secrets, not embed them")
        return config


class WorkflowCreate(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{2,119}$")
    description: str = Field(default="", max_length=2000)
    version: int = Field(default=1, ge=1)
    status: WorkflowStatus = WorkflowStatus.DRAFT
    steps: list[StepDefinition] = Field(min_length=1, max_length=50)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_base_seconds: int = Field(default=5, ge=1, le=3600)


class WorkflowRead(WorkflowCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_by: str
    created_at: datetime
    updated_at: datetime


class ScheduleCreate(BaseModel):
    interval_seconds: int = Field(ge=60, le=86400)
    starts_at: datetime | None = None


class ScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_id: str
    interval_seconds: int
    enabled: bool
    next_run_at: datetime
    last_run_at: datetime | None
    created_by: str
    created_at: datetime


class ExecutionCreate(BaseModel):
    input_payload: JsonObject = Field(default_factory=dict)
    trigger_type: TriggerType = TriggerType.MANUAL


class StepExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step_index: int
    step_name: str
    step_kind: str
    status: str
    attempt_count: int
    output_payload: JsonObject | None
    error_message: str | None


class ExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_id: str
    status: ExecutionStatus
    trigger_type: TriggerType
    idempotency_key: str
    input_payload: JsonObject
    output_payload: JsonObject | None
    attempt_count: int
    current_step: int
    next_retry_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    correlation_id: str
    requested_by: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    step_executions: list[StepExecutionRead] = Field(default_factory=list)


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    execution_id: str | None
    workflow_id: str | None
    event_type: str
    actor_id: str
    correlation_id: str
    details: JsonObject
    created_at: datetime
