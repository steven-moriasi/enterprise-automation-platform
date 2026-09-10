from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_execution_queue
from app.infrastructure.database import get_session
from app.infrastructure.queue import RedisExecutionQueue

router = APIRouter(tags=["platform"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def readiness(
    session: Annotated[Session, Depends(get_session)],
    queue: Annotated[RedisExecutionQueue, Depends(get_execution_queue)],
) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
        queue.ping()
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A required dependency is unavailable",
        ) from exc
    return {"status": "ready"}


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
