"""Shared builders for offline tests: the application wired with fakes."""

from pathlib import Path

from fastapi import FastAPI

from cafe_norte.api.access import AccessGate
from cafe_norte.conversation.handlers import UpdateCandidateHandler
from cafe_norte.conversation.registry import ToolRegistry
from cafe_norte.conversation.runtime import Limits, Runtime
from cafe_norte.domain.configuration import load_configurations
from cafe_norte.knowledge.fake import FakeRetriever
from cafe_norte.main import create_app
from cafe_norte.model.contracts import Model
from cafe_norte.persistence.memory import MemoryStore

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"


def build_test_app(*, model: Model) -> FastAPI:
    store = MemoryStore()
    configurations = load_configurations(CONFIG_DIR)
    registry = ToolRegistry(
        {"update_candidate": UpdateCandidateHandler(store=store, configurations=configurations)}
    )
    runtime = Runtime(
        model=model,
        tools=registry,
        retriever=FakeRetriever(),
        store=store,
        configurations=configurations,
        signals=None,
        limits=Limits(),
        owner="test",
    )
    return create_app(
        runtime=runtime,
        store=store,
        configurations=configurations,
        gate=AccessGate(code=None, secret=b"test-secret"),
        web_dir=ROOT / "web",
    )
