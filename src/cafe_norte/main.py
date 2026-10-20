"""Composition root. Reads the environment once, names every concrete adapter, builds the app.

Defaults are fakes: ``make run`` with no ``.env`` serves the page with a scripted model, an
in-memory store, a canned retriever and voice off. Nothing else in the package reads
``os.environ``."""

import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from cafe_norte.api.access import AccessGate, gate_from_env
from cafe_norte.api.contracts import ErrorResponse
from cafe_norte.api.routes import TurnTasks, build_router
from cafe_norte.conversation import prompts
from cafe_norte.conversation.contracts import ConversationRuntime
from cafe_norte.conversation.handlers import all_handlers
from cafe_norte.conversation.registry import ToolRegistry
from cafe_norte.conversation.runtime import Limits, Runtime
from cafe_norte.domain.configuration import load_configurations
from cafe_norte.domain.contracts import ConfigId, StoreConfiguration
from cafe_norte.errors import MESSAGES, ErrorCode, ServiceError
from cafe_norte.knowledge.fake import FakeRetriever
from cafe_norte.model.contracts import Model, ModelFinished, ModelText
from cafe_norte.model.fake import FakeModel
from cafe_norte.model.select import model_from_env
from cafe_norte.persistence.contracts import Store
from cafe_norte.persistence.memory import MemoryStore
from cafe_norte.voice.contracts import RoomProvisioner, VoiceMode, VoiceSessionController

STATUS: dict[ErrorCode, int] = {
    "busy": 503,
    "timeout": 504,
    "provider_unavailable": 503,
    "provider_rejected": 502,
    "invalid_response": 502,
    "validation_failed": 422,
    "unauthorized": 401,
    "not_found": 404,
    "conflict": 409,
    "limit_exceeded": 429,
    "session_ended": 409,
    "internal_error": 500,
}


def create_app(
    *,
    runtime: ConversationRuntime,
    store: Store,
    configurations: dict[ConfigId, StoreConfiguration],
    gate: AccessGate,
    rooms: RoomProvisioner | None = None,
    voice: VoiceSessionController | None = None,
    web_dir: Path | None = None,
    voice_mode: VoiceMode = "off",
    max_voice_sessions: int = 2,
    session_seconds: float = 480.0,
) -> FastAPI:
    """Build from typed collaborators. Lifespan today: cancel in-flight turns on shutdown.
    Later stages add store warm-up, calendar seeding, lease renewal and the summary worker."""
    tasks = TurnTasks()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await tasks.shutdown()

    app = FastAPI(title="Café Norte · Ana", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.include_router(
        build_router(
            runtime=runtime,
            store=store,
            configurations=configurations,
            rooms=rooms,
            voice=voice,
            gate=gate,
            tasks=tasks,
            voice_mode=voice_mode,
            max_voice_sessions=max_voice_sessions,
            session_seconds=session_seconds,
        )
    )

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, error: ServiceError) -> JSONResponse:
        body = ErrorResponse(code=error.code, message=error.public_message("es"))
        return JSONResponse(body.model_dump(), status_code=STATUS[error.code])

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, __: RequestValidationError) -> JSONResponse:
        """Never echoes the offending input back."""
        body = ErrorResponse(code="validation_failed", message=MESSAGES["es"]["validation_failed"])
        return JSONResponse(body.model_dump(), status_code=422)

    if web_dir is not None:
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app


def _model(env: Mapping[str, str]) -> Model:
    selector = env.get("CAFE_NORTE_MODEL", "fake")
    if selector != "fake":
        return model_from_env(selector, env)
    demo = (ModelText(text=prompts.load("fake_model").strip()), ModelFinished(reason="stop"))
    return FakeModel([], fallback=demo)


def create_default_app(env: Mapping[str, str] | None = None) -> FastAPI:
    """Select adapters from ``env`` (default ``os.environ``) and call ``create_app``.

    Persistence is the in-memory store until the Postgres adapter lands; ``CAFE_NORTE_DATABASE_URL``
    is read by nothing yet."""
    env = env if env is not None else os.environ
    store = MemoryStore()
    configurations = load_configurations(Path(env.get("CAFE_NORTE_CONFIG_DIR", "config")))
    registry = ToolRegistry(all_handlers(store=store, configurations=configurations))
    runtime = Runtime(
        model=_model(env),
        tools=registry,
        retriever=FakeRetriever(),
        store=store,
        configurations=configurations,
        signals=None,
        limits=Limits(
            llm_first_output_seconds=float(env.get("CAFE_NORTE_LLM_FIRST_OUTPUT_SECONDS", "6")),
            tool_seconds=float(env.get("CAFE_NORTE_TOOL_SECONDS", "10")),
            session_seconds=float(env.get("CAFE_NORTE_SESSION_SECONDS", "480")),
            max_answer_characters=int(env.get("CAFE_NORTE_MAX_ANSWER_CHARACTERS", "600")),
        ),
        owner=env.get("K_REVISION", "local"),
    )
    return create_app(
        runtime=runtime,
        store=store,
        configurations=configurations,
        gate=gate_from_env(env),
        web_dir=Path(env.get("CAFE_NORTE_WEB_DIR", "web")),
    )
