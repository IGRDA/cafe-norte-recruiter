"""What one call used of the speech providers, as measured. No audio framework in it:
``bridge.UsageObserver`` feeds it the providers' own usage reports and the pipeline the room's
joins and leaves; times are arguments."""

from datetime import datetime
from typing import Literal

from cafe_norte.domain.contracts import SessionId
from cafe_norte.observability.contracts import UsageKind, UsageRecord

Participant = Literal["bot", "candidate"]


class SpeechMeter:
    """Deepgram's audio seconds, ElevenLabs' characters and the minutes each participant spent
    in the Daily room. ``records`` turns them into usage the price table knows."""

    def __init__(self) -> None:
        self.stt_seconds = 0.0
        self.tts_characters = 0
        self._entered: dict[Participant, datetime] = {}
        self._minutes = 0.0

    def heard(self, seconds: float) -> None:
        self.stt_seconds += seconds

    def spoke(self, characters: int) -> None:
        self.tts_characters += characters

    def entered(self, who: Participant, at: datetime) -> None:
        self._entered.setdefault(who, at)

    def left(self, who: Participant, at: datetime) -> None:
        since = self._entered.pop(who, None)
        if since is not None:
            self._minutes += (at - since).total_seconds() / 60

    def records(
        self, session_id: SessionId, *, at: datetime, stt_model: str, tts_model: str
    ) -> tuple[UsageRecord, ...]:
        """Everything measured, with whoever is still in the room counted until ``at``."""
        open_minutes = sum((at - since).total_seconds() / 60 for since in self._entered.values())
        measured: tuple[tuple[UsageKind, str, float], ...] = (
            ("stt_seconds", stt_model, self.stt_seconds),
            ("tts_characters", tts_model, float(self.tts_characters)),
            ("media_participant_minutes", "daily", self._minutes + open_minutes),
        )
        return tuple(
            UsageRecord(
                session_id=session_id,
                turn_id=None,
                kind=kind,
                quantity=quantity,
                unit_detail=detail,
                estimated=False,
            )
            for kind, detail, quantity in measured
        )
