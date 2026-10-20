"""Tool handlers: what happens after the registry has validated a call.

Each handler reads the authoritative state from the store, lets the domain decide, commits,
and only then returns the ``StateUpdated`` the channel will render. ``model_text`` always
tells the model its next step in one sentence, because the model follows it literally."""

import uuid
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel

from cafe_norte.conversation.brief import ReadbackField, field_readback, render_brief_es
from cafe_norte.conversation.contracts import StateUpdated, ToolContext, ToolHandler, ToolOutcome
from cafe_norte.conversation.tools import (
    ConfirmBriefArgs,
    ConfirmFieldArgs,
    EndSessionArgs,
    PresentConfirmationArgs,
    ToolName,
    UpdateCandidateArgs,
)
from cafe_norte.domain import confirmation, fields
from cafe_norte.domain.candidate import (
    apply_patch,
    changed_fields,
    ready_for_brief,
    unfinished_fields,
    validate_patch,
)
from cafe_norte.domain.contracts import (
    BriefTarget,
    ConfigId,
    ConfirmationId,
    Evidence,
    FieldTarget,
    ReviewFlag,
    SessionState,
    StoreConfiguration,
)
from cafe_norte.domain.lifecycle import LifecycleEvent, transition
from cafe_norte.domain.result import Err
from cafe_norte.persistence.contracts import Store

READBACK_FIELDS: tuple[ReadbackField, ...] = ("contact_phone", "earliest_start_date")
NEXT_STEP = {
    "brief": "Now call present_confirmation(target=brief).",
    "interview": "Now ask, in one short sentence, whether they would like an interview.",
    "goodbye": "Session ended. Say goodbye in one short sentence.",
}


def all_handlers(
    *, store: Store, configurations: Mapping[ConfigId, StoreConfiguration]
) -> dict[ToolName, ToolHandler]:
    """Every tool the model may call today; the registry advertises exactly these."""
    return {
        "update_candidate": UpdateCandidateHandler(store=store, configurations=configurations),
        "present_confirmation": PresentConfirmationHandler(
            store=store, configurations=configurations
        ),
        "confirm_field": ConfirmFieldHandler(store=store),
        "confirm_brief": ConfirmBriefHandler(store=store),
        "end_session": EndSessionHandler(store=store),
    }


class _Handler:
    def __init__(self, *, store: Store) -> None:
        self._store = store

    async def _state(self, context: ToolContext) -> SessionState | None:
        return await self._store.sessions.get(context.session_id)

    async def _save(self, state: SessionState, *, expected_revision: int) -> None:
        async with self._store.transaction() as tx:
            await self._store.sessions.save(tx, state, expected_revision=expected_revision)

    @staticmethod
    def _updated(state: SessionState) -> StateUpdated:
        return StateUpdated(
            revision=state.candidate.revision,
            candidate=state.candidate,
            pending_confirmation=state.pending_confirmation,
            booking=state.booking,
            lifecycle=state.lifecycle,
            outcome=state.outcome,
        )

    @staticmethod
    def _refuse(summary: str, model_text: str) -> ToolOutcome:
        return ToolOutcome(ok=False, model_text=model_text, summary=summary)


def _next_question(state: SessionState) -> str:
    """What the model should do after a save: one field, the brief, or the interview."""
    missing = unfinished_fields(state.candidate)
    if missing:
        # Name only the next field: listing them all made the model ask them all at once.
        return f"Now ask about {missing[0]} only, in one short sentence, and end your turn."
    pending = state.pending_confirmation
    if (
        pending is not None
        and pending.status == "confirmed"
        and isinstance(pending.target, BriefTarget)
    ):
        return NEXT_STEP["interview"]
    return NEXT_STEP["brief"]


