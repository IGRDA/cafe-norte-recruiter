"""`make quality`'s report: pure folds over what pytest, coverage and mutmut already wrote."""

from pathlib import Path

from scripts.quality_report import (
    LayerCount,
    MutationScore,
    coverage_totals,
    layer_counts,
    mutation_scores,
    report,
    slowest,
)

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest">
<testcase classname="tests.unit.test_a" name="test_fast" time="0.010"/>
<testcase classname="tests.component.test_b" name="test_slow" time="1.500"/>
<testcase classname="tests.http.test_c" name="test_middle" time="0.300"/>
</testsuite></testsuites>"""


def test_tests_properties_and_machines_are_counted_per_layer(tmp_path: Path) -> None:
    (tmp_path / "unit").mkdir()
    (tmp_path / "unit" / "test_a.py").write_text(
        "@given(st.integers())\ndef test_p(n): ...\nclass M(RuleBasedStateMachine): ...\n"
    )
    (tmp_path / "e2e").mkdir()
    (tmp_path / "e2e" / "test_b.py").write_text("def test_x(): ...\n")
    ids = [
        "tests/unit/test_a.py::test_p",
        "tests/unit/test_a.py::TestM::runTest",
        "tests/e2e/test_b.py::test_x",
    ]

    counts = layer_counts(ids, tmp_path)

    assert counts == [
        LayerCount(layer="unit", tests=2, properties=1, machines=1),
        LayerCount(layer="component", tests=0, properties=0, machines=0),
        LayerCount(layer="http", tests=0, properties=0, machines=0),
        LayerCount(layer="e2e", tests=1, properties=0, machines=0),
    ]


def test_mutants_are_scored_per_module_with_their_survivors() -> None:
    metas = {
        "cafe_norte.domain.lifecycle": {
            "cafe_norte.domain.lifecycle.x_transition__mutmut_1": 1,
            "cafe_norte.domain.lifecycle.x_transition__mutmut_2": 0,
            "cafe_norte.domain.lifecycle.x_transition__mutmut_3": 33,
            "cafe_norte.domain.lifecycle.x_transition__mutmut_4": 3,
        }
    }

    (score,) = mutation_scores(metas)

    assert score == MutationScore(
        module="cafe_norte.domain.lifecycle",
        killed=2,
        survived=("cafe_norte.domain.lifecycle.x_transition__mutmut_2",),
        untested=1,
    )
    assert score.percent == 50.0


def test_the_slowest_tests_come_first() -> None:
    assert slowest(JUNIT, 2) == [
        ("tests.component.test_b::test_slow", 1.5),
        ("tests.http.test_c::test_middle", 0.3),
    ]


def test_coverage_totals_read_lines_and_branches() -> None:
    totals = {"totals": {"percent_covered": 91.51, "num_branches": 10, "covered_branches": 9}}
    assert coverage_totals(totals) == (91.51, 90.0)


def test_the_report_names_every_section() -> None:
    text = report(
        [LayerCount(layer="unit", tests=3, properties=1, machines=0)],
        (91.5, 90.0),
        [("tests.unit.test_a::test_x", 0.2)],
        [MutationScore(module="m", killed=1, survived=("m.x__mutmut_2",), untested=0)],
    )
    for heading in ("Pyramid", "Coverage", "Slowest", "Mutation", "m.x__mutmut_2"):
        assert heading in text
