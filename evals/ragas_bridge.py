"""Retrieval runs as ragas samples, scored with ragas' ID-based context precision and recall.

Offline and model-free: the fixture's expected sections are chunk ids, so the ID-based
metrics apply exactly (no fuzzy string matching, no LLM). Only answerable questions have a
reference; unsupported and leakage questions stay with our own numbers. Faithfulness needs
answers and a paid judge and is not computed here (D43)."""

import math
import warnings
from collections.abc import Sequence

from evals.contracts import RagasCaseScore, RagasSample, RagasScores, RetrievalCase, RetrievalRun


def to_ragas_samples(
    runs: Sequence[RetrievalRun], cases: Sequence[RetrievalCase]
) -> list[RagasSample]:
    by_id = {c.id: c for c in cases}
    return [
        RagasSample(
            case_id=run.case_id,
            user_input=by_id[run.case_id].question,
            retrieved_context_ids=run.returned,
            reference_context_ids=by_id[run.case_id].expected_sections,
        )
        for run in runs
        if by_id[run.case_id].kind == "answerable"
    ]


async def score_with_ragas(samples: Sequence[RagasSample]) -> RagasScores:
    """ragas is imported here, not at module load: it takes seconds and only this needs it."""
    from ragas import SingleTurnSample

    with warnings.catch_warnings():
        # ragas 0.4 deprecates this path for one with no ID-based precision yet.
        warnings.simplefilter("ignore", DeprecationWarning)
        from ragas.metrics import IDBasedContextPrecision, IDBasedContextRecall

    precision_metric, recall_metric = IDBasedContextPrecision(), IDBasedContextRecall()
    scores: list[RagasCaseScore] = []
    for sample in samples:
        ragas_sample = SingleTurnSample(
            user_input=sample.user_input,
            retrieved_context_ids=list(sample.retrieved_context_ids),
            reference_context_ids=list(sample.reference_context_ids),
        )
        precision = float(await precision_metric.single_turn_ascore(ragas_sample))
        recall = float(await recall_metric.single_turn_ascore(ragas_sample))
        scores.append(
            RagasCaseScore(
                case_id=sample.case_id,
                precision=None if math.isnan(precision) else precision,
                recall=recall,
            )
        )
    precisions = [s.precision for s in scores if s.precision is not None]
    return RagasScores(
        samples=len(scores),
        mean_precision=sum(precisions) / len(precisions) if precisions else None,
        mean_recall=sum(s.recall for s in scores) / len(scores) if scores else 0.0,
        nothing_retrieved=len(scores) - len(precisions),
        per_case=tuple(scores),
    )
