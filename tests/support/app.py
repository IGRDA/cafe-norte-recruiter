"""The application and the runtime wired with fakes, as ``main.py`` wires the real ones."""

from collections.abc import Awaitable, Callable
from datetime import datetime

from fastapi import FastAPI

from cafe_norte.api.access import AccessGate
from cafe_norte.api.limits import RequestLimits
from cafe_norte.conversation.contracts import SignalAnalyzer
from cafe_norte.conversation.handlers import all_handlers
from cafe_norte.conversation.registry import ToolRegistry
from cafe_norte.conversation.runtime import Limits, Runtime, _utcnow
from cafe_norte.conversation.wording import Wording
from cafe_norte.domain.contracts import SessionId
from cafe_norte.knowledge.contracts import Retriever
from cafe_norte.knowledge.fake import FakeRetriever
from cafe_norte.main import close_hook, create_app
from cafe_norte.model.contracts import Model
from cafe_norte.observability.contracts import Estimator, ProcessVersions, Telemetry
from cafe_norte.observability.fakes import NullTelemetry
from cafe_norte.persistence.contracts import Store
from cafe_norte.persistence.export import SCHEMA_VERSION
from cafe_norte.persistence.memory import MemoryStore
from cafe_norte.voice.contracts import RoomProvisioner, VoiceMode, VoiceSessionController
from tests.support import ROOT
from tests.support.builders import CONFIGS

VERSIONS = ProcessVersions(
    model_id="fake", prompt_version="test", schema_version=SCHEMA_VERSION, commit_sha="test"
)


def build_runtime(
    *,
    model: Model,
    store: Store,
    owner: str = "test",
    signals: SignalAnalyzer | None = None,
    limits: Limits | None = None,
    telemetry: Telemetry | None = None,
    clock: Callable[[], datetime] | None = None,
    on_closed: Callable[[SessionId], Awaitable[None]] | None = None,
    retriever: Retriever | None = None,
    wording: Wording | None = None,
) -> Runtime:
    """The real runtime and handlers over ``store``, the real configuration and no knowledge
    unless a ``retriever`` is given."""
    return Runtime(
        model=model,
        tools=ToolRegistry(
            all_handlers(
                store=store, configurations=CONFIGS, retriever=retriever or FakeRetriever()
            )
        ),
        store=store,
        configurations=CONFIGS,
        signals=signals,
        limits=limits or Limits(),
        telemetry=telemetry or NullTelemetry(),
        owner=owner,
        on_closed=on_closed,
        clock=clock or _utcnow,
        wording=wording,
    )


def build_test_app(
    *,
    model: Model,
    voice_mode: VoiceMode = "off",
    rooms: RoomProvisioner | None = None,
    voice: VoiceSessionController | None = None,
    access_code: str | None = None,
    store: MemoryStore | None = None,
    estimate: Estimator | None = None,
    retriever: Retriever | None = None,
    request_limits: RequestLimits | None = None,
) -> FastAPI:
    store = store if store is not None else MemoryStore()
    return create_app(
        runtime=build_runtime(
            model=model,
            store=store,
            on_closed=close_hook(store, CONFIGS, VERSIONS, estimate),
            retriever=retriever,
        ),
        store=store,
        configurations=CONFIGS,
        gate=AccessGate(code=access_code, secret=b"test-secret"),
        versions=VERSIONS,
        web_dir=ROOT / "web",
        voice_mode=voice_mode,
        rooms=rooms,
        voice=voice,
        estimate=estimate,
        request_limits=request_limits,
    )
