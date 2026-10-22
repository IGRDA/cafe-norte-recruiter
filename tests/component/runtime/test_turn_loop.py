"""The turn loop: persistence before announcement, tool rounds, repair, cancellation, time."""

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from typing import Any

import pytest

from cafe_norte.conversation import prompts
from cafe_norte.conversation.contracts import (
    AssistantText,
    RuntimeEvent,
    StateUpdated,
    ToolFinished,
    TurnFailed,
    TurnFinished,
    TurnInput,
    TurnStarted,
)
from cafe_norte.conversation.runtime import Limits
from cafe_norte.domain.contracts import (
    InputId,
)
from cafe_norte.model.contracts import (
    ModelError,
    ModelEvent,
    ModelMessage,
    ModelText,
    ToolCall,
    ToolSchema,
)
from cafe_norte.model.fake import FakeModel
from tests.support.builders import NOW, SESSION
from tests.support.harness import (
    STOP,
    WANTS_TOOLS,
    Harness,
    fill_record,
    name_call,
    present_brief,
    says,
    turn,
    voice_run,
)


async def test_the_candidate_state_is_committed_before_the_state_update_is_yielded() -> None:
    h = Harness([[name_call(), WANTS_TOOLS], says("Hola.")])
    await h.open_session()
    revisions_seen: list[int] = []
    async for event in h.runtime.run_turn(turn("Soy Lucía")):
        if isinstance(event, StateUpdated):
            state = await h.store.sessions.get(SESSION)
            assert state is not None
            revisions_seen.append(state.candidate.revision)
    assert revisions_seen == [1]


async def test_sentences_are_streamed_as_they_complete_and_the_tail_is_flushed() -> None:
    h = Harness([says("Hola, soy ", "Ana. ¿Cómo te ", "llamas?")])
    await h.open_session()
    events = await h.run("Hola")
    assert [e.text for e in events if isinstance(e, AssistantText)] == [
        "Hola, soy Ana.",
        "¿Cómo te llamas?",
    ]
    assert isinstance(events[-1], TurnFinished)


async def test_every_event_is_journaled_with_increasing_seq_before_it_is_yielded() -> None:
    h = Harness([says("Hola.")])
    await h.open_session()
    seen = 0
    async for _ in h.runtime.run_turn(turn("Hola")):
        seen += 1
        assert h.store.events.last_seq(SESSION) == seen


async def test_a_second_runtime_over_the_same_store_continues_the_sequence() -> None:
    """The store owns the sequence: a restarted process never reuses a number."""
    h = Harness([says("Hola."), says("Otra vez.")])
    await h.open_session()
    await h.run("Hola", "in-1")
    before = h.store.events.last_seq(SESSION)
    second = Harness([says("Otra vez.")], store=h.store)
    await second.run("Sigo aquí", "in-2")
    seqs = [e.seq for e in h.store.events.all(SESSION)]
    assert seqs == list(range(1, len(seqs) + 1)) and seqs[-1] > before


async def test_the_model_sees_history_state_and_only_registered_tools() -> None:
    h = Harness([[name_call(), WANTS_TOOLS], says("Encantada."), says("Sí.")])
    await h.open_session()
    await h.run("Soy Lucía", "in-1")
    await h.run("¿Me oyes?", "in-2")
    third = h.model.calls[2]
    assert [m.role for m in third] == ["system", "user", "assistant", "user"]
    assert third[2].content == "Encantada."
    assert '"candidate_known_values": {"name": "Lucía"}' in third[0].content
    assert '"name": "captured"' in third[0].content
    assert '"status"' not in third[0].content.split("candidate_known_values")[1].split("}")[0]
    assert [t.name for t in h.model.advertised_tools[0]] == [
        "update_candidate",
        "search_knowledge",
        "list_interview_slots",
        "present_confirmation",
        "confirm_field",
        "confirm_brief",
        "reserve_interview",
        "review_readback",
        "request_human_followup",
        "end_session",
    ]


