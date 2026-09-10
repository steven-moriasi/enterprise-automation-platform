from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.executions import router as executions_router
from app.api.routes.health import router as health_router
from app.api.routes.schedules import router as schedules_router
from app.api.routes.webhooks import router as webhooks_router
from app.api.routes.workflows import router as workflows_router
from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)
    yield


app = FastAPI(
    title="Enterprise Automation Platform",
    description=(
        "Portfolio/reference implementation for reliable enterprise workflow execution. "
        "It is not presented as a deployed commercial system."
    ),
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(health_router)
app.include_router(workflows_router)
app.include_router(schedules_router)
app.include_router(webhooks_router)
app.include_router(executions_router)
