from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.enums import ExecutionStatus
from app.domain.models import Execution
from app.infrastructure.queue import ExecutionDispatcher
from app.services.audit import append_audit_event


def dispatch_due_executions(
    session: Session,
    dispatcher: ExecutionDispatcher,
    *,
    batch_size: int = 100,
) -> int:
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
    dispatched = 0
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
        session.commit()
        dispatcher.enqueue(execution_id)
        dispatched += 1
    return dispatched
