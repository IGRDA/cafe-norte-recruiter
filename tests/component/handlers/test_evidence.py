"""Evidence is the candidate's own words."""

from cafe_norte.domain.contracts import (
    Captured,
    Evidence,
    TurnId,
)
from tests.support.tools import World, args, context


async def test_evidence_in_none_of_the_candidates_messages_is_refused() -> None:
    w = await World().open()
    await w.said("t1", "Me llamo Lucía Marín.")
    outcome = await w.update_handler(
        context("t2"),
        args(
            "update_candidate",
            patch={"experience": "ninguna"},
            evidence_text="no tengo experiencia previa",
        ),
    )
    assert not outcome.ok and outcome.summary == "evidence_not_said"
    assert "once per message" in outcome.model_text and "repeat" in outcome.model_text
    assert (await w.current()).candidate.experience.status == "unset"


async def test_the_evidence_kept_is_the_whole_message_and_its_turn() -> None:
    w = await World().open()
    await w.said("t1", "Hola. Me llamo Lucía Marín, sí.")
    outcome = await w.update_handler(
        context("t2"),
        args(
            "update_candidate", patch={"name": "Lucía Marín"}, evidence_text="me llamo Lucía Marín"
        ),
    )
    assert outcome.ok
    name = (await w.current()).candidate.name
    assert isinstance(name, Captured)
    assert name.evidence == Evidence(
        source_turn_id=TurnId("t1"), text="Hola. Me llamo Lucía Marín, sí."
    )
