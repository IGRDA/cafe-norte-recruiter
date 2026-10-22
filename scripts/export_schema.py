"""Generate the browser boundary schema from the API's Pydantic models.

``make export-schema`` also generates TypeScript and checks both artifacts in tests.
The session export schema is available directly from ``ExportDocument.model_json_schema()``.
"""

import json
from pathlib import Path

from cafe_norte.api.contracts import browser_schema

ROOT = Path(__file__).resolve().parents[1]
BROWSER_OUT = ROOT / "web" / "src" / "api" / "contracts.schema.json"


def main() -> int:
    BROWSER_OUT.parent.mkdir(parents=True, exist_ok=True)
    BROWSER_OUT.write_text(json.dumps(browser_schema(), indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {BROWSER_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
