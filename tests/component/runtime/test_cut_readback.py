"""A read-back the candidate cut: the offer, the parts, carrying on (D39)."""

import json

from cafe_norte.conversation.brief import render_brief
from cafe_norte.conversation.contracts import (
    AssistantText,
    TurnStarted,
)
from cafe_norte.conversation.readback import review_parts
from cafe_norte.domain import confirmation
from cafe_norte.domain.contracts import (
    Confirmation,
)
from cafe_norte.model.contracts import (
    ModelEvent,
)
from tests.support.builders import CONFIG, SESSION, full_record
from tests.support.harness import (
    WANTS_TOOLS,
    Harness,
    fill_record,
    present_brief,
    says,
    tools_started,
    voice_run,
)

OFFER = "Perdona, me has contestado antes de acabar. ¿Lo repasamos por partes o seguimos?"


async def cut_summary(*scripts: list[ModelEvent]) -> Harness:
    """The summary said by voice and cut after its first sentence; then ``scripts``."""
    h = Harness([[present_brief(), WANTS_TOOLS], says(""), *scripts])
    await h.open_session()
    await fill_record(h)
    events = await voice_run(h, "ya está todo", "v-1")
    turn_id = next(e for e in events if isinstance(e, TurnStarted)).turn_id
    await h.runtime.delivered(turn_id, text="Te resumo lo que tengo.", complete=False)
    return h


async def pending_now(h: Harness) -> Confirmation:
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.pending_confirmation is not None
    return state.pending_confirmation


async def test_a_yes_over_the_cut_summary_is_routed_to_the_offer_without_the_model() -> None:
    h = await cut_summary(says(OFFER))
    events = await voice_run(h, "Sí, está todo bien.", "v-2")
    assert tools_started(events) == ["review_readback"]
    pending = await pending_now(h)
    assert pending.status == "pending" and pending.review is not None
    assert pending.review.stage == "offered"
    assert "offer" in h.model.calls[-1][0].content  # readback_answered tells the model


async def test_a_plain_no_to_the_offer_carries_on_and_confirms_it_as_waived() -> None:
    h = await cut_summary(says(OFFER), says("¿Alguna duda?"))
    await voice_run(h, "Sí.", "v-2")
    events = await voice_run(h, "No.", "v-3")
    assert tools_started(events) == ["review_readback"]
    pending = await pending_now(h)
    assert pending.status == "confirmed"
    assert confirmation.assurance(pending) == "waived"


async def test_a_no_over_the_cut_summary_rejects_it() -> None:
    h = await cut_summary(says("Vale, ¿qué cambio?"))
    events = await voice_run(h, "No es correcto.", "v-2")
    assert tools_started(events) == ["confirm_brief"]
    assert (await pending_now(h)).status == "rejected"


async def test_going_over_it_each_part_is_said_and_heard_by_its_own_playback() -> None:

    parts = review_parts(render_brief(full_record(), CONFIG, "es"), "es")
    h = await cut_summary(says(OFFER), *[says("")] * len(parts), says("¿Alguna duda?"))
    await voice_run(h, "Sí.", "v-2")
    for number, part in enumerate(parts, start=3):
        events = await voice_run(h, "Sí.", f"v-{number}")
        said = " ".join(e.text for e in events if isinstance(e, AssistantText))
        assert said == part  # the part, word for word, and nothing else
        turn_id = next(e for e in events if isinstance(e, TurnStarted)).turn_id
        await h.runtime.delivered(turn_id, text=part, complete=False)  # heard to its check
        assert (await pending_now(h)).fully_delivered is True
    await voice_run(h, "Sí.", "v-9")
    pending = await pending_now(h)
    assert pending.status == "confirmed"
    assert confirmation.assurance(pending) == "reviewed"


def pending_seen(h: Harness) -> dict[str, object]:
    """The pending read-back as the model saw it in its last call."""
    content = h.model.calls[-1][0].content
    facts = json.loads(content.split("## Datos de esta sesión (JSON)\n", 1)[1].split("\n\n")[0])
    pending = facts["pending_confirmation"]
    assert isinstance(pending, dict)
    return pending


async def test_the_model_sees_whether_the_read_back_was_heard_and_where_its_review_is() -> None:
    h = await cut_summary(says(OFFER), says(""), says(""))
    await voice_run(h, "Sí.", "v-2")
    assert pending_seen(h) | {"heard": False, "review": "offered"} == pending_seen(h)
    await voice_run(h, "Sí.", "v-3")
    review = pending_seen(h)["review"]
    assert isinstance(review, str) and review.startswith("part 1 of ")
    await voice_run(h, "Sigue.", "v-4")
    assert pending_seen(h)["review"] == "waived" and pending_seen(h)["status"] == "confirmed"
