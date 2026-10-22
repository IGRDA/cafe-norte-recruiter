"""A held-out set for the signals suite, written by another model from a fixed grid.

The development set (``turns.yaml``) was written by the same hand that wrote the questions;
tuning on it and scoring on it would flatter every system. Here a chat model writes the
candidate's words for each cell of ``GRID`` (session language × kind × sentiment), and the
labels are the cell's, never the model's. A second call checks every line against its cell
and drops the ones that do not fit; nothing is relabelled, by the model or by hand. The file is
generated once, committed and not edited.

``uv run python -m evals.signals_generate --yes`` (needs ``OPENAI_API_KEY``)."""

import argparse
import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cafe_norte.domain.contracts import Sentiment
from cafe_norte.errors import Language
from cafe_norte.model.contracts import Model, ModelMessage, ModelText
from cafe_norte.model.select import model_from_env
from evals.contracts import LanguageKind, SignalCase

ROOT = Path(__file__).resolve().parents[1]
HELDOUT = ROOT / "evals" / "cases" / "signals" / "heldout.yaml"
WRITER = "openai/gpt-4.1"
CALL_SECONDS = 60.0
SLACK = 2  # extra lines per cell, so a dropped line rarely leaves the cell short

# (kind, sentiment, how many) per session language.
GRID: tuple[tuple[LanguageKind, Sentiment, int], ...] = (
    ("stay", "neutral", 8),
    ("stay", "positive", 4),
    ("stay", "frustrated", 5),
    ("stay", "uncertain", 5),
    ("explicit", "neutral", 2),
    ("explicit", "frustrated", 1),
    ("explicit", "positive", 1),
    ("indirect", "neutral", 3),
    ("indirect", "uncertain", 2),
    ("written_other", "neutral", 3),
    ("mention", "neutral", 4),
    ("borrowed", "neutral", 4),
)

NAMES: dict[Language, str] = {"es": "Spanish", "en": "English"}

KIND_TEXT: dict[LanguageKind, str] = {
    "stay": "an ordinary reply in {session}, with no request and no mention of any language",
    "explicit": "an explicit request to continue in {other} instead of {session}, with a request "
    "word (please, can we, I'd prefer); written in {session} or in {other}",
    "indirect": "says the candidate cannot speak or follow {session} well (their {session} is "
    "poor, they only speak {other}), without directly asking to switch; written in {session} or "
    "in {other}",
    "written_other": "an ordinary answer to Ana's question written entirely in {other}, with no "
    "request and no mention of any language",
    "mention": "written in {session}; names a language without asking to leave {session}: asks "
    "whether {other} is needed for the job, says they studied {other}, or turns down an offer "
    "to switch to {other}",
    "borrowed": "an ordinary reply in {session} with one or two borrowed words from {other} "
    "(ok, sorry, thanks, vale, gracias); no request and no mention of any language",
}

SENTIMENT_TEXT: dict[Sentiment, str] = {
    "neutral": "a neutral tone: plain answers or questions, no enthusiasm, no annoyance, no doubt",
    "positive": "clear enthusiasm or thanks",
    "frustrated": "annoyance, impatience, sarcasm, or feeling misunderstood or made to repeat",
    "uncertain": "hesitation, doubt or confusion about what to answer",
}

SYSTEM = """You write test data: short lines a job candidate says to Ana, a voice and chat \
recruiting assistant for Café Norte, a coffee shop chain in Madrid hiring baristas. Ana asks \
for the candidate's name, phone, work permit, days and shifts, hours a week, start date and \
experience, answers questions about the job and books an interview.

Write varied, realistic lines: some typed with punctuation, some like a voice transcript \
(lowercase, no punctuation, fillers). Never repeat a line. Never explain. Reply with one JSON \
object and nothing else: {"cases": [{"ana": "<Ana's previous sentence, in the session \
language>", "text": "<the candidate's line>"}]}"""


