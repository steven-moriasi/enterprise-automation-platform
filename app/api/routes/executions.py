from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.domain.enums import ExecutionStatus
from app.domain.models import AuditEvent, DispatchOutbox, Execution
from app.domain.schemas import AuditEventRead, ExecutionRead
from app.infrastructure.auth import AuthContext, require_roles
from app.infrastructure.database import get_session
from app.services.audit import append_audit_event

router = APIRouter(prefix="/api/v1/executions", tags=["executions"])
OperatorContext = Annotated[AuthContext, Depends(require_roles("admin", "operator"))]
ViewerContext = Annotated[AuthContext, Depends(require_roles("admin", "operator", "viewer"))]


def _get_execution(session: Session, execution_id: str) -> Execution:
    execution = session.scalar(
        select(Execution)
        .options(selectinload(Execution.step_executions))
        .where(Execution.id == execution_id)
    )
    if execution is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return execution


@router.get("", response_model=list[ExecutionRead])
def list_executions(
    _context: ViewerContext,
    session: Annotated[Session, Depends(get_session)],
    workflow_id: str | None = None,
    execution_status: Annotated[
        ExecutionStatus | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[Execution]:
    query = (
        select(Execution)
        .options(selectinload(Execution.step_executions))
        .order_by(Execution.created_at.desc(), Execution.id.desc())
        .limit(limit)
    )
    if workflow_id is not None:
        query = query.where(Execution.workflow_id == workflow_id)
    if execution_status is not None:
        query = query.where(Execution.status == execution_status)
    return list(session.scalars(query))


@router.get("/{execution_id}", response_model=ExecutionRead)
def get_execution(
    execution_id: str,
    _context: ViewerContext,
    session: Annotated[Session, Depends(get_session)],
) -> Execution:
    return _get_execution(session, execution_id)


@router.get("/{execution_id}/audit", response_model=list[AuditEventRead])
def get_execution_audit(
    execution_id: str,
    _context: ViewerContext,
    session: Annotated[Session, Depends(get_session)],
) -> list[AuditEvent]:
    _get_execution(session, execution_id)
    return list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.execution_id == execution_id)
            .order_by(AuditEvent.created_at, AuditEvent.id)
        )
    )


@router.post(
    "/{execution_id}/retry",
    response_model=ExecutionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_dead_letter_execution(
    execution_id: str,
    context: OperatorContext,
    session: Annotated[Session, Depends(get_session)],
) -> Execution:
    execution = _get_execution(session, execution_id)
    if execution.status != ExecutionStatus.DEAD_LETTER:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only dead-lettered executions can be retried manually",
        )
    execution.status = ExecutionStatus.QUEUED
    execution.attempt_count = 0
    execution.finished_at = None
    execution.next_retry_at = None
    execution.last_error_code = None
    execution.last_error_message = None
    session.add(DispatchOutbox(execution_id=execution.id))
    append_audit_event(
        session,
        event_type="execution_manual_retry_requested",
        actor_id=context.subject,
        correlation_id=execution.correlation_id,
        workflow_id=execution.workflow_id,
        execution_id=execution.id,
        details={"prior_attempt_count": execution.attempt_count},
    )
    session.commit()
    return execution
