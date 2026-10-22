"""The runtime's word-for-word texts in a language without reviewed files.

The English template files (``opening``, ``resume``, ``brief``, ``controls``, ``ui``,
``voice``) are worded once per process and language by the model, and checked: a table keeps
every key and, in every row, exactly the ``{placeholders}`` of its source; a prose file keeps
its placeholders. A file that fails the check, or does not come back in time, stays English.
The facts never pass through the model: the runtime fills the placeholders afterwards, as it
does for Spanish and English."""

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta

from cafe_norte.conversation import prompts
from cafe_norte.errors import TABLED, Language
from cafe_norte.model.contracts import Model, ModelMessage, ModelText

log = logging.getLogger(__name__)

WORDED_FILES = ("opening", "resume", "brief", "controls", "ui", "voice")
TABLES = frozenset({"brief", "controls", "ui", "voice"})
WORDING_SECONDS = 20.0  # per file; the first turn in a new language waits for it, once
_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")

INSTRUCTIONS = (
    "Translate the text below from English into {english} ({native}) for a recruiting "
    "assistant who speaks to job candidates informally and warmly. Keep every {{placeholder}} "
    "exactly as written, untranslated. {shape} Reply with the translation only."
)
TABLE_SHAPE = (
    "Each line is `key: sentence`: keep every key and the colon unchanged and translate only "
    "the sentence."
)
PROSE_SHAPE = "Keep the sentences in the same order."


def source(name: str) -> str:
    """The English file without its comment and prose lines: what the model is given."""
    text = prompts.load(name, "en")
    if name not in TABLES:
        return text.strip()
    rows = prompts.table(name, "en")
    return "\n".join(f"{key}: {sentence}" for key, sentence in rows.items())


def keeps_shape(name: str, original: str, worded: str) -> bool:
    """The check a worded file must pass: same keys and the same placeholders per row for a
    table, the same placeholders for prose. Pure."""
    if name not in TABLES:
        return sorted(_PLACEHOLDER.findall(original)) == sorted(_PLACEHOLDER.findall(worded))
    before = _rows(original)
    after = _rows(worded)
    return before.keys() == after.keys() and all(
        sorted(_PLACEHOLDER.findall(before[k])) == sorted(_PLACEHOLDER.findall(after[k]))
        and after[k].strip()
        for k in before
    )


def _rows(text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(": ")
        if sep and " " not in key.strip():
            rows[key.strip()] = value.strip()
    return rows


class Wording:
    """Words the template files for one language at a time, once per process; a second
    session in the same language finds them ready. Concurrent first uses share one call."""

    def __init__(self, model: Model, *, seconds: float = WORDING_SECONDS) -> None:
        self._model = model
        self._seconds = seconds
        self._ready: dict[Language, asyncio.Task[None]] = {}

    async def prepare(self, language: Language) -> None:
        if language in TABLED:
            return
        task = self._ready.get(language)
        if task is None:
            task = asyncio.ensure_future(self._word_all(language))
            self._ready[language] = task
        await asyncio.shield(task)

    async def _word_all(self, language: Language) -> None:
        await asyncio.gather(*(self._word(name, language) for name in WORDED_FILES))

    async def _word(self, name: str, language: Language) -> None:
        original = source(name)
        info = prompts.languages()[language]
        instructions = INSTRUCTIONS.format(
            english=info.english,
            native=info.native,
            shape=TABLE_SHAPE if name in TABLES else PROSE_SHAPE,
        )
        messages = (
            ModelMessage(role="system", content=instructions),
            ModelMessage(role="user", content=original),
        )
        deadline = datetime.now(UTC) + timedelta(seconds=self._seconds)
        try:
            async with asyncio.timeout(self._seconds):
                parts = [
                    e.text
                    async for e in self._model.stream(messages, (), deadline=deadline)
                    if isinstance(e, ModelText)
                ]
        except Exception as error:  # a failed wording is English, never a failed turn
            log.warning("wording %s in %s failed: %s", name, language, type(error).__name__)
            return
        worded = "".join(parts).strip()
        if not keeps_shape(name, original, worded):
            log.warning(
                "wording %s in %s dropped a key or placeholder: English kept", name, language
            )
            return
        prompts.use_worded(name, language, worded)
