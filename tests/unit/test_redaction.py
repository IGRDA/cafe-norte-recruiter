"""Laws of ``redact``: no generated personal datum or secret survives, whatever surrounds it;
what it returns has nothing left to redact; the length bound always holds."""

from hypothesis import given
from hypothesis import strategies as st

from cafe_norte.observability.redaction import redact

words = st.lists(st.from_regex(r"[a-záéíóúñ]{1,10}", fullmatch=True), max_size=4).map(" ".join)
emails = st.from_regex(r"[a-z]{1,8}(\.[a-z]{1,5})?@[a-z]{2,8}\.(es|com|org)", fullmatch=True)
phones = st.from_regex(r"((\+|00)34[ .-]?)?[6-9][0-9]{2}([ .-]?[0-9]{3}){2}", fullmatch=True)
national_ids = st.from_regex(r"[0-9]{8}[A-Z]|[XYZ][0-9]{7}[A-Z]", fullmatch=True)
ibans = st.from_regex(r"ES[0-9]{2}( ?[0-9]{4}){5}", fullmatch=True)
cards = st.from_regex(r"[0-9]{4}([ -]?[0-9]{4}){3}", fullmatch=True)
# Every secret holds a digit and the words around it hold none, so a digit left is a leak.
secrets = st.from_regex(
    r"((api_key|token|secret|password) ?[=:] ?|(sk|pk)-)[A-Za-z]{0,8}[0-9][A-Za-z0-9]{7,8}",
    fullmatch=True,
)
# Text dense in what the masks look for: digits, separators, @, letters an IBAN starts with.
noisy = st.text(alphabet="0123456789 +-.:=@_aesXYZESkp", max_size=80)


@given(words, st.one_of(phones, national_ids, ibans, cards), words)
def test_no_digit_of_a_phone_id_iban_or_card_survives(before: str, datum: str, after: str) -> None:
    assert not any(c.isdigit() for c in redact(f"{before} {datum} {after}"))


@given(words, emails, words)
def test_no_email_survives(before: str, email: str, after: str) -> None:
    assert "@" not in redact(f"{before} {email} {after}")


@given(words, secrets, words)
def test_no_secret_survives(before: str, secret: str, after: str) -> None:
    assert not any(c.isdigit() for c in redact(f"{before} {secret} {after}"))


@given(noisy)
def test_what_redact_returns_has_nothing_left_to_redact(text: str) -> None:
    once = redact(text)
    assert redact(once) == once


@given(st.text(max_size=300), st.integers(min_value=1, max_value=200))
def test_the_result_never_exceeds_the_limit(text: str, limit: int) -> None:
    assert len(redact(text, limit=limit)) <= limit


@given(words)
def test_text_with_nothing_to_mask_that_fits_comes_back_unchanged(text: str) -> None:
    assert redact(text, limit=max(len(text), 1)) == text
