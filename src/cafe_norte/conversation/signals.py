"""Fast synchronous controls and the asynchronous classifier adapter.

``explicit_controls`` is the synchronous path: plain patterns over finalized text, run before
the model in the same turn, for stop and human requests and for explicit language requests.
``ModelSignalAnalyzer`` is the soft path: a small classifier call after the turn, whose
sentiment shapes the next response only (``fresh_sentiment``)."""

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from cafe_norte.conversation import prompts
from cafe_norte.conversation.contracts import SignalAnalysis
from cafe_norte.domain.contracts import Sentiment, Signal, TurnId
from cafe_norte.domain.numbers import plain
from cafe_norte.errors import Language, ServiceError
from cafe_norte.model.contracts import Model, ModelMessage, ModelText, ModelUsage

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
    folded = plain(text)
    found.update(control for control, pattern in _SWITCHES if pattern.search(folded))
    return frozenset(found)


def requested_language(controls: frozenset[Control], current: Language) -> Language:
    """The language asked for when exactly one switch was requested; ``current`` otherwise."""
    asked = {_SWITCH_TO[c] for c in controls if c in _SWITCH_TO}
    return asked.pop() if len(asked) == 1 else current


def _clauses(text: str) -> list[str]:
    folded = plain(text).replace("'", "").replace("’", "")
    clauses = (" ".join(_NOT_A_WORD.sub(" ", part).split()) for part in _CLAUSE_BREAK.split(folded))
    return [clause for clause in clauses if clause]


def _negated(before: str) -> bool:
    return not _NEGATIONS.isdisjoint(before.split()[-_NEGATION_WINDOW:])


# ---- a farewell (D46) ----------------------------------------------------------------------------

_FAREWELLS = (
    "adios", "hasta luego", "hasta pronto", "hasta manana", "hasta la proxima", "nos vemos",
    "chao", "chau", "goodbye", "bye", "see you", "take care",
    "gracias", "thank you", "thanks",  # thanks alone, once nothing is left, is the close
)  # fmt: skip
# Words that leave something still to do: a farewell with one of them is the model's to read.
_STILL_TO_DO = frozenset(
    "pero espera cambiar cambio otra otro cancelar mover duda pregunta "
    "but wait change another cancel move actually question".split()
)


def is_farewell(text: str) -> bool:
    """The candidate is closing: a goodbye or thanks, with no question and nothing still to
    change ("adiós, pero ¿puedo cambiar la hora?" is not one). Only read once the interview is
    booked, when thanks means the candidate is done. Pure; both languages."""
    if "?" in text:
        return False
    words = " ".join(_clauses(text))
    return _without(words, _FAREWELLS)[1] and _STILL_TO_DO.isdisjoint(words.split())


# ---- plain answers to a read-back ----------------------------------------------------------------

ReadbackAnswer = Literal["affirm", "deny", "skip"]

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
# ones ("todo", "está", "eso") only support them, so "todo" alone is not an answer. The phrases
# say yes with weak words only, or with words that are not yes-words on their own.
_YES_PHRASES = ("de acuerdo", "eso es", "asi es")
_YES_CORE = frozenset(
    {"si", "vale", "correcto", "bien", "perfecto", "exacto", "claro", "efectivamente"}
    | {"yes", "right", "correct", "fine", "good", "exactly", "yeah", "yep", "sure"}
)
_YES_WEAK = frozenset({"todo", "esta", "eso", "asi", "es", "lo", "all", "that", "thats", "is"})
# "Carry on" is its own answer: to an offer to go over a read-back it means "no need" (an informed
# skip), and it is checked before a no because "no hace falta" and "no need" start with one. A
# bare "no" never rides along: "No es correcto. Sigue." is a correction, so it is the model's.
_SKIP = (
    "no hace falta",
    "no es necesario",
    "no need",
    "carry on",
    "go on",
    "move on",
    "keep going",
    "skip",
    "sigue",
    "sigamos",
    "seguimos",
    "continua",
    "continuemos",
    "adelante",
)
_SKIP_ALONGSIDE = frozenset({"lets", "it", "please", "por", "favor", "ya"})
# Checked in order: the first whose phrase is found decides, and only what it allows may remain.
_PHRASE_ANSWERS: tuple[tuple[ReadbackAnswer, tuple[str, ...], frozenset[str]], ...] = (
    ("skip", _SKIP, _YES_CORE | _YES_WEAK | _SKIP_ALONGSIDE),
    ("deny", _DENY, frozenset()),
)
_FILLERS = frozenset(
    {"mhmm", "mhm", "mmm", "mm", "hmm", "eh", "ah", "uh", "um", "pues", "bueno", "ok", "okay"}
)


