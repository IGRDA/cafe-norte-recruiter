"""SSE wire format, replay and heartbeat."""

import asyncio
from datetime import UTC, datetime

from cafe_norte.api.contracts import SessionEvent
from cafe_norte.api.events import encode, stream, to_session_event
from cafe_norte.conversation.contracts import AssistantText, TurnStarted
from cafe_norte.domain.contracts import SessionId, TurnId
from cafe_norte.persistence.contracts import EventRecord
from cafe_norte.persistence.memory import MemoryStore

NOW = datetime(2026, 10, 20, tzinfo=UTC)
SID = SessionId("s1")


def test_encode_matches_the_sse_grammar() -> None:
    event = SessionEvent(
        session_id=SID,
        seq=7,
        turn_id=TurnId("t"),
        at=NOW,
        payload=AssistantText(text="Hola.", spoken_form="Hola."),
    )
    wire = encode(event).decode()
    assert wire.startswith("id: 7\nevent: assistant_text\ndata: {")
    assert wire.endswith("}\n\n")
    assert "\n\n" not in wire[:-2]


def test_a_journaled_record_round_trips_to_a_typed_payload() -> None:
    started = TurnStarted(turn_id=TurnId("t"), language="es", text="hola")
    record = EventRecord(
        session_id=SID,
        turn_id=TurnId("t"),
        seq=1,
        kind="turn_started",
        payload_json=started.model_dump_json(),
        at=NOW,
    )
    assert to_session_event(record).payload == started


async def test_stream_replays_after_seq_and_sends_heartbeats_while_idle() -> None:
    store = MemoryStore()
    started = TurnStarted(turn_id=TurnId("t"), language="es", text="hola")
    async with store.transaction() as tx:
        for seq in (1, 2, 3):
            await store.events.append(
                tx,
                EventRecord(
                    session_id=SID,
                    turn_id=TurnId("t"),
                    seq=seq,
                    kind="turn_started",
                    payload_json=started.model_dump_json(),
                    at=NOW,
                ),
            )
    chunks: list[bytes] = []
    source = stream(store.events, SID, after_seq=1, heartbeat_seconds=0.02)
    async with asyncio.timeout(1):
        async for chunk in source:
            chunks.append(chunk)
            if chunk.startswith(b":"):
                break
    await source.aclose()
    assert [c.split(b"\n")[0] for c in chunks] == [b"id: 2", b"id: 3", b": ping"]
