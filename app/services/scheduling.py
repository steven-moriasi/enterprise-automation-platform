from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.enums import ExecutionStatus, TriggerType, WorkflowStatus
from app.domain.models import DispatchOutbox, Execution, Workflow, WorkflowSchedule
from app.infrastructure.queue import ExecutionDispatcher
from app.services.audit import append_audit_event


def prepare_due_schedules(session: Session, *, batch_size: int = 100) -> int:
    now = datetime.now(UTC)
    schedules = list(
        session.scalars(
            select(WorkflowSchedule)
            .join(Workflow)
            .where(
                WorkflowSchedule.enabled.is_(True),
                WorkflowSchedule.next_run_at <= now,
                Workflow.status == WorkflowStatus.ACTIVE,
            )
            .order_by(WorkflowSchedule.next_run_at)
            .limit(batch_size)
        )
    )
    prepared = 0
    for schedule in schedules:
        due_at = schedule.next_run_at
        result = session.execute(
            update(WorkflowSchedule)
            .where(
                WorkflowSchedule.id == schedule.id,
                WorkflowSchedule.enabled.is_(True),
                WorkflowSchedule.next_run_at == due_at,
            )
            .values(
                last_run_at=due_at,
                next_run_at=due_at + timedelta(seconds=schedule.interval_seconds),
            )
        )
        if result.rowcount != 1:
            continue
        idempotency_key = f"schedule:{schedule.id}:{due_at.isoformat()}"
        execution = Execution(
            workflow_id=schedule.workflow_id,
            status=ExecutionStatus.QUEUED,
            trigger_type=TriggerType.SCHEDULE,
            idempotency_key=idempotency_key,
            input_payload={
                "schedule_id": schedule.id,
                "scheduled_for": due_at.isoformat(),
            },
            correlation_id=idempotency_key,
            requested_by="scheduler",
        )
        session.add(execution)
        session.flush()
        session.add(DispatchOutbox(execution_id=execution.id))
        append_audit_event(
            session,
            event_type="scheduled_execution_requested",
            actor_id="scheduler",
            correlation_id=execution.correlation_id,
            workflow_id=execution.workflow_id,
            execution_id=execution.id,
            details={"schedule_id": schedule.id, "scheduled_for": due_at.isoformat()},
        )
        session.commit()
        prepared += 1
    return prepared


def prepare_due_retries(session: Session, *, batch_size: int = 100) -> int:
    now = datetime.now(UTC)
    execution_ids = list(
        session.scalars(
            select(Execution.id)
            .where(
                Execution.status == ExecutionStatus.RETRY_SCHEDULED,
                Execution.next_retry_at <= now,
            )
            .order_by(Execution.next_retry_at)
            .limit(batch_size)
        )
    )
    prepared = 0
    for execution_id in execution_ids:
        result = session.execute(
            update(Execution)
            .where(
                Execution.id == execution_id,
                Execution.status == ExecutionStatus.RETRY_SCHEDULED,
                Execution.next_retry_at <= now,
            )
            .values(status=ExecutionStatus.QUEUED, next_retry_at=None)
        )
        if result.rowcount != 1:
            continue
        execution = session.get(Execution, execution_id)
        if execution is None:
            continue
        append_audit_event(
            session,
            event_type="execution_requeued",
            actor_id="scheduler",
            correlation_id=execution.correlation_id,
            workflow_id=execution.workflow_id,
            execution_id=execution.id,
            details={"attempt_count": execution.attempt_count},
        )
        session.add(DispatchOutbox(execution_id=execution_id))
        session.commit()
        prepared += 1
    return prepared


def publish_dispatch_outbox(
    session: Session,
    dispatcher: ExecutionDispatcher,
    *,
    batch_size: int = 100,
) -> int:
    records = list(
        session.scalars(
            select(DispatchOutbox)
            .where(DispatchOutbox.published_at.is_(None))
            .order_by(DispatchOutbox.created_at)
            .limit(batch_size)
        )
    )
    published = 0
    for record in records:
        try:
            dispatcher.enqueue(record.execution_id)
        except Exception as exc:
            record.attempt_count += 1
            record.last_error = str(exc)[:2000]
            session.commit()
            continue
        record.attempt_count += 1
        record.last_error = None
        record.published_at = datetime.now(UTC)
        session.commit()
        published += 1
    return published
