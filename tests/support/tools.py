"""Calling tool handlers directly: the context a turn gives them and validated arguments."""

import json

from pydantic import BaseModel

from cafe_norte.conversation.contracts import ToolContext
from cafe_norte.conversation.tools import ARGUMENT_MODELS, ToolName
from cafe_norte.domain.contracts import TurnId
from tests.support.builders import NOW, SID


def context(turn: str = "t1") -> ToolContext:
    return ToolContext(
        session_id=SID, turn_id=TurnId(turn), now=NOW, language="es", lease_generation=None
    )


def args(name: ToolName, **payload: object) -> BaseModel:
    return ARGUMENT_MODELS[name].model_validate_json(json.dumps(payload, default=str))
