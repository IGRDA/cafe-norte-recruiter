"""``RuntimeBridge``: the one Pipecat ``FrameProcessor`` that talks to the runtime.

Imports Pipecat lazily so the rest of the application never depends on it."""

from cafe_norte.conversation.contracts import ConversationRuntime
from cafe_norte.domain.contracts import SessionId


def build_bridge(runtime: ConversationRuntime, session_id: SessionId) -> object:
    """Create the processor. Returns ``object`` here because Pipecat types are optional.

    Behaviour: final transcription frame → ``TurnInput`` → ``run_turn``; each ``AssistantText``
    becomes a text frame with ``spoken_form``; interruption frame → close the generator,
    report ``delivered(text, complete=False)``; a filler acknowledgement is emitted only while a
    tool is actually running and is excluded from useful-answer latency."""
    raise NotImplementedError
