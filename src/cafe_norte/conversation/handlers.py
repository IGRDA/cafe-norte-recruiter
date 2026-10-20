"""Tool handlers: what happens after the registry has validated a call.

Each handler reads the authoritative state from the store, lets the domain decide, commits,
and only then returns the ``StateUpdated`` the channel will render."""

from collections.abc import Mapping

from pydantic import BaseModel

from cafe_norte.conversation.contracts import StateUpdated, ToolContext, ToolOutcome
from cafe_norte.conversation.tools import UpdateCandidateArgs
from cafe_norte.domain.candidate import (
    apply_patch,
    changed_fields,
    unfinished_fields,
    validate_patch,
)
from cafe_norte.domain.contracts import ConfigId, Evidence, ReviewFlag, StoreConfiguration
from cafe_norte.domain.result import Err
from cafe_norte.persistence.contracts import Store


class UpdateCandidateHandler:
    """``update_candidate``: validate against the store configuration, apply, persist with the
    revision the model saw, announce. A domain refusal goes back to the model as text so it
    can ask again; nothing is written."""

    def __init__(self, *, store: Store, configurations: Mapping[ConfigId, StoreConfiguration]):
        self._store = store
        self._configurations = configurations

    async def __call__(self, context: ToolContext, arguments: BaseModel) -> ToolOutcome:
        if not isinstance(arguments, UpdateCandidateArgs):
            raise TypeError(f"expected UpdateCandidateArgs, got {type(arguments).__name__}")
        state = await self._store.sessions.get(context.session_id)
        if state is None:
            return ToolOutcome(ok=False, model_text="Session not found.", summary="not_found")
        configuration = self._configurations[state.config_id]

        result = validate_patch(arguments.patch, configuration, context.now.date())
        if isinstance(result, Err):
            error = result.error
            return ToolOutcome(
                ok=False,
                model_text=(
                    f"Rejected field {error.field}: {error.reason} {error.detail}".strip()
                    + ". Nothing was saved; ask the candidate again."
                ),
                summary=f"validation_failed:{error.field}:{error.reason}",
            )

        evidence = Evidence(source_turn_id=context.turn_id, text=arguments.evidence_text)
        candidate = apply_patch(state.candidate, result.value, evidence)
        flags = state.review_flags
        if result.value.work_authorization in {"no", "unsure"}:
            flags = (
                *flags,
                ReviewFlag(
                    kind="work_authorization",
                    turn_id=context.turn_id,
                    note=f"self-reported {result.value.work_authorization}",
                ),
            )
        async with self._store.transaction() as tx:
            await self._store.sessions.save(
                tx,
                state.model_copy(update={"candidate": candidate, "review_flags": flags}),
                expected_revision=state.candidate.revision,
            )
            await tx.commit()

        changed = ", ".join(changed_fields(result.value)) or "nothing"
        missing = unfinished_fields(candidate)
        # Name only the next field: listing them all made the model ask them all at once.
        next_step = (
            f"Now ask about {missing[0]} only, in one short sentence, and end your turn."
            if missing
            else "Nothing is left to ask; close in one short sentence."
        )
        return ToolOutcome(
            ok=True,
            model_text=f"Saved: {changed}. {next_step}",
            summary=f"captured:{changed}",
            events=(
                StateUpdated(
                    revision=candidate.revision,
                    candidate=candidate,
                    pending_confirmation=state.pending_confirmation,
                    booking=state.booking,
                    lifecycle=state.lifecycle,
                    outcome=state.outcome,
                ),
            ),
        )
