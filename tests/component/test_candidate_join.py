"""A bot in a room nobody joins ends the call after a short wait (D55), instead of holding a
voice place until Pipecat's five-minute idle timeout: the morning's refusals of 22 October."""

import asyncio

from cafe_norte.voice.pipeline import CANDIDATE_JOIN_SECONDS, end_unless_joined
from tests.support.time import FakeTime


async def test_nobody_joins_and_the_call_ends_at_the_deadline() -> None:
    time, joined, ended = FakeTime(), asyncio.Event(), []

    async def end() -> None:
        ended.append(time.now())

    watch = asyncio.create_task(
        end_unless_joined(joined, end, seconds=CANDIDATE_JOIN_SECONDS, sleep=time.sleep)
    )
    await time.advance(CANDIDATE_JOIN_SECONDS - 1)
    assert ended == []

    await time.advance(1)

    assert await watch is True and len(ended) == 1


async def test_the_candidate_joins_in_time_and_the_call_goes_on() -> None:
    time, joined, ended = FakeTime(), asyncio.Event(), []

    async def end() -> None:
        ended.append(time.now())

    watch = asyncio.create_task(
        end_unless_joined(joined, end, seconds=CANDIDATE_JOIN_SECONDS, sleep=time.sleep)
    )
    await time.advance(5)
    joined.set()

    assert await watch is False
    await time.advance(CANDIDATE_JOIN_SECONDS * 2)
    assert ended == []
