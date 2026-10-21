"""Review flags that ask a person to follow up: one way to add them, one way to ask."""

from cafe_norte.domain.contracts import ReviewFlag, SessionState, TurnId


def add_followup(state: SessionState, turn_id: TurnId, note: str) -> SessionState:
    """The state with one more ``human_followup`` flag; the conversation goes on. One flag
    per turn: a second request in the same turn (the runtime's control, then the model's
    tool) leaves the state unchanged."""
    if any(f.kind == "human_followup" and f.turn_id == turn_id for f in state.review_flags):
        return state
    flag = ReviewFlag(kind="human_followup", turn_id=turn_id, note=note)
    return state.model_copy(update={"review_flags": (*state.review_flags, flag)})


def has_followup(state: SessionState) -> bool:
    return any(flag.kind == "human_followup" for flag in state.review_flags)