async def test_a_domain_refusal_goes_back_to_the_model_and_writes_nothing() -> None:
    bad = ToolCall(
        call_id="c1",
        name="update_candidate",
        arguments_json=json.dumps(
            {"patch": {"earliest_start_date": "2020-01-01"}, "evidence_text": "en 2020"}
        ),
    )
    h = Harness([[bad, WANTS_TOOLS], says("¿Cuándo?")])
    await h.open_session()
    events = await h.run("Empecé en 2020")
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert finished[0].ok is False
    assert finished[0].summary == "validation_failed:earliest_start_date:past_date"
    assert not any(isinstance(e, StateUpdated) for e in events)
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.candidate.revision == 0
    assert "Rejected field earliest_start_date: past_date" in h.model.calls[1][-1].content


async def test_tool_rounds_are_bounded() -> None:
    forever: list[list[ModelEvent]] = [[name_call(f"c{i}"), WANTS_TOOLS] for i in range(5)]
    h = Harness(forever, limits=Limits(max_tool_rounds=2))
    await h.open_session()
    events = await h.run("Soy Lucía")
    assert len([e for e in events if isinstance(e, ToolFinished)]) == 2
    assert isinstance(events[-1], TurnFailed) and events[-1].code == "limit_exceeded"
    assert len(h.model.calls) == 3


class Clock:
    """A settable clock: a test puts it where the turn ends and gives the turn an earlier
    ``received_at``, so the turn lasted exactly that long."""

    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now

    def turn(self, text: str, input_id: str, *, since: float, lasted: float) -> TurnInput:
        """A turn received ``lasted`` seconds before ``self.now`` moves to ``since`` seconds
        after the previous ``now`` (the gap the candidate took)."""
        received = self.now + timedelta(seconds=since)
        self.now = received + timedelta(seconds=lasted)
        return TurnInput(
            session_id=SESSION,
            input_id=InputId(input_id),
            text=text,
            channel="text",
            received_at=received,
        )


async def run_at(h: Harness, given: TurnInput) -> list[RuntimeEvent]:
    return [event async for event in h.runtime.run_turn(given)]


async def test_active_seconds_add_up_across_turns_with_a_capped_gap() -> None:
    clock = Clock()
    h = Harness([says("Uno."), says("Dos.")], clock=clock)
    await h.open_session()
    await run_at(h, clock.turn("a", "in-1", since=10, lasted=4))  # nothing before it: 4 s
    await run_at(h, clock.turn("b", "in-2", since=100, lasted=3))  # gap capped at 30 + 3 s
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.lifecycle == "active"
    assert state.active_seconds == 37.0


async def test_the_turn_that_crosses_the_cap_saves_its_facts_then_ends_the_session() -> None:
    clock = Clock()
    h = Harness(
        [[name_call(), WANTS_TOOLS], says("Encantada.")],
        limits=Limits(session_seconds=60),
        clock=clock,
    )
    await h.open_session()
    events = await run_at(h, clock.turn("Soy Lucía", "in-1", since=0, lasted=70))
    kinds = [type(e).__name__ for e in events]
    states = [e for e in events if isinstance(e, StateUpdated)]
    assert states[0].lifecycle == "active"  # the capture, committed first
    assert states[-1].lifecycle == "abandoned"
    goodbye = prompts.table("controls", "es")["time_cap"]
    said = " ".join(e.text for e in events if isinstance(e, AssistantText))
    assert said.endswith(goodbye)
    assert kinds.index("StateUpdated", kinds.index("ToolFinished")) < len(kinds) - 1
    assert isinstance(events[-1], TurnFinished)
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.lifecycle == "abandoned"
    assert state.candidate.name is not None  # nothing the candidate said is lost
    later = await run_at(h, clock.turn("Hola", "in-2", since=1, lasted=1))
    assert isinstance(later[-1], TurnFailed) and later[-1].code == "session_ended"


async def test_the_goodbye_is_in_the_session_language_and_is_part_of_the_stored_turn() -> None:
    clock = Clock()
    h = Harness([says("Nice.")], limits=Limits(session_seconds=60), clock=clock)
    await h.open_session("en")
    events = await run_at(h, clock.turn("Hi", "in-1", since=0, lasted=70))
    goodbye = prompts.table("controls", "en")["time_cap"]
    assert " ".join(e.text for e in events if isinstance(e, AssistantText)).endswith(goodbye)
    stored = await h.store.turns.recent(SESSION, 5)
    assert stored[-1].role == "assistant" and stored[-1].text.endswith(goodbye)


