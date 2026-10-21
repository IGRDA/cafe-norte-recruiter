# `domain`: the rules the model cannot bend

Pure Python. No I/O, no clock reads, no model calls, no framework imports beyond Pydantic. Every
function takes values and returns values; time comes in as an argument. This is the module the
spec means by "code-enforced validation": the LLM proposes, these functions decide.

| File | Contents |
| --- | --- |
| `contracts.py` | Identifiers, enums, the `FieldState` sum type, `CandidateRecord`, patches, confirmations, booking, slots, lifecycle, outcome, review flags, `StoreConfiguration`, `SessionState` |
| `result.py` | `Ok[T] | Err[E]`: how domain functions refuse without raising |
| `fields.py` | Transitions of one field: `capture`, `confirm`, `mark_unknown`, `decline`, `value_of` |
| `candidate.py` | Validating and applying a patch to the whole record; which fields are still unfinished. The brief's sentences are candidate-facing text, so rendering lives in `conversation/brief.py` |
| `confirmation.py` | Presenting a pending confirmation and interpreting a response against it |
| `booking.py` | The five conditions a reservation needs (`reservation_allowed`), the slot half of them (`slot_offerable`) and the server-generated `idempotency_key` |
| `calendar.py` | `interview_slots`: the simulated calendar as a deterministic rule over a store's shifts and `interview_times` (D29) |
| `numbers.py` | Whether a number appears in the candidate's words, as digits or spoken (`mentions_number`), `spelled` (0–99, es/en) and `plain` (case-folded, no accents) |
| `slot_choice.py` | Which offered slot an answer means: `read_slot_words` (positions, weekdays, days, relative days, times, part of day, leftover words) and `choose_slot` → `Chosen \| Ambiguous \| NoMatch \| NotAChoice`; only an answer all about the slot is a choice (D41) |
| `lifecycle.py` | Allowed `lifecycle` transitions (`transition`, `is_terminal`) and the outcome each terminal event implies: an early end with a follow-up flag is `human_followup_requested` |
| `review.py` | `add_followup` (at most one `human_followup` flag per turn) and `has_followup`: the one place the tool handler and the runtime's explicit-request control add a follow-up |
| `configuration.py` | Loading and validating the two store configurations from `config/` |

## Field algebra

A collected field is one of five states; only two carry a value.

```text
FieldState[T] = Unset | Captured[T] | Confirmed[T] | Unknown | Declined

capture      : FieldState[T] × T × Evidence  → Captured[T]        (drops a stale confirmation)
confirm      : FieldState[T] × ConfirmationId → Ok[Confirmed[T]] | Err[FieldError]
mark_unknown : FieldState[T] × attempts       → Unknown
decline      : FieldState[T] × TurnId         → Declined
value_of     : FieldState[T]                  → T | None            (None unless Captured/Confirmed)
```

`tests/test_field_algebra.py` pins these laws with property tests. The JSON export shape
(`value`, `status`, `source_turn_id`, `evidence_text`) is the serialisation of this union, not a
second model.

## Revisions

Every accepted patch increments `CandidateRecord.revision`. A brief confirmation names the
revision it was shown for; a later patch invalidates it (see `confirmation.py`). The session
records the revision the candidate affirmed in `brief_confirmed_revision`, and the candidate's
words asking for an interview in `schedule_intent`. A reservation needs the brief confirmed at
the current revision, that intent, and a delivered, affirmed slot confirmation bound to the
same revision (see `booking.py`).
