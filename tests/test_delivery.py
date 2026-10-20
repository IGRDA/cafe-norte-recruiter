"""The delivery ledger: which of Ana's sentences the candidate actually heard."""

from hypothesis import given
from hypothesis import strategies as st

from cafe_norte.voice.delivery import Ledger, finished, heard, readback_heard, sent

BRIEF = "Te resumo lo que tengo. Te llamas Lucía. ¿Es todo correcto?"


def test_nothing_sent_means_nothing_heard_and_complete() -> None:
    assert heard(Ledger()) == ("", True)


def test_sentences_are_heard_in_order_as_their_tts_finishes() -> None:
    ledger = sent(sent(Ledger(), "Te resumo lo que tengo."), "Te llamas Lucía.")
    assert heard(ledger) == ("", False)
    ledger = finished(ledger)
    assert heard(ledger) == ("Te resumo lo que tengo.", False)
    ledger = finished(ledger)
    assert heard(ledger) == ("Te resumo lo que tengo. Te llamas Lucía.", True)


def test_finished_never_exceeds_sent() -> None:
    ledger = finished(finished(sent(Ledger(), "Hola.")))
    assert ledger.finished == 1 and heard(ledger) == ("Hola.", True)


def test_a_read_back_is_heard_only_when_its_last_sentence_finished() -> None:
    ledger = Ledger()
    for sentence in ("Te resumo lo que tengo.", "Te llamas Lucía.", "¿Es todo correcto?"):
        ledger = sent(ledger, sentence)
    assert not readback_heard(finished(finished(ledger)), BRIEF)
    assert readback_heard(finished(finished(finished(ledger))), BRIEF)
    assert not readback_heard(Ledger(), BRIEF)


@given(st.lists(st.text(min_size=1), max_size=8), st.integers(min_value=0, max_value=12))
def test_heard_is_a_prefix_of_what_was_sent(sentences: list[str], done: int) -> None:
    ledger = Ledger()
    for sentence in sentences:
        ledger = sent(ledger, sentence)
    for _ in range(done):
        ledger = finished(ledger)
    text, complete = heard(ledger)
    assert ledger.finished == min(done, len(sentences))
    assert complete == (ledger.finished == len(sentences))
    assert text == " ".join(sentences[: ledger.finished])