class UpdateCandidateHandler(_Handler):
    """``update_candidate``: validate against the store configuration, apply, persist with the
    revision the model saw, announce. A domain refusal goes back to the model as text so it
    can ask again; nothing is written."""

    def __init__(self, *, store: Store, configurations: Mapping[ConfigId, StoreConfiguration]):
        super().__init__(store=store)
        self._configurations = configurations

    async def __call__(self, context: ToolContext, arguments: BaseModel) -> ToolOutcome:
        assert isinstance(arguments, UpdateCandidateArgs)
        state = await self._state(context)
        if state is None:
            return self._refuse("not_found", "Session not found.")
        configuration = self._configurations[state.config_id]

        result = validate_patch(arguments.patch, configuration, context.now.date())
        if isinstance(result, Err):
            error = result.error
            return self._refuse(
                f"validation_failed:{error.field}:{error.reason}",
                f"Rejected field {error.field}: {error.reason} {error.detail}".strip()
                + ". Nothing was saved; ask the candidate again.",
            )
        changed = changed_fields(result.value)
        if not changed and result.value.note is None:
            return self._refuse("empty_patch", "Nothing to save; call only with stated facts.")

        evidence = Evidence(source_turn_id=context.turn_id, text=arguments.evidence_text)
        candidate = apply_patch(state.candidate, result.value, evidence)
        flags = state.review_flags
        if result.value.work_authorization in {"no", "unsure"}:
            note = f"self-reported {result.value.work_authorization}"
            flags = (
                *flags,
                ReviewFlag(kind="work_authorization", turn_id=context.turn_id, note=note),
            )
        pending = confirmation.invalidated_by_patch(state, candidate.revision, changed)
        new_state = state.model_copy(
            update={"candidate": candidate, "review_flags": flags, "pending_confirmation": pending}
        )
        await self._save(new_state, expected_revision=state.candidate.revision)

        saved = ", ".join(changed) or "note"
        readback = next((f for f in READBACK_FIELDS if f in changed), None)
        if readback is not None:
            step = f"Read it back: call present_confirmation(target=field, field={readback}) now."
        elif pending is not None and pending.status == "invalidated":
            step = "The pending read-back is void; present the brief again when ready."
        else:
            step = _next_question(new_state)
        return ToolOutcome(
            ok=True,
            model_text=f"Saved: {saved}. {step}",
            summary=f"captured:{saved}",
            events=(self._updated(new_state),),
        )


class PresentConfirmationHandler(_Handler):
    """``present_confirmation``: build the exact text, record it as pending, and hand it to the
    runtime to speak. The model is told it was already spoken."""

    def __init__(self, *, store: Store, configurations: Mapping[ConfigId, StoreConfiguration]):
        super().__init__(store=store)
        self._configurations = configurations

    async def __call__(self, context: ToolContext, arguments: BaseModel) -> ToolOutcome:
        assert isinstance(arguments, PresentConfirmationArgs)
        state = await self._state(context)
        if state is None:
            return self._refuse("not_found", "Session not found.")
        configuration = self._configurations[state.config_id]
        revision = state.candidate.revision

        if arguments.target == "brief":
            if not ready_for_brief(state.candidate):
                first = unfinished_fields(state.candidate)[0]
                return self._refuse(
                    f"brief_not_ready:{first}",
                    f"The brief needs every field settled; ask about {first} first.",
                )
            target: FieldTarget | BriefTarget = BriefTarget(revision=revision)
            text = render_brief_es(state.candidate, configuration)
        elif arguments.target == "field" and arguments.field in READBACK_FIELDS:
            field_name: ReadbackField = arguments.field
            value = fields.value_of(getattr(state.candidate, field_name))
            if value is None:
                return self._refuse(
                    f"nothing_to_read_back:{field_name}", f"{field_name} has no value yet."
                )
            target = FieldTarget(field=field_name, revision=revision)
            text = field_readback(field_name, value, configuration)
        else:
            return self._refuse(
                f"no_readback_for:{arguments.field or arguments.target}",
                "Only contact_phone, earliest_start_date and the brief are read back.",
            )

        pending = confirmation.present(
            state, target, text, context.turn_id, ConfirmationId(uuid.uuid4().hex)
        )
        new_state = state.model_copy(update={"pending_confirmation": pending})
        await self._save(new_state, expected_revision=revision)
        return ToolOutcome(
            ok=True,
            model_text="The read-back was already spoken. Reply with nothing and wait.",
            summary=f"presented:{target.kind}",
            events=(self._updated(new_state),),
            spoken=text,
        )


