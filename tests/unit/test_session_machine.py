"""The session domain as a state machine: facts change, Ana reads back, playback finishes or is
cut, the candidate answers or goes over it, in any order, as the runtime drives them. After
every step the promises of the spec still hold."""

from datetime import timedelta

from hypothesis import event
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from cafe_norte.domain.booking import reservation_allowed
from cafe_norte.domain.candidate import apply_patch, changed_fields
from cafe_norte.domain.confirmation import (
    Answer,
    ReviewAnswer,
    advance_review,
    invalidated_by_patch,
    present,
    ready_to_confirm,
    respond,
)
from cafe_norte.domain.contracts import (
    BriefTarget,
    CandidatePatch,
    Confirmation,
    ConfirmationId,
    ConfirmationTarget,
    FieldTarget,
    InterviewSlot,
    SlotId,
    SlotTarget,
    TurnId,
)
from cafe_norte.domain.result import Ok, Result
from tests.support.builders import CONFIG_ID, EVIDENCE, NOW, session_state
from tests.support.strategies import patches

SLOT = InterviewSlot(
    slot_id=SlotId("tomorrow-1030"),
    config_id=CONFIG_ID,
    starts_at_utc=NOW + timedelta(days=1),
    duration_minutes=30,
    status="available",
)
PARTS = 3


def revision_of(target: ConfirmationTarget) -> int:
    return target.brief_revision if isinstance(target, SlotTarget) else target.revision


class Session(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.state = session_state().model_copy(update={"schedule_intent": EVIDENCE})
        self.turn = 1
        self.highest_revision = 0

    @property
    def turn_id(self) -> TurnId:
        return TurnId(f"t{self.turn}")

    def pending(self, change: dict[str, object]) -> None:
        confirmation = self.state.pending_confirmation
        if confirmation is not None and confirmation.status == "pending":
            self.keep(confirmation.model_copy(update=change))

    def keep(self, confirmation: Confirmation | None) -> None:
        self.state = self.state.model_copy(update={"pending_confirmation": confirmation})

    def settle(self, result: Result[Confirmation, str]) -> None:
        if not isinstance(result, Ok):
            return
        confirmation = result.value
        self.keep(confirmation)
        if confirmation.status == "confirmed" and isinstance(confirmation.target, BriefTarget):
            self.state = self.state.model_copy(
                update={"brief_confirmed_revision": confirmation.target.revision}
            )

    # ---- what happens ----------------------------------------------------------------------------

    @rule()
    def the_candidate_speaks_again(self) -> None:
        self.turn += 1

    @rule(patch=patches())
    def the_facts_change(self, patch: CandidatePatch) -> None:
        record = apply_patch(self.state.candidate, patch, EVIDENCE)
        self.keep(invalidated_by_patch(self.state, record.revision, changed_fields(patch)))
        self.state = self.state.model_copy(update={"candidate": record})

    @rule(kind=st.sampled_from(["field", "brief", "slot"]))
    def ana_reads_back(self, kind: str) -> None:
        revision = self.state.candidate.revision
        target: ConfirmationTarget
        if kind == "field":
            target = FieldTarget(field="name", revision=revision)
        elif kind == "brief":
            target = BriefTarget(revision=revision)
        else:
            target = SlotTarget(slot_id=SLOT.slot_id, brief_revision=revision)
        self.keep(
            present(self.state, target, "¿Es correcto?", self.turn_id, ConfirmationId(f"c{kind}"))
        )

    @rule(heard=st.booleans())
    def the_saying_plays_to_the_end_or_is_cut(self, heard: bool) -> None:
        self.pending({"fully_delivered": heard})

    @rule(answer=st.sampled_from(["affirm", "deny", "correct", "unrelated"]))
    def the_candidate_answers(self, answer: Answer) -> None:
        self.settle(respond(self.state, answer, self.turn_id))

    @rule(answer=st.sampled_from(["affirm", "skip"]))
    def the_candidate_goes_over_it_or_carries_on(self, answer: ReviewAnswer) -> None:
        self.settle(advance_review(self.state, answer, self.turn_id, parts=PARTS))

    @rule(kind=st.sampled_from(["field", "brief", "slot"]))
    def a_read_back_is_heard_and_affirmed(self, kind: str) -> None:
        """The happy path in one step, so a run reaches the booking gate's open side."""
        self.ana_reads_back(kind)
        self.the_saying_plays_to_the_end_or_is_cut(heard=True)
        self.the_candidate_speaks_again()
        self.the_candidate_answers("affirm")

    # ---- what always holds -----------------------------------------------------------------------

    @invariant()
    def nothing_is_confirmed_unless_heard_reviewed_or_waived_by_the_candidate(self) -> None:
        confirmation = self.state.pending_confirmation
        if confirmation is not None and confirmation.status == "confirmed":
            assert ready_to_confirm(confirmation)
            assert confirmation.response_turn_id != confirmation.presented_turn_id

    @invariant()
    def a_pending_read_back_is_about_the_current_facts(self) -> None:
        confirmation = self.state.pending_confirmation
        if confirmation is not None and confirmation.status == "pending":
            assert revision_of(confirmation.target) == self.state.candidate.revision

    @invariant()
    def the_revision_never_goes_back(self) -> None:
        assert self.state.candidate.revision >= self.highest_revision
        self.highest_revision = self.state.candidate.revision

    @invariant()
    def a_booking_needs_this_brief_confirmed_and_this_slot_affirmed(self) -> None:
        confirmation = self.state.pending_confirmation
        if isinstance(reservation_allowed(self.state, SLOT, confirmation, now=NOW), Ok):
            event("a booking was allowed")  # the run reaches the gate's open side
            assert confirmation is not None and confirmation.status == "confirmed"
            assert self.state.brief_confirmed_revision == self.state.candidate.revision
            assert revision_of(confirmation.target) == self.state.candidate.revision


TestSession = Session.TestCase
