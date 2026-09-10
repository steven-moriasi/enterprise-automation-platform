import hashlib
import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.domain.enums import TriggerType, WorkflowStatus
from app.domain.models import Execution, Workflow
from app.domain.schemas import ExecutionRead
from app.domain.types import JsonObject
from app.infrastructure.database import get_session
from app.services.execution_requests import request_execution

router = APIRouter(prefix="/api/v1/workflows", tags=["webhooks"])
json_object_adapter = TypeAdapter(JsonObject)


@router.post(
    "/{workflow_id}/webhook",
    response_model=ExecutionRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_webhook(
    workflow_id: str,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    signature: Annotated[str, Header(alias="X-Webhook-Signature")],
    event_id: Annotated[
        str,
        Header(alias="X-Webhook-Event-ID", min_length=8, max_length=160),
    ],
) -> Execution:
    if settings.webhook_signing_secret is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook signing is not configured",
        )
    body = await request.body()
    if len(body) > settings.max_webhook_body_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Webhook body exceeds the configured limit",
        )
    expected = "sha256=" + hmac.new(
        settings.webhook_signing_secret.get_secret_value().encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook signature validation failed",
        )
    try:
        payload = json_object_adapter.validate_json(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Webhook body must be a JSON object",
        ) from exc

    workflow = session.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if workflow.status != WorkflowStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only active workflows can receive webhooks",
        )

    execution, replayed = request_execution(
        session,
        workflow=workflow,
        trigger_type=TriggerType.WEBHOOK,
        idempotency_key=f"webhook:{event_id}",
        correlation_id=event_id,
        requested_by="webhook",
        input_payload=payload,
    )
    if replayed:
        response.headers["Idempotent-Replay"] = "true"
    return execution
