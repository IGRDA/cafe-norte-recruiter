"""Fast synchronous controls and the asynchronous classifier adapter."""

from typing import Literal

from cafe_norte.domain.contracts import Signal, TurnId
from cafe_norte.errors import Language
from cafe_norte.model.contracts import Model

Control = Literal["stop", "human", "switch_es", "switch_en"]


def explicit_controls(text: str, language: Language) -> frozenset[Control]:
    """Pattern-based detection of stop, human and language requests. Pure, no model."""
    raise NotImplementedError


class ModelSignalAnalyzer:
    """Small classifier call, off the critical path; stale results never override a newer
    explicit preference."""

    def __init__(self, model: Model) -> None:
        raise NotImplementedError

    async def analyze(self, turn_id: TurnId, text: str, language: Language) -> Signal:
        raise NotImplementedError
