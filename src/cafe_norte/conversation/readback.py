"""Going over a read-back the candidate cut (D39): its short parts.

A part is a slice of the read-back's own sentences, so what is gone over is the text that is
confirmed (D20); each part ends with the short check from ``prompts/brief.<language>.md``."""

from cafe_norte.conversation.brief import brief_intro, review_check
from cafe_norte.conversation.prompt import sentences
from cafe_norte.errors import Language

PART_SENTENCES = 2  # sentences of the read-back per part
PART_CHARACTERS = 160  # a part of two sentences stays under this (one longer sentence is alone)


def review_parts(presentation_text: str, language: Language) -> tuple[str, ...]:
    """The read-back without its intro and closing question, in parts short enough to hear to
    the end, each followed by the check. A one-sentence read-back is one part."""
    said = sentences(presentation_text)
    if said and said[-1].endswith("?"):
        said = said[:-1]
    if said and said[0] == brief_intro(language):
        said = said[1:]
    groups: list[list[str]] = []
    for sentence in said:
        last = groups[-1] if groups else None
        if (
            last is not None
            and len(last) < PART_SENTENCES
            and len(" ".join([*last, sentence])) <= PART_CHARACTERS
        ):
            last.append(sentence)
        else:
            groups.append([sentence])
    check = review_check(language)
    return tuple(" ".join([*group, check]) for group in groups) or (presentation_text,)
