"""Write examples/session_export.schema.json from the Pydantic export model."""

import json
from pathlib import Path

from cafe_norte.persistence.export import ExportDocument

OUT = Path(__file__).resolve().parents[1] / "examples" / "session_export.schema.json"


def main() -> int:
    OUT.write_text(
        json.dumps(ExportDocument.model_json_schema(), indent=2, ensure_ascii=False) + "\n"
    )
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
