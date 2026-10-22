"""Prompt building and the sentence splitting a streamed answer goes through."""

from hypothesis import given
from hypothesis import strategies as st

from cafe_norte.conversation.prompt import clean_sentence, sentences, split_sentences


def test_sentences_split_at_an_opening_mark_or_capital_without_a_space() -> None:
    done, rest = split_sentences("¿Tienes permiso?¿Qué días puedes?(nota) Sí. Y más")
    assert done == ["¿Tienes permiso?", "¿Qué días puedes?", "(nota) Sí."]
    assert rest == "Y más"
    # The model sometimes writes the candidate's answer right after its own question.
    done, rest = split_sentences("¿Te interesa el puesto?Sí, me interesa.Él también. 3.5 horas")
    assert done == ["¿Te interesa el puesto?", "Sí, me interesa.", "Él también."]
    assert rest == "3.5 horas"


@given(st.text(alphabet="Hola. ¿Qué tal?¡Sí! (nota) 3.5 horas…\n", max_size=60), st.data())
def test_any_chunking_of_a_stream_says_the_same_sentences_as_the_whole_text(
    text: str, data: st.DataObject
) -> None:
    """How the runtime reads a stream: split what has come, keep the rest for the next chunk."""
    cuts = sorted(data.draw(st.lists(st.integers(0, len(text)), max_size=6)))
    chunks = [text[a:b] for a, b in zip([0, *cuts], [*cuts, len(text)], strict=True)]

    said: list[str] = []
    rest = ""
    for chunk in chunks:
        done, rest = split_sentences(rest + chunk)
        said += done
    tail = clean_sentence(rest)

    assert said + ([tail] if tail else []) == sentences(text)


@given(st.text(max_size=60))
def test_a_clean_sentence_is_already_clean(text: str) -> None:
    once = clean_sentence(text)
    assert clean_sentence(once) == once
