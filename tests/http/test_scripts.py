"""The post-deploy smoke check against the ASGI app, and the secrets script's dry run."""

import httpx
import pytest
from fastapi import FastAPI
from scripts.ops import set_secrets, smoke

from cafe_norte.model.contracts import ModelFinished, ModelText
from cafe_norte.model.fake import FakeModel
from tests.support.app import build_test_app


def app(code: str | None) -> FastAPI:
    model = FakeModel([], fallback=[ModelText(text="Vale."), ModelFinished(reason="stop")])
    return build_test_app(model=model, access_code=code)


async def test_smoke_passes_against_a_gated_app_with_the_right_code() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app("cafe-2026")), base_url="https://demo.test"
    ) as client:
        report = await smoke.run(client, access_code="cafe-2026")
    assert report.ok, report.steps
    assert [name for name, ok in report.steps] == [
        "page",
        "health_live",
        "health_ready",
        "runtime",
        "session_needs_code",
        "access",
        "session_created",
    ]


async def test_smoke_fails_and_names_the_step_when_the_code_is_wrong() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app("cafe-2026")), base_url="https://demo.test"
    ) as client:
        report = await smoke.run(client, access_code="latte")
    assert not report.ok
    assert ("access", False) in report.steps


async def test_smoke_against_an_open_app_skips_the_code_steps() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(None)), base_url="https://demo.test"
    ) as client:
        report = await smoke.run(client, access_code=None)
    assert report.ok and ("session_created", True) in report.steps


def test_set_secrets_dry_run_lists_only_the_names_present(
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = {"DAILY_API_KEY": "d", "OPENAI_API_KEY": "o", "UNRELATED": "x"}
    assert set_secrets.main(["--project", "p", "--dry-run"], env=env) == 0
    out = capsys.readouterr().out
    assert "DAILY_API_KEY" in out and "OPENAI_API_KEY" in out
    assert "UNRELATED" not in out and "d" not in out.split("DAILY_API_KEY")[1][:3]


def test_set_secrets_commands_never_contain_the_value() -> None:
    commands = set_secrets.commands("p", {"DAILY_API_KEY": "topsecret"})
    assert len(commands) == 1
    assert "topsecret" not in " ".join(commands[0].argv)
    assert commands[0].argv[:4] == ["gcloud", "secrets", "versions", "add"]
    assert "--data-file=-" in commands[0].argv and commands[0].stdin == "topsecret"


def test_set_secrets_only_writes_the_names_asked_for() -> None:
    """Uploading the Langfuse keys from a full local .env must not touch the hosted access code,
    the cookie secret or the provider keys, whose local values differ."""
    env = {
        "LANGFUSE_PUBLIC_KEY": "pk",
        "LANGFUSE_SECRET_KEY": "sk",
        "CAFE_NORTE_ACCESS_CODE": "local-code",
        "OPENAI_API_KEY": "local-key",
    }
    planned = set_secrets.commands("p", env, only=("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"))
    assert [c.name for c in planned] == ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"]


def test_set_secrets_refuses_an_unknown_name_in_only(capsys: pytest.CaptureFixture[str]) -> None:
    code = set_secrets.main(["--project", "p", "--dry-run", "--only", "NOT_A_SECRET"], env={})
    assert code == 2 and "NOT_A_SECRET" in capsys.readouterr().err
