"""The per-client ceilings of the hosted demo: a sliding window per key, time as an argument."""

from hypothesis import given
from hypothesis import strategies as st

from cafe_norte.api.limits import RequestLimits, SlidingWindow


def test_a_key_gets_its_limit_within_the_window_and_no_more() -> None:
    window = SlidingWindow(limit=3, seconds=60)

    allowed = [window.hit("1.2.3.4", now=t) for t in (0, 1, 2, 3)]

    assert allowed == [True, True, True, False]


def test_keys_are_counted_apart() -> None:
    window = SlidingWindow(limit=1, seconds=60)

    assert window.hit("1.2.3.4", now=0)
    assert window.hit("5.6.7.8", now=0)
    assert not window.hit("1.2.3.4", now=1)


def test_a_hit_ages_out_after_the_window() -> None:
    window = SlidingWindow(limit=1, seconds=60)
    window.hit("ip", now=0)

    assert not window.hit("ip", now=59.9)
    assert window.hit("ip", now=60)


def test_a_refused_hit_is_not_counted() -> None:
    window = SlidingWindow(limit=1, seconds=60)
    window.hit("ip", now=0)
    window.hit("ip", now=30)  # refused

    assert window.hit("ip", now=60)  # only the first hit had to age out


def test_quiet_keys_are_forgotten() -> None:
    window = SlidingWindow(limit=1, seconds=60)
    for n in range(100):
        window.hit(f"ip-{n}", now=0)

    window.hit("late", now=120)

    assert window.tracked == 1


@given(st.lists(st.floats(min_value=0, max_value=1_000), max_size=60))
def test_no_window_of_the_given_length_ever_holds_more_than_the_limit(times: list[float]) -> None:
    window = SlidingWindow(limit=4, seconds=10)

    accepted = [t for t in sorted(times) if window.hit("ip", now=t)]

    assert all(sum(1 for u in accepted if t - 10 < u <= t) <= 4 for t in accepted)


def test_limits_read_from_the_environment_where_set() -> None:
    limits = RequestLimits.from_env(
        {"CAFE_NORTE_SESSIONS_PER_DAY": "40", "CAFE_NORTE_SESSION_STARTS_PER_HOUR": ""}
    )

    assert limits == RequestLimits(sessions_per_day=40)
