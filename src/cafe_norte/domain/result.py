"""A result type so domain functions can refuse without exceptions.

Exceptions are for infrastructure. A rule that says "no" returns ``Err`` with a typed reason
that the runtime turns into a clarification question or a review flag."""

from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")
E = TypeVar("E")


@dataclass(frozen=True, slots=True)
class Ok[T]:
    value: T


@dataclass(frozen=True, slots=True)
class Err[E]:
    error: E


Result = Ok[T] | Err[E]
