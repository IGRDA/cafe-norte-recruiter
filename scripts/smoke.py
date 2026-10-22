"""Post-deployment smoke check: page, health, access gate and session creation. No model call,
so a deploy costs nothing and cannot fail on a provider hiccup.

    uv run python scripts/smoke.py https://cafenorte-recruiting.duckdns.org  # SMOKE_ACCESS_CODE
"""

import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx

SESSION = {"config_id": "chamberi_barista_v1", "language": "es", "channel": "text"}


@dataclass
class Report:
    steps: list[tuple[str, bool]] = field(default_factory=list)
    details: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(ok for _, ok in self.steps)

    def step(self, name: str, ok: bool, detail: str = "") -> None:
        self.steps.append((name, ok))
        if detail:
            self.details.append(f"{name}: {detail}")


async def run(client: httpx.AsyncClient, *, access_code: str | None) -> Report:
    report = Report()

    async def check(name: str, probe: Callable[[], Awaitable[tuple[bool, str]]]) -> bool:
        try:
            ok, detail = await probe()
        except httpx.HTTPError as error:
            ok, detail = False, f"{type(error).__name__}"
        report.step(name, ok, detail)
        return ok

    async def page() -> tuple[bool, str]:
        r = await client.get("/")
        return r.status_code == 200 and "Café Norte" in r.text, f"HTTP {r.status_code}"

    async def health(path: str) -> tuple[bool, str]:
        r = await client.get(path)
        return r.status_code == 200, f"HTTP {r.status_code}"

    async def runtime() -> tuple[bool, str]:
        r = await client.get("/api/runtime")
        body = r.json() if r.status_code == 200 else {}
        return r.status_code == 200 and "access_required" in body, f"HTTP {r.status_code} {body}"

    async def session_needs_code() -> tuple[bool, str]:
        r = await client.post("/api/sessions", json=SESSION)
        return r.status_code == 401, f"HTTP {r.status_code}"

    async def access() -> tuple[bool, str]:
        r = await client.post("/api/access", json={"code": access_code or ""})
        return r.status_code == 204, f"HTTP {r.status_code}"

    async def session_created() -> tuple[bool, str]:
        r = await client.post("/api/sessions", json=SESSION)
        return r.status_code == 201, f"HTTP {r.status_code}"

    await check("page", page)
    await check("health_live", lambda: health("/health/live"))
    await check("health_ready", lambda: health("/health/ready"))
    if await check("runtime", runtime):
        gated = (await client.get("/api/runtime")).json()["access_required"]
        if gated:
            await check("session_needs_code", session_needs_code)
            await check("access", access)
    await check("session_created", session_created)
    return report


async def _main(url: str) -> int:
    async with httpx.AsyncClient(base_url=url, timeout=20, follow_redirects=True) as client:
        report = await run(client, access_code=os.environ.get("SMOKE_ACCESS_CODE"))
    for name, ok in report.steps:
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    for detail in report.details:
        print(f"     {detail}")
    print("smoke:", "passed" if report.ok else "FAILED", url)
    return 0 if report.ok else 1


def main(url: str) -> int:
    return asyncio.run(_main(url))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"))
