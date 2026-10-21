"""Fast synchronous controls and the asynchronous classifier adapter.

``explicit_controls`` is the synchronous path: plain patterns over finalized text, run before
the model in the same turn, for stop and human requests and for explicit language requests.
``ModelSignalAnalyzer`` is the soft path: a small classifier call after the turn, whose
sentiment shapes the next response only (``fresh_sentiment``)."""

import asyncio
import logging
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from cafe_norte.conversation import prompts
from cafe_norte.domain.contracts import Sentiment, Signal, TurnId
from cafe_norte.errors import Language, ServiceError
from cafe_norte.model.contracts import Model, ModelMessage, ModelText

Control = Literal["stop", "human", "switch_es", "switch_en"]

log = logging.getLogger(__name__)

# ---- explicit controls ---------------------------------------------------------------------------

# Stop and human requests are matched in every language: a candidate may ask for a person in
# English during a Spanish session. Each pattern runs against one normalized clause: lowercase,
# no accents, no apostrophes, single spaces.
_PERSON_ES = (
    r"(?:una persona(?: real| de verdad)?|alguien(?: real| de verdad| del equipo)?"
    r"|un humano|una humana|un reclutador|una reclutadora|un responsable|una responsable"
    r"|el encargado|la encargada)"
)
_PERSON_EN = (
    r"(?:a (?:real |actual )?(?:person|human)|an actual person|some(?:one|body)(?: real)?"
    r"|a recruiter|a manager)"
)
_PATTERNS: dict[Language, dict[Control, re.Pattern[str]]] = {
    "es": {
        "human": re.compile(
            rf"\b(?:(?:hablar|hable|habla|pasame|pasarme|me pasas|ponme|ponerme|comunicame"
            rf"|comunicarme) con|quiero|prefiero|que me atienda) {_PERSON_ES}\b"
        ),
        "stop": re.compile(
            r"\b(?:quiero|prefiero|vamos a|podemos) (?:parar|terminar|acabar|dejarlo|colgar)\b"
            r"|\bno quiero (?:seguir|continuar)\b"
            r"|\b(?:lo dejo|lo dejamos|dejemoslo) (?:aqui|ya)\b"
            r"|\b(?:terminar|acabar|cortar|colgar) (?:la llamada|aqui)\b"
            r"|^(?:para|parar|basta|stop)(?: ya| por favor)?$"
        ),
    },
    "en": {
        "human": re.compile(
            rf"\b(?:(?:talk|speak) (?:to|with)|i want|id like|i need|get me|put me through to)"
            rf" {_PERSON_EN}\b"
        ),
        "stop": re.compile(
            r"\b(?:i want to|id like to|lets|can we|i wanna) (?:stop|end|quit|finish|hang up)\b"
            r"|\bi (?:dont|do not) want to (?:continue|go on)\b"
            r"|\b(?:end|stop) (?:the call|this call|here)\b"
            r"|^(?:stop|enough|quit)(?: now| please)?$"
        ),
    },
}

_CLAUSE_BREAK = re.compile(r"[.,;:!?¡¿\n]+")
_NOT_A_WORD = re.compile(r"[^a-z0-9 ]+")
_NEGATIONS = frozenset({"no", "nunca", "not", "dont", "never"})
_NEGATION_WINDOW = 3  # words before a match that can negate it ("no quiero hablar con…")

# An explicit language request names the language with a request word around it; a bare
# borrowed word ("Starbucks", "I studied English") never matches. Matched on the whole text
# in lower case without accents, so "English, please" keeps its comma.
_EN = r"english(?![\w-])"
_ES = r"(?:spanish|espanol|castellano)(?![\w-])"
_SWITCHES: tuple[tuple[Control, re.Pattern[str]], ...] = (
    (
        "switch_en",
        re.compile(
            rf"\b(?:(?:in|into|to|speak) {_EN}|{_EN},? please|en ingles\b"
            r"|hablar? ingles\b|ingles,? por favor)"
        ),
    ),
    (
        "switch_es",
        re.compile(rf"\b(?:(?:in|into|to|speak|en|hablar?) {_ES}|{_ES},? (?:please|por favor))"),
    ),
)
_SWITCH_TO: dict[Control, Language] = {"switch_es": "es", "switch_en": "en"}


def explicit_controls(text: str) -> frozenset[Control]:
    """Pattern-based detection of stop, human and language requests. Pure, no model.

    Each clause is matched on its own for stop and human requests, so "No, quiero hablar con
    una persona" is a request and "no quiero hablar con una persona" is not. Language requests
    are matched on the whole text."""
    found: set[Control] = set()
    for clause in _clauses(text):
        for patterns in _PATTERNS.values():
            for control, pattern in patterns.items():
                match = pattern.search(clause)
                if match and not _negated(clause[: match.start()]):
                    found.add(control)
    plain = _plain(text)
    found.update(control for control, pattern in _SWITCHES if pattern.search(plain))
    return frozenset(found)


def requested_language(controls: frozenset[Control], current: Language) -> Language:
    """The language asked for when exactly one switch was requested; ``current`` otherwise."""
    asked = {_SWITCH_TO[c] for c in controls if c in _SWITCH_TO}
    return asked.pop() if len(asked) == 1 else current


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _clauses(text: str) -> list[str]:
    plain = _plain(text).replace("'", "").replace("’", "")
    clauses = (" ".join(_NOT_A_WORD.sub(" ", part).split()) for part in _CLAUSE_BREAK.split(plain))
    return [clause for clause in clauses if clause]


