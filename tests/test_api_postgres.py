"""End to end on Postgres: the S01 scenario through the real runtime and handlers, then a
second process over the same database finds the session, its booking and its sequence."""

import pytest
from evals.runner import load_scenarios, run_fake

from cafe_norte.conversation.contracts import TurnFailed, TurnInput
from cafe_norte.conversation.handlers import all_handlers
from cafe_norte.conversation.registry import ToolRegistry
from cafe_norte.conversation.runtime import Limits, Runtime
from cafe_norte.domain.configuration import load_configurations
from cafe_norte.domain.contracts import InputId, SessionId
from cafe_norte.knowledge.fake import FakeRetriever
from cafe_norte.model.fake import FakeModel
from cafe_norte.persistence.contracts import Store
from cafe_norte.persistence.export import ExportDocument
from cafe_norte.persistence.postgres import PostgresStore
from tests.support import CONFIG_DIR
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
