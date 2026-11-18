import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.controllers import health
from app.controllers.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.db import mongo
from app.db.indexes import ensure_indexes
from app.dependencies import get_push_service, get_reminder_service
from app.schemas.push import ReminderRunResult
from app.tasks.reminder_loop import reminder_loop

logger = logging.getLogger(__name__)


def _clean_message(message: str) -> str:
    return message.removeprefix("Value error, ")


def _error(status_code: int, message: str, **extra: object) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": False, "error": message, **extra})


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return _error(exc.status_code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(p) for p in err["loc"][1:]),
                "message": _clean_message(err["msg"]),
            }
            for err in exc.errors()
        ]
        first = exc.errors()[0]["msg"] if exc.errors() else ""
        # Custom validators carry user-facing text; built-in ones get a generic message.
        message = _clean_message(first) if first.startswith("Value error, ") else "Invalid request."
        return _error(422, message, details=details)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=exc)
        return _error(500, "Something went wrong. Please try again.")


async def _send_due_reminders() -> ReminderRunResult:
    db = mongo.get_database()
    return await get_reminder_service(db, get_push_service(db)).send_due()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        mongo.connect(settings)
        if settings.ensure_indexes_on_startup:
            try:
                await ensure_indexes(mongo.get_database())
            except Exception:
                logger.exception("Could not verify MongoDB indexes; continuing")
        stop = asyncio.Event()
        reminder_task: asyncio.Task[None] | None = None
        # A timer can't run on serverless hosts (the function is frozen between requests); there
        # an external scheduler must call /api/v1/cron/send-reminders instead.
        on_vercel = bool(os.environ.get("VERCEL"))
        if on_vercel and settings.reminder_timer_enabled:
            logger.info("Running on Vercel: reminder timer disabled, use the cron endpoint")
        if settings.reminder_timer_enabled and not on_vercel:
            reminder_task = asyncio.create_task(
                reminder_loop(_send_due_reminders, settings.reminder_interval_seconds, stop)
            )
        try:
            yield
        finally:
            stop.set()
            if reminder_task is not None:
                await reminder_task
            await mongo.disconnect()

    app = FastAPI(
        title=f"{settings.app_name} API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",  # always on, in every environment
        openapi_url="/openapi.json",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    _register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


def _misconfigured_app(missing: list[str]) -> FastAPI:
    """Served instead of the real app when required settings are absent.

    Serverless hosts turn a crash on import into an opaque 500 (FUNCTION_INVOCATION_FAILED).
    This answers every request with the names (never the values) of the missing variables.
    """
    message = "Server is not configured. Missing environment variables: " + ", ".join(missing)
    logger.error(message)
    fallback = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @fallback.api_route(
        "/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    )
    async def _not_configured(path: str) -> JSONResponse:
        return _error(503, message)

    return fallback


def build_app() -> FastAPI:
    try:
        return create_app()
    except ValidationError as exc:
        missing = sorted(
            {str(err["loc"][0]).upper() for err in exc.errors() if err["type"] == "missing"}
        )
        if not missing:
            raise
        return _misconfigured_app(missing)


app = build_app()
