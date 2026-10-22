"""Bounded concurrency (D51): never more than the limit in flight, results in input order."""

import asyncio

from evals.pool import bounded


async def test_at_most_the_limit_runs_at_once_and_the_order_is_kept() -> None:
    running, most = 0, 0

    async def work(n: int) -> int:
        nonlocal running, most
        running += 1
        most = max(most, running)
        await asyncio.sleep(0.01 * (5 - n % 5))  # later items finish first
        running -= 1
        return n * 10

    assert await bounded(list(range(10)), work, limit=3) == [n * 10 for n in range(10)]
    assert most == 3


async def test_a_limit_below_one_still_runs_everything_one_at_a_time() -> None:
    async def work(n: int) -> int:
        return n

    assert await bounded([1, 2], work, limit=0) == [1, 2]
