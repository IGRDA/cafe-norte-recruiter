"""End to end on Postgres: the S01 scenario through the real runtime and handlers, then a
second process over the same database finds the session, its booking and its sequence."""

import pytest
from evals.runner import load_scenarios, run_fake

from cafe_norte.api.access import AccessGate
from cafe_norte.conversation.contracts import AssistantText, TurnFailed, TurnFinished, TurnInput
from cafe_norte.conversation.handlers import all_handlers
from cafe_norte.conversation.registry import ToolRegistry
from cafe_norte.conversation.runtime import Limits, Runtime
from cafe_norte.domain.configuration import load_configurations
from cafe_norte.domain.contracts import ConfigId, InputId, SessionId, SessionState
from cafe_norte.domain.fields import value_of
from cafe_norte.knowledge.fake import FakeRetriever
from cafe_norte.model.fake import FakeModel
from cafe_norte.persistence.contracts import Store
from cafe_norte.persistence.export import ExportDocument
from cafe_norte.persistence.postgres import PostgresStore
from tests.support import CONFIG_DIR
from tests.test_runtime import WANTS_TOOLS, name_call, says
from tests.test_store_contract import NOW, VERSIONS

pytestmark = pytest.mark.postgres


async def test_s01_runs_on_postgres_and_survives_a_restart(
    store: Store, test_database_url: str
) -> None:
    if not isinstance(store, PostgresStore):
        pytest.skip("the memory parameter is covered by test_scenarios.py")
    scenario = next(s for s in load_scenarios() if s.id == "S01")
    record = await run_fake(scenario, store)
    assert all(check.ok for check in record.checks), [c for c in record.checks if not c.ok]
    assert record.export is not None
    ExportDocument.model_validate_json(record.export.model_dump_json())

    restarted = PostgresStore(test_database_url)
    await restarted.open()
    session_id = SessionId("eval-S01")
    state = await restarted.sessions.get(session_id)
    assert state is not None and state.lifecycle == "completed" and state.booking is not None
    before = await restarted.snapshot(session_id, versions=VERSIONS, taken_at=NOW)
    assert before is not None and len(before.turns) == len(record.export.transcript)

    configurations = load_configurations(CONFIG_DIR)
    runtime = Runtime(
        model=FakeModel([]),
        tools=ToolRegistry(
            all_handlers(store=restarted, configurations=configurations, retriever=FakeRetriever())
        ),
        store=restarted,
        configurations=configurations,
        signals=None,
        limits=Limits(),
        owner="restarted",
    )
    turn = TurnInput(
        session_id=session_id,
        input_id=InputId("after"),
        text="¿Hola?",
        channel="text",
        received_at=NOW,
    )
    events = [e async for e in runtime.run_turn(turn)]
    assert isinstance(events[-1], TurnFailed) and events[-1].code == "session_ended"
    after = await restarted.snapshot(session_id, versions=VERSIONS, taken_at=NOW)
    assert after is not None and [e.seq for e in after.events][-1] == before.events[-1].seq + 1
    await restarted.close()


def runtime_over(store: Store, model: FakeModel, owner: str) -> Runtime:
    configurations = load_configurations(CONFIG_DIR)
    return Runtime(
        model=model,
        tools=ToolRegistry(
            all_handlers(store=store, configurations=configurations, retriever=FakeRetriever())
        ),
        store=store,
        configurations=configurations,
        signals=None,
        limits=Limits(),
        owner=owner,
        clock=lambda: NOW,
    )


async def test_s12_restart_zombie_worker_and_private_resume(
    store: Store, test_database_url: str
) -> None:
    """S12: the state and the sequence survive a container replacement, a worker that still
    holds the old lease cannot mutate the session, and the private link resumes it."""
    if not isinstance(store, PostgresStore):
        pytest.skip("S12 is about durability; the memory store dies with the process")
    session_id = SessionId("s12")
    await store.sessions.create(
        SessionState(
            session_id=session_id,
            config_id=ConfigId("chamberi_barista_v1"),
            config_version="1",
            language="es",
            channel="text",
            created_at=NOW,
        ),
        access_hash="",
    )
    gate = AccessGate(code=None, secret=b"test")
    token, token_hash = gate.new_resume_token()
    await store.resume_tokens.issue(session_id, token_hash, gate.expiry(NOW))
    first = runtime_over(store, FakeModel([[name_call(), WANTS_TOOLS], says("Encantada.")]), "a")
    async for _ in first.open_session(session_id):
        pass
    async for _ in first.run_turn(turn_input(session_id, "Soy Lucía", "in-1")):
        pass
    zombie = await store.leases.claim(session_id, "a", ttl_seconds=60)  # "a" dies holding it
    assert zombie is not None
    await store.close()

    replacement = PostgresStore(test_database_url)
    await replacement.open()
    second = runtime_over(replacement, FakeModel([says("Sigo aquí.")]), "b")
    refused = [e async for e in second.run_turn(turn_input(session_id, "¿Hola?", "in-2"))]
    assert isinstance(refused[-1], TurnFailed) and refused[-1].code == "conflict"
    await replacement.leases.release(zombie)  # the TTL does this by itself after a minute

    resumed = await replacement.resume_tokens.redeem(gate.token_hash(token), now=NOW)
    assert resumed == session_id
    spoken = [e async for e in second.resume_session(session_id)]
    assert isinstance(spoken[1], AssistantText) and spoken[1].text.startswith("Hola de nuevo")
    state = await replacement.sessions.get(session_id)
    assert state is not None and state.candidate.name.status == "captured"
    assert value_of(state.candidate.name) == "Lucía"
    done = [e async for e in second.run_turn(turn_input(session_id, "¿Hola?", "in-3"))]
    assert isinstance(done[-1], TurnFinished)
    snapshot = await replacement.snapshot(session_id, versions=VERSIONS, taken_at=NOW)
    assert snapshot is not None
    seqs = [e.seq for e in snapshot.events]
    assert seqs == list(range(1, len(seqs) + 1))
    await replacement.close()


def turn_input(session_id: SessionId, text: str, input_id: str) -> TurnInput:
    return TurnInput(
        session_id=session_id,
        input_id=InputId(input_id),
        text=text,
        channel="text",
        received_at=NOW,
    )
