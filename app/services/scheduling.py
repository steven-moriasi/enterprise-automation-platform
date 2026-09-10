from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.enums import ExecutionStatus, FailureKind, TriggerType, WorkflowStatus
from app.domain.models import (
    DispatchOutbox,
    Execution,
    FailureRecord,
    Workflow,
    WorkflowSchedule,
)
from app.infrastructure.queue import ExecutionDispatcher
from app.services.audit import append_audit_event


def reap_expired_executions(session: Session, *, batch_size: int = 100) -> int:
    now = datetime.now(UTC)
    executions = list(
        session.scalars(
            select(Execution)
            .join(Workflow)
            .where(
                Execution.status == ExecutionStatus.RUNNING,
                Execution.lease_expires_at.is_not(None),
                Execution.lease_expires_at <= now,
            )
            .order_by(Execution.lease_expires_at)
            .limit(batch_size)
        )
    )
    reaped = 0
    for execution in executions:
        lease_token = execution.lease_token
        if lease_token is None:
            continue
        retryable = execution.attempt_count < execution.workflow.max_attempts
        new_status = ExecutionStatus.QUEUED if retryable else ExecutionStatus.DEAD_LETTER
        result = session.execute(
            update(Execution)
            .where(
                Execution.id == execution.id,
                Execution.status == ExecutionStatus.RUNNING,
                Execution.lease_token == lease_token,
                Execution.lease_expires_at <= now,
            )
            .values(
                status=new_status,
                lease_owner=None,
                lease_token=None,
                lease_expires_at=None,
                heartbeat_at=None,
                finished_at=now if not retryable else None,
                last_error_code="worker_lease_expired",
                last_error_message="Worker lease expired before completion",
            )
        )
        if result.rowcount != 1:
            session.rollback()
            continue

        if retryable:
            session.add(DispatchOutbox(execution_id=execution.id))
            event_type = "execution_lease_requeued"
        else:
            session.add(
                FailureRecord(
                    execution_id=execution.id,
                    step_index=execution.current_step,
                    kind=FailureKind.TRANSIENT,
                    code="worker_lease_expired",
                    message="Worker lease expired before completion",
                )
            )
            event_type = "execution_lease_dead_lettered"
        append_audit_event(
            session,
            event_type=event_type,
            actor_id="scheduler",
            correlation_id=execution.correlation_id,
            workflow_id=execution.workflow_id,
            execution_id=execution.id,
            details={"attempt_count": execution.attempt_count},
        )
        session.commit()
        reaped += 1
    return reaped


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
