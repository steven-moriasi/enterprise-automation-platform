from sqlalchemy.orm import Session

from app.domain.models import AuditEvent
from app.domain.types import JsonObject


def append_audit_event(
    session: Session,
    *,
    event_type: str,
    actor_id: str,
    correlation_id: str,
    details: JsonObject,
    workflow_id: str | None = None,
    execution_id: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        event_type=event_type,
        actor_id=actor_id,
        correlation_id=correlation_id,
        details=details,
        workflow_id=workflow_id,
        execution_id=execution_id,
    )
    session.add(event)
    return event
