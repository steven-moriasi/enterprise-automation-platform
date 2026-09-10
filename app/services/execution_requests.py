from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.enums import ExecutionStatus, TriggerType
from app.domain.models import DispatchOutbox, Execution, Workflow
from app.domain.types import JsonObject
from app.services.audit import append_audit_event


def request_execution(
    session: Session,
    *,
    workflow: Workflow,
    trigger_type: TriggerType,
    idempotency_key: str,
    correlation_id: str,
    requested_by: str,
    input_payload: JsonObject,
) -> tuple[Execution, bool]:
    existing = session.scalar(
        select(Execution).where(
            Execution.workflow_id == workflow.id,
            Execution.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing, True

    execution = Execution(
        workflow_id=workflow.id,
        status=ExecutionStatus.QUEUED,
        trigger_type=trigger_type,
        idempotency_key=idempotency_key,
        input_payload=input_payload,
        correlation_id=correlation_id,
        requested_by=requested_by,
    )
    session.add(execution)
    try:
        session.flush()
        session.add(DispatchOutbox(execution_id=execution.id))
        append_audit_event(
            session,
            event_type="execution_requested",
            actor_id=requested_by,
            correlation_id=correlation_id,
            workflow_id=workflow.id,
            execution_id=execution.id,
            details={"trigger_type": trigger_type.value},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        replay = session.scalar(
            select(Execution).where(
                Execution.workflow_id == workflow.id,
                Execution.idempotency_key == idempotency_key,
            )
        )
        if replay is None:
            raise
        return replay, True
    session.refresh(execution)
    return execution, False
