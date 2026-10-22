"""Laws of the field sum type, as properties over arbitrary values and prior states."""

from hypothesis import given
from hypothesis import strategies as st

from cafe_norte.domain.contracts import (
    Captured,
    ConfirmationId,
    Confirmed,
    Evidence,
    FieldState,
    TurnId,
)
from cafe_norte.domain.fields import capture, confirm, decline, mark_unknown, value_of
from cafe_norte.domain.result import Err, Ok
from tests.support.strategies import confirmation_ids, evidence, field_states

values = st.text()


@given(field_states(values), values, evidence)
def test_capture_always_yields_the_new_value(prior: FieldState[str], v: str, e: Evidence) -> None:
    after = capture(prior, v, e)
    assert after.status == "captured" and after.value == v and after.evidence == e


@given(field_states(values), values, evidence, confirmation_ids)
def test_confirm_after_capture_keeps_value_and_evidence(
    prior: FieldState[str], v: str, e: Evidence, c: ConfirmationId
) -> None:
    result = confirm(capture(prior, v, e), c)
    assert isinstance(result, Ok)
    assert result.value.value == v and result.value.evidence == e
    assert result.value.confirmation_id == c


@given(field_states(values), confirmation_ids)
def test_confirm_refuses_anything_without_a_captured_value(
    prior: FieldState[str], c: ConfirmationId
) -> None:
    result = confirm(prior, c)
    if isinstance(prior, Captured | Confirmed):
        assert isinstance(result, Ok)
    else:
        assert isinstance(result, Err) and result.error.reason == "not_captured"


@given(field_states(values))
def test_only_captured_and_confirmed_carry_a_value(prior: FieldState[str]) -> None:
    if isinstance(prior, Captured | Confirmed):
        assert value_of(prior) == prior.value
    else:
        assert value_of(prior) is None


@given(field_states(values), values, evidence, confirmation_ids)
def test_a_correction_after_confirmation_drops_the_confirmation(
    prior: FieldState[str], v: str, e: Evidence, c: ConfirmationId
) -> None:
    confirmed = confirm(capture(prior, v, e), c)
    assert isinstance(confirmed, Ok)
    corrected = capture(confirmed.value, v + "x", e)
    assert corrected.status == "captured"


@given(field_states(values))
def test_unknown_and_declined_clear_any_previous_value(prior: FieldState[str]) -> None:
    assert value_of(mark_unknown(prior, 2)) is None
    assert value_of(decline(prior, TurnId("t1"))) is None
