"""Bounded concurrency for the live phases: the phases (scenarios, probes, judges) run
one after the other; inside a phase, independent sessions and judge calls run at most
``limit`` at a time. One session's turns stay in order: each line answers the last."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence

# Sessions or judged runs in flight. Each model round sends about 10 000 tokens and gpt-4.1
# answers in about a second: four sessions at once passed its 450 000 tokens a minute on this
# organisation and 39 turns failed with 429. Raise it only for a model with more room.
CONCURRENCY = 2


async def bounded[T, R](
    items: Sequence[T], work: Callable[[T], Awaitable[R]], *, limit: int = CONCURRENCY
) -> list[R]:
    """``work`` over every item, at most ``limit`` at a time; results in the items' order."""
    gate = asyncio.Semaphore(max(limit, 1))

    async def one(item: T) -> R:
        async with gate:
            return await work(item)

    return list(await asyncio.gather(*(one(item) for item in items)))