async def test_a_turn_under_the_cap_leaves_the_session_active() -> None:
    clock = Clock()
    h = Harness([says("Hola.")], limits=Limits(session_seconds=60), clock=clock)
    await h.open_session()
    events = await run_at(h, clock.turn("Hola", "in-1", since=0, lasted=20))
    assert not any(isinstance(e, StateUpdated) for e in events)
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.lifecycle == "active"


class Watched(FakeModel):
    """A fake model that notes when its stream was closed."""

    closed = False

    async def stream(
        self, messages: tuple[ModelMessage, ...], tools: tuple[Any, ...], *, deadline: datetime
    ) -> AsyncGenerator[ModelEvent, None]:
        try:
            async for event in super().stream(messages, tools, deadline=deadline):
                yield event
        finally:
            self.closed = True


async def assert_interrupted_and_released(h: Harness) -> None:
    kinds = [e.kind for e in h.store.events.all(SESSION)]
    last = h.store.events.all(SESSION)[-1]
    assert kinds[-1] == "turn_finished" and '"interrupted":true' in last.payload_json
    stored = await h.store.turns.recent(SESSION, 5)
    assert stored[-1].role == "assistant" and stored[-1].interrupted
    assert await h.store.leases.claim(SESSION, "intruder", ttl_seconds=60) is not None


async def test_closing_a_turn_mid_stream_journals_it_as_interrupted() -> None:
    h = Harness([])
    watched = Watched([says("Hola. ", "Te cuento algo. ", "¿Y tú?")])
    h.runtime._model = watched
    await h.open_session()
    stream = h.runtime.run_turn(turn("Hola"))
    first = ""
    async for event in stream:
        if isinstance(event, AssistantText):
            first = event.text
            break
    await stream.aclose()
    assert watched.closed
    await assert_interrupted_and_released(h)
    stored = await h.store.turns.recent(SESSION, 5)
    assert stored[-1].text == first  # what was generated before the close, nothing more


async def test_cancelling_a_turn_inside_a_model_call_journals_it_as_interrupted() -> None:
    h = Harness([says("Hola.")], slow_calls=1)
    await h.open_session()

    async def consume() -> None:
        async for _ in h.runtime.run_turn(turn("Hola")):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.1)  # the model has said nothing yet
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await assert_interrupted_and_released(h)


async def test_a_scripted_model_failure_fails_one_turn_and_leaves_the_script_for_the_next() -> None:
    h = Harness([says("Hola.")])
    await h.open_session()
    h.model.fail_next()
    failed = await h.run("Hola", "in-1")
    assert isinstance(failed[-1], TurnFailed) and failed[-1].code == "provider_unavailable"
    ok = await h.run("Hola otra vez", "in-2")
    assert [e.text for e in ok if isinstance(e, AssistantText)] == ["Hola."]


def malformed_call(call_id: str = "bad") -> ToolCall:
    return ToolCall(call_id=call_id, name="update_candidate", arguments_json='{"patch": {}}')


async def test_one_malformed_call_is_repaired_and_the_turn_finishes() -> None:
    h = Harness([[malformed_call(), WANTS_TOOLS], [name_call(), WANTS_TOOLS], says("¿Cuándo?")])
    await h.open_session()
    events = await h.run("Soy Lucía")
    assert not any(isinstance(e, TurnFailed) for e in events)
    assert isinstance(events[-1], TurnFinished)
    assert "Invalid arguments for update_candidate" in h.model.calls[1][-1].content


async def test_a_second_malformed_call_ends_the_turn_with_invalid_response() -> None:
    h = Harness(
        [[malformed_call("a"), WANTS_TOOLS], [malformed_call("b"), WANTS_TOOLS], says("Hola.")]
    )
    await h.open_session()
    events = await h.run("Soy Lucía")
    failed = events[-1]
    assert isinstance(failed, TurnFailed) and failed.code == "invalid_response"
    assert len(h.model.calls) == 2  # no third round
    assert not any(isinstance(e, AssistantText) for e in events)


async def test_a_domain_refusal_is_not_a_malformed_call() -> None:
    past = ToolCall(
        call_id="p",
        name="update_candidate",
        arguments_json=json.dumps(
            {"patch": {"earliest_start_date": "2020-01-01"}, "evidence_text": "en 2020"}
        ),
    )
    h = Harness([[past, WANTS_TOOLS], [past, WANTS_TOOLS], [past, WANTS_TOOLS], says("¿Cuándo?")])
    await h.open_session()
    events = await h.run("Empecé en 2020")
    assert not any(isinstance(e, TurnFailed) for e in events)


