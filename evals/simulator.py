"""An LLM that plays the candidate from a persona, for live scenario runs.

What the candidate does on each line is decided here, from the persona and the transcript,
by ``cue``: a pure function, so a correction, a language switch or a question always happens
and on a line the report can name. The model only puts the cue into words."""

from functools import cache
from typing import get_args

from cafe_norte.conversation import prompts
from cafe_norte.errors import Language
from evals.contracts import Cue, Persona, Transcript


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
