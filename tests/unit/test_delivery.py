"""The delivery ledger: which of Ana's sentences the candidate actually heard."""

from hypothesis import given
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from cafe_norte.voice.delivery import Ledger, finished, heard, sent


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


class Playback(RuleBasedStateMachine):
    """Sentences sent and playback finishing, interleaved in any order, beside a plain model."""

    def __init__(self) -> None:
        super().__init__()
        self.ledger = Ledger()
        self.sent: list[str] = []
        self.played = 0

    @rule(
        sentence=st.sampled_from(
            ["Te resumo lo que tengo.", "Te llamas Lucía.", "¿Es todo correcto?", "Vale."]
        )
    )
    def a_sentence_goes_to_tts(self, sentence: str) -> None:
        self.ledger = sent(self.ledger, sentence)
        self.sent.append(sentence)

    @rule()
    def a_sentence_finishes_playing(self) -> None:
        self.ledger = finished(self.ledger)
        self.played = min(self.played + 1, len(self.sent))

    @invariant()
    def heard_is_what_played_and_complete_means_all_of_it(self) -> None:
        assert heard(self.ledger) == (
            " ".join(self.sent[: self.played]),
            self.played == len(self.sent),
        )


TestPlayback = Playback.TestCase