async def test_a_duplicate_input_id_fails_once_with_conflict_and_calls_no_model() -> None:
    h = Harness([says("Hola.")])
    await h.open_session()
    await h.run("Hola", "in-1")
    events = await h.run("Hola otra vez", "in-1")
    assert [type(e) for e in events] == [TurnFailed]
    assert isinstance(events[0], TurnFailed) and events[0].code == "conflict"
    assert len(h.model.calls) == 1


class BrokenModel:
    model_id = "broken"

    async def stream(
        self,
        messages: tuple[ModelMessage, ...],
        tools: tuple[ToolSchema, ...],
        *,
        deadline: datetime,
    ) -> AsyncGenerator[ModelEvent, None]:
        raise ModelError("secret provider detail", code="provider_unavailable")
        yield  # pragma: no cover


async def test_a_model_error_becomes_a_turn_failed_with_public_text_only() -> None:
    h = Harness([])
    h.runtime._model = BrokenModel()
    await h.open_session()
    events = await h.run("Hola")
    assert isinstance(events[0], TurnStarted)
    failed = events[-1]
    assert isinstance(failed, TurnFailed)
    assert failed.code == "provider_unavailable"
    assert "secret" not in failed.message


async def test_a_slow_first_token_fails_with_timeout() -> None:
    """Always too slow: the first round and its one retry both miss the bound."""
    h = Harness([], limits=Limits(llm_first_output_seconds=0.05))
    h.runtime._model = FakeModel([], delay_seconds=0.2, fallback=says("tarde"))
    await h.open_session()
    events = await h.run("Hola")
    assert isinstance(events[-1], TurnFailed) and events[-1].code == "timeout"


async def test_the_opening_is_journaled_and_becomes_history_for_the_first_turn() -> None:
    h = Harness([says("Encantada.")])
    await h.open_session()
    opening = [e async for e in h.runtime.open_session(SESSION)]
    assert [type(e) for e in opening] == [TurnStarted, AssistantText, TurnFinished]
    assert isinstance(opening[1], AssistantText)
    assert opening[1].text.startswith("Hola, soy Ana, la asistente de IA de Café Norte.")
    await h.run("Sí, me viene bien.")
    roles = [m.role for m in h.model.calls[0]]
    assert roles == ["system", "assistant", "user"]
    assert h.model.calls[0][1].content == opening[1].text
    # A second opening for the same session is refused, not duplicated.
    again = [e async for e in h.runtime.open_session(SESSION)]
    assert isinstance(again[0], TurnFailed) and again[0].code == "conflict"


async def test_the_prompt_carries_todays_date_in_madrid_and_the_weekday() -> None:
    h = Harness([says("Vale.")])
    await h.open_session()
    await h.run("Hola")
    content = h.model.calls[0][0].content
    assert '"today": {"date": "2026-10-20", "weekday": "martes"}' in content
    # A lookup table for relative dates, so the model never does weekday arithmetic.
    assert '"next_days": {"miércoles": "2026-10-21"' in content
    assert '"lunes": "2026-10-26"' in content and '"martes": "2026-10-27"' not in content


async def test_doubtful_work_authorization_raises_a_review_flag_without_blocking() -> None:
    call = ToolCall(
        call_id="c1",
        name="update_candidate",
        arguments_json=json.dumps(
            {"patch": {"work_authorization": "unsure"}, "evidence_text": "no estoy segura"}
        ),
    )
    h = Harness([[call, WANTS_TOOLS], says("Entiendo.")])
    await h.open_session()
    events = await h.run("No estoy segura de si tengo permiso")
    state = await h.store.sessions.get(SESSION)
    assert state is not None
    assert [f.kind for f in state.review_flags] == ["work_authorization"]
    assert state.candidate.work_authorization.status == "captured"
    assert isinstance(events[-1], TurnFinished)


async def test_a_sentence_is_not_spoken_twice_in_one_turn() -> None:
    h = Harness(
        [[ModelText(text="¿Cómo te llamas? "), name_call(), WANTS_TOOLS], says("¿Cómo te llamas?")]
    )
    await h.open_session()
    events = await h.run("Hola")
    assert [e.text for e in events if isinstance(e, AssistantText)] == ["¿Cómo te llamas?"]
    assert isinstance(events[-1], TurnFinished)


