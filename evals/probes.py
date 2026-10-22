"""QA probes (D51): each knowledge-base question asked live as the first line of its own
session, so what Ana answers can be scored apart from the rest of the interview.

``probe`` drives one session and records the answer, the chunks shown in that turn (with
their text, for faithfulness) and the tools the turn called, from the journal. ``run_probes``
serves the app on loopback per model, as the live scenarios do (``live_runs.target``). Nothing
here is judged: the deterministic reads are ``scorers.facts_missing`` and ``abstained``; the
judges run afterwards (``ragas_bridge.judge_probes``)."""

from collections.abc import Mapping, Sequence

import httpx

from cafe_norte.domain.configuration import load_configurations
from cafe_norte.errors import ServiceError
from evals.contracts import ProbeRecord, RetrievalCase, RunRecord
from evals.live import HttpConversation, LiveError, ScriptedCandidate, drive
from evals.live_runs import HTTP_TIMEOUT, ROOT, target
from evals.pool import CONCURRENCY, bounded
from evals.scorers import tool_trajectory
from evals.testset import kb_chunks


async def probe(
    case: RetrievalCase,
    conversation: HttpConversation,
    *,
    model: str,
    chunk_text: Mapping[str, str],
    allowed_doc_ids: frozenset[str],
) -> ProbeRecord:
    """Ana's opening, then the question, then the end. A probe that breaks is a recorded miss."""
    base = {
        "case_id": case.id,
        "scenario_id": case.id,
        "mode": "live",
        "model": model,
        "language": case.language,
    }
    try:
        finished = await drive(conversation, ScriptedCandidate([case.question]), max_turns=1)
    except (LiveError, ServiceError, httpx.HTTPError) as error:
        broken = RunRecord(
            **base,
            versions=None,
            export=None,
            checks=(),
            provider_failed=False,
            estimated_cost_eur=None,
            failure=f"{type(error).__name__}: {error}",
        )
        return ProbeRecord(
            case_id=case.id, kind=case.kind, run=broken, expected_facts=case.expected_facts
        )
    export = finished.export
    (turn,) = finished.observations[1:]
    run = RunRecord(
        **base,
        session_id=conversation.session_id,
        versions=export.versions,
        export=export,
        checks=(),
        provider_failed=bool(turn.failed),
        estimated_cost_eur=export.metrics.estimated_marginal_cost_eur,
        tool_calls=turn.tools,
        first_text_ms=(turn.client_first_text_ms,) if turn.client_first_text_ms else (),
        turn_ms=(turn.client_total_ms,) if turn.client_total_ms is not None else (),
        lines=1,
        cost_is_partial=export.metrics.cost_is_partial,
    )
    sources = tuple(dict.fromkeys(turn.sources))
    return ProbeRecord(
        case_id=case.id,
        kind=case.kind,
        run=run,
        expected_facts=case.expected_facts,
        answer=" ".join(turn.spoken),
        sources=sources,
        foreign_sources=tuple(s for s in sources if s.split("#")[0] not in allowed_doc_ids),
        contexts=tuple(chunk_text[s] for s in sources if s in chunk_text),
        tools=tool_trajectory(export),
    )


async def run_probes(
    cases: Sequence[RetrievalCase],
    *,
    model: str,
    base_url: str | None,
    access_code: str | None,
    env: Mapping[str, str],
    concurrency: int = CONCURRENCY,
) -> list[ProbeRecord]:
    """Every question, one session each, ``concurrency`` at a time, in the cases' order."""
    configurations = load_configurations(ROOT / "config")
    chunk_text = {c.chunk_id: c.text for c in kb_chunks()}
    async with target(model, base_url, env) as url:

        async def one(case: RetrievalCase) -> ProbeRecord:
            async with httpx.AsyncClient(base_url=url, timeout=HTTP_TIMEOUT) as client:
                allowed = configurations[case.config_id].kb_doc_ids
                conversation = HttpConversation(
                    client,
                    config_id=case.config_id,
                    language=case.language,
                    allowed_doc_ids=allowed,
                    access_code=access_code if base_url else None,
                )
                record = await probe(
                    case, conversation, model=model, chunk_text=chunk_text, allowed_doc_ids=allowed
                )
            print(_line(record), flush=True)
            return record

        return await bounded(cases, one, limit=concurrency)


def _line(record: ProbeRecord) -> str:
    if record.run.failure:
        return f"BROKEN {record.case_id}  {record.run.failure}"
    return f"probe  {record.case_id} {record.kind:<11} {list(record.tools)}  {record.answer[:70]}"
