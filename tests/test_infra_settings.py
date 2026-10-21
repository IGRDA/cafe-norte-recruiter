"""Every hosted plain setting (`plain_env` in `infra/app/main.tf`) is one the app knows."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def plain_env_keys() -> set[str]:
    main_tf = (ROOT / "infra/app/main.tf").read_text()
    block = re.search(r"plain_env\s*=\s*join\((.*?)\]\)", main_tf, re.S)
    assert block, "main.tf has no `plain_env = join(...)` block"
    return set(re.findall(r'^\s*"([A-Z][A-Z0-9_]*)=', block.group(1), re.M))


def test_every_hosted_setting_is_in_env_example() -> None:
    # A misspelled key is silently ignored: CAFE_NORTE_TRACE_CONTNT=on would leave content off.
    keys = plain_env_keys()
    assert keys, "no setting parsed: the check would pass for nothing"
    known = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", (ROOT / ".env.example").read_text(), re.M))
    assert keys <= known, f"not in .env.example, probably misspelled: {sorted(keys - known)}"
