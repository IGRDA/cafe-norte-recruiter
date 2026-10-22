"""Bounded concurrency for the live phases (D51): the phases (scenarios, probes, judges) run
one after the other; inside a phase, independent sessions and judge calls run at most
``limit`` at a time. One session's turns stay in order: each line answers the last."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence

CONCURRENCY = 4  # sessions or judge calls in flight; well inside OpenAI's rate limits


async def bounded[T, R](
    items: Sequence[T], work: Callable[[T], Awaitable[R]], *, limit: int = CONCURRENCY
) -> list[R]:
    """``work`` over every item, at most ``limit`` at a time; results in the items' order."""
    gate = asyncio.Semaphore(max(limit, 1))

    async def one(item: T) -> R:
        async with gate:
            return await work(item)

    return list(await asyncio.gather(*(one(item) for item in items)))
