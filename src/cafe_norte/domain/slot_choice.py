"""Which interview slot a candidate's words mean (D41). Pure; both languages, no language
argument: the words of one language never collide with the other's in a slot answer.

``read_slot_words`` says what was said (an ordinal, a weekday, a day of the month, a relative
day, a clock time, a part of the day) and what was left over; ``choose_slot`` holds those words
against the slots just offered. As with a plain yes (D35), only an answer that is all about the
slot is a choice: one word that is neither a slot word nor the talk around a choice ("me va
bien", "mejor", "sí") makes it the model's, which covers refusals ("no, ninguno") and questions
("¿dura treinta minutos?") alike. Nothing is guessed: a feature that was not said does not
filter."""

import re
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from typing import Literal

from cafe_norte.domain.calendar import HORIZON_DAYS
from cafe_norte.domain.contracts import Frozen
from cafe_norte.domain.numbers import plain, spelled

LAST = -1  # "el último", "the last one"
Part = Literal["morning", "afternoon"]
Clock = tuple[int, int | None]  # an hour, and the minute when it was said


class SlotWords(Frozen):
    """What the words say; an empty set or ``None`` means "not said"."""

    positions: frozenset[int] = frozenset()  # 1-based, or LAST
    weekdays: frozenset[int] = frozenset()  # Monday is 0
    days: frozenset[int] = frozenset()  # day of the month
    offsets: frozenset[int] = frozenset()  # days from today: hoy 0, mañana 1
    times: frozenset[Clock] = frozenset()
    part: Part | None = None
    rest: str = ""  # the words nothing above explained, normalised


class Chosen(Frozen):
    """Exactly one offered slot fits; ``index`` into the offer as it was spoken."""

    index: int


class Ambiguous(Frozen):
    """Two or more offered slots fit, in offer order: ask which."""

    indices: tuple[int, ...]


class NoMatch(Frozen):
    """Slot words that fit nothing offered; ``day`` is the day they name inside the calendar's
    horizon, when they name one, so the offer can be made again for it."""

    day: date | None


class NotAChoice(Frozen):
    """No slot words, or words besides them that are not the talk around a choice."""


SlotChoice = Chosen | Ambiguous | NoMatch | NotAChoice


# ---- vocabulary: lower case, no accents --------------------------------------------------------


def _counted(words: str, start: int) -> dict[str, int]:
    """``"lunes martes"`` from 0 → ``{"lunes": 0, "martes": 1}``."""
    return {word: n for n, word in enumerate(words.split(), start=start)}


_WEEKDAYS = {
    **_counted("lunes martes miercoles jueves viernes sabado domingo", 0),
    **_counted("monday tuesday wednesday thursday friday saturday sunday", 0),
}
_MONTHS = (
    "enero febrero marzo abril mayo junio julio agosto septiembre setiembre octubre noviembre "
    "diciembre january february march april may june july august september october november "
    "december"
).split()
_POSITIONS = {
    **dict.fromkeys(("primero", "primer", "primera", "first"), 1),
    **dict.fromkeys(("segundo", "segunda", "second"), 2),
    **dict.fromkeys(("tercero", "tercer", "tercera", "third"), 3),
    **dict.fromkeys(("ultimo", "ultima", "last"), LAST),
}
_ORDINAL_UNITS = _counted("first second third fourth fifth sixth seventh eighth ninth", 1)
_ORDINAL_DAYS = {  # English ordinals that cannot be a position
    **_counted(
        "fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth "
        "fifteenth sixteenth seventeenth eighteenth nineteenth twentieth",
        4,
    ),
    "thirtieth": 30,
}
_MINUTES = {"media": 30, "cuarto": 15, "veinticinco": 25, "veinte": 20, "diez": 10, "cinco": 5}
_MINUTE_WORDS = {
    "fifteen": 15,
    "quince": 15,
    "thirty": 30,
    "treinta": 30,
    "forty five": 45,
    "cuarenta y cinco": 45,
    "forty": 40,
    "cuarenta": 40,
    "fifty": 50,
    "cincuenta": 50,
}
# Joining words that say nothing: what is left of an answer after them is the caller's.
_GLUE = frozenset(
    "el la los las un una de del al a en para por favor please the at on for of o or y and one "
    "slot hueco opcion option day dia hora time around about sobre hacia this esta este que".split()
)
# What people say around a choice, kept in ``rest`` (a yes in it still counts) but no reason to
# leave the answer to the model. Anything else is: "no", "ninguno", "otro", "presencial"...
_CHOICE_TALK = frozenset(
    "si vale exacto perfecto claro correcto genial estupendo bien va viene me mejor prefiero "
    "quiero puedo podria gracias eso es asi acuerdo venga entonces hay algo tienes tiene pues "
    "bueno "
    "yes yeah yep sure ok okay great perfect fine good works that thats sounds right correct "
    "exactly i id like prefer want take thanks thank you is there anything have do then lets "
    "suits better best can could will ill go with eh mm mhm mhmm hmm um uh so well".split()
)
_AFTERNOON_FROM = 14  # a slot at 14:00 or later is "de la tarde"