async def test_a_runaway_answer_is_cut_and_the_turn_still_finishes() -> None:
    junk = [ModelText(text="(Esperando respuesta)") for _ in range(200)]
    h = Harness(
        [[ModelText(text="¿Tienes permiso de trabajo? "), *junk, STOP]],
        limits=Limits(max_answer_characters=100),
    )
    await h.open_session()
    events = await h.run("Maialen")
    said = [e.text for e in events if isinstance(e, AssistantText)]
    assert said == ["¿Tienes permiso de trabajo?"]
    assert isinstance(events[-1], TurnFinished)


async def test_the_tool_result_tells_the_model_what_was_already_said_this_turn() -> None:
    h = Harness([[ModelText(text="¿Cómo te llamas? "), name_call(), WANTS_TOOLS], says("")])
    await h.open_session()
    await h.run("Hola")
    tool_message = h.model.calls[1][-1]
    assert tool_message.role == "tool"
    assert "Already said to the candidate this turn: ¿Cómo te llamas?" in tool_message.content
    assert "Do not repeat or rephrase it" in tool_message.content


async def test_stage_directions_and_dot_runs_are_never_spoken() -> None:
    h = Harness([says("(Esperando respuesta.) ", "Vale........ ", "¿Qué fecha podrías empezar?")])
    await h.open_session()
    events = await h.run("Hola")
    assert [e.text for e in events if isinstance(e, AssistantText)] == [
        "Vale.",
        "¿Qué fecha podrías empezar?",
    ]


async def test_the_tool_result_names_only_the_next_question() -> None:
    """Listing every missing field made the model ask them all at once (measured 1 of 6 single
    questions); naming the next one alone gave 6 of 6."""
    h = Harness([[name_call(), WANTS_TOOLS], says("¿Te interesa el puesto?")])
    await h.open_session()
    await h.run("Soy Lucía")
    content = h.model.calls[1][-1].content
    assert content.startswith("Saved: name. Now ask about interest only, in one short sentence")
    assert "work_authorization" not in content


async def test_nothing_is_spoken_after_the_first_question_of_a_turn() -> None:
    """Spec: one main question at a time. The prompt asks for it; the runtime guarantees it."""
    h = Harness(
        [
            says(
                "Perfecto. ",
                "¿Cuántas horas a la semana? ",
                "¿Cuál es la fecha? ",
                "¿Qué experiencia?",
            )
        ]
    )
    await h.open_session()
    events = await h.run("lunes y jueves")
    said = [e.text for e in events if isinstance(e, AssistantText)]
    assert said == ["Perfecto.", "¿Cuántas horas a la semana?"]
    assert isinstance(events[-1], TurnFinished)


async def test_a_question_before_the_tool_call_silences_the_round_after_it() -> None:
    h = Harness(
        [
            [ModelText(text="¿Cómo te llamas? "), name_call(), WANTS_TOOLS],
            says("¿Te interesa el puesto?"),
        ]
    )
    await h.open_session()
    events = await h.run("Soy Lucía.")
    assert [e.text for e in events if isinstance(e, AssistantText)] == ["¿Cómo te llamas?"]
    assert any(isinstance(e, StateUpdated) for e in events)  # the tool call still ran


async def test_a_presentation_is_spoken_verbatim_before_tool_finished_and_marked_delivered() -> (
    None
):
    h = Harness([[present_brief(), WANTS_TOOLS], says("Dime.")])
    await h.open_session()
    await fill_record(h)
    events = await h.run("ya está todo")
    kinds = [type(e).__name__ for e in events]
    spoken = [e.text for e in events if isinstance(e, AssistantText)]
    assert kinds.index("AssistantText") < kinds.index("ToolFinished")
    assert spoken[0] == "Te resumo lo que tengo." and spoken[-1] == "¿Es todo correcto?"
    assert "Dime." not in spoken  # the brief ends with the turn's one question
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.pending_confirmation is not None
    assert state.pending_confirmation.fully_delivered is True
    assert state.pending_confirmation.presentation_text == " ".join(spoken)


