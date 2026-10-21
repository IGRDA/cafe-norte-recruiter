"""Lexical ranking: a tokenizer for Spanish and English text and BM25 (Okapi) over it.

Thirty lines own the whole dependency: the corpus is seventy chunks, and a scorer this small
is easier to read than to configure."""

import math
import re
import unicodedata
from collections import Counter

K1 = 1.5
B = 0.75

STOPWORDS = frozenset(
    "de la el en y a los las del que es un una por con para se su al lo como mas o the of to "
    "is in and for do i".split()
)
_WORD = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> tuple[str, ...]:
    """Lowercase, accents stripped, letters and digits only, no one-letter tokens or stopwords."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return tuple(t for t in _WORD.findall(ascii_text.lower()) if len(t) > 1 and t not in STOPWORDS)


class BM25:
    """Scores are comparable within one corpus only; ``None`` is never returned, zero is."""

    def __init__(self, documents: tuple[tuple[str, ...], ...]) -> None:
        self._counts = tuple(Counter(d) for d in documents)
        self._lengths = tuple(len(d) for d in documents)
        self._average = (sum(self._lengths) / len(documents)) if documents else 0.0
        frequency: Counter[str] = Counter()
        for count in self._counts:
            frequency.update(count.keys())
        n = len(documents)
        self._idf = {t: math.log(1 + (n - df + 0.5) / (df + 0.5)) for t, df in frequency.items()}

    def scores(self, query: tuple[str, ...]) -> tuple[float, ...]:
        return tuple(self._score(query, i) for i in range(len(self._counts)))

    def _score(self, query: tuple[str, ...], i: int) -> float:
        count, length = self._counts[i], self._lengths[i]
        norm = K1 * (1 - B + B * length / self._average) if self._average else K1
        total = 0.0
        for term in query:
            tf = count.get(term, 0)
            if tf:
                total += self._idf[term] * tf * (K1 + 1) / (tf + norm)
        return total