def _numbers() -> dict[str, int]:
    """Every spoken number 1 to 59 in both languages, from the one table ``numbers`` owns."""
    words = {
        spelled(n, language).replace("-", " "): n for language in ("es", "en") for n in range(1, 60)
    }
    del words["one"]  # "the second one" is not a one
    return words


_NUMBERS = _numbers()


def _any(words: list[str] | dict[str, int] | tuple[str, ...]) -> str:
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


_NUM = rf"(\d{{1,2}}|{_any(_NUMBERS)})"  # no boundaries: "5pm" is a number and a suffix
_MONTH = _any(_MONTHS)

# ---- patterns, tried in this order -------------------------------------------------------------


def _p(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


_YEAR = _p(r"\b(?:19|20)\d{2}\b")
_CLOCK = _p(r"\b(\d{1,2})\x01(\d{2})\b")
_HOUR_AND = _p(rf"\b{_NUM}\s+y\s+({_any(_MINUTES)})\b")
_HOUR_LESS = _p(
    rf"\b{_NUM}\s+menos\s+({_any(('cuarto', 'veinticinco', 'veinte', 'diez', 'cinco'))})\b"
)
_ON_THE_HOUR = _p(rf"\b{_NUM}\s+(?:en\s+punto|oclock)\b")
_HALF_PAST = _p(rf"\b(half|quarter)\s+(past|to)\s+{_NUM}\b")
_HOUR_MINUTES = _p(rf"\b{_NUM}\s+({_any(_MINUTE_WORDS)})\b")
_AM_PM = _p(rf"\b{_NUM}\s*(am|pm)\b")
_HOUR_H = _p(r"\b(\d{1,2})\s?h\b")
_CUED_HOUR = _p(rf"\b(?:a\s+las|sobre\s+las|hacia\s+las|las|at|around|about)\s+{_NUM}\b")
_ORDINAL_OF_MONTH = _p(
    rf"\b(primero|primer|segundo|tercero|tercer|first|second|third)\s+(?:de|of)\s+(?={_MONTH}\b)"
)
_TENS_ORDINAL = _p(rf"\b(twenty|thirty)\s+({_any(_ORDINAL_UNITS)})\b")
_BARE_ORDINAL = _p(rf"\b({_any(_ORDINAL_DAYS)})\b")
_THIS_PART = _p(r"\b(?:esta|this)\s+(manana|tarde|noche|morning|afternoon|evening)\b")
_PART_OF_DAY = _p(
    r"\b(?:(?:por|de|en)\s+)?la\s+(manana|tarde|noche)\b|\b(morning|afternoon|evening|night)\b"
)
_AM_PM_WORD = _p(r"\b(am|pm)\b")
_AFTER_TOMORROW = _p(r"\b(?:pasado\s+manana|day\s+after\s+tomorrow)\b")
_TOMORROW = _p(r"\b(?:manana|tomorrow)\b")
_TODAY = _p(r"\b(?:hoy|today)\b")
_WEEKDAY = _p(rf"\b({_any(_WEEKDAYS)})\b")
_POSITION = _p(rf"\b({_any(_POSITIONS)})\b")
_DAY = _p(rf"\b{_NUM}(?:st|nd|rd|th|o)?\b")
_MONTH_NAME = _p(rf"\b(?:{_MONTH})\b")


def _normal(text: str) -> str:
    """Lower case, no accents or apostrophes, words and digits only; a clock's colon or point
    between digits is kept as \\x01 so "10:30" survives and a full stop does not."""
    spaced = plain(text).replace("'", "").replace("’", "")
    spaced = re.sub(r"\b([ap])\.\s?m\b\.?", r"\1m", spaced)  # "10:30 a.m."
    clocked = re.sub(r"(?<=\d)[:.](?=\d)", "\x01", spaced)
    return " " + " ".join(re.sub(r"[^a-z0-9\x01]+", " ", clocked).split()) + " "


def _n(token: str) -> int:
    return int(token) if token.isdigit() else _NUMBERS[token]


def _clock(hour: int, minute: int | None) -> Clock | None:
    return (hour, minute) if 0 <= hour <= 23 and (minute is None or 0 <= minute <= 59) else None


def _day(day: int) -> int | None:
    return day if 1 <= day <= 31 else None


class _Scan:
    """The text with what has been read taken out of it, pass after pass."""

    def __init__(self, text: str) -> None:
        self.text = _normal(text)

    def eat[T](
        self, pattern: re.Pattern[str], read: Callable[[re.Match[str]], T | None]
    ) -> list[T]:
        """Take every match ``read`` accepts out of the text and return what it read; a match
        ``read`` refuses stays where it is."""
        found: list[T] = []

        def take(match: re.Match[str]) -> str:
            value = read(match)
            if value is None:
                return match.group(0)
            found.append(value)
            return " "

        self.text = pattern.sub(take, self.text)
        return found


def read_slot_words(text: str) -> SlotWords:
    """What ``text`` says about a slot. The passes run from the most specific phrase to the
    least ("diez y media" before "diez", "la mañana" before "mañana"), each taking what it
    reads out of the text so that no word is read twice."""
    scan = _Scan(text)
    scan.text = re.sub(r"\bla una\b", "las uno", scan.text)  # "a la una" is one o'clock
    scan.eat(_YEAR, lambda m: True)

    times: set[Clock] = set()
    parts: set[Part] = set()
    times.update(scan.eat(_CLOCK, lambda m: _clock(int(m[1]), int(m[2]))))
    times.update(scan.eat(_HOUR_AND, lambda m: _clock(_n(m[1]), _MINUTES[m[2]])))
    times.update(scan.eat(_HOUR_LESS, lambda m: _before(_n(m[1]), 60 - _MINUTES[m[2]])))
    times.update(scan.eat(_ON_THE_HOUR, lambda m: _clock(_n(m[1]), 0)))
    times.update(scan.eat(_HALF_PAST, _half_past))
    times.update(scan.eat(_HOUR_MINUTES, lambda m: _clock(_n(m[1]), _MINUTE_WORDS[m[2]])))
    for clock, suffix in scan.eat(_AM_PM, _am_pm):
        times.add(clock)
        parts.add("morning" if suffix == "am" else "afternoon")
    times.update(scan.eat(_HOUR_H, lambda m: _clock(int(m[1]), None)))
    times.update(scan.eat(_CUED_HOUR, lambda m: _clock(_n(m[1]), None)))

    days: set[int] = set()
    days.update(scan.eat(_ORDINAL_OF_MONTH, lambda m: _POSITIONS[m[1]]))
    days.update(
        scan.eat(
            _TENS_ORDINAL, lambda m: _day((20 if m[1] == "twenty" else 30) + _ORDINAL_UNITS[m[2]])
        )
    )
    days.update(scan.eat(_BARE_ORDINAL, lambda m: _ORDINAL_DAYS[m[1]]))

    offsets: set[int] = set()
    for name in scan.eat(_THIS_PART, lambda m: m[1]):  # "esta mañana" is today, not tomorrow
        parts.add(_part(name))
        offsets.add(0)
    for name in scan.eat(_PART_OF_DAY, lambda m: m[1] or m[2]):
        parts.add(_part(name))
    for word in scan.eat(_AM_PM_WORD, lambda m: m[1]):
        parts.add("morning" if word == "am" else "afternoon")

    offsets.update(scan.eat(_AFTER_TOMORROW, lambda m: 2))
    offsets.update(scan.eat(_TOMORROW, lambda m: 1))
    offsets.update(scan.eat(_TODAY, lambda m: 0))
    weekdays = set(scan.eat(_WEEKDAY, lambda m: _WEEKDAYS[m[1]]))
    positions = set(scan.eat(_POSITION, lambda m: _POSITIONS[m[1]]))
    days.update(scan.eat(_DAY, lambda m: _day(_n(m[1]))))
    scan.eat(_MONTH_NAME, lambda m: True)

    rest = " ".join(w for w in scan.text.replace("\x01", " ").split() if w not in _GLUE)
    return SlotWords(
        positions=frozenset(positions),
        weekdays=frozenset(weekdays),
        days=frozenset(days),
        offsets=frozenset(offsets),
        times=frozenset(times),
        part=next(iter(parts)) if len(parts) == 1 else None,
        rest=rest,
    )


def _part(name: str) -> Part:
    return "morning" if name in {"manana", "morning"} else "afternoon"


def _before(hour: int, minute: int) -> Clock | None:
    """ "Once menos cuarto": a quarter of an hour before eleven."""
    return _clock(hour - 1, minute) if hour >= 1 else None


def _half_past(match: re.Match[str]) -> Clock | None:
    kind, direction, hour = match[1], match[2], _n(match[3])
    if direction == "to":
        return _before(hour, 45) if kind == "quarter" else None
    return _clock(hour, 30 if kind == "half" else 15)


def _am_pm(match: re.Match[str]) -> tuple[Clock, str] | None:
    clock = _clock(_n(match[1]), None)
    return None if clock is None else (clock, match[2])


# ---- choosing ----------------------------------------------------------------------------------


def choose_slot(
    words: SlotWords,
    offered: Sequence[datetime],
    *,
    today: date,
    shortlist: tuple[int, ...] = (),
) -> SlotChoice:
    """Hold ``words`` against the ``offered`` start times (local, in the order they were
    spoken). Each feature said is a filter and the filters intersect; the values of one
    feature are alternatives. A ``shortlist`` left by an earlier ambiguous answer narrows the
    matches when it keeps any of them; when it keeps none, the words left it, and it is
    dropped."""
    if not _says_a_slot(words) or not _CHOICE_TALK.issuperset(words.rest.split()):
        return NotAChoice()
    fits = tuple(
        i for i, start in enumerate(offered) if _fits(words, i, len(offered), start, today)
    )
    narrowed = tuple(i for i in fits if i in shortlist)
    found = narrowed or fits
    if len(found) == 1:
        return Chosen(index=found[0])
    if found:
        return Ambiguous(indices=found)
    return NoMatch(day=_named_day(words, today))


def _says_a_slot(words: SlotWords) -> bool:
    return bool(
        words.positions
        or words.weekdays
        or words.days
        or words.offsets
        or words.times
        or words.part
    )


def _fits(words: SlotWords, index: int, size: int, start: datetime, today: date) -> bool:
    position = {index + 1} | ({LAST} if index == size - 1 else set())
    return (
        (not words.positions or bool(words.positions & position))
        and _on_day(words, start.date(), today)
        and (not words.times or any(_at(clock, start) for clock in words.times))
        and (words.part is None or (start.hour >= _AFTERNOON_FROM) == (words.part == "afternoon"))
    )


def _on_day(words: SlotWords, day: date, today: date) -> bool:
    return (
        (not words.weekdays or day.weekday() in words.weekdays)
        and (not words.days or day.day in words.days)
        and (not words.offsets or (day - today).days in words.offsets)
    )


def _at(clock: Clock, start: datetime) -> bool:
    """A spoken hour is the hour or, below twelve, the same hour after noon: an interview
    "a las cinco" is at 17:00. A minute counts only when it was said."""
    hour, minute = clock
    hour_fits = start.hour == hour or (hour < 12 and start.hour == hour + 12)
    return hour_fits and (minute is None or start.minute == minute)


def _named_day(words: SlotWords, today: date) -> date | None:
    """The first day from today within the calendar's horizon that the words name."""
    if not (words.weekdays or words.days or words.offsets):
        return None
    days = (today + timedelta(days=n) for n in range(HORIZON_DAYS + 1))
    return next((day for day in days if _on_day(words, day, today)), None)
