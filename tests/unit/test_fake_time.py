"""``FakeTime``: the virtual clock and sleep every timing test runs on."""

import asyncio
from datetime import timedelta

from tests.support.builders import NOW
from tests.support.time import FakeTime, settle


async def test_a_sleeper_wakes_only_once_its_time_has_come() -> None:
    time = FakeTime()
    woke: list[float] = []

    async def nap() -> None:
        await time.sleep(2)
        woke.append((time.now() - NOW).total_seconds())

    task = asyncio.create_task(nap())
    await time.advance(1.9)
    assert woke == []

    await time.advance(0.1)
    assert woke == [2.0]
    await task


async def test_sleepers_wake_in_order_at_their_own_instant() -> None:
    time = FakeTime()
    woke: list[tuple[str, float]] = []

    async def nap(name: str, seconds: float) -> None:
        await time.sleep(seconds)
        woke.append((name, (time.now() - NOW).total_seconds()))

    tasks = [asyncio.create_task(nap("late", 3)), asyncio.create_task(nap("early", 1))]
    await time.advance(5)

    assert woke == [("early", 1.0), ("late", 3.0)]
    assert time.now() == NOW + timedelta(seconds=5)
    await asyncio.gather(*tasks)


async def test_a_sleep_started_by_a_woken_task_is_honoured_within_the_same_advance() -> None:
    time = FakeTime()
    ticks: list[float] = []

    async def every_second() -> None:
        while True:
            await time.sleep(1)
            ticks.append((time.now() - NOW).total_seconds())

    task = asyncio.create_task(every_second())
    await time.advance(3.5)

    assert ticks == [1.0, 2.0, 3.0]
    task.cancel()


async def test_a_cancelled_sleeper_never_wakes() -> None:
    time = FakeTime()
    woke: list[str] = []

    async def nap() -> None:
        await time.sleep(1)
        woke.append("nap")

    task = asyncio.create_task(nap())
    await settle()
    task.cancel()
    await time.advance(2)

    assert woke == [] and task.cancelled()


async def test_a_zero_sleep_only_yields() -> None:
    time = FakeTime()
    done: list[str] = []

    async def no_wait() -> None:
        await time.sleep(0)
        done.append("done")

    task = asyncio.create_task(no_wait())
    await settle()

    assert done == ["done"] and time.now() == NOW
    await task
