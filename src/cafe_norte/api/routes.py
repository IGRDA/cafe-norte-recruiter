"""Routes from ports."""

from fastapi import APIRouter

from cafe_norte.api.access import AccessGate
from cafe_norte.conversation.contracts import ConversationRuntime
from cafe_norte.domain.contracts import ConfigId, StoreConfiguration
from cafe_norte.persistence.contracts import Store
from cafe_norte.voice.contracts import RoomProvisioner, VoiceSessionController


def build_router(
    *,
    runtime: ConversationRuntime,
    store: Store,
    configurations: dict[ConfigId, StoreConfiguration],
    rooms: RoomProvisioner | None,
    voice: VoiceSessionController | None,
    gate: AccessGate,
) -> APIRouter:
    """Voice endpoints return ``provider_unavailable`` when ``rooms``/``voice`` are None."""
    raise NotImplementedError
