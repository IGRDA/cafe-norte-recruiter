"""An LLM that plays the candidate from a persona, for live scenario runs.

What the candidate does on each line is decided here, from the persona and the transcript,
by ``cue``: a pure function, so a correction, a language switch or a question always happens
and on a line the report can name. The model only puts the cue into words."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import get_args

from cafe_norte.conversation import prompts
from cafe_norte.errors import Language
from cafe_norte.model.contracts import Model, ModelMessage, ModelText
from evals.contracts import CandidateSimulator, Cue, Persona, Transcript
from evals.scorers import relative_date


def cue(persona: Persona, language: Language, transcript: Transcript) -> Cue:
    """The cue for the next candidate line.

    - ``asks[k]`` is raised on line ``k + 2`` (line 1 answers the greeting).
    - ``corrections`` answer the first brief Ana reads back, and only that one.
    - after line ``switch_language_after_turn`` the candidate speaks the other language.
    - after line ``withdraws_after_turn`` the candidate leaves politely."""
    line = 1 + sum(1 for speaker, _ in transcript if speaker == "candidate")
    switch = persona.switch_language_after_turn
    speaks = _other(language) if switch is not None and line > switch else language
    ask_index = line - 2
    briefs = sum(1 for speaker, text in transcript if speaker == "ana" and _is_brief(text))
    withdraw = persona.withdraws_after_turn is not None and line > persona.withdraws_after_turn
    return Cue(
        language=speaks,
        mood=persona.mood,
        ask=persona.asks[ask_index] if 0 <= ask_index < len(persona.asks) else None,
        corrections=persona.corrections if briefs == 1 and _last_ana_is_brief(transcript) else (),
        withdraw=withdraw,
    )


def _other(language: Language) -> Language:
    return "en" if language == "es" else "es"


def _last_ana_is_brief(transcript: Transcript) -> bool:
    return bool(transcript) and transcript[-1][0] == "ana" and _is_brief(transcript[-1][1])


def _is_brief(text: str) -> bool:
    return any(question in text for question in _brief_questions())


@cache
def _brief_questions() -> frozenset[str]:
    """The brief's fixed closing question in every language: the runtime reads it word for
    word (D20), so it marks a read-back reliably."""
    return frozenset(prompts.table("brief", lang)["question"] for lang in get_args(Language))


PROMPT = Path(__file__).with_name("prompts") / "simulator.md"
REPLY_SECONDS = 30.0  # the simulator's own model call
LANGUAGE_NAMES: dict[Language, str] = {"es": "Spanish (Spain)", "en": "English"}


class SimulatorError(Exception):
    """The simulator produced nothing usable; the run stops rather than send a guess."""


class ModelCandidateSimulator:
    """Words a cue through the ``Model`` port: the persona in the system message, the
    conversation and this line's instructions in the user message, no tools."""

    def __init__(
        self, model: Model, *, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._model = model
        self._clock = clock

    @property
    def model_id(self) -> str:
        return self._model.model_id

    async def reply(self, persona: Persona, cue: Cue, transcript: Transcript) -> str:
        messages = (
            ModelMessage(role="system", content=_system(persona, self._clock())),
            ModelMessage(role="user", content=_user(cue, transcript)),
        )
        deadline = self._clock() + timedelta(seconds=REPLY_SECONDS)
        parts = [
            event.text
            async for event in self._model.stream(messages, (), deadline=deadline)
            if isinstance(event, ModelText)
        ]
        line = "".join(parts).strip().strip('"').strip()
        if not line:
            raise SimulatorError("the simulator said nothing")
        return line


class SimulatedCandidate:
    """The ``Candidate`` a live run talks to: the cue decides, the simulator words it. Once it
    has withdrawn it has nothing more to say."""

    def __init__(self, simulator: CandidateSimulator, persona: Persona, language: Language) -> None:
        self._simulator = simulator
        self._persona = persona
        self._language: Language = language
        self._withdrawn = False

    async def next_line(self, transcript: Transcript) -> str | None:
        if self._withdrawn:
            return None
        this = cue(self._persona, self._language, transcript)
        self._withdrawn = this.withdraw
        return await self._simulator.reply(self._persona, this, transcript)


def _system(persona: Persona, now: datetime) -> str:
    facts = "\n".join(f"- {field}: {_dated(value, now)}" for field, value in persona.facts.items())
    return _template().format(
        today=f"{now:%A} {now.day} {now:%B %Y}",
        facts=facts or "- nothing beyond your first name being private",
        declines=", ".join(persona.declines) or "none",
        interview="want" if persona.wants_interview else "do not want",
        mood="frustrated and impatient; say so briefly"
        if persona.mood == "frustrated"
        else "relaxed and cooperative",
    )


def _dated(value: str, now: datetime) -> str:
    """A relative date with the day it means: the model miscounts weekdays on its own."""
    day = relative_date(value, now.date())
    return value if day is None else f"{value} ({day:%A} {day.day} {day:%B %Y})"


def _user(cue: Cue, transcript: Transcript) -> str:
    said = "\n".join(
        f"{'Ana' if speaker == 'ana' else 'You'}: {text}" for speaker, text in transcript
    )
    instructions = [f"Write in {LANGUAGE_NAMES[cue.language]}."]
    if cue.ask:
        instructions.append(f"Answer briefly, then ask this question in your own words: {cue.ask}")
    for field, value in cue.corrections:
        instructions.append(f"Ana's summary is wrong: correct {field} to {value}.")
    if cue.withdraw:
        instructions.append("You have changed your mind: politely leave the conversation now.")
    return f"The conversation so far:\n{said}\n\nInstructions for this message:\n" + "\n".join(
        f"- {line}" for line in instructions
    )


@cache
def _template() -> str:
    return PROMPT.read_text(encoding="utf-8")
