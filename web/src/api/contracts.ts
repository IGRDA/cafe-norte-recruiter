/* Generated from contracts.schema.json by `npm run types` (after `make export-schema`). Do not edit. */

/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "YearMonth".
 */
export type YearMonth = string;

export interface BrowserContracts {
  AccessRequest: AccessRequest;
  CreateSessionRequest: CreateSessionRequest;
  ResumeRequest: ResumeRequest;
  TurnRequest: TurnRequest;
  ConfirmationAnswer: ConfirmationAnswer;
  VoiceTimingReport: VoiceTimingReport;
  RuntimeInfo: RuntimeInfo;
  LanguageOption: LanguageOption;
  ConfigurationSummary: ConfigurationSummary;
  CreateSessionResponse: CreateSessionResponse;
  ResumeResponse: ResumeResponse;
  TurnAccepted: TurnAccepted;
  VoiceStartResponse: VoiceStartResponse;
  ErrorResponse: ErrorResponse;
  SessionEvent: SessionEvent;
  SessionSnapshotResponse: SessionSnapshotResponse;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "AccessRequest".
 */
export interface AccessRequest {
  code: string;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "CreateSessionRequest".
 */
export interface CreateSessionRequest {
  config_id: string;
  language: "es" | "en" | "fr" | "pt" | "it" | "de" | "ro" | "ar" | "zh" | "uk";
  channel: "voice" | "text";
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "ResumeRequest".
 */
export interface ResumeRequest {
  token: string;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "TurnRequest".
 */
export interface TurnRequest {
  input_id: string;
  text: string;
  expected_revision?: number | null;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "ConfirmationAnswer".
 */
export interface ConfirmationAnswer {
  input_id: string;
  answer: "affirm" | "deny";
  expected_revision: number;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "VoiceTimingReport".
 */
export interface VoiceTimingReport {
  turn_id: string | null;
  event: "speech_end" | "first_audio" | "barge_in" | "playback_stopped" | "connected";
  monotonic_ms: number;
}
/**
 * What the page needs before it renders: which voice to offer and the stores; and the
 * commit this process runs, which the deploy waits for.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "RuntimeInfo".
 */
export interface RuntimeInfo {
  voice: "off" | "pipecat";
  signals: "off" | "labels" | "jev";
  languages: LanguageOption[];
  config_ids: string[];
  access_required: boolean;
  commit_sha: string;
}
/**
 * A language Ana answers in, as the page lists it (D63).
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "LanguageOption".
 */
export interface LanguageOption {
  code: "es" | "en" | "fr" | "pt" | "it" | "de" | "ro" | "ar" | "zh" | "uk";
  native: string;
  rtl: boolean;
  tested: boolean;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "ConfigurationSummary".
 */
export interface ConfigurationSummary {
  config_id: string;
  store_name: string;
  city: string;
  hours_per_week: number;
  languages: ("es" | "en" | "fr" | "pt" | "it" | "de" | "ro" | "ar" | "zh" | "uk")[];
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "CreateSessionResponse".
 */
export interface CreateSessionResponse {
  session_id: string;
  resume_url: string;
  versions: VersionStamp;
}
/**
 * Attached to every session and evaluation run.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "VersionStamp".
 */
export interface VersionStamp {
  config_id: string;
  config_version: string;
  kb_version: string;
  prompt_version: string;
  schema_version: string;
  model_id: string;
  stt_model: string;
  tts_model: string;
  voice_id: string;
  commit_sha: string;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "ResumeResponse".
 */
export interface ResumeResponse {
  session_id: string;
}
/**
 * The turn is queued; its events arrive on the session stream.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "TurnAccepted".
 */
export interface TurnAccepted {
  input_id: string;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "VoiceStartResponse".
 */
export interface VoiceStartResponse {
  room_url: string;
  candidate_token: string;
  expires_at: string;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "ErrorResponse".
 */
export interface ErrorResponse {
  code:
    | "busy"
    | "timeout"
    | "provider_unavailable"
    | "provider_rejected"
    | "invalid_response"
    | "validation_failed"
    | "unauthorized"
    | "not_found"
    | "conflict"
    | "limit_exceeded"
    | "rate_limited"
    | "session_ended"
    | "internal_error";
  message: string;
}
/**
 * SSE envelope. ``seq`` is monotonic per session and doubles as the SSE id.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "SessionEvent".
 */
export interface SessionEvent {
  session_id: string;
  seq: number;
  turn_id: string | null;
  at: string;
  payload:
    | TurnStarted
    | AssistantText
    | ToolStarted
    | ToolFinished
    | StateUpdated
    | SourcesShown
    | SignalRecorded
    | TurnFinished
    | TurnFailed
    | VoiceState;
}
/**
 * Opens a turn. ``text`` is the finalized user input the turn answers (persisted before
 * this is emitted), empty for Ana's opening; the browser renders the user bubble from it so
 * the transcript comes from the stream alone, replay included.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "TurnStarted".
 */
export interface TurnStarted {
  type: "turn_started";
  turn_id: string;
  language: "es" | "en" | "fr" | "pt" | "it" | "de" | "ro" | "ar" | "zh" | "uk";
  text: string;
}
/**
 * A sentence or clause ready for display and TTS. ``spoken_form`` has dates, times, money
 * and phone numbers normalized for speech; ``text`` keeps canonical values.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "AssistantText".
 */
export interface AssistantText {
  type: "assistant_text";
  text: string;
  spoken_form: string;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "ToolStarted".
 */
export interface ToolStarted {
  type: "tool_started";
  name: string;
  arguments: string;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "ToolFinished".
 */
export interface ToolFinished {
  type: "tool_finished";
  name: string;
  ok: boolean;
  summary: string;
}
/**
 * Emitted after the transaction commits. The browser renders this, not the transcript.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "StateUpdated".
 */
export interface StateUpdated {
  type: "state_updated";
  revision: number;
  candidate: CandidateRecord;
  pending_confirmation: Confirmation | null;
  booking: Booking | null;
  lifecycle: "active" | "paused" | "completed" | "stopped" | "abandoned" | "failed";
  outcome: ("reserved" | "brief_only" | "not_interested" | "human_followup_requested" | "incomplete") | null;
  language: ("es" | "en" | "fr" | "pt" | "it" | "de" | "ro" | "ar" | "zh" | "uk") | null;
}
/**
 * Server-held candidate facts. The language is a session preference (``SessionState``),
 * not a collected fact.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "CandidateRecord".
 */
export interface CandidateRecord {
  revision: number;
  name: Unset | CapturedAnnotatedStrStringConstraints | ConfirmedAnnotatedStrStringConstraints | Unknown | Declined;
  contact_phone:
    Unset | CapturedAnnotatedStrStringConstraints1 | ConfirmedAnnotatedStrStringConstraints1 | Unknown | Declined;
  interest: Unset | CapturedLiteralYesUnsureNo | ConfirmedLiteralYesUnsureNo | Unknown | Declined;
  work_authorization: Unset | CapturedLiteralYesUnsureNo | ConfirmedLiteralYesUnsureNo | Unknown | Declined;
  availability_days:
    | Unset
    | CapturedFrozensetLiteralMonTueWedThuFriSatSun
    | ConfirmedFrozensetLiteralMonTueWedThuFriSatSun
    | Unknown
    | Declined;
  availability_shifts: Unset | CapturedFrozensetNewType | ConfirmedFrozensetNewType | Unknown | Declined;
  hours_per_week:
    | Unset
    | CapturedAnnotatedIntFieldInfoAnnotationNoneTypeRequiredTrueMetadataGeGe1LeLe60
    | ConfirmedAnnotatedIntFieldInfoAnnotationNoneTypeRequiredTrueMetadataGeGe1LeLe60
    | Unknown
    | Declined;
  earliest_start_date:
    | Unset
    | CapturedAnnotatedUnionDateYearMonthBeforeValidator
    | ConfirmedAnnotatedUnionDateYearMonthBeforeValidator
    | Unknown
    | Declined;
  experience:
    Unset | CapturedAnnotatedStrStringConstraints2 | ConfirmedAnnotatedStrStringConstraints2 | Unknown | Declined;
  notes: string[];
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "Unset".
 */
export interface Unset {
  status: "unset";
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "cafe_norte__domain__contracts__Captured_Annotated_str__StringConstraints____1".
 */
export interface CapturedAnnotatedStrStringConstraints {
  status: "captured";
  value: string;
  evidence: Evidence;
}
/**
 * Where a value came from: finalized user text of one turn, never an STT interim.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "Evidence".
 */
export interface Evidence {
  source_turn_id: string;
  text: string;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "cafe_norte__domain__contracts__Confirmed_Annotated_str__StringConstraints____1".
 */
export interface ConfirmedAnnotatedStrStringConstraints {
  status: "confirmed";
  value: string;
  evidence: Evidence;
  confirmation_id: string;
}
/**
 * Two failed clarification attempts, or the candidate does not know.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "Unknown".
 */
export interface Unknown {
  status: "unknown";
  attempts: number;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "Declined".
 */
export interface Declined {
  status: "declined";
  source_turn_id: string;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "cafe_norte__domain__contracts__Captured_Annotated_str__StringConstraints____2".
 */
export interface CapturedAnnotatedStrStringConstraints1 {
  status: "captured";
  value: string;
  evidence: Evidence;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "cafe_norte__domain__contracts__Confirmed_Annotated_str__StringConstraints____2".
 */
export interface ConfirmedAnnotatedStrStringConstraints1 {
  status: "confirmed";
  value: string;
  evidence: Evidence;
  confirmation_id: string;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "Captured_Literal__yes____unsure____no___".
 */
export interface CapturedLiteralYesUnsureNo {
  status: "captured";
  value: "yes" | "unsure" | "no";
  evidence: Evidence;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "Confirmed_Literal__yes____unsure____no___".
 */
export interface ConfirmedLiteralYesUnsureNo {
  status: "confirmed";
  value: "yes" | "unsure" | "no";
  evidence: Evidence;
  confirmation_id: string;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "Captured_frozenset_Literal__mon____tue____wed____thu____fri____sat____sun____".
 */
export interface CapturedFrozensetLiteralMonTueWedThuFriSatSun {
  status: "captured";
  value: ("mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun")[];
  evidence: Evidence;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "Confirmed_frozenset_Literal__mon____tue____wed____thu____fri____sat____sun____".
 */
export interface ConfirmedFrozensetLiteralMonTueWedThuFriSatSun {
  status: "confirmed";
  value: ("mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun")[];
  evidence: Evidence;
  confirmation_id: string;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "Captured_frozenset_NewType__".
 */
export interface CapturedFrozensetNewType {
  status: "captured";
  value: string[];
  evidence: Evidence;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "Confirmed_frozenset_NewType__".
 */
export interface ConfirmedFrozensetNewType {
  status: "confirmed";
  value: string[];
  evidence: Evidence;
  confirmation_id: string;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "Captured_Annotated_int__FieldInfo_annotation_NoneType__required_True__metadata__Ge_ge_1___Le_le_60_____".
 */
export interface CapturedAnnotatedIntFieldInfoAnnotationNoneTypeRequiredTrueMetadataGeGe1LeLe60 {
  status: "captured";
  value: number;
  evidence: Evidence;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "Confirmed_Annotated_int__FieldInfo_annotation_NoneType__required_True__metadata__Ge_ge_1___Le_le_60_____".
 */
export interface ConfirmedAnnotatedIntFieldInfoAnnotationNoneTypeRequiredTrueMetadataGeGe1LeLe60 {
  status: "confirmed";
  value: number;
  evidence: Evidence;
  confirmation_id: string;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "Captured_Annotated_Union_date__YearMonth___BeforeValidator__".
 */
export interface CapturedAnnotatedUnionDateYearMonthBeforeValidator {
  status: "captured";
  value: YearMonth;
  evidence: Evidence;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "Confirmed_Annotated_Union_date__YearMonth___BeforeValidator__".
 */
export interface ConfirmedAnnotatedUnionDateYearMonthBeforeValidator {
  status: "confirmed";
  value: YearMonth;
  evidence: Evidence;
  confirmation_id: string;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "cafe_norte__domain__contracts__Captured_Annotated_str__StringConstraints____3".
 */
export interface CapturedAnnotatedStrStringConstraints2 {
  status: "captured";
  value: string;
  evidence: Evidence;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "cafe_norte__domain__contracts__Confirmed_Annotated_str__StringConstraints____3".
 */
export interface ConfirmedAnnotatedStrStringConstraints2 {
  status: "confirmed";
  value: string;
  evidence: Evidence;
  confirmation_id: string;
}
/**
 * One read-back and its answer. A bare "yes" only means something against the pending one.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "Confirmation".
 */
export interface Confirmation {
  confirmation_id: string;
  target: FieldTarget | BriefTarget | SlotTarget;
  presentation_text: string;
  presented_turn_id: string;
  fully_delivered: boolean;
  review: (ReviewOffered | ReviewInParts | ReviewWaived) | null;
  response_turn_id: string | null;
  status: "pending" | "confirmed" | "rejected" | "invalidated" | "expired";
  source: "model" | "ui";
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "FieldTarget".
 */
export interface FieldTarget {
  kind: "field";
  field:
    | "name"
    | "contact_phone"
    | "interest"
    | "work_authorization"
    | "availability_days"
    | "availability_shifts"
    | "hours_per_week"
    | "earliest_start_date"
    | "experience";
  revision: number;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "BriefTarget".
 */
export interface BriefTarget {
  kind: "brief";
  revision: number;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "SlotTarget".
 */
export interface SlotTarget {
  kind: "slot";
  slot_id: string;
  brief_revision: number;
}
/**
 * The read-back was cut and Ana offered to go over it; the candidate has not chosen yet.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "ReviewOffered".
 */
export interface ReviewOffered {
  stage: "offered";
  turn_id: string;
}
/**
 * Being gone over in short parts; ``part`` is the one said last (0-based).
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "ReviewInParts".
 */
export interface ReviewInParts {
  stage: "in_parts";
  part: number;
  parts: number;
  turn_id: string;
}
/**
 * The candidate chose to carry on without going over it: an informed skip.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "ReviewWaived".
 */
export interface ReviewWaived {
  stage: "waived";
  turn_id: string;
}
/**
 * A committed simulated reservation. Exists only after the database transaction commits.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "Booking".
 */
export interface Booking {
  slot_id: string;
  config_id: string;
  starts_at_utc: string;
  confirmation_id: string;
  idempotency_key: string;
  committed_at: string;
  simulated: true;
}
/**
 * What the candidate asked and which chunks were shown for it, title › section.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "SourcesShown".
 */
export interface SourcesShown {
  type: "sources_shown";
  question: string;
  chunk_ids: string[];
  titles: string[];
  sections: string[];
  excerpts: string[];
}
/**
 * The asynchronous classifier's verdict on one user turn, journaled after that turn
 * ended. Advisory: the reviewer panel and the export show it; it never scores anyone.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "SignalRecorded".
 */
export interface SignalRecorded {
  type: "signal_recorded";
  signal: Signal;
}
/**
 * Conversational signal attached to the turn it came from; never a hiring input.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "Signal".
 */
export interface Signal {
  turn_id: string;
  sentiment: "neutral" | "positive" | "frustrated" | "uncertain";
  explicit_human_request: boolean;
  explicit_stop: boolean;
  language_switch_to: ("es" | "en" | "fr" | "pt" | "it" | "de" | "ro" | "ar" | "zh" | "uk") | null;
  evidence_text: string;
  probabilities: SignalProbabilities | null;
}
/**
 * What a decision model gave each option (D52), shown on the page as it arrives (D62).
 * Advisory: the verdict in ``Signal`` is what the runtime acts on.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "SignalProbabilities".
 */
export interface SignalProbabilities {
  sentiment: {
    [k: string]: number;
  };
  language: {
    [k: string]: number;
  };
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "TurnFinished".
 */
export interface TurnFinished {
  type: "turn_finished";
  turn_id: string;
  interrupted: boolean;
  usage: UsageRecord[];
  timings: StageTiming[];
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "UsageRecord".
 */
export interface UsageRecord {
  session_id: string;
  turn_id: string | null;
  kind: "llm_tokens" | "tts_characters" | "stt_seconds" | "media_participant_minutes";
  quantity: number;
  unit_detail: string;
  estimated: boolean;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "StageTiming".
 */
export interface StageTiming {
  session_id: string;
  turn_id: string;
  stage:
    | "speech_end_to_transcript"
    | "llm_first_output"
    | "llm_total"
    | "tool"
    | "tts_first_audio"
    | "useful_answer"
    | "barge_in_to_stop"
    | "text_first_token"
    | "text_total";
  milliseconds: number;
  source: "server" | "browser" | "server_proxy";
  tool_name: string;
}
/**
 * Terminal for the turn; the session may continue. ``message`` is fixed public text.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "TurnFailed".
 */
export interface TurnFailed {
  type: "turn_failed";
  turn_id: string;
  code:
    | "busy"
    | "timeout"
    | "provider_unavailable"
    | "provider_rejected"
    | "invalid_response"
    | "validation_failed"
    | "unauthorized"
    | "not_found"
    | "conflict"
    | "limit_exceeded"
    | "rate_limited"
    | "session_ended"
    | "internal_error";
  message: string;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "VoiceState".
 */
export interface VoiceState {
  type: "voice_state";
  status: "connecting" | "listening" | "thinking" | "speaking" | "paused" | "ended";
}
/**
 * What `GET /api/sessions/{id}` returns: one consistent read for the owner. The pending
 * confirmation is ``state.pending_confirmation``; ``last_seq`` is where the stream resumes.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "SessionSnapshotResponse".
 */
export interface SessionSnapshotResponse {
  session_id: string;
  last_seq: number;
  state: SessionState;
  transcript: TurnRecord[];
  versions: VersionStamp;
}
/**
 * The authoritative state the runtime reads and the repositories persist.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "SessionState".
 */
export interface SessionState {
  session_id: string;
  config_id: string;
  config_version: string;
  language: "es" | "en" | "fr" | "pt" | "it" | "de" | "ro" | "ar" | "zh" | "uk";
  channel: "voice" | "text";
  created_at: string;
  lifecycle: "active" | "paused" | "completed" | "stopped" | "abandoned" | "failed";
  outcome: ("reserved" | "brief_only" | "not_interested" | "human_followup_requested" | "incomplete") | null;
  candidate: CandidateRecord1;
  pending_confirmation: Confirmation | null;
  brief_confirmed_revision: number | null;
  schedule_intent: Evidence | null;
  slot_offer: SlotOffer | null;
  booking: Booking | null;
  review_flags: ReviewFlag[];
  active_seconds: number;
  turn_count: number;
}
/**
 * Server-held candidate facts. The language is a session preference (``SessionState``),
 * not a collected fact.
 */
export interface CandidateRecord1 {
  revision: number;
  name: Unset | CapturedAnnotatedStrStringConstraints | ConfirmedAnnotatedStrStringConstraints | Unknown | Declined;
  contact_phone:
    Unset | CapturedAnnotatedStrStringConstraints1 | ConfirmedAnnotatedStrStringConstraints1 | Unknown | Declined;
  interest: Unset | CapturedLiteralYesUnsureNo | ConfirmedLiteralYesUnsureNo | Unknown | Declined;
  work_authorization: Unset | CapturedLiteralYesUnsureNo | ConfirmedLiteralYesUnsureNo | Unknown | Declined;
  availability_days:
    | Unset
    | CapturedFrozensetLiteralMonTueWedThuFriSatSun
    | ConfirmedFrozensetLiteralMonTueWedThuFriSatSun
    | Unknown
    | Declined;
  availability_shifts: Unset | CapturedFrozensetNewType | ConfirmedFrozensetNewType | Unknown | Declined;
  hours_per_week:
    | Unset
    | CapturedAnnotatedIntFieldInfoAnnotationNoneTypeRequiredTrueMetadataGeGe1LeLe60
    | ConfirmedAnnotatedIntFieldInfoAnnotationNoneTypeRequiredTrueMetadataGeGe1LeLe60
    | Unknown
    | Declined;
  earliest_start_date:
    | Unset
    | CapturedAnnotatedUnionDateYearMonthBeforeValidator
    | ConfirmedAnnotatedUnionDateYearMonthBeforeValidator
    | Unknown
    | Declined;
  experience:
    Unset | CapturedAnnotatedStrStringConstraints2 | ConfirmedAnnotatedStrStringConstraints2 | Unknown | Declined;
  notes: string[];
}
/**
 * The slots Ana last offered, in the order she said them, and the ones an ambiguous answer
 * left in question (D41). The runtime matches the candidate's choice against it.
 *
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "SlotOffer".
 */
export interface SlotOffer {
  slots: OfferedSlot[];
  shortlist: string[];
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "OfferedSlot".
 */
export interface OfferedSlot {
  slot_id: string;
  starts_at_utc: string;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "ReviewFlag".
 */
export interface ReviewFlag {
  kind: "work_authorization" | "human_followup" | "unsupported_question" | "reschedule_request" | "other";
  turn_id: string;
  note: string;
}
/**
 * This interface was referenced by `BrowserContracts`'s JSON-Schema
 * via the `definition` "TurnRecord".
 */
export interface TurnRecord {
  turn_id: string;
  session_id: string;
  input_id: string;
  role: "user" | "assistant";
  channel: "voice" | "text";
  language: "es" | "en" | "fr" | "pt" | "it" | "de" | "ro" | "ar" | "zh" | "uk";
  text: string;
  delivered_text: string | null;
  interrupted: boolean;
  started_at: string;
  finished_at: string | null;
}
