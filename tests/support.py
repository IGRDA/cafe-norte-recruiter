"""Shared builders for offline tests: the application wired with fakes."""

from pathlib import Path

from fastapi import FastAPI

from cafe_norte.api.access import AccessGate
from cafe_norte.conversation.handlers import all_handlers
from cafe_norte.conversation.registry import ToolRegistry
from cafe_norte.conversation.runtime import Limits, Runtime
from cafe_norte.domain.configuration import load_configurations
from cafe_norte.knowledge.fake import FakeRetriever
from cafe_norte.main import close_hook, create_app
from cafe_norte.model.contracts import Model
from cafe_norte.observability.contracts import Estimator, ProcessVersions
from cafe_norte.persistence.export import SCHEMA_VERSION
from cafe_norte.persistence.memory import MemoryStore
from cafe_norte.voice.contracts import RoomProvisioner, VoiceMode, VoiceSessionController

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
VERSIONS = ProcessVersions(
    model_id="fake", prompt_version="test", schema_version=SCHEMA_VERSION, commit_sha="test"
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
) -> FastAPI:
    store = store if store is not None else MemoryStore()
    configurations = load_configurations(CONFIG_DIR)
    registry = ToolRegistry(
        all_handlers(store=store, configurations=configurations, retriever=FakeRetriever())
    )
    runtime = Runtime(
        model=model,
        tools=registry,
        store=store,
        configurations=configurations,
        signals=None,
        limits=Limits(),
        owner="test",
        on_closed=close_hook(store, configurations, VERSIONS, estimate),
    )
    return create_app(
        runtime=runtime,
        store=store,
        configurations=configurations,
        gate=AccessGate(code=access_code, secret=b"test-secret"),
        versions=VERSIONS,
        web_dir=ROOT / "web",
        voice_mode=voice_mode,
        rooms=rooms,
        voice=voice,
        estimate=estimate,
    )
