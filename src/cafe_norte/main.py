"""Composition root. Reads the environment once, names every concrete adapter, builds the app.

Defaults are fakes: ``make run`` with no ``.env`` serves the page with a scripted model, an
in-memory store, a canned retriever and voice off. Nothing else in the package reads
``os.environ``."""

import os
from collections.abc import Mapping

from fastapi import FastAPI

from cafe_norte.api.access import AccessGate
from cafe_norte.conversation.contracts import ConversationRuntime
from cafe_norte.domain.contracts import ConfigId, StoreConfiguration
from cafe_norte.persistence.contracts import Store
from cafe_norte.voice.contracts import RoomProvisioner, VoiceSessionController


def create_app(
    *,
    runtime: ConversationRuntime,
    store: Store,
    configurations: dict[ConfigId, StoreConfiguration],
    gate: AccessGate,
    rooms: RoomProvisioner | None = None,
    voice: VoiceSessionController | None = None,
) -> FastAPI:
    """Build from typed collaborators. Lifespan: open the store, warm the retriever, seed the
    calendar, start lease renewal and the summary/cleanup workers; on shutdown stop admission,
    pause owned sessions and release media within Cloud Run's grace period."""
    raise NotImplementedError


def create_default_app(env: Mapping[str, str] | None = None) -> FastAPI:
    """Select adapters from ``env`` (default ``os.environ``) and call ``create_app``."""
    _ = env if env is not None else os.environ
    raise NotImplementedError