def answer_to_readback(text: str) -> ReadbackAnswer | None:
    """``affirm``, ``deny`` or ``skip`` (carry on without going over it) when the whole utterance
    is that plain answer (with fillers such as "mhmm"); ``None`` when anything else is said,
    which stays the model's to interpret ("sí, pero el teléfono es otro"). Pure; both languages."""
    words = " ".join(" ".join(_clauses(text)).split())
    for answer, phrases, alongside in _PHRASE_ANSWERS:
        rest, found = _without(words, phrases)
        if found:
            leftover = [w for w in rest.split() if w not in _FILLERS and w not in alongside]
            return answer if not leftover else None  # a plain word plus more: the model decides
    return "affirm" if _is_plain_yes(words) else None


def _without(words: str, phrases: tuple[str, ...]) -> tuple[str, bool]:
    """``words`` minus every whole-word occurrence of the phrases, and whether any was found."""
    rest, found = words, False
    for phrase in phrases:
        rest, hits = re.subn(rf"\b{re.escape(phrase)}\b", " ", rest)
        found = found or hits > 0
    return rest, found


def _is_plain_yes(words: str) -> bool:
    """Only yes-words and fillers, at least one core yes-word or yes phrase, any order. A
    negation is never a yes-word, so "no está todo bien" is not a yes."""
    rest, phrase = _without(words, _YES_PHRASES)
    left = [w for w in rest.split() if w not in _FILLERS]
    return all(w in _YES_CORE or w in _YES_WEAK for w in left) and (
        phrase or any(w in _YES_CORE for w in left)
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

    async def analyze(self, turn_id: TurnId, text: str, language: Language) -> SignalAnalysis:
        """The verdict and the tokens it cost; the tokens are reported even when the verdict
        is no signal, and are ``None`` only when the call never finished."""
        reply = _Reply()
        try:
            async with asyncio.timeout(self._deadline_seconds):
                await self._complete(text, language, reply)
            verdict = _Verdict.model_validate_json(_strip_fence("".join(reply.parts)))
        except (TimeoutError, ServiceError, ValidationError) as error:
            log.info("no signal for turn %s: %s", turn_id, type(error).__name__)
            return self._analysis(None, reply)
        return self._analysis(_signal(turn_id, text, language, verdict), reply)

    def _analysis(self, signal: Signal | None, reply: "_Reply") -> SignalAnalysis:
        return SignalAnalysis(signal=signal, usage=reply.usage, model_id=self._model.model_id)

    async def _complete(self, text: str, language: Language, reply: "_Reply") -> None:
        messages = (
            ModelMessage(role="system", content=prompts.load("classifier")),
            ModelMessage(role="user", content=f"language: {language}\ntext: {text}"),
        )
        deadline = datetime.now(UTC) + timedelta(seconds=self._deadline_seconds)
        async for event in self._model.stream(messages, (), deadline=deadline):
            if isinstance(event, ModelText):
                reply.parts.append(event.text)
            elif isinstance(event, ModelUsage):
                reply.usage = event


class _Reply:
    """What the classifier call streamed so far; kept outside the call so a verdict that
    fails to parse still reports the tokens it cost."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.usage: ModelUsage | None = None


def _signal(turn_id: TurnId, text: str, language: Language, verdict: _Verdict) -> Signal | None:
    """A verdict becomes a signal only when the candidate's own words back it."""
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
