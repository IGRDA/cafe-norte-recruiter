"""`make quality`: one report of the suite's shape and strength, folded from what pytest,
coverage and mutmut already wrote. Pure folds and one ``main`` that reads the files."""

import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".quality"
LAYERS = ("unit", "component", "http", "e2e")
KILLED, SURVIVED, UNTESTED = {1, 3}, {0}, {5, 33}  # mutmut's exit codes (mutmut/stats.py)


class LayerCount(BaseModel):
    model_config = ConfigDict(frozen=True)

    layer: str
    tests: int
    properties: int
    machines: int


class MutationScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    module: str
    killed: int
    survived: tuple[str, ...]
    untested: int

    @property
    def percent(self) -> float:
        tried = self.killed + len(self.survived) + self.untested
        return 100.0 * self.killed / tried if tried else 100.0


def layer_counts(node_ids: Sequence[str], tests_dir: Path) -> list[LayerCount]:
    """Collected tests per layer folder, and the properties and state machines in its files."""
    counts = []
    for layer in LAYERS:
        sources = [p.read_text() for p in sorted((tests_dir / layer).rglob("test_*.py"))]
        counts.append(
            LayerCount(
                layer=layer,
                tests=sum(1 for node in node_ids if node.startswith(f"tests/{layer}/")),
                properties=sum(source.count("@given(") for source in sources),
                machines=sum(source.count("(RuleBasedStateMachine)") for source in sources),
            )
        )
    return counts


def mutation_scores(metas: Mapping[str, Mapping[str, int | None]]) -> list[MutationScore]:
    """Per mutated module: mutants killed, the survivors by name, and those no test reached."""
    return [
        MutationScore(
            module=module,
            killed=sum(1 for code in codes.values() if code in KILLED),
            survived=tuple(sorted(key for key, code in codes.items() if code in SURVIVED)),
            untested=sum(1 for code in codes.values() if code in UNTESTED),
        )
        for module, codes in sorted(metas.items())
    ]


def slowest(junit_xml: str, n: int) -> list[tuple[str, float]]:
    cases = ET.fromstring(junit_xml).iter("testcase")
    timed = [(f"{c.get('classname')}::{c.get('name')}", float(c.get("time", 0))) for c in cases]
    return sorted(timed, key=lambda case: -case[1])[:n]


def coverage_totals(coverage: Mapping[str, Any]) -> tuple[float, float]:
    """Line-and-branch percentage, and the branch percentage alone, from coverage's JSON."""
    totals = coverage["totals"]
    branches = totals.get("num_branches", 0)
    branch_percent = 100.0 * totals.get("covered_branches", 0) / branches if branches else 100.0
    return float(totals["percent_covered"]), branch_percent


def report(
    layers: Sequence[LayerCount],
    coverage: tuple[float, float],
    slow: Sequence[tuple[str, float]],
    mutations: Sequence[MutationScore],
) -> str:
    survivors = [name for m in mutations for name in m.survived]
    sections = [
        "## Pyramid",
        _table(
            ("Layer", "Tests", "Properties", "Machines"),
            [(c.layer, c.tests, c.properties, c.machines) for c in layers],
        ),
        "## Coverage",
        f"Lines and branches {coverage[0]:.1f} %, branches alone {coverage[1]:.1f} %",
        "## Slowest tests",
        "\n".join(f"- {seconds:.2f} s {name}" for name, seconds in slow),
        "## Mutation",
        _table(
            ("Module", "Score", "Killed", "Survived", "No test"),
            [
                (m.module, f"{m.percent:.0f} %", m.killed, len(m.survived), m.untested)
                for m in mutations
            ],
        ),
    ]
    if survivors:
        sections.append("Survivors (`uv run mutmut show <name>`):")
        sections.append("\n".join(f"- {name}" for name in survivors))
    return "\n\n".join(sections) + "\n"


def _table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    """A Markdown table; every column but the first is right-aligned."""
    align = ["---", *["---:"] * (len(header) - 1)]
    lines = [header, align, *[[str(cell) for cell in row] for row in rows]]
    return "\n".join("| " + " | ".join(line) + " |" for line in lines)


def _metas(mutants: Path) -> dict[str, dict[str, int | None]]:
    metas = {}
    for meta in sorted(mutants.rglob("*.py.meta")):
        module = ".".join(meta.relative_to(mutants / "src").with_suffix("").with_suffix("").parts)
        metas[module] = json.loads(meta.read_text())["exit_code_by_key"]
    return metas


def main() -> int:
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    node_ids = [line for line in collected.splitlines() if re.match(r"tests/.+::", line)]
    text = report(
        layer_counts(node_ids, ROOT / "tests"),
        coverage_totals(json.loads((OUT / "coverage.json").read_text())),
        slowest((OUT / "junit.xml").read_text(), 10),
        mutation_scores(_metas(ROOT / "mutants")),
    )
    (OUT / "report.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
