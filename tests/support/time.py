"""Virtual time for code that takes a clock and a sleep: no test waits on the wall clock."""

import asyncio
import heapq
import itertools
from datetime import datetime, timedelta

from tests.support.builders import NOW

# Event-loop passes that let every task woken by a step run until it waits again. Woken code
# here awaits a handful of times (a runtime generator, a speak, an event); 50 is ample.
SETTLE_PASSES = 50


async def settle() -> None:
    """Let every runnable task run until it waits on something."""
    for _ in range(SETTLE_PASSES):
        await asyncio.sleep(0)


class FakeTime:
    """One virtual instant shared by ``now`` (the clock) and ``sleep``. ``advance`` moves it,
    waking each sleeper that falls due, in order and at its own instant."""

    def __init__(self, start: datetime = NOW) -> None:
        self._now = start
        self._order = itertools.count()
        self._sleepers: list[tuple[datetime, int, asyncio.Future[None]]] = []

    def now(self) -> datetime:
        return self._now

    async def sleep(self, seconds: float) -> None:
        """Parks until ``advance`` reaches it; zero or less only yields, as ``asyncio.sleep``."""
        if seconds <= 0:
            await asyncio.sleep(0)
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        due = self._now + timedelta(seconds=seconds)
        heapq.heappush(self._sleepers, (due, next(self._order), future))
        await future

    async def advance(self, seconds: float) -> None:
        target = self._now + timedelta(seconds=seconds)
        await settle()
        while self._sleepers and self._sleepers[0][0] <= target:
            due, _, future = heapq.heappop(self._sleepers)
            self._now = due
            if not future.done():
                future.set_result(None)
            await settle()
        self._now = target
        await settle()
