"""What the candidate actually heard. Pure: sentences in, playback completions in, text out.

The bridge sends sentences to TTS one at a time and sees a stop event when each finishes
playing. An interruption freezes the ledger; ``heard`` is then the exact text the candidate
was played, and a read-back only counts when its final sentence was among them."""

from pydantic import BaseModel, ConfigDict, Field


class Ledger(BaseModel):
    model_config = ConfigDict(frozen=True)

    sent: tuple[str, ...] = ()
    finished: int = Field(default=0, ge=0)


def sent(ledger: Ledger, sentence: str) -> Ledger:
    return ledger.model_copy(update={"sent": (*ledger.sent, sentence)})


def finished(ledger: Ledger) -> Ledger:
    """One more sentence finished playing; never counts beyond what was sent."""
    return ledger.model_copy(update={"finished": min(ledger.finished + 1, len(ledger.sent))})


def heard(ledger: Ledger) -> tuple[str, bool]:
    """The text played to the end, and whether that is everything that was sent."""
    text = " ".join(ledger.sent[: ledger.finished])
    return text, ledger.finished == len(ledger.sent)


def readback_heard(ledger: Ledger, presentation_text: str) -> bool:
    """A read-back was heard when its last sentence is among the finished ones."""
    last = presentation_text.rsplit(" ", 1)[-1] if " " in presentation_text else presentation_text
    played = ledger.sent[: ledger.finished]
    return any(sentence.endswith(last) and sentence in presentation_text for sentence in played)
