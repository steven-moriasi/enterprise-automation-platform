from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ExecutionStatus, FailureKind, TriggerType, WorkflowStatus
from app.domain.models import AuditEvent, Execution, FailureRecord, Workflow
from app.domain.types import JsonObject
from app.services.executions import ExecutionService, retry_delay_seconds
from app.services.steps import (
    PermanentStepFailure,
    StepContext,
    TransientStepFailure,
)


class FailOnceRunner:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, kind: str, config: JsonObject, context: StepContext) -> JsonObject:
        self.calls += 1
        if self.calls == 1:
            raise TransientStepFailure("Dependency unavailable")
        return {"recovered": True}


class PermanentFailureRunner:
    def run(self, kind: str, config: JsonObject, context: StepContext) -> JsonObject:
        raise PermanentStepFailure("Invalid connector configuration")


def create_execution(
    session: Session,
    *,
    steps: list[JsonObject] | None = None,
    max_attempts: int = 3,
) -> Execution:
    workflow = Workflow(
        name=f"workflow-{datetime.now(UTC).timestamp()}",
        status=WorkflowStatus.ACTIVE,
        steps=steps
        or [
            {
                "name": "assign-owner",
                "kind": "assign",
                "config": {"target": "owner", "value": "operations"},
            },
            {
                "name": "check-risk",
                "kind": "condition",
                "config": {"field": "risk", "equals": "high"},
            },
        ],
        max_attempts=max_attempts,
        retry_base_seconds=5,
        created_by="test",
    )
    session.add(workflow)
    session.flush()
    execution = Execution(
        workflow_id=workflow.id,
        status=ExecutionStatus.QUEUED,
        trigger_type=TriggerType.MANUAL,
        idempotency_key=f"request-{workflow.id}",
        input_payload={"risk": "high"},
        correlation_id=f"correlation-{workflow.id}",
        requested_by="test",
    )
    session.add(execution)
    session.commit()
    return execution


def test_execution_completes_and_duplicate_delivery_is_ignored(session: Session) -> None:
    execution = create_execution(session)
    service = ExecutionService(session)

    assert service.run(execution.id) is True
    assert service.run(execution.id) is False

    session.refresh(execution)
    assert execution.status == ExecutionStatus.SUCCEEDED
    assert execution.attempt_count == 1
    assert execution.lease_token is None
    assert execution.lease_expires_at is None
    assert execution.output_payload == {
        "owner": "operations",
        "field": "risk",
        "matched": True,
    }
    assert [step.status.value for step in execution.step_executions] == [
        "succeeded",
        "succeeded",
    ]
    event_types = list(
        session.scalars(
            select(AuditEvent.event_type)
            .where(AuditEvent.execution_id == execution.id)
            .order_by(AuditEvent.created_at)
        )
    )
    assert event_types == ["step_succeeded", "step_succeeded", "execution_succeeded"]


def test_transient_failure_is_scheduled_then_resumed(session: Session) -> None:
    execution = create_execution(
        session,
        steps=[
            {
                "name": "unstable-connector",
                "kind": "emit_event",
                "config": {"event_name": "connector.requested"},
            }
        ],
    )
    runner = FailOnceRunner()

    assert ExecutionService(session, runner).run(execution.id) is True
    session.refresh(execution)
    assert execution.status == ExecutionStatus.RETRY_SCHEDULED
    assert execution.attempt_count == 1
    assert execution.lease_token is None
    assert execution.next_retry_at is not None
    assert execution.last_error_code == "step_failed"

    execution.status = ExecutionStatus.QUEUED
    execution.next_retry_at = None
    session.commit()

    assert ExecutionService(session, runner).run(execution.id) is True
    session.refresh(execution)
    assert execution.status == ExecutionStatus.SUCCEEDED
    assert execution.attempt_count == 2
    assert execution.output_payload == {"recovered": True}
    assert execution.step_executions[0].attempt_count == 2


def test_permanent_failure_is_dead_lettered_without_retry(session: Session) -> None:
    execution = create_execution(
        session,
        steps=[
            {
                "name": "invalid-connector",
                "kind": "emit_event",
                "config": {"event_name": "connector.requested"},
            }
        ],
    )

    assert ExecutionService(session, PermanentFailureRunner()).run(execution.id) is True

    session.refresh(execution)
    failure = session.scalar(
        select(FailureRecord).where(FailureRecord.execution_id == execution.id)
    )
    assert execution.status == ExecutionStatus.DEAD_LETTER
    assert execution.finished_at is not None
    assert failure is not None
    assert failure.kind == FailureKind.PERMANENT
    assert failure.step_index == 0


def test_transient_failure_is_dead_lettered_after_attempt_limit(session: Session) -> None:
    execution = create_execution(
        session,
        steps=[
            {
                "name": "unavailable-connector",
                "kind": "emit_event",
                "config": {"event_name": "connector.requested"},
            }
        ],
        max_attempts=1,
    )

    assert ExecutionService(session, FailOnceRunner()).run(execution.id) is True

    session.refresh(execution)
    assert execution.status == ExecutionStatus.DEAD_LETTER
    assert execution.attempt_count == 1


def test_retry_delay_is_deterministic_and_exponential() -> None:
    first = retry_delay_seconds("execution-1", 1, 10)
    repeated = retry_delay_seconds("execution-1", 1, 10)
    second = retry_delay_seconds("execution-1", 2, 10)

    assert first == repeated
    assert 8 <= first <= 12
    assert 16 <= second <= 24
