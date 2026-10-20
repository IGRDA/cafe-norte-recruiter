"""Laws of the field sum type, as properties over arbitrary values and prior states."""

from hypothesis import given
from hypothesis import strategies as st

from cafe_norte.domain.contracts import (
    Captured,
    ConfirmationId,
    Confirmed,
    Declined,
    Evidence,
    FieldState,
    TurnId,
    Unknown,
    Unset,
)
from cafe_norte.domain.fields import capture, confirm, decline, is_settled, mark_unknown, value_of
from cafe_norte.domain.result import Err, Ok

evidence = st.builds(
    Evidence, source_turn_id=st.text(min_size=1).map(TurnId), text=st.text(min_size=1)
)
values = st.text()
confirmation_ids = st.text(min_size=1).map(ConfirmationId)


def states(value_strategy: st.SearchStrategy[str]) -> st.SearchStrategy[FieldState[str]]:
    return st.one_of(
        st.just(Unset()),
        st.builds(Captured[str], value=value_strategy, evidence=evidence),
        st.builds(
            Confirmed[str],
            value=value_strategy,
            evidence=evidence,
            confirmation_id=confirmation_ids,
        ),
        st.builds(Unknown, attempts=st.integers(min_value=0, max_value=5)),
        st.builds(Declined, source_turn_id=st.text(min_size=1).map(TurnId)),
    )


@given(states(values), values, evidence)
def test_capture_always_yields_the_new_value(prior: FieldState[str], v: str, e: Evidence) -> None:
    after = capture(prior, v, e)
    assert after.status == "captured" and after.value == v and after.evidence == e


@given(states(values), values, evidence, confirmation_ids)
def test_confirm_after_capture_keeps_value_and_evidence(
    prior: FieldState[str], v: str, e: Evidence, c: ConfirmationId
) -> None:
    result = confirm(capture(prior, v, e), c)
    assert isinstance(result, Ok)
    assert result.value.value == v and result.value.evidence == e
    assert result.value.confirmation_id == c


@given(states(values), confirmation_ids)
def test_confirm_refuses_anything_without_a_captured_value(
    prior: FieldState[str], c: ConfirmationId
) -> None:
    result = confirm(prior, c)
    if isinstance(prior, Captured | Confirmed):
        assert isinstance(result, Ok)
    else:
        assert isinstance(result, Err) and result.error.reason == "not_captured"


@given(states(values))
def test_only_captured_and_confirmed_carry_a_value(prior: FieldState[str]) -> None:
    if isinstance(prior, Captured | Confirmed):
        assert value_of(prior) == prior.value
    else:
        assert value_of(prior) is None


@given(states(values), values, evidence, confirmation_ids)
def test_a_correction_after_confirmation_drops_the_confirmation(
    prior: FieldState[str], v: str, e: Evidence, c: ConfirmationId
) -> None:
    confirmed = confirm(capture(prior, v, e), c)
    assert isinstance(confirmed, Ok)
    corrected = capture(confirmed.value, v + "x", e)
    assert corrected.status == "captured"


@given(states(values))
def test_unknown_and_declined_are_settled_and_valueless(prior: FieldState[str]) -> None:
    assert value_of(mark_unknown(prior, 2)) is None
    assert value_of(decline(prior, TurnId("t1"))) is None
    assert is_settled(mark_unknown(prior, 2)) and is_settled(decline(prior, TurnId("t1")))
    assert not is_settled(Unset())
