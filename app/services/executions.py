import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Protocol, cast

import structlog
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.core.metrics import execution_duration, execution_outcomes, step_outcomes
from app.domain.enums import ExecutionStatus, FailureKind, StepStatus
from app.domain.models import Execution, FailureRecord, StepExecution, Workflow
from app.domain.types import JsonObject
from app.services.audit import append_audit_event
from app.services.steps import DefaultStepRunner, StepContext, StepFailure, StepRunner

logger = structlog.get_logger()


class _RowCountResult(Protocol):
    rowcount: int


def retry_delay_seconds(execution_id: str, attempt: int, base_seconds: int) -> float:
    exponential = base_seconds * (2 ** max(attempt - 1, 0))
    digest = hashlib.sha256(f"{execution_id}:{attempt}".encode()).digest()
    jitter_ratio = (int.from_bytes(digest[:2]) / 65535 - 0.5) * 0.4
    delay = float(exponential) * (1.0 + jitter_ratio)
    return max(1.0, delay)


class ExecutionService:
    def __init__(
        self,
        session: Session,
        runner: StepRunner | None = None,
        *,
        worker_id: str = "test-worker",
        lease_seconds: int = 60,
    ) -> None:
        self.session = session
        self.runner = runner or DefaultStepRunner()
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.lease_token = str(uuid.uuid4())

    def run(self, execution_id: str) -> bool:
        now = datetime.now(UTC)
        claimed = cast(
            _RowCountResult,
            self.session.execute(
                update(Execution)
                .where(
                    Execution.id == execution_id,
                    Execution.status == ExecutionStatus.QUEUED,
                )
                .values(
                    status=ExecutionStatus.RUNNING,
                    started_at=datetime.now(UTC),
                    attempt_count=Execution.attempt_count + 1,
                    next_retry_at=None,
                    lease_owner=self.worker_id,
                    lease_token=self.lease_token,
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                )
            ),
        )
        self.session.commit()
        if claimed.rowcount != 1:
            return False

        execution = self._load(execution_id)
        started = monotonic()
        try:
            self._run_steps(execution)
        finally:
            execution_duration.observe(monotonic() - started)
        return True

    def _load(self, execution_id: str) -> Execution:
        execution = self.session.scalar(
            select(Execution)
            .options(selectinload(Execution.workflow), selectinload(Execution.step_executions))
            .where(Execution.id == execution_id)
        )
        if execution is None:
            raise LookupError(f"Execution not found: {execution_id}")
        return execution

    def _run_steps(self, execution: Execution) -> None:
        accumulated_output: JsonObject = dict(execution.output_payload or {})
        step_rows = {row.step_index: row for row in execution.step_executions}

        for index in range(execution.current_step, len(execution.workflow.steps)):
            if not self._renew_lease(execution.id):
                return
            definition = execution.workflow.steps[index]
            name = definition.get("name")
            kind = definition.get("kind")
            config = definition.get("config", {})
            if (
                not isinstance(name, str)
                or not isinstance(kind, str)
                or not isinstance(config, dict)
            ):
                self._fail_execution(
                    execution,
                    index,
                    "invalid_definition",
                    "Persisted workflow step is invalid",
                    transient=False,
                )
                return

            row = step_rows.get(index)
            if row is None:
                row = StepExecution(
                    execution_id=execution.id,
                    step_index=index,
                    step_name=name,
                    step_kind=kind,
                    status=StepStatus.RUNNING,
                    attempt_count=1,
                    started_at=datetime.now(UTC),
                )
                self.session.add(row)
                step_rows[index] = row
            else:
                row.status = StepStatus.RUNNING
                row.attempt_count += 1
                row.started_at = datetime.now(UTC)
            row.error_message = None
            self.session.commit()

            try:
                output = self.runner.run(
                    kind,
                    config,
                    StepContext(
                        execution_id=execution.id,
                        input_payload=execution.input_payload,
                        accumulated_output=accumulated_output,
                    ),
                )
            except StepFailure as exc:
                if not self._renew_lease(execution.id):
                    return
                row.status = StepStatus.FAILED
                row.error_message = str(exc)
                row.finished_at = datetime.now(UTC)
                step_outcomes.labels(kind=kind, status="failed").inc()
                self._fail_execution(
                    execution,
                    index,
                    exc.code,
                    str(exc),
                    transient=exc.transient,
                )
                return
            except Exception:
                if not self._renew_lease(execution.id):
                    return
                logger.exception(
                    "unexpected_step_failure",
                    execution_id=execution.id,
                    step_index=index,
                )
                row.status = StepStatus.FAILED
                row.error_message = "Unexpected step failure"
                row.finished_at = datetime.now(UTC)
                step_outcomes.labels(kind=kind, status="failed").inc()
                self._fail_execution(
                    execution,
                    index,
                    "unexpected_step_failure",
                    "Unexpected step failure",
                    transient=True,
                )
                return

            if not self._renew_lease(execution.id):
                return
            accumulated_output = {**accumulated_output, **output}
            row.status = StepStatus.SUCCEEDED
            row.output_payload = output
            row.finished_at = datetime.now(UTC)
            execution.current_step = index + 1
            execution.output_payload = accumulated_output
            append_audit_event(
                self.session,
                event_type="step_succeeded",
                actor_id="worker",
                correlation_id=execution.correlation_id,
                workflow_id=execution.workflow_id,
                execution_id=execution.id,
                details={"step_index": index, "step_name": name, "step_kind": kind},
            )
            step_outcomes.labels(kind=kind, status="succeeded").inc()
            self.session.commit()

        if not self._renew_lease(execution.id):
            return
        execution.status = ExecutionStatus.SUCCEEDED
        execution.finished_at = datetime.now(UTC)
        self._clear_lease(execution)
        execution.last_error_code = None
        execution.last_error_message = None
        append_audit_event(
            self.session,
            event_type="execution_succeeded",
            actor_id="worker",
            correlation_id=execution.correlation_id,
            workflow_id=execution.workflow_id,
            execution_id=execution.id,
            details={"attempt_count": execution.attempt_count},
        )
        execution_outcomes.labels(status=ExecutionStatus.SUCCEEDED.value).inc()
        self.session.commit()

    def _fail_execution(
        self,
        execution: Execution,
        step_index: int,
        code: str,
        message: str,
        *,
        transient: bool,
    ) -> None:
        workflow: Workflow = execution.workflow
        retryable = transient and execution.attempt_count < workflow.max_attempts
        failure_kind = FailureKind.TRANSIENT if transient else FailureKind.PERMANENT
        execution.last_error_code = code
        execution.last_error_message = message
        execution.current_step = step_index
        self._clear_lease(execution)
        self.session.add(
            FailureRecord(
                execution_id=execution.id,
                step_index=step_index,
                kind=failure_kind,
                code=code,
                message=message,
            )
        )

        if retryable:
            delay = retry_delay_seconds(
                execution.id,
                execution.attempt_count,
                workflow.retry_base_seconds,
            )
            execution.status = ExecutionStatus.RETRY_SCHEDULED
            execution.next_retry_at = datetime.now(UTC) + timedelta(seconds=delay)
            event_type = "execution_retry_scheduled"
            details: JsonObject = {
                "attempt_count": execution.attempt_count,
                "delay_seconds": round(delay, 3),
                "error_code": code,
            }
        else:
            execution.status = ExecutionStatus.DEAD_LETTER
            execution.finished_at = datetime.now(UTC)
            event_type = "execution_dead_lettered"
            details = {
                "attempt_count": execution.attempt_count,
                "failure_kind": failure_kind.value,
                "error_code": code,
            }
            execution_outcomes.labels(status=ExecutionStatus.DEAD_LETTER.value).inc()

        append_audit_event(
            self.session,
            event_type=event_type,
            actor_id="worker",
            correlation_id=execution.correlation_id,
            workflow_id=execution.workflow_id,
            execution_id=execution.id,
            details=details,
        )
        self.session.commit()

    def _renew_lease(self, execution_id: str) -> bool:
        now = datetime.now(UTC)
        renewed = cast(
            _RowCountResult,
            self.session.execute(
                update(Execution)
                .where(
                    Execution.id == execution_id,
                    Execution.status == ExecutionStatus.RUNNING,
                    Execution.lease_token == self.lease_token,
                )
                .values(
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                )
            ),
        )
        self.session.commit()
        return renewed.rowcount == 1

    @staticmethod
    def _clear_lease(execution: Execution) -> None:
        execution.lease_owner = None
        execution.lease_token = None
        execution.lease_expires_at = None
        execution.heartbeat_at = None
