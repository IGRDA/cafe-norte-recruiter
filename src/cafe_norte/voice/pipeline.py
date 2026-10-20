"""Pipeline assembly for one session."""

from cafe_norte.conversation.contracts import ConversationRuntime
from cafe_norte.domain.contracts import SessionId
from cafe_norte.voice.contracts import Room


class PipecatVoiceController:
    """Implements ``VoiceSessionController``. Keeps provider connections open during a call,
    warms nothing per call, and releases everything on stop or SIGTERM."""

    def __init__(
        self,
        runtime: ConversationRuntime,
        *,
        deepgram_api_key: str,
        elevenlabs_api_key: str,
        voice_id: str,
    ) -> None:
        raise NotImplementedError

    async def start(self, session_id: SessionId, room: Room) -> None:
        raise NotImplementedError

    async def stop(self, session_id: SessionId, *, reason: str) -> None:
        raise NotImplementedError
