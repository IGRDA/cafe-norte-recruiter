"""Rubric judge through the Model port. Output must be actual JSON booleans."""

from cafe_norte.model.contracts import Model


async def judge(model: Model, *, transcript: str, rubric: tuple[str, ...]) -> dict[str, bool]:
    raise NotImplementedError
