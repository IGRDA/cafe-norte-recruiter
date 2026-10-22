"""Write examples/session_export.schema.json from the Pydantic export model, and the browser's
contract schema (web/src/api/contracts.schema.json) the page's TypeScript types come from."""

import json
from pathlib import Path

from cafe_norte.api.contracts import browser_schema
from cafe_norte.persistence.export import ExportDocument

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples" / "session_export.schema.json"
BROWSER_OUT = ROOT / "web" / "src" / "api" / "contracts.schema.json"


def main() -> int:
    OUT.write_text(
        json.dumps(ExportDocument.model_json_schema(), indent=2, ensure_ascii=False) + "\n"
    )
    print(f"wrote {OUT}")
    BROWSER_OUT.parent.mkdir(parents=True, exist_ok=True)
    BROWSER_OUT.write_text(json.dumps(browser_schema(), indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {BROWSER_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
