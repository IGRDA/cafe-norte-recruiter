"""Fixtures of the evaluation tooling's tests: a simulated candidate's persona and the run
record of the committed example export."""

from evals.contracts import JudgeVerdict, Persona, RunRecord, Speaker, Transcript

from cafe_norte.persistence.export import ExportDocument
from tests.support import ROOT

PERSONA = Persona(
    facts={"name": "Lucía Marín", "hours_per_week": "30"},
    corrections=(("hours_per_week", "25"),),
    asks=("¿Cuántas horas son?", "¿Hay parking?"),
)
GREETING: Transcript = (("ana", "Hola, soy Ana. ¿Te viene bien ahora?"),)
BRIEF_SPOKEN = "Te leo el resumen. Lucía Marín, 30 horas. ¿Es todo correcto?"


def after(*lines: tuple[Speaker, str]) -> Transcript:
    return (*GREETING, *lines)


EXPORT = ExportDocument.model_validate_json(
    (ROOT / "examples" / "session_export.example.json").read_text()
)


def record(judged: JudgeVerdict | None = None) -> RunRecord:
    return RunRecord(
        case_id="S01",
        mode="live",
        model="openai/gpt-4o-mini",
        versions=EXPORT.versions,
        export=EXPORT,
        checks=(),
        judge=judged,
        provider_failed=False,
        estimated_cost_eur=0.0,
    )
