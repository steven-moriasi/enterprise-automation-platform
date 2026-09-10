import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.enums import WorkflowStatus
from app.domain.models import Execution, Workflow
from app.domain.schemas import ExecutionCreate, ExecutionRead, WorkflowCreate, WorkflowRead
from app.infrastructure.auth import AuthContext, require_roles
from app.infrastructure.database import get_session
from app.services.audit import append_audit_event
from app.services.execution_requests import request_execution

router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])
AdminContext = Annotated[AuthContext, Depends(require_roles("admin"))]
OperatorContext = Annotated[AuthContext, Depends(require_roles("admin", "operator"))]
ViewerContext = Annotated[AuthContext, Depends(require_roles("admin", "operator", "viewer"))]


@router.post("", response_model=WorkflowRead, status_code=status.HTTP_201_CREATED)
def create_workflow(
    payload: WorkflowCreate,
    context: AdminContext,
    session: Annotated[Session, Depends(get_session)],
) -> Workflow:
    workflow = Workflow(
        name=payload.name,
        description=payload.description,
        version=payload.version,
        status=payload.status,
        steps=[step.model_dump(mode="json") for step in payload.steps],
        max_attempts=payload.max_attempts,
        retry_base_seconds=payload.retry_base_seconds,
        created_by=context.subject,
    )
    session.add(workflow)
    try:
        session.flush()
        append_audit_event(
            session,
            event_type="workflow_created",
            actor_id=context.subject,
            correlation_id=str(uuid.uuid4()),
            workflow_id=workflow.id,
            details={"name": workflow.name, "version": workflow.version},
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workflow name and version already exist",
        ) from exc
    session.refresh(workflow)
    return workflow


@router.get("", response_model=list[WorkflowRead])
def list_workflows(
    _context: ViewerContext,
    session: Annotated[Session, Depends(get_session)],
) -> list[Workflow]:
    return list(session.scalars(select(Workflow).order_by(Workflow.name, Workflow.version)))


@router.get("/{workflow_id}", response_model=WorkflowRead)
def get_workflow(
    workflow_id: str,
    _context: ViewerContext,
    session: Annotated[Session, Depends(get_session)],
) -> Workflow:
    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return workflow


@router.post(
    "/{workflow_id}/executions",
    response_model=ExecutionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_execution(
    workflow_id: str,
    payload: ExecutionCreate,
    context: OperatorContext,
    session: Annotated[Session, Depends(get_session)],
    response: Response,
    idempotency_key: Annotated[
        str,
        Header(alias="X-Idempotency-Key", min_length=8, max_length=160),
    ],
    correlation_id: Annotated[
        str | None,
        Header(alias="X-Correlation-ID", min_length=8, max_length=160),
    ] = None,
) -> Execution:
    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if workflow.status != WorkflowStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only active workflows can be executed",
        )

    request_correlation_id = correlation_id or str(uuid.uuid4())
    execution, replayed = request_execution(
        session,
        workflow=workflow,
        trigger_type=payload.trigger_type,
        idempotency_key=idempotency_key,
        input_payload=payload.input_payload,
        correlation_id=request_correlation_id,
        requested_by=context.subject,
    )
    if replayed:
        response.headers["Idempotent-Replay"] = "true"
    return execution