class _ConfirmHandler(_Handler):
    """Shared by ``confirm_field`` and ``confirm_brief``: the domain resolves the pending
    read-back; the subclass says what to do next."""

    kind: Literal["field", "brief"]

    async def __call__(self, context: ToolContext, arguments: BaseModel) -> ToolOutcome:
        assert isinstance(arguments, ConfirmFieldArgs | ConfirmBriefArgs)
        state = await self._state(context)
        if state is None:
            return self._refuse("not_found", "Session not found.")
        pending = state.pending_confirmation
        if pending is not None and pending.target.kind != self.kind:
            return self._refuse(
                "confirmation_refused:wrong_target",
                f"The pending read-back is a {pending.target.kind}, not a {self.kind}.",
            )
        result = confirmation.respond(state, arguments.answer, context.turn_id)
        if isinstance(result, Err):
            return self._refuse(
                f"confirmation_refused:{result.error}",
                f"No {self.kind} read-back can be answered now ({result.error}). "
                + ("Present it again." if result.error != "nothing_pending" else "Continue."),
            )
        resolved = result.value
        candidate = state.candidate
        if resolved.status == "confirmed" and isinstance(resolved.target, FieldTarget):
            confirmed = fields.confirm(
                getattr(candidate, resolved.target.field), resolved.confirmation_id
            )
            if not isinstance(confirmed, Err):
                data = candidate.model_dump()
                data[resolved.target.field] = confirmed.value.model_dump()
                candidate = type(candidate).model_validate(data)
        new_state = state.model_copy(
            update={"pending_confirmation": resolved, "candidate": candidate}
        )
        await self._save(new_state, expected_revision=state.candidate.revision)
        step = (
            _next_question(new_state)
            if resolved.status == "confirmed"
            else "Now ask what is wrong in one short sentence, then call update_candidate."
        )
        return ToolOutcome(
            ok=True,
            model_text=f"{self.kind} read-back {resolved.status}. {step}",
            summary=f"{self.kind}:{resolved.status}",
            events=(self._updated(new_state),),
        )


class ConfirmFieldHandler(_ConfirmHandler):
    kind = "field"


class ConfirmBriefHandler(_ConfirmHandler):
    kind = "brief"


class EndSessionHandler(_Handler):
    """``end_session``: the lifecycle table decides; the outcome follows from the state."""

    EVENTS: dict[str, LifecycleEvent] = {
        "candidate_done": "complete",
        "not_interested": "stop",
        "candidate_stop": "stop",
        "limit": "abandon",
    }

    async def __call__(self, context: ToolContext, arguments: BaseModel) -> ToolOutcome:
        assert isinstance(arguments, EndSessionArgs)
        state = await self._state(context)
        if state is None:
            return self._refuse("not_found", "Session not found.")
        result = transition(state, self.EVENTS[arguments.reason])
        if isinstance(result, Err):
            return self._refuse(
                f"lifecycle_refused:{result.error}",
                f"The session is already {result.error}. Say goodbye in one sentence.",
            )
        lifecycle, outcome = result.value
        new_state = state.model_copy(update={"lifecycle": lifecycle, "outcome": outcome})
        await self._save(new_state, expected_revision=state.candidate.revision)
        return ToolOutcome(
            ok=True,
            model_text=NEXT_STEP["goodbye"],
            summary=f"ended:{lifecycle}:{outcome}",
            events=(self._updated(new_state),),
        )
