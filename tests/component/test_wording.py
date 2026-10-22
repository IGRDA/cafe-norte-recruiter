"""Fixed texts in a language without reviewed files: the model words the English
templates once per language, a wording that loses a key or a placeholder stays English, and
the facts are filled in by the runtime afterwards, never by the model."""

from collections.abc import Iterator, Sequence

import pytest

from cafe_norte.conversation import prompts
from cafe_norte.conversation.brief import field_readback
from cafe_norte.conversation.contracts import AssistantText
from cafe_norte.conversation.wording import Wording, keeps_shape
from cafe_norte.model.contracts import ModelEvent, ModelMessage, ModelText, ToolSchema
from cafe_norte.model.fake import FakeModel
from cafe_norte.persistence.memory import MemoryStore
from tests.support.app import build_runtime
from tests.support.builders import NOW, session_state
from tests.support.harness import STOP


@pytest.fixture(autouse=True)
def nothing_worded() -> Iterator[None]:
    """Worded texts live for the process; every test starts and ends without them."""
    prompts._WORDED.clear()
    yield
    prompts._WORDED.clear()


def french(messages: tuple[ModelMessage, ...], _: tuple[ToolSchema, ...]) -> Sequence[ModelEvent]:
    """A stand-in translator: marks every sentence, keeps keys and placeholders."""
    text = messages[-1].content
    rows = []
    for line in text.splitlines():
        key, sep, value = line.partition(": ")
        rows.append(f"{key}: [fr] {value}" if sep and " " not in key else f"[fr] {line}")
    return [ModelText(text="\n".join(rows)), STOP]


def careless(messages: tuple[ModelMessage, ...], _: tuple[ToolSchema, ...]) -> Sequence[ModelEvent]:
    """A translator that drops every placeholder."""
    return [ModelText(text=messages[-1].content.replace("{", "").replace("}", "")), STOP]


def test_the_shape_check() -> None:
    assert keeps_shape("brief", "phone: Tu número es {value}.", "phone: Ton numéro est {value}.")
    assert not keeps_shape("brief", "phone: Es {value}.", "phone: C'est le numéro.")  # fact lost
    assert not keeps_shape("brief", "phone: Es {value}.", "telephone: C'est {value}.")  # key lost
    assert not keeps_shape("brief", "a: x {v}.\nb: y.", "a: x {v}.")  # a row dropped
    assert keeps_shape("opening", "Hola, soy Ana.", "Bonjour, je suis Ana.")
    assert not keeps_shape("opening", "En {store}.", "À la boutique.")


async def test_a_language_is_worded_once_and_its_facts_are_the_runtimes() -> None:
    model = FakeModel([], policy=french)
    wording = Wording(model)
    await wording.prepare("fr")
    await wording.prepare("fr")  # the second session in French finds it ready
    assert len(model.calls) == 6  # six files, one call each, once
    said = field_readback("contact_phone", "612345678", "fr")
    assert said.startswith("[fr]") and "345 678" in said  # worded around the runtime's value


async def test_a_wording_that_loses_a_placeholder_stays_english() -> None:
    await Wording(FakeModel([], policy=careless)).prepare("fr")
    assert field_readback("contact_phone", "612345678", "fr") == field_readback(
        "contact_phone", "612345678", "en"
    )


async def test_spanish_and_english_are_never_worded() -> None:
    model = FakeModel([], policy=french)
    await Wording(model).prepare("es")
    await Wording(model).prepare("en")
    assert not model.calls


async def test_a_french_session_opens_with_the_worded_greeting() -> None:
    store = MemoryStore()
    state = session_state().model_copy(update={"language": "fr"})
    await store.sessions.create(state, access_hash="")
    runtime = build_runtime(
        model=FakeModel([]),
        store=store,
        clock=lambda: NOW,
        wording=Wording(FakeModel([], policy=french)),
    )
    events = [e async for e in runtime.open_session(state.session_id)]
    said = [e.text for e in events if isinstance(e, AssistantText)]
    assert said and all(s.startswith("[fr]") for s in said)
