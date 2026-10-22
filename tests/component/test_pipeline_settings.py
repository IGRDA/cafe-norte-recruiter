"""What the voice pipeline is configured with: turn start, turn end and the STT language.
The assembly itself needs provider keys; these pure pieces carry the decisions."""

import pytest

pytest.importorskip("pipecat")

from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import (  # noqa: E402
    LocalSmartTurnAnalyzerV3,
)
from pipecat.turns.user_start.min_words_user_turn_start_strategy import (  # noqa: E402
    MinWordsUserTurnStartStrategy,
)
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import (  # noqa: E402
    TurnAnalyzerUserTurnStopStrategy,
)

from cafe_norte.voice.pipeline import (  # noqa: E402
    BARGE_IN_WORDS,
    FINISHED_TURN_SILENCE_SECONDS,
    UNFINISHED_TURN_SILENCE_SECONDS,
    pipeline_params,
    stt_settings,
    user_turn_strategies,
    vad_params,
)


def test_a_turn_starts_on_words_and_two_are_needed_to_cut_ana_off() -> None:
    """A soft transcript counts even if VAD misses it; a cough alone must not interrupt Ana."""
    (start,) = user_turn_strategies().start or []
    assert isinstance(start, MinWordsUserTurnStartStrategy)
    assert start._min_words == BARGE_IN_WORDS == 2  # noqa: SLF001


def test_a_finished_sentence_waits_half_a_second_of_silence() -> None:
    """Allow a breath inside a sentence without prematurely ending the turn."""
    assert vad_params().stop_secs == FINISHED_TURN_SILENCE_SECONDS == 0.5


def test_a_turn_ends_when_it_sounds_finished_not_after_a_fixed_second() -> None:
    """Finished speech ends promptly; an unfinished sentence keeps its longer silence window."""
    (stop,) = user_turn_strategies().stop or []
    assert isinstance(stop, TurnAnalyzerUserTurnStopStrategy)
    analyzer = stop._turn_analyzer  # noqa: SLF001
    assert isinstance(analyzer, LocalSmartTurnAnalyzerV3)
    assert analyzer._params.stop_secs == UNFINISHED_TURN_SILENCE_SECONDS  # noqa: SLF001


def test_speech_is_recognised_in_every_language_at_once() -> None:
    """Recognition must still hear the candidate when the reply language changes."""
    settings = stt_settings()
    assert settings.language == "multi"
    assert settings.model == "nova-3" and settings.interim_results is True


def test_the_providers_report_their_usage_so_the_cost_is_measured() -> None:
    """Deepgram's seconds and ElevenLabs' characters arrive only as usage metrics."""
    assert pipeline_params().enable_usage_metrics
