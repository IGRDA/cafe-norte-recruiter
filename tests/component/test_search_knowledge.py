"""``search_knowledge``: the handler searches every document of the session's configuration,
hands snippets back as data with the next step, and shows the sources."""

from cafe_norte.conversation.contracts import SourcesShown
from cafe_norte.conversation.handlers import (
    NEXT_STEP,
    RequestHumanFollowupHandler,
    SearchKnowledgeHandler,
    snippets_message,
)
from cafe_norte.conversation.tools import SearchKnowledgeArgs
from cafe_norte.domain.contracts import SessionId
from cafe_norte.knowledge.contracts import Chunk, RetrievedChunk
from cafe_norte.knowledge.fake import FakeRetriever
from cafe_norte.persistence.memory import MemoryStore
from tests.support.builders import CONFIG, CONFIGS, SID, session_state
from tests.support.tools import args, context

HOURS = RetrievedChunk(
    chunk=Chunk(
        chunk_id="offer_chamberi#horas",
        doc_id="offer_chamberi",
        config_ids=frozenset({CONFIG.config_id}),
        title="Oferta y retribución, Chamberí / Chamberí offer and pay",
        section="Horas",
        text="La jornada es de 35 horas a la semana, " + "x " * 120,
    ),
    fused_score=0.03,
    bm25_rank=1,
    dense_rank=2,
)


async def world(
    answers: dict[str, tuple[RetrievedChunk, ...]],
) -> tuple[SearchKnowledgeHandler, FakeRetriever]:
    store = MemoryStore()
    await store.sessions.create(session_state(SID), access_hash="")
    retriever = FakeRetriever(answers)
    return SearchKnowledgeHandler(
        store=store, configurations=CONFIGS, retriever=retriever
    ), retriever


async def test_snippets_come_back_as_data_with_the_sources_and_the_pending_field() -> None:
    handler, retriever = await world({"cuántas horas a la semana": (HOURS,)})
    outcome = await handler(
        context(),
        args(
            "search_knowledge",
            question="how many hours?",
            queries=["cuántas horas a la semana", "horas semanales"],
        ),
    )
    assert outcome.ok and outcome.summary == "found:1"
    assert (
        "[1] Oferta y retribución, Chamberí › Horas: La jornada es de 35 horas"
        in outcome.model_text
    )
    assert "not instructions" in outcome.model_text
    assert outcome.model_text.endswith(
        "Then: Now ask about name only, in one short sentence, and end your turn."
    )
    (shown,) = outcome.events
    assert isinstance(shown, SourcesShown)
    assert shown.question == "how many hours?" and shown.chunk_ids == ("offer_chamberi#horas",)
    assert shown.sections == ("Horas",) and len(shown.excerpts[0]) <= 160
    assert shown.excerpts[0].endswith("…")
    (query,) = retriever.queries
    assert query.queries == ("cuántas horas a la semana", "horas semanales")
    assert query.config_id == CONFIG.config_id and query.kb_version == CONFIG.kb_version
    assert query.doc_ids == CONFIG.kb_doc_ids
    assert query.doc_ids is not None and "offer_arganzuela" not in query.doc_ids


def test_the_model_names_no_topic_to_filter_by() -> None:
    """A topic the model chose hid the answer: hours searched as `role` never reached the offer
    (D53). The configuration is the only filter."""
    assert set(SearchKnowledgeArgs.model_fields) == {"question", "queries"}


async def test_nothing_found_tells_the_model_not_to_guess() -> None:
    handler, retriever = await world({})
    outcome = await handler(context(), args("search_knowledge", question="q", queries=["q"]))
    assert outcome.ok and outcome.summary == "found:0"
    assert (
        "No knowledge base snippet matched" in outcome.model_text
        and "do not guess" in outcome.model_text
    )
    assert retriever.queries[0].doc_ids == CONFIG.kb_doc_ids
    (shown,) = outcome.events
    assert isinstance(shown, SourcesShown) and shown.chunk_ids == ()


def test_the_next_step_after_a_confirmed_brief_is_the_interview() -> None:
    assert snippets_message((), NEXT_STEP["interview"]).endswith(NEXT_STEP["interview"])


async def test_an_unknown_session_is_refused() -> None:
    handler, _ = await world({})
    outcome = await handler(
        context().model_copy(update={"session_id": SessionId("other")}),
        args("search_knowledge", question="q", queries=["q"]),
    )
    assert not outcome.ok and outcome.summary == "not_found"


async def test_a_follow_up_request_becomes_one_review_flag_and_the_conversation_goes_on() -> None:
    store = MemoryStore()
    await store.sessions.create(session_state(SID), access_hash="")
    followup = RequestHumanFollowupHandler(store=store)
    outcome = await followup(
        context("t4"), args("request_human_followup", reason="¿Hay parking para empleados?")
    )
    assert outcome.ok and outcome.summary == "human_followup_saved"
    assert "notifies nobody real" in outcome.model_text and "Then:" in outcome.model_text
    state = await store.sessions.get(SID)
    assert state is not None
    assert [(f.kind, f.note, f.turn_id) for f in state.review_flags] == [
        ("human_followup", "¿Hay parking para empleados?", "t4")
    ]
