"""The live path end to end on loopback: the real app served by uvicorn on 127.0.0.1, the
scripted model, the runner's HTTP adapter. Same scenario, both modes, same verdicts."""

import httpx
from evals.live import HttpConversation, ScriptedCandidate, drive, serve
from evals.runner import load_scenarios, run_fake, script_events
from evals.scorers import run_check

from cafe_norte.domain.contracts import ConfigId
from cafe_norte.model.fake import FakeModel
from tests.support.app import build_test_app


async def test_a_scripted_scenario_scores_the_same_live_and_fake() -> None:
    (scenario,) = load_scenarios(only=["S03"])
    scripts = [r for steps in scenario.fake_script for r in script_events(steps)]
    app = build_test_app(model=FakeModel(scripts))
    async with serve(app) as base_url, httpx.AsyncClient(base_url=base_url) as client:
        live = HttpConversation(
            client,
            config_id=ConfigId(scenario.config_id),
            language=scenario.language,
            allowed_doc_ids=frozenset(),
        )
        finished = await drive(live, ScriptedCandidate(scenario.scripted_turns), max_turns=10)

    fake = await run_fake(scenario)
    live_checks = tuple(run_check(finished.result, check) for check in scenario.checks)
    assert [c.ok for c in live_checks] == [c.ok for c in fake.checks] == [True] * 4
    assert " ".join(finished.result.spoken_by_turn[-1]) == (
        "Entendido, gracias por tu tiempo. Que vaya bien."
    )
    assert finished.export.session.lifecycle == "stopped"


async def test_drive_stops_when_the_session_ends_even_with_lines_left() -> None:
    (scenario,) = load_scenarios(only=["S03"])
    scripts = [r for steps in scenario.fake_script for r in script_events(steps)]
    lines = (*scenario.scripted_turns, "¿Sigues ahí?")
    async with (
        serve(build_test_app(model=FakeModel(scripts))) as base_url,
        httpx.AsyncClient(base_url=base_url) as client,
    ):
        live = HttpConversation(
            client,
            config_id=ConfigId("chamberi_barista_v1"),
            language="es",
            allowed_doc_ids=frozenset(),
        )
        finished = await drive(live, ScriptedCandidate(lines), max_turns=10)
    assert len(finished.result.spoken_by_turn) == 2


async def test_drive_stops_at_the_turn_cap() -> None:
    (scenario,) = load_scenarios(only=["S03"])
    scripts = [r for steps in scenario.fake_script for r in script_events(steps)]
    async with (
        serve(build_test_app(model=FakeModel(scripts))) as base_url,
        httpx.AsyncClient(base_url=base_url) as client,
    ):
        live = HttpConversation(
            client,
            config_id=ConfigId("chamberi_barista_v1"),
            language="es",
            allowed_doc_ids=frozenset(),
        )
        finished = await drive(live, ScriptedCandidate(scenario.scripted_turns), max_turns=1)
    assert len(finished.result.spoken_by_turn) == 1
