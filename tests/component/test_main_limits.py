"""The composition root turns the request ceilings on exactly when an access code is set."""

from cafe_norte.api.access import gate_from_env
from cafe_norte.api.limits import RequestLimits
from cafe_norte.main import _request_limits


def test_ceilings_follow_the_access_code() -> None:
    hosted = {"CAFE_NORTE_ACCESS_CODE": "x", "CAFE_NORTE_COOKIE_SECRET": "s"}

    assert _request_limits(hosted, gate_from_env(hosted)) == RequestLimits()
    assert _request_limits({}, gate_from_env({})) is None
