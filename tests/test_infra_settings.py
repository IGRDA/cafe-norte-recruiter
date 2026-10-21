"""The hosted demo's plain settings (`infra/app/main.tf`, `plain_env`) as a contract, offline."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN_TF = ROOT / "infra" / "app" / "main.tf"
ENV_EXAMPLE = ROOT / ".env.example"

BLOCK = re.compile(r"plain_env\s*=\s*join\(\s*\"\\n\"\s*,\s*\[(.*?)\]\s*\)", re.DOTALL)
SETTING = re.compile(r'^\s*"([A-Z][A-Z0-9_]*)=([^"]*)"', re.MULTILINE)


def plain_env(main_tf: str) -> dict[str, str]:
    block = BLOCK.search(main_tf)
    assert block, "main.tf has no `plain_env = join(...)` block"
    return {key: value for key, value in SETTING.findall(block.group(1))}


def known_settings(env_example: str) -> set[str]:
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", env_example, re.MULTILINE))


def test_the_parser_reads_the_settings_and_their_values() -> None:
    text = 'plain_env = join("\\n", [\n  "A=1",\n  "B=${var.b}", # note\n])'
    assert plain_env(text) == {"A": "1", "B": "${var.b}"}


def test_hosted_traces_carry_redacted_content() -> None:
    assert plain_env(MAIN_TF.read_text())["CAFE_NORTE_TRACE_CONTENT"] == "on"


def test_every_hosted_setting_is_a_known_setting() -> None:
    settings = plain_env(MAIN_TF.read_text())
    assert settings, "no setting parsed: the check would pass for nothing"
    unknown = set(settings) - known_settings(ENV_EXAMPLE.read_text())
    assert not unknown, f"not in .env.example, probably misspelled: {sorted(unknown)}"
