"""ElevenLabs v4 Turbo over HTTP, one request per sentence, without the gap between
sentences: the request for the next sentence is sent as soon as its text arrives, not after
the previous audio finished downloading, and the sentences before stay as ``previous_text``
so the voice carries over. Pipecat's service does the synthesis, timestamps and frames;
this one only decides when a request starts and what context it carries."""

import asyncio
from collections.abc import Mapping
from typing import Any, cast

import aiohttp
from pipecat.frames.frames import Frame, InterruptionFrame, TTSSpeakFrame, TTSStoppedFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.elevenlabs.tts import (
    ELEVENLABS_CONTEXT_UNSUPPORTED_MODELS,
    ElevenLabsHttpTTSService,
    ElevenLabsHttpTTSSettings,
)
from pipecat.services.elevenlabs.tts_base import elevenlabs_language_code
from pipecat.utils.types import assert_given

PREVIOUS_TEXT_CHARACTERS = 300  # of context sent with a sentence; the newest words kept
PREFETCH_DEPTH = 1  # sentences requested ahead of the one being synthesised


def trimmed_context(text: str, limit: int = PREVIOUS_TEXT_CHARACTERS) -> str:
    """The newest ``limit`` characters of ``text``, cut at a word."""
    if len(text) <= limit:
        return text
    return text[-limit:].split(" ", 1)[-1]


class PrefetchingElevenLabsHttpTTSService(ElevenLabsHttpTTSService):
    def __init__(self, *, aiohttp_session: aiohttp.ClientSession, **kwargs: Any) -> None:
        super().__init__(aiohttp_session=aiohttp_session, **kwargs)
        self._http = aiohttp_session
        self._prefetched: dict[str, asyncio.Task[aiohttp.ClientResponse]] = {}
        self._queued: list[str] = []  # sentences received and not yet synthesised, in order
        self._session = cast(
            aiohttp.ClientSession, _PrefetchedSession(aiohttp_session, self._prefetched)
        )

    # ---- when a request starts ---------------------------------------------------------------

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        if isinstance(frame, TTSSpeakFrame) and direction == FrameDirection.DOWNSTREAM:
            self.prefetch(frame.text)
        elif isinstance(frame, InterruptionFrame):
            self.forget()
        await super().process_frame(frame, direction)

    def prefetch(self, text: str) -> None:
        """Send the request for ``text`` now, with the sentences before it as context, so its
        first audio is ready when the sentence before has played."""
        context = self.context_for(text)
        self._queued.append(text)
        if text not in self._prefetched and len(self._prefetched) < PREFETCH_DEPTH + 1:
            self._prefetched[text] = asyncio.create_task(self._post(text, context))

    def context_for(self, text: str) -> str:
        """What the voice said before ``text``: the sentences already synthesised and those
        queued ahead of it."""
        before = " ".join(s for s in (self._previous_text, *self._queued) if s)
        return trimmed_context(before)

    async def run_tts(self, text: str, context_id: str):  # type: ignore[no-untyped-def]
        async for frame in super().run_tts(text, context_id):
            yield frame
        if text in self._queued:
            self._queued.remove(text)

    def forget(self) -> None:
        """A barge-in: what was queued will not be said; requests in flight are dropped."""
        for task in self._prefetched.values():
            if task.done() and not task.cancelled() and task.exception() is None:
                task.result().release()
            else:
                task.cancel()
        self._prefetched.clear()
        self._queued.clear()

    @property
    def _tts(self) -> ElevenLabsHttpTTSSettings:
        return cast(ElevenLabsHttpTTSSettings, self._settings)

    async def _post(self, text: str, previous: str) -> aiohttp.ClientResponse:
        voice = assert_given(self._tts.voice)
        return await self._http.post(
            f"{self._base_url}/v1/text-to-speech/{voice}/stream/with-timestamps",
            json=self.payload_for(text, previous),
            headers={"xi-api-key": self._api_key, "Content-Type": "application/json"},
            params=self.query_for(),
        )

    def payload_for(self, text: str, previous: str) -> dict[str, Any]:
        """The same body Pipecat's ``run_tts`` builds, so the response fits its parser."""
        model = assert_given(self._tts.model)
        payload: dict[str, Any] = {"text": text, "model_id": model}
        if previous and model not in ELEVENLABS_CONTEXT_UNSUPPORTED_MODELS:
            payload["previous_text"] = previous
        if self._voice_settings:
            payload["voice_settings"] = self._voice_settings
        normalization = assert_given(self._tts.apply_text_normalization)
        if normalization is not None:
            payload["apply_text_normalization"] = normalization
        language = elevenlabs_language_code(model, assert_given(self._tts.language))
        if language:
            payload["language_code"] = language
        return payload

    def query_for(self) -> dict[str, str]:
        params = {"output_format": self._output_format}
        latency = assert_given(self._tts.optimize_streaming_latency)
        if latency is not None:
            params["optimize_streaming_latency"] = str(latency)
        if self._enable_logging is not None:
            params["enable_logging"] = str(self._enable_logging).lower()
        return params

    # ---- what context a sentence carries ------------------------------------------------------

    async def push_frame(
        self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM
    ) -> None:
        previous = self._previous_text
        await super().push_frame(frame, direction)
        if isinstance(frame, TTSStoppedFrame):
            # Pipecat forgets the context at every sentence end; the next sentence keeps it.
            self._previous_text = trimmed_context(previous)


class _PrefetchedSession:
    """Stands in for the aiohttp session inside ``run_tts``: a request already sent for this
    sentence is reused, any other goes out as it would have."""

    def __init__(
        self,
        inner: aiohttp.ClientSession,
        prefetched: dict[str, asyncio.Task[aiohttp.ClientResponse]],
    ) -> None:
        self._inner = inner
        self._prefetched = prefetched

    def post(self, url: str, *, json: Mapping[str, Any], **kwargs: Any) -> Any:
        task = self._prefetched.pop(str(json.get("text")), None)
        if task is None:
            return self._inner.post(url, json=json, **kwargs)
        return _Reused(task)


class _Reused:
    def __init__(self, task: asyncio.Task[aiohttp.ClientResponse]) -> None:
        self._task = task
        self._response: aiohttp.ClientResponse | None = None

    async def __aenter__(self) -> aiohttp.ClientResponse:
        self._response = await self._task
        return self._response

    async def __aexit__(self, *exc: object) -> None:
        if self._response is not None:
            self._response.release()
