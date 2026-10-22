"""The read-back behaviour matrix, on fakes only: every kind of read-back x where its
saying is cut x what the candidate says first x how they go on. A small policy model follows
the prompt's read-back rules from the facts it is given, so no row needs a script of its own.

Invariants, for every row: no turn fails and the read-back settles within a few turns; the
export's ``assurance`` (heard whole, gone over to the end, or carried on after the offer) is the
one the row's path predicts, so nothing is confirmed without a full hearing or an explicit
carry-on; no read-back is said whole more than twice."""

import json
from collections.abc import Sequence
from datetime import date
from typing import Literal

import pytest

from cafe_norte.conversation.brief import field_readback, render_brief
from cafe_norte.conversation.contracts import (
    AssistantText,
    RuntimeEvent,
    TurnFailed,
    TurnInput,
    TurnStarted,
)
from cafe_norte.conversation.prompt import sentences
from cafe_norte.conversation.readback import review_parts
from cafe_norte.domain.contracts import InputId, SessionState
from cafe_norte.model.contracts import ModelEvent, ModelMessage, ModelText, ToolCall, ToolSchema
from cafe_norte.model.fake import FakeModel
from cafe_norte.persistence.export import build_export
from cafe_norte.persistence.memory import MemoryStore
from cafe_norte.persistence.seed import seed_calendar
from tests.support.builders import CONFIG, CONFIGS, NOW, SESSION, STAMP, full_record
from tests.support.harness import (
    WANTS_TOOLS,
    Harness,
    fill_record,
    offer_call,
    present_brief,
    says,
)

Kind = Literal["date", "phone", "brief", "slot"]
Reply = Literal["yes", "no", "correction", "carry_on", "unrelated"]
FollowUp = Literal["go_over", "carry_on"]
Outcome = Literal["heard", "reviewed", "waived", "rejected"]

OFFER = "Perdona, me has contestado antes de acabar. ¿Lo repasamos por partes o seguimos?"
UNRELATED = "¿Hay parking cerca?"
REPLIES: dict[Reply, str] = {
    "yes": "Sí.",
    "no": "No.",
    "carry_on": "Sigue.",
    "unrelated": UNRELATED,
}
FOLLOW_UPS = 8  # turns after the first reply; the longest path (four parts) needs six


def update(evidence: str, **patch: object) -> ToolCall:
    payload = {"patch": patch, "evidence_text": evidence}
    return ToolCall(call_id="u1", name="update_candidate", arguments_json=json.dumps(payload))


# What the candidate says (and the model calls) until the read-back is said, the last line
# being the one that says it; then what they say to correct it, and the model's call for that.
SETUP: dict[Kind, tuple[tuple[str, ToolCall | None], ...]] = {
    "date": (
        ("El 2 de noviembre.", update("El 2 de noviembre.", earliest_start_date="2026-11-02")),
    ),
    "phone": (
        ("Mi teléfono es el 612 345 678.", update("612 345 678", contact_phone="+34612345678")),
    ),
    "brief": (("Ya está todo.", present_brief()),),
    "slot": (
        ("Sí, quiero entrevista.", offer_call("2026-10-23")),
        ("El viernes a las diez y media.", None),  # the runtime reads that slot back
    ),
}
CORRECTION: dict[Kind, tuple[str, ToolCall | None]] = {
    "date": (
        "No, el tres de noviembre.",
        update("el tres de noviembre", earliest_start_date="2026-11-03"),
    ),
    "phone": ("No, es el 699 111 222.", update("699 111 222", contact_phone="+34699111222")),
    "brief": ("No, son veinte horas a la semana.", update("veinte horas", hours_per_week=20)),
    "slot": ("El de las cinco.", None),  # the other Friday slot: the runtime reads it back
}
READ_BACK: dict[Kind, str] = {
    "date": field_readback("earliest_start_date", date(2026, 11, 2), "es"),
    "phone": field_readback("contact_phone", "+34612345678", "es"),
    "brief": render_brief(full_record(), CONFIG, "es"),
    "slot": "He apuntado la entrevista el viernes. ¿Te la reservo?",  # two sentences, checked
}


class Policy:
    """Follows system.md's read-back rules from the session facts: the setup calls first; then
    the offer when the system asks for it; an update for a correction; an answer and the
    read-back presented again for an unrelated question; nothing otherwise."""

    def __init__(self, setup: Sequence[ToolCall | None], correction: ToolCall | None) -> None:
        self._setup = list(setup)
        self._correction = correction

    def __call__(
        self, messages: tuple[ModelMessage, ...], tools: tuple[ToolSchema, ...]
    ) -> list[ModelEvent]:
        return self._decide(messages)

    def _decide(self, messages: tuple[ModelMessage, ...]) -> list[ModelEvent]:
        last = messages[-1]
        if last.role == "tool":
            if "present the brief again" in last.content:  # after a corrected fact
                return [present_brief("p2"), WANTS_TOOLS]
            return says("")
        if self._setup:
            call = self._setup.pop(0)
            return says("") if call is None else [call, WANTS_TOOLS]
        facts = json.loads(
            messages[0].content.split("## Datos de esta sesión (JSON)\n", 1)[1].split("\n\n")[0]
        )
        if "Make the one offer" in (facts["readback_answered"] or ""):
            return says(OFFER)
        pending = facts["pending_confirmation"]
        if last.content.startswith(("No, ", "El de")) and self._correction is not None:
            return [self._correction, WANTS_TOOLS]
        if last.content == UNRELATED and pending is not None and pending["status"] == "pending":
            target = {"target": pending["kind"]}
            if pending["kind"] == "field":
                target["field"] = pending["field"]
            if pending["kind"] == "slot":
                target["slot_id"] = pending["slot_id"]
            again = ToolCall(
                call_id="p3", name="present_confirmation", arguments_json=json.dumps(target)
            )
            return [ModelText(text="No lo sé, lo consulto después."), again, WANTS_TOOLS]
        return says("")


