"""Server-Sent Events encoding and replay."""

import asyncio
from collections.abc import AsyncGenerator

from pydantic import TypeAdapter

from cafe_norte.api.contracts import SessionEvent, VoiceState
from cafe_norte.conversation.contracts import RuntimeEvent
from cafe_norte.domain.contracts import SessionId
from cafe_norte.persistence.contracts import EventRecord, Events

HEARTBEAT_SECONDS = 15.0

_PAYLOAD: TypeAdapter[RuntimeEvent | VoiceState] = TypeAdapter(RuntimeEvent | VoiceState)


def encode(event: SessionEvent) -> bytes:
    """``id: <seq>\\nevent: <type>\\ndata: <json>\\n\\n``."""
    data = event.model_dump_json()
    return f"id: {event.seq}\nevent: {event.payload.type}\ndata: {data}\n\n".encode()


def to_session_event(record: EventRecord) -> SessionEvent:
    return SessionEvent(
        session_id=record.session_id,
        seq=record.seq,
        turn_id=record.turn_id,
        at=record.at,
        payload=_PAYLOAD.validate_json(record.payload_json),
    )


async def stream(
    events: Events,
    session_id: SessionId,
    *,
    after_seq: int,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
) -> AsyncGenerator[bytes, None]:
    """Persisted events after ``after_seq``, then live ones; heartbeat comments keep Cloud Run's
    600-second timeout from idling the connection."""
    queue: asyncio.Queue[EventRecord] = asyncio.Queue()

    async def pump() -> None:
        async for record in events.since(session_id, after_seq):
            await queue.put(record)

    producer = asyncio.create_task(pump())
    try:
        while True:
            try:
                async with asyncio.timeout(heartbeat_seconds):
                    record = await queue.get()
            except TimeoutError:
                yield b": ping\n\n"
                continue
            yield encode(to_session_event(record))
    finally:
        producer.cancel()
