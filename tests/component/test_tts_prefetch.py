"""The next sentence's request goes out before the previous audio has finished, with the
sentences before it as context (D59). Pipecat's parser is not run here: the hosted demo is
where the audio is heard."""

import asyncio
from typing import Any, cast

import aiohttp
import pytest

pytest.importorskip("pipecat")

from cafe_norte.voice.pipeline import tts_settings  # noqa: E402
from cafe_norte.voice.tts import (  # noqa: E402
    PrefetchingElevenLabsHttpTTSService,
    trimmed_context,
)


class FakeResponse:
    def __init__(self) -> None:
        self.released = False

    def release(self) -> None:
        self.released = True


class FakeSession:
    """Records every request as it is sent; a response is given only when asked."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.answers: list[asyncio.Future[FakeResponse]] = []

    async def post(self, url: str, *, json: dict[str, Any], **_: Any) -> FakeResponse:
        self.sent.append(json)
        answer: asyncio.Future[FakeResponse] = asyncio.get_running_loop().create_future()
        self.answers.append(answer)
        return await answer


def service(http: FakeSession) -> PrefetchingElevenLabsHttpTTSService:
    tts = PrefetchingElevenLabsHttpTTSService(
        api_key="k",
        aiohttp_session=cast(aiohttp.ClientSession, http),
        settings=tts_settings("voice"),
    )
    tts._output_format = "pcm_16000"  # noqa: SLF001  (set by Pipecat's setup, not run here)
    return tts


async def test_the_second_sentence_is_requested_before_the_first_is_answered() -> None:
    http = FakeSession()
    tts = service(http)
    tts.prefetch("Hola, soy Ana.")
    tts.prefetch("¿Cómo te llamas?")
    await asyncio.sleep(0)
    assert [r["text"] for r in http.sent] == ["Hola, soy Ana.", "¿Cómo te llamas?"]
    assert "previous_text" not in http.sent[0]
    assert http.sent[1]["previous_text"] == "Hola, soy Ana."
    assert http.sent[1]["model_id"] == tts_settings("voice").model
    tts.forget()


async def test_run_tts_reuses_the_request_sent_for_its_sentence() -> None:
    http = FakeSession()
    tts = service(http)
    tts.prefetch("Hola.")
    await asyncio.sleep(0)
    http.answers[0].set_result(FakeResponse())
    async with tts._session.post("u", json={"text": "Hola."}) as response:  # noqa: SLF001
        assert isinstance(response, FakeResponse) and not response.released
    assert response.released and len(http.sent) == 1  # no second request for the same text
    other = tts._session.post("u", json={"text": "Otra."})  # noqa: SLF001
    assert asyncio.iscoroutine(other)  # not prefetched: sent as Pipecat would
    other.close()


async def test_a_barge_in_drops_what_was_queued() -> None:
    http = FakeSession()
    tts = service(http)
    tts.prefetch("Uno.")
    tts.prefetch("Dos.")
    await asyncio.sleep(0)
    http.answers[0].set_result(FakeResponse())
    await asyncio.sleep(0)
    tts.forget()
    await asyncio.sleep(0)
    assert tts.context_for("Tres.") == ""
    tts.prefetch("Tres.")
    await asyncio.sleep(0)
    assert "previous_text" not in http.sent[-1]
    tts.forget()


def test_the_context_keeps_the_newest_words() -> None:
    assert trimmed_context("corto") == "corto"
    long = " ".join(["palabra"] * 60)
    kept = trimmed_context(long)
    assert len(kept) <= 300 and kept.startswith("palabra") and long.endswith(kept)
