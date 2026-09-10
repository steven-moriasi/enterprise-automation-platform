from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ExecutionStatus
from app.domain.models import AuditEvent, DispatchOutbox
from app.services.scheduling import prepare_due_retries, publish_dispatch_outbox
from tests.test_execution_service import create_execution


class RecordingDispatcher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.execution_ids: list[str] = []

    def enqueue(self, execution_id: str) -> None:
        if self.fail:
            raise ConnectionError("Redis unavailable")
        self.execution_ids.append(execution_id)


def test_due_retry_creates_transactional_dispatch(session: Session) -> None:
    execution = create_execution(session)
    execution.status = ExecutionStatus.RETRY_SCHEDULED
    execution.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
    execution.attempt_count = 1
    session.commit()

    assert prepare_due_retries(session) == 1

    session.refresh(execution)
    outbox = session.scalar(
        select(DispatchOutbox).where(DispatchOutbox.execution_id == execution.id)
    )
    audit = session.scalar(
        select(AuditEvent).where(
            AuditEvent.execution_id == execution.id,
            AuditEvent.event_type == "execution_requeued",
        )
    )
    assert execution.status == ExecutionStatus.QUEUED
    assert execution.next_retry_at is None
    assert outbox is not None
    assert audit is not None


def test_future_retry_is_not_prepared(session: Session) -> None:
    execution = create_execution(session)
    execution.status = ExecutionStatus.RETRY_SCHEDULED
    execution.next_retry_at = datetime.now(UTC) + timedelta(minutes=5)
    session.commit()

    assert prepare_due_retries(session) == 0
    assert session.scalar(select(DispatchOutbox)) is None


def test_outbox_failure_is_recorded_and_can_be_retried(session: Session) -> None:
    execution = create_execution(session)
    record = DispatchOutbox(execution_id=execution.id)
    session.add(record)
    session.commit()

    assert publish_dispatch_outbox(session, RecordingDispatcher(fail=True)) == 0
    session.refresh(record)
    assert record.attempt_count == 1
    assert record.published_at is None
    assert record.last_error == "Redis unavailable"

    dispatcher = RecordingDispatcher()
    assert publish_dispatch_outbox(session, dispatcher) == 1
    session.refresh(record)
    assert record.attempt_count == 2
    assert record.published_at is not None
    assert record.last_error is None
    assert dispatcher.execution_ids == [execution.id]
