"""Write examples/session_export.example.json: scenario S01 replayed offline with the fake
model, so the example is a real document from the real runtime and never a hand-written one."""

import asyncio
from pathlib import Path

from evals.runner import load_scenarios, run_fake

OUT = Path(__file__).resolve().parents[1] / "examples" / "session_export.example.json"


async def render() -> str:
    (scenario,) = load_scenarios(only=["S01"])
    record = await run_fake(scenario)
    failed = [c.name for c in record.checks if not c.ok]
    if failed or record.export is None:
        raise SystemExit(f"S01 did not pass: {failed or 'no export'}")
    return record.export.model_dump_json(indent=2) + "\n"


def main() -> int:
    OUT.write_text(asyncio.run(render()), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