class _Line(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    ana: str = Field(min_length=1)
    text: str = Field(min_length=1)


class _Fits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    fits: tuple[bool, ...]


class _Lines(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    cases: tuple[_Line, ...]


VERIFY = """You check test data. For each numbered candidate line, answer true only if the \
line clearly is {cell}. Reply with one JSON object and nothing else: {{"fits": [true, false, \
...]}}, one boolean per line, in order."""


def cell(language: Language, kind: LanguageKind, sentiment: Sentiment) -> str:
    """The cell's description, with the languages named: the writer and the checker read it."""
    other: Language = "en" if language == "es" else "es"
    kind_text = KIND_TEXT[kind].format(session=NAMES[language], other=NAMES[other])
    return f"{kind_text}, said with {SENTIMENT_TEXT[sentiment]}"


def request(language: Language, kind: LanguageKind, sentiment: Sentiment, count: int) -> str:
    return (
        f"Session language: {NAMES[language]}; Ana speaks {NAMES[language]}.\n"
        f"Write exactly {count} different candidate lines. Each line is "
        f"{cell(language, kind, sentiment)}."
    )


async def generate(
    model: Model, grid: Sequence[tuple[LanguageKind, Sentiment, int]] = GRID
) -> list[SignalCase]:
    """Per cell and session language, one call writes ``count + SLACK`` lines and a second
    call checks each against the cell; the first ``count`` that fit are kept, with labels from
    the cell. A line is dropped, never relabelled. A malformed reply, or a cell with no line
    that fits, raises."""
    cases: list[SignalCase] = []
    languages: tuple[Language, ...] = ("es", "en")
    for language in languages:
        for kind, sentiment, count in grid:
            written = await _ask(model, request(language, kind, sentiment, count + SLACK))
            fits = await _check(model, cell(language, kind, sentiment), written)
            lines = [line for line, ok in zip(written, fits, strict=False) if ok]
            if not lines:
                raise ValueError(f"{language}/{kind}/{sentiment}: no line fits")
            other: Language = "en" if language == "es" else "es"
            reply: Language = (
                other if kind in {"explicit", "indirect", "written_other"} else language
            )
            for line in lines[:count]:
                cases.append(
                    SignalCase(
                        id=f"h-{language}-{len(cases) + 1:03d}",
                        session_language=language,
                        ana=line.ana,
                        text=line.text,
                        sentiment=sentiment,
                        reply_language=reply,
                        kind=kind,
                    )
                )
    return cases


async def _complete(model: Model, system: str, content: str) -> str:
    messages = (
        ModelMessage(role="system", content=system),
        ModelMessage(role="user", content=content),
    )
    deadline = datetime.now(UTC) + timedelta(seconds=CALL_SECONDS)
    parts = [
        e.text
        async for e in model.stream(messages, (), deadline=deadline)
        if isinstance(e, ModelText)
    ]
    raw = "".join(parts).strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
    return raw


async def _ask(model: Model, content: str) -> tuple[_Line, ...]:
    raw = await _complete(model, SYSTEM, content)
    try:
        return _Lines.model_validate_json(raw).cases
    except ValidationError as error:
        raise ValueError(f"malformed reply: {raw[:200]}") from error


async def _check(model: Model, description: str, lines: Sequence[_Line]) -> list[bool]:
    numbered = "\n".join(
        f"{i}. Ana: {line.ana} | Candidate: {line.text}" for i, line in enumerate(lines, 1)
    )
    raw = await _complete(model, VERIFY.format(cell=description), numbered)
    try:
        return list(_Fits.model_validate_json(raw).fits)
    except ValidationError as error:
        raise ValueError(f"malformed check: {raw[:200]}") from error


def dump(cases: Sequence[SignalCase], writer: str) -> str:
    header = (
        f"# Held-out signals set, generated by {writer} with evals/signals_generate.py on "
        f"{datetime.now(UTC).date().isoformat()}.\n"
        "# Labels come from the generation grid, not from the model or a reader. Not edited by "
        "hand.\n"
    )
    rows = [json.dumps(c.model_dump(exclude_defaults=False), ensure_ascii=False) for c in cases]
    return header + "".join(f"- {row}\n" for row in rows)


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals.signals_generate")
    parser.add_argument("--writer", default=WRITER)
    parser.add_argument("--out", default=str(HELDOUT))
    parser.add_argument("--yes", action="store_true", help="spend: about 48 calls")
    args = parser.parse_args(argv)
    total = 2 * sum(count for _, _, count in GRID)
    print(f"held-out: up to {total} cases in {4 * len(GRID)} calls to {args.writer}")
    if not args.yes:
        print("Nothing was called: add --yes to generate.")
        return 0
    model = model_from_env(args.writer, env if env is not None else os.environ)
    cases = asyncio.run(generate(model))
    Path(args.out).write_text(dump(cases, args.writer))
    yaml.safe_load(Path(args.out).read_text())  # the file must load as the suite reads it
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