async def test_a_presentation_is_spoken_in_full_even_after_the_model_asked_something() -> None:
    """The one-question rule bounds the model's own text; a read-back is authoritative."""
    h = Harness([[ModelText(text="¿Lo repaso? "), present_brief(), WANTS_TOOLS], says("¿Vale?")])
    await h.open_session()
    await fill_record(h)
    events = await h.run("ya está")
    spoken = [e.text for e in events if isinstance(e, AssistantText)]
    assert spoken[0] == "¿Lo repaso?"
    assert "Te resumo lo que tengo." in spoken and spoken[-1] == "¿Es todo correcto?"
    assert "¿Vale?" not in spoken


async def test_a_turn_on_an_ended_session_fails_with_session_ended_and_persists_nothing() -> None:
    h = Harness([says("Hola.")])
    await h.open_session()
    state = await h.store.sessions.get(SESSION)
    assert state is not None
    async with h.store.transaction() as tx:
        await h.store.sessions.save(
            tx,
            state.model_copy(update={"lifecycle": "completed", "outcome": "brief_only"}),
            expected_revision=0,
        )
    events = await h.run("¿sigues ahí?")
    assert [type(e) for e in events] == [TurnFailed]
    assert isinstance(events[0], TurnFailed) and events[0].code == "session_ended"
    assert events[0].message == "Esta conversación ha terminado."
    assert await h.store.turns.recent(SESSION, 10) == ()
    assert h.model.calls == ()


async def test_a_voice_read_back_is_delivered_only_when_the_channel_says_so() -> None:
    """Text marks a read-back delivered when journaled; voice waits for playback."""
    h = Harness([[present_brief(), WANTS_TOOLS], says("")])
    await h.open_session()
    await fill_record(h)
    events = await voice_run(h, "ya está todo")
    turn_id = next(e for e in events if isinstance(e, TurnStarted)).turn_id
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.pending_confirmation is not None
    assert state.pending_confirmation.fully_delivered is False

    # Interrupted after the first sentence: not delivered, and a "sí" cannot confirm it.
    await h.runtime.delivered(turn_id, text="Te resumo lo que tengo.", complete=False)
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.pending_confirmation is not None
    assert state.pending_confirmation.fully_delivered is False
    assistant = [t for t in await h.store.turns.recent(SESSION, 10) if t.role == "assistant"][-1]
    assert assistant.delivered_text == "Te resumo lo que tengo." and assistant.interrupted is True

    # Heard to the end on a later playback: delivered.
    await h.runtime.delivered(
        turn_id, text=state.pending_confirmation.presentation_text, complete=True
    )
    state = await h.store.sessions.get(SESSION)
    assert state is not None and state.pending_confirmation is not None
    assert state.pending_confirmation.fully_delivered is True


async def test_end_stops_or_abandons_through_the_lifecycle_table() -> None:
    h = Harness([])
    await h.open_session()
    await h.runtime.end(SESSION, "limit")
    state = await h.store.sessions.get(SESSION)
    assert state is not None and (state.lifecycle, state.outcome) == ("abandoned", "incomplete")
    h2 = Harness([])
    await h2.open_session()
    await h2.runtime.end(SESSION, "stop")
    state = await h2.store.sessions.get(SESSION)
    assert state is not None and (state.lifecycle, state.outcome) == ("stopped", "incomplete")
    await h2.runtime.end(SESSION, "stop")  # already terminal: a no-op, not an error


async def test_an_unknown_session_fails_with_not_found_and_journals_nothing() -> None:
    h = Harness([])
    events = await h.run("Hola")
    assert isinstance(events[0], TurnFailed) and events[0].code == "not_found"
    assert h.store.events.all(SESSION) == ()


@pytest.mark.parametrize("text", ["", "   "])
async def test_blank_model_output_still_finishes_the_turn(text: str) -> None:
    h = Harness([says(text)])
    await h.open_session()
    events = await h.run("Hola")
    assert not any(isinstance(e, AssistantText) for e in events)
    assert isinstance(events[-1], TurnFinished)


async def test_an_answer_the_model_invents_after_its_question_is_not_spoken() -> None:
    h = Harness([says("¿Te interesa el puesto de barista?Sí, me interesa el puesto.")])
    await h.open_session()
    events = await h.run("mi nombre es Iñaki")
    said = [e.text for e in events if isinstance(e, AssistantText)]
    assert said == ["¿Te interesa el puesto de barista?"]
