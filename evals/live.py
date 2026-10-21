"""Live runs: a session driven through the public HTTP API, exactly as the browser drives it.

``HttpConversation`` creates the session, posts one turn per candidate line and reads that
turn's events from the SSE stream (resuming from the last sequence it saw) until
``turn_finished`` or ``turn_failed``. The events fold into the same ``TurnObservation`` the
fake replay builds, so the scorers do not know which mode produced a result."""

import asyncio
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing

import httpx

from cafe_norte.api.contracts import (
    CreateSessionRequest,
    CreateSessionResponse,
    SessionEvent,
    SessionSnapshotResponse,
    TurnRequest,
    VoiceState,
)
from cafe_norte.conversation.contracts import AssistantText
from cafe_norte.domain.contracts import ConfigId, InputId, SessionId
from cafe_norte.errors import Language
from cafe_norte.persistence.export import ExportDocument
from evals.contracts import Finished, TurnObservation
from evals.observation import fold, session_result

TURN_TIMEOUT_SECONDS = 90.0  # a turn with no end after this is reported, not awaited
RECONNECT_SECONDS = 0.05  # pause before resuming a stream that closed mid-turn


class LiveError(Exception):
    """The server refused something the run cannot continue without."""


class HttpConversation:
    """One session over HTTP. The client carries the base URL and the cookies the server sets
    (access, then session ownership)."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        config_id: ConfigId,
        language: Language,
        allowed_doc_ids: frozenset[str],
        access_code: str | None = None,
        turn_timeout: float = TURN_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._config_id = config_id
        self._language: Language = language
        self._allowed = allowed_doc_ids
        self._access_code = access_code
        self._turn_timeout = turn_timeout
        self._clock = clock
        self._session_id = SessionId("")
        self._last_seq = 0
        self._observations: list[TurnObservation] = []

    @property
    def session_id(self) -> SessionId:
        return self._session_id

    async def start(self) -> TurnObservation:
        if self._access_code is not None:
            response = await self._client.post("/api/access", json={"code": self._access_code})
            if response.status_code != 204:
                raise LiveError(f"access refused ({response.status_code})")
        request = CreateSessionRequest(
            config_id=self._config_id, language=self._language, channel="text"
        )
        response = await self._client.post("/api/sessions", content=request.model_dump_json())
        created = CreateSessionResponse.model_validate_json(self._ok(response).content)
        self._session_id = created.session_id
        return await self._read_turn(self._clock())

    async def say(self, text: str) -> TurnObservation:
        number = len(self._observations)
        request = TurnRequest(input_id=InputId(f"{self._session_id}-in-{number}"), text=text)
        posted_at = self._clock()
        self._ok(await self._client.post(self._path("turns"), content=request.model_dump_json()))
        return await self._read_turn(posted_at)

    async def finish(self) -> Finished:
        self._ok(await self._client.post(self._path("end")))
        snapshot = SessionSnapshotResponse.model_validate_json(
            self._ok(await self._client.get(self._path())).content
        )
        export = ExportDocument.model_validate_json(
            self._ok(await self._client.get(self._path("export"))).content
        )
        result = session_result(
            snapshot.state,
            snapshot.transcript,
            self._observations[1:],  # the opening is not a candidate line
            allowed_doc_ids=self._allowed,
            signals=export.signals,
        )
        return Finished(result=result, export=export, observations=tuple(self._observations))

    async def _read_turn(self, posted_at: float) -> TurnObservation:
        observation = TurnObservation()
        first_text: float | None = None
        try:
            async with asyncio.timeout(self._turn_timeout):
                while not observation.done:
                    async with aclosing(self._events()) as events:
                        async for event in events:
                            if isinstance(event.payload, VoiceState):
                                continue
                            observation = fold(observation, event.payload)
                            if isinstance(event.payload, AssistantText) and first_text is None:
                                first_text = self._clock()
                            if observation.done:
                                break
                    if not observation.done:
                        await asyncio.sleep(RECONNECT_SECONDS)
        except TimeoutError:
            observation = observation.model_copy(
                update={"failed": observation.failed or "no_turn_end"}
            )
        ended = self._clock()
        observation = observation.model_copy(
            update={
                "client_first_text_ms": None
                if first_text is None
                else round((first_text - posted_at) * 1000),
                "client_total_ms": round((ended - posted_at) * 1000),
            }
        )
        self._observations.append(observation)
        return observation

    async def _events(self) -> AsyncGenerator[SessionEvent, None]:
        """The session's events after the last one seen; ends when the server closes."""
        headers = {"Last-Event-ID": str(self._last_seq)} if self._last_seq else {}
        async with self._client.stream("GET", self._path("events"), headers=headers) as response:
            self._ok(response)
            data = ""
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[len("data: ") :]
                elif line == "" and data:
                    event = SessionEvent.model_validate_json(data)
                    data = ""
                    self._last_seq = event.seq
                    yield event

    def _path(self, tail: str = "") -> str:
        base = f"/api/sessions/{self._session_id}"
        return f"{base}/{tail}" if tail else base

    @staticmethod
    def _ok(response: httpx.Response) -> httpx.Response:
        if response.is_error:
            raise LiveError(
                f"{response.request.method} {response.request.url.path}: {response.status_code}"
            )
        return response
