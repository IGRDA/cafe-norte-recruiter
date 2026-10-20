"""An LLM that plays the candidate from a persona, for live scenario runs."""

from cafe_norte.model.contracts import Model
from evals.contracts import Persona


class ModelCandidateSimulator:
    def __init__(self, model: Model) -> None:
        raise NotImplementedError

    async def reply(self, persona: Persona, transcript: tuple[tuple[str, str], ...]) -> str:
        raise NotImplementedError
