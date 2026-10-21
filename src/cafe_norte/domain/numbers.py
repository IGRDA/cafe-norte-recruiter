"""Whether a number appears in the candidate's words, as digits or spoken (es, en). Pure.

Speech-to-text writes "treinta y cinco" as often as "35"; a typed answer may say "35h". The
check guards the rule that no value is ever guessed into a field: a number the model saves
must be one the candidate said."""

import re
import unicodedata

from cafe_norte.errors import Language

_ES_UNITS = (
    "cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince "
    "dieciseis diecisiete dieciocho diecinueve veinte veintiuno veintidos veintitres "
    "veinticuatro veinticinco veintiseis veintisiete veintiocho veintinueve"
).split()
_ES_TENS = {
    3: "treinta",
    4: "cuarenta",
    5: "cincuenta",
    6: "sesenta",
    7: "setenta",
    8: "ochenta",
    9: "noventa",
}
_EN_UNITS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen"
).split()
_EN_TENS = {
    2: "twenty",
    3: "thirty",
    4: "forty",
    5: "fifty",
    6: "sixty",
    7: "seventy",
    8: "eighty",
    9: "ninety",
}


def spelled(n: int, language: Language) -> str:
    """``35`` → ``treinta y cinco`` / ``thirty-five``, for 0 to 99, without accents."""
    if not 0 <= n <= 99:
        raise ValueError(f"spelled() covers 0 to 99, not {n}")
    if language == "es":
        if n < 30:
            return _ES_UNITS[n]
        tens, unit = divmod(n, 10)
        return _ES_TENS[tens] + (f" y {_ES_UNITS[unit]}" if unit else "")
    if n < 20:
        return _EN_UNITS[n]
    tens, unit = divmod(n, 10)
    return _EN_TENS[tens] + (f"-{_EN_UNITS[unit]}" if unit else "")


def mentions_number(text: str, n: int) -> bool:
    """``n`` written as a whole number in ``text`` ("35", "35h"), or spoken in either
    language ("treinta y cinco", "thirty five"). "135" does not mention 35."""
    folded = plain(text)
    if re.search(rf"(?<!\d){n}(?!\d)", folded):
        return True
    if not 0 <= n <= 99:
        return False
    words = " ".join(folded.replace("-", " ").split())
    return any(
        re.search(rf"\b{re.escape(spelled(n, language).replace('-', ' '))}\b", words)
        and not _longer_number_follows(words, spelled(n, language).replace("-", " "))
        for language in ("es", "en")
    )


def _longer_number_follows(words: str, spoken: str) -> bool:
    """ "treinta" inside "treinta y cinco" is thirty-five, not thirty."""
    return bool(
        re.search(
            rf"\b{re.escape(spoken)} (y )?(uno|dos|tres|cuatro|cinco|seis|siete|"
            rf"ocho|nueve|one|two|three|four|five|six|seven|eight|nine)\b",
            words,
        )
    )


def plain(text: str) -> str:
    """Case-folded, without accents: how every word list in ``domain`` is matched."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))
