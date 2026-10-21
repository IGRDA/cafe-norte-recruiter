"""Composition root. Reads the environment once, names every concrete adapter, builds the app.

Defaults are fakes: ``make run`` with no ``.env`` serves the page with a scripted model, an
in-memory store, a canned retriever and voice off. Nothing else in the package reads
``os.environ``."""

import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from cafe_norte.api.access import AccessGate, gate_from_env
from cafe_norte.api.contracts import ErrorResponse
from cafe_norte.api.routes import TurnTasks, build_router
from cafe_norte.conversation import prompts
from cafe_norte.conversation.contracts import ConversationRuntime, SignalAnalyzer
from cafe_norte.conversation.handlers import all_handlers
from cafe_norte.conversation.registry import ToolRegistry
from cafe_norte.conversation.runtime import Limits, Runtime
from cafe_norte.conversation.signals import ModelSignalAnalyzer
from cafe_norte.domain.configuration import load_configurations
from cafe_norte.domain.contracts import ConfigId, StoreConfiguration
from cafe_norte.errors import MESSAGES, ErrorCode, Language, ServiceError
from cafe_norte.knowledge.contracts import Retriever
from cafe_norte.knowledge.hybrid import HybridRetriever
from cafe_norte.knowledge.index import lexical_index, load_index
from cafe_norte.knowledge.loader import load_documents
from cafe_norte.model.contracts import Model, ModelFinished, ModelText
from cafe_norte.model.fake import FakeModel
from cafe_norte.model.select import model_from_env
from cafe_norte.observability.contracts import ProcessVersions
from cafe_norte.persistence.contracts import Store
from cafe_norte.persistence.export import SCHEMA_VERSION
from cafe_norte.persistence.memory import MemoryStore
from cafe_norte.persistence.postgres import PostgresStore
from cafe_norte.persistence.seed import seed_calendar
from cafe_norte.voice.contracts import (
    RoomProvisioner,
    VoiceMode,
    VoiceSessionController,
    VoiceTexts,
)

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
    versions: ProcessVersions,
    rooms: RoomProvisioner | None = None,
    voice: VoiceSessionController | None = None,
    web_dir: Path | None = None,
    voice_mode: VoiceMode = "off",
    max_voice_sessions: int = 2,
    session_seconds: float = 480.0,
    warm_up: Callable[[], Awaitable[None]] | None = None,
    seed: bool = False,
) -> FastAPI:
    """Build from typed collaborators. Lifespan: open the store (migrations), seed the
    simulated calendar when ``seed`` is set, ``warm_up`` (the embedding model) before the first
    request, cancel in-flight turns on
    shutdown. Later stages add lease renewal and the summary worker."""
    tasks = TurnTasks()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await store.open()
        if seed:
            await seed_calendar(store, configurations, now=datetime.now(UTC))
        if warm_up is not None:
            await warm_up()
        yield
        await tasks.shutdown()
        await store.close()

    app = FastAPI(title="Café Norte · Ana", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.include_router(
        build_router(
            runtime=runtime,
            store=store,
            configurations=configurations,
            rooms=rooms,
            voice=voice,
            gate=gate,
            versions=versions,
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


def _signals(env: Mapping[str, str]) -> SignalAnalyzer | None:
    """The asynchronous classifier is opt-in: ``CAFE_NORTE_SIGNAL_MODEL`` names a small model
    (same selector format as ``CAFE_NORTE_MODEL``); unset, no turn pays for a second call."""
    selector = env.get("CAFE_NORTE_SIGNAL_MODEL", "")
    return ModelSignalAnalyzer(model_from_env(selector, env)) if selector else None


def create_default_app(env: Mapping[str, str] | None = None) -> FastAPI:
    """Select adapters from ``env`` (default ``os.environ``) and call ``create_app``."""
    env = env if env is not None else os.environ
    voice_mode = _voice_mode(env)
    store = _store(env, voice_mode=voice_mode)
    configurations = load_configurations(Path(env.get("CAFE_NORTE_CONFIG_DIR", "config")))
    retriever, warm_up = _retriever(env, configurations)
    registry = ToolRegistry(
        all_handlers(store=store, configurations=configurations, retriever=retriever)
    )
    model = _model(env)
    runtime = Runtime(
        model=model,
        tools=registry,
        store=store,
        configurations=configurations,
        signals=_signals(env),
        limits=Limits(
            llm_first_output_seconds=float(env.get("CAFE_NORTE_LLM_FIRST_OUTPUT_SECONDS", "6")),
            tool_seconds=float(env.get("CAFE_NORTE_TOOL_SECONDS", "10")),
            session_seconds=float(env.get("CAFE_NORTE_SESSION_SECONDS", "480")),
            max_answer_characters=int(env.get("CAFE_NORTE_MAX_ANSWER_CHARACTERS", "600")),
        ),
        owner=env.get("K_REVISION", "local"),
    )
    rooms: RoomProvisioner | None = None
    voice: VoiceSessionController | None = None
    if voice_mode == "pipecat":
        rooms, voice = _hosted_voice(env, runtime)
    return create_app(
        runtime=runtime,
        store=store,
        configurations=configurations,
        gate=gate_from_env(env),
        versions=ProcessVersions(
            model_id=model.model_id,
            prompt_version=prompts.PROMPT_VERSION,
            schema_version=SCHEMA_VERSION,
            commit_sha=env.get("CAFE_NORTE_COMMIT_SHA", "local"),
            voice_id=env.get("ELEVENLABS_VOICE_ID", "") if voice_mode == "pipecat" else "",
        ),
        web_dir=Path(env.get("CAFE_NORTE_WEB_DIR", "web")),
        voice_mode=voice_mode,
        rooms=rooms,
        voice=voice,
        max_voice_sessions=int(env.get("CAFE_NORTE_MAX_VOICE_SESSIONS", "2")),
        session_seconds=float(env.get("CAFE_NORTE_SESSION_SECONDS", "480")),
        warm_up=warm_up,
        seed=True,
    )


def _store(env: Mapping[str, str], *, voice_mode: VoiceMode) -> Store:
    """Postgres when ``CAFE_NORTE_DATABASE_URL`` is set, the memory store otherwise, so
    ``make run`` with no ``.env`` needs no Docker. Hosted voice on Postgres waits for the
    admission rows of the next persistence stage: a per-process cap would be forgotten by a
    restart, and refusing at startup is better than a cap that is not one."""
    dsn = env.get("CAFE_NORTE_DATABASE_URL", "")
    if not dsn:
        return MemoryStore()
    if voice_mode == "pipecat":
        raise ValueError("CAFE_NORTE_VOICE=pipecat on Postgres needs the admission rows (PR2)")
    return PostgresStore(dsn, pool_size=int(env.get("CAFE_NORTE_DB_POOL_SIZE", "5")))


def _retriever(
    env: Mapping[str, str], configurations: Mapping[ConfigId, StoreConfiguration]
) -> tuple[Retriever, Callable[[], Awaitable[None]] | None]:
    """``lexical``: BM25 over ``kb/`` built at startup, no extra, no artifact. ``hybrid``: the
    artifact from ``make build-index`` plus FastEmbed for queries, warmed up before serving."""
    mode = env.get("CAFE_NORTE_RETRIEVER", "lexical")
    versions = {c.kb_version for c in configurations.values()}
    if len(versions) != 1:
        raise ValueError(f"configurations disagree on kb_version: {sorted(versions)}")
    kb_version = versions.pop()
    if mode == "lexical":
        documents = load_documents(Path(env.get("CAFE_NORTE_KB_DIR", "kb")))
        return HybridRetriever(lexical_index(documents, kb_version=kb_version), None), None
    if mode == "hybrid":
        from cafe_norte.knowledge.embedder import DEFAULT_MODEL, FastEmbedEmbedder

        index = load_index(Path(env.get("CAFE_NORTE_KB_INDEX", "kb/index")), kb_version=kb_version)
        embedder = FastEmbedEmbedder(env.get("CAFE_NORTE_EMBEDDING_MODEL", DEFAULT_MODEL))
        if index.manifest.embedding_model != embedder.name:
            raise ValueError(
                f"index built with {index.manifest.embedding_model}, not {embedder.name}"
            )
        return HybridRetriever(index, embedder), embedder.warm_up
    raise ValueError(f"CAFE_NORTE_RETRIEVER must be lexical or hybrid, not {mode!r}")


def _voice_mode(env: Mapping[str, str]) -> VoiceMode:
    value = env.get("CAFE_NORTE_VOICE", "off")
    if value not in ("off", "browser", "pipecat"):
        raise ValueError(f"CAFE_NORTE_VOICE must be off, browser or pipecat, not {value!r}")
    return value  # type: ignore[return-value]


def voice_texts() -> dict[Language, VoiceTexts]:
    def texts(language: Language) -> VoiceTexts:
        table = prompts.table("voice", language)
        return VoiceTexts(
            opening=prompts.load("opening", language).strip(),
            filler=table["filler"],
            idle_prompt=table["idle_prompt"],
        )

    return {language: texts(language) for language in get_args(Language)}


def _hosted_voice(
    env: Mapping[str, str], runtime: Runtime
) -> tuple[RoomProvisioner, VoiceSessionController]:
    """Pipecat voice needs the three provider keys and a voice; imported lazily so the
    optional extra is never touched otherwise."""
    from cafe_norte.voice.daily import DailyRooms
    from cafe_norte.voice.pipeline import PipecatVoiceController

    missing = [
        name
        for name in (
            "DAILY_API_KEY",
            "DEEPGRAM_API_KEY",
            "ELEVENLABS_API_KEY",
            "ELEVENLABS_VOICE_ID",
        )
        if not env.get(name)
    ]
    if missing:
        raise ValueError(f"CAFE_NORTE_VOICE=pipecat needs {', '.join(missing)}")
    rooms = DailyRooms(env["DAILY_API_KEY"], httpx.AsyncClient(timeout=15))
    controller = PipecatVoiceController(
        runtime,
        deepgram_api_key=env["DEEPGRAM_API_KEY"],
        elevenlabs_api_key=env["ELEVENLABS_API_KEY"],
        voice_id=env["ELEVENLABS_VOICE_ID"],
        texts=voice_texts(),
    )
    return rooms, controller