def expected(kind: Kind, cut: bool, reply: Reply, follow: FollowUp) -> Outcome:
    """Expected assurance for the read-back path exercised by this row."""
    if reply == "no" and kind != "slot":
        return "rejected"  # a no rejects a read-back, heard or not; a slot's no is the model's
    if reply == "correction" or not cut:
        return "heard"  # the corrected read-back is said again whole and heard
    one_part = len(review_parts(READ_BACK[kind], "es")) == 1
    if reply == "unrelated":  # presented again: straight to its first part, heard
        return "reviewed" if follow == "go_over" or one_part else "waived"
    if one_part:  # no offer: only a carry-on waives it; a yes says it again once and
        return "waived" if reply == "carry_on" else "reviewed"  # the next answer confirms it
    return "reviewed" if follow == "go_over" else "waived"


def next_line(state: SessionState, follow: FollowUp) -> str | None:
    """The simulated candidate after the first reply: hears everything to the end; says yes
    to a read-back, and to the offer and each part either yes or carry on."""
    pending = state.pending_confirmation
    if pending is None or pending.status != "pending":
        return None
    if pending.review is None:
        return "Sí."
    return "Sí." if follow == "go_over" else "Sigue."


async def say(h: Harness, text: str, number: int, *, cut: int | None = None) -> list[RuntimeEvent]:
    """One voice turn, then its playback: heard to the end, or cut after ``cut`` sentences."""
    voice = TurnInput(
        session_id=SESSION,
        input_id=InputId(f"v-{number}"),
        text=text,
        channel="voice",
        received_at=NOW,
    )
    events = [event async for event in h.runtime.run_turn(voice)]
    turn_id = next(e for e in events if isinstance(e, TurnStarted)).turn_id
    said = [e.text for e in events if isinstance(e, AssistantText)]
    if cut is None:
        await h.runtime.delivered(turn_id, text=" ".join(said), complete=True)
    else:
        await h.runtime.delivered(turn_id, text=" ".join(said[:cut]), complete=False)
    return events


async def opened(kind: Kind) -> Harness:
    model = FakeModel([], policy=Policy([call for _, call in SETUP[kind]], CORRECTION[kind][1]))
    h = Harness([], store=MemoryStore(clock=lambda: NOW), model=model)
    await h.open_session()
    await fill_record(h)
    if kind == "slot":
        await seed_calendar(h.store, CONFIGS, now=NOW)
        state = await h.store.sessions.get(SESSION)
        assert state is not None
        async with h.store.transaction() as tx:
            confirmed = state.model_copy(
                update={"brief_confirmed_revision": state.candidate.revision}
            )
            await h.store.sessions.save(tx, confirmed, expected_revision=state.candidate.revision)
    return h


CASES = [
    (kind, cut, reply, follow)
    for kind in ("date", "phone", "brief", "slot")
    for cut in range(len(sentences(READ_BACK[kind])) + 1)
    for reply in ("yes", "no", "correction", "carry_on", "unrelated")
    for follow in ("go_over", "carry_on")
]


@pytest.mark.parametrize(("kind", "cut", "reply", "follow"), CASES)
async def test_a_read_back_cut_anywhere_settles_as_its_path_says(
    kind: Kind, cut: int, reply: Reply, follow: FollowUp
) -> None:
    h = await opened(kind)
    setup = SETUP[kind]
    events: list[RuntimeEvent] = []
    for number, (words, _) in enumerate(setup[:-1], start=1):
        events += await say(h, words, number)
    whole = len(sentences(READ_BACK[kind]))
    heard = cut == whole
    events += await say(h, setup[-1][0], len(setup), cut=None if heard else cut)
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.pending_confirmation is not None
    read_back = state.pending_confirmation.presentation_text
    assert len(sentences(read_back)) == whole  # the row cuts the read-back actually said

    number = len(setup) + 1
    line: str | None = REPLIES[reply] if reply != "correction" else CORRECTION[kind][0]
    for _ in range(FOLLOW_UPS + 1):
        if line is None:
            break
        events += await say(h, line, number)
        number += 1
        state = await h.store.sessions.get(SESSION)
        assert state is not None
        line = next_line(state, follow)
    assert line is None, "the read-back did not settle"
    assert not [e for e in events if isinstance(e, TurnFailed)]

    snapshot = await h.store.snapshot(SESSION, versions=STAMP, taken_at=NOW)
    assert snapshot is not None
    document = build_export(snapshot)
    final = document.confirmations[-1]
    outcome = "rejected" if final.status == "rejected" else final.assurance
    assert outcome == expected(kind, not heard, reply, follow)
    assert all(c.assurance is not None for c in document.confirmations if c.status == "confirmed")
    said_by_turn = [t.text for t in document.transcript if t.role == "assistant"]
    for confirmation in document.confirmations:
        times = sum(confirmation.presentation_text in said for said in said_by_turn)
        assert times <= 2, f"said whole {times} times: {confirmation.presentation_text}"
