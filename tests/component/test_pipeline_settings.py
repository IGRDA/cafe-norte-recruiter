"""What the voice pipeline is configured with: turn start, turn end and the STT language.
The assembly itself needs provider keys; these pure pieces carry the decisions (D35)."""

import pytest

pytest.importorskip("pipecat")

from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import (  # noqa: E402
    LocalSmartTurnAnalyzerV3,
)
from pipecat.turns.user_start.transcription_user_turn_start_strategy import (  # noqa: E402
    TranscriptionUserTurnStartStrategy,
)
from pipecat.turns.user_start.vad_user_turn_start_strategy import (  # noqa: E402
    VADUserTurnStartStrategy,
)
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import (  # noqa: E402
    TurnAnalyzerUserTurnStopStrategy,
)

from cafe_norte.voice.pipeline import (  # noqa: E402
    UNFINISHED_TURN_SILENCE_SECONDS,
    pipeline_params,
    stt_settings,
    user_turn_strategies,
)


def test_a_transcript_can_start_a_turn_when_vad_misses_a_soft_answer() -> None:
    """The hosted call: VAD never fired on a soft "sí" while Deepgram transcribed it."""
    start = user_turn_strategies().start or []
    assert [type(s) for s in start] == [
        VADUserTurnStartStrategy,
        TranscriptionUserTurnStartStrategy,
    ]


def test_a_turn_ends_when_it_sounds_finished_not_after_a_fixed_second() -> None:
    """D49: the fixed second of D35 was most of the wait after every answer. The model ends a
    finished sentence at once; "Tengo dudas sobre… dónde…" still waits for more words."""
    (stop,) = user_turn_strategies().stop or []
    assert isinstance(stop, TurnAnalyzerUserTurnStopStrategy)
    analyzer = stop._turn_analyzer  # noqa: SLF001
    assert isinstance(analyzer, LocalSmartTurnAnalyzerV3)
    assert analyzer._params.stop_secs == UNFINISHED_TURN_SILENCE_SECONDS  # noqa: SLF001


@pytest.mark.parametrize("language", ["es", "en"])
def test_speech_is_recognised_in_the_session_language_not_multi(language: str) -> None:
    """The hosted call: in `multi`, "sí" came back as "C" and "Sì"."""
    settings = stt_settings(language)  # type: ignore[arg-type]
    assert str(settings.language).lower().startswith(language)
    assert settings.model == "nova-3" and settings.interim_results is True


def test_the_providers_report_their_usage_so_the_cost_is_measured() -> None:
    """Deepgram's seconds and ElevenLabs' characters arrive only as usage metrics (D44)."""
    assert pipeline_params().enable_usage_metrics
