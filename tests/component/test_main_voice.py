"""The composition root picks the voice mode from the environment: off or hosted."""

import pytest

from cafe_norte.main import _voice_mode


def test_off_is_the_default() -> None:
    assert _voice_mode({}) == "off"


def test_hosted_voice_is_accepted() -> None:
    assert _voice_mode({"CAFE_NORTE_VOICE": "pipecat"}) == "pipecat"


def test_an_unknown_mode_is_refused() -> None:
    with pytest.raises(ValueError, match=r"must be off or pipecat, not 'phone'$"):
        _voice_mode({"CAFE_NORTE_VOICE": "phone"})