def _negated(before: str) -> bool:
    return not _NEGATIONS.isdisjoint(before.split()[-_NEGATION_WINDOW:])


# ---- plain answers to a read-back ----------------------------------------------------------------

ReadbackAnswer = Literal["affirm", "deny"]

# Whole phrases, longest first, so "no es correcto" is a denial and never "no" + "es correcto".
_DENY = (
    "no es correcto",
    "no esta bien",
    "no es asi",
    "no lo es",
    "incorrecto",
    "no no",
    "no",
    "thats wrong",
    "thats not right",
    "not correct",
    "incorrect",
    "nope",
    "wrong",
)
# A yes is made of yes-words in any order. ``_YES_CORE`` words say yes by themselves; the weak
# ones ("todo", "está", "eso") only support them, so "todo" alone is not an answer. Phrases are
# taken out first, so "de acuerdo" counts as one core word.
_YES_PHRASES = ("de acuerdo", "eso es", "asi es", "si lo es", "thats right", "that is right")
_YES_CORE = frozenset(
    {"si", "vale", "correcto", "bien", "perfecto", "exacto", "claro", "efectivamente"}
    | {"yes", "right", "correct", "fine", "good", "exactly", "yeah", "yep", "sure"}
)
_YES_WEAK = frozenset({"todo", "esta", "eso", "asi", "es", "lo", "all", "that", "thats", "is"})
_FILLERS = frozenset(
    {"mhmm", "mhm", "mmm", "mm", "hmm", "eh", "ah", "uh", "um", "pues", "bueno", "ok", "okay"}
)


def answer_to_readback(text: str) -> ReadbackAnswer | None:
    """``affirm`` or ``deny`` when the whole utterance is a plain yes or no (with fillers such
    as "mhmm"); ``None`` when anything else is said, which stays the model's to interpret
    ("sí, pero el teléfono es otro"). Pure; both languages."""
    words = " ".join(" ".join(_clauses(text)).split())
    rest, found = words, False
    for phrase in _DENY:
        pattern = re.compile(rf"\b{re.escape(phrase)}\b")
        if pattern.search(rest):
            found = True
            rest = pattern.sub(" ", rest)
    if found:
        leftover = [w for w in rest.split() if w not in _FILLERS]
        return "deny" if not leftover else None  # a plain no plus something else: the model decides
    return "affirm" if _is_plain_yes(words) else None


def _is_plain_yes(words: str) -> bool:
    """Only yes-words and fillers, at least one core yes-word, no negation, any order."""
    for phrase in _YES_PHRASES:
        words = re.sub(rf"\b{re.escape(phrase)}\b", " yes ", words)
    rest = [w for w in words.split() if w not in _FILLERS]
    return (
        bool(rest)
        and all(w in _YES_CORE or w in _YES_WEAK for w in rest)
        and any(w in _YES_CORE for w in rest)
    )


# ---- asynchronous classifier ---------------------------------------------------------------------


class _Verdict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    sentiment: Sentiment
    evidence_text: str = ""


class ModelSignalAnalyzer:
    """Small classifier call, off the critical path; stale results never override a newer
    explicit preference. ``None`` when the verdict is late, malformed or not backed by the
    candidate's own words: nothing is guessed into a signal."""

    def __init__(self, model: Model, *, deadline_seconds: float = 5.0) -> None:
        self._model = model
        self._deadline_seconds = deadline_seconds

    async def analyze(self, turn_id: TurnId, text: str, language: Language) -> Signal | None:
        try:
            async with asyncio.timeout(self._deadline_seconds):
                raw = await self._complete(text, language)
            verdict = _Verdict.model_validate_json(_strip_fence(raw))
        except (TimeoutError, ServiceError, ValidationError) as error:
            log.info("no signal for turn %s: %s", turn_id, type(error).__name__)
            return None
        evidence = verdict.evidence_text.strip()
        if evidence.casefold() not in text.casefold() or (
            verdict.sentiment != "neutral" and not evidence
        ):
            log.info("no signal for turn %s: evidence not in the text", turn_id)
            return None
        controls = explicit_controls(text)
        asked = requested_language(controls, language)
        return Signal(
            turn_id=turn_id,
            sentiment=verdict.sentiment,
            explicit_human_request="human" in controls,
            explicit_stop="stop" in controls,
            language_switch_to=None if asked == language else asked,
            evidence_text=evidence,
        )

    async def _complete(self, text: str, language: Language) -> str:
        messages = (
            ModelMessage(role="system", content=prompts.load("classifier")),
            ModelMessage(role="user", content=f"language: {language}\ntext: {text}"),
        )
        deadline = datetime.now(UTC) + timedelta(seconds=self._deadline_seconds)
        parts: list[str] = []
        async for event in self._model.stream(messages, (), deadline=deadline):
            if isinstance(event, ModelText):
                parts.append(event.text)
        return "".join(parts)


def _strip_fence(raw: str) -> str:
    """Models sometimes wrap JSON in a Markdown fence; the payload is what is inside."""
    body = raw.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[-1].rsplit("```", 1)[0]
    return body.strip()


SOFT_SENTIMENTS: frozenset[Sentiment] = frozenset({"frustrated", "uncertain"})


def fresh_sentiment(signal: Signal | None, previous_turn_id: TurnId | None) -> Sentiment | None:
    """The sentiment the next response should adapt to: only from the immediately previous
    user turn, and only when it asks for a change of tone. Stale or neutral results are
    dropped, never carried forward."""
    if signal is None or signal.turn_id != previous_turn_id:
        return None
    return signal.sentiment if signal.sentiment in SOFT_SENTIMENTS else None
