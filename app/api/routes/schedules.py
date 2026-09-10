from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import WorkflowStatus
from app.domain.models import Workflow, WorkflowSchedule
from app.domain.schemas import ScheduleCreate, ScheduleRead
from app.infrastructure.auth import AuthContext, require_roles
from app.infrastructure.database import get_session
from app.services.audit import append_audit_event

router = APIRouter(prefix="/api/v1/workflows/{workflow_id}/schedules", tags=["schedules"])
AdminContext = Annotated[AuthContext, Depends(require_roles("admin"))]
ViewerContext = Annotated[AuthContext, Depends(require_roles("admin", "operator", "viewer"))]


@router.post("", response_model=ScheduleRead, status_code=status.HTTP_201_CREATED)
def create_schedule(
    workflow_id: str,
    payload: ScheduleCreate,
    context: AdminContext,
    session: Annotated[Session, Depends(get_session)],
) -> WorkflowSchedule:
    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if workflow.status != WorkflowStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only active workflows can be scheduled",
        )

    now = datetime.now(UTC)
    schedule = WorkflowSchedule(
        workflow_id=workflow_id,
        interval_seconds=payload.interval_seconds,
        next_run_at=payload.starts_at or now + timedelta(seconds=payload.interval_seconds),
        created_by=context.subject,
    )
    session.add(schedule)
    session.flush()
    append_audit_event(
        session,
        event_type="workflow_schedule_created",
        actor_id=context.subject,
        correlation_id=schedule.id,
        workflow_id=workflow_id,
        details={
            "schedule_id": schedule.id,
            "interval_seconds": schedule.interval_seconds,
            "next_run_at": schedule.next_run_at.isoformat(),
        },
    )
    session.commit()
    session.refresh(schedule)
    return schedule


@router.get("", response_model=list[ScheduleRead])
def list_schedules(
    workflow_id: str,
    _context: ViewerContext,
    session: Annotated[Session, Depends(get_session)],
) -> list[WorkflowSchedule]:
    if session.get(Workflow, workflow_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return list(
        session.scalars(
            select(WorkflowSchedule)
            .where(WorkflowSchedule.workflow_id == workflow_id)
            .order_by(WorkflowSchedule.created_at, WorkflowSchedule.id)
        )
    )
