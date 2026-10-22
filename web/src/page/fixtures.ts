// Test builders for contract values; only what a reducer test needs to vary is a parameter.
import type { ConfigurationSummary, LanguageOption, SessionEvent, Signal, StateUpdated, VersionStamp } from "../api/contracts";
import { initial, reduce, type Action, type Effect, type State } from "./reducer";

export const STORE: ConfigurationSummary = {
  config_id: "chamberi",
  store_name: "Café Norte Chamberí",
  city: "Madrid",
  hours_per_week: 20,
  languages: ["es", "en"],
};

export const LANGUAGES: LanguageOption[] = [
  { code: "es", native: "español", rtl: false, tested: true },
  { code: "en", native: "English", rtl: false, tested: true },
  { code: "fr", native: "français", rtl: false, tested: false },
  { code: "ar", native: "العربية", rtl: true, tested: false },
];

export const VERSIONS: VersionStamp = {
  config_id: "chamberi",
  config_version: "1",
  kb_version: "kb1",
  prompt_version: "ana_v22",
  schema_version: "1",
  model_id: "fake",
  stt_model: "",
  tts_model: "",
  voice_id: "",
  commit_sha: "local",
};

/** Reduce a sequence of actions, collecting every effect requested along the way. */
export function run(state: State, ...actions: Action[]): { state: State; effects: Effect[] } {
  const effects: Effect[] = [];
  for (const action of actions) state = reduce(state, action, (effect) => effects.push(effect));
  return { state, effects };
}

export function booted(store: string | null = "chamberi"): State {
  return run(initial({ store, language: "es", resumeToken: null, code: null }), {
    type: "booted",
    voiceOffered: true,
    signalsMode: "jev",
    languages: LANGUAGES,
    stores: [STORE],
  }).state;
}

/** A page with an open session "s1" and no events yet. */
export function active(): State {
  return run(booted(), {
    type: "session-opened",
    body: { session_id: "s1", resume_url: "/#resume=abc", versions: VERSIONS },
  }).state;
}

let seq = 0;

export function event(payload: SessionEvent["payload"], turnId: string | null = "t1"): Action {
  seq += 1;
  return {
    type: "event-received",
    event: { session_id: "s1", seq, turn_id: turnId, at: "2026-10-22T10:00:00Z", payload },
  };
}

const UNSET = { status: "unset" } as const;

export function stateUpdated(overrides: Partial<StateUpdated> = {}): StateUpdated {
  return {
    type: "state_updated",
    revision: 1,
    candidate: {
      revision: 1,
      name: UNSET,
      contact_phone: UNSET,
      interest: UNSET,
      work_authorization: UNSET,
      availability_days: UNSET,
      availability_shifts: UNSET,
      hours_per_week: UNSET,
      earliest_start_date: UNSET,
      experience: UNSET,
      notes: [],
    },
    pending_confirmation: null,
    booking: null,
    lifecycle: "active",
    outcome: null,
    language: "es",
    ...overrides,
  };
}

export function pendingBrief(revision = 3): StateUpdated {
  return stateUpdated({
    revision,
    pending_confirmation: {
      confirmation_id: "c1",
      target: { kind: "brief", revision },
      presentation_text: "Te llamas Ana. ¿Es todo correcto?",
      presented_turn_id: "t1",
      fully_delivered: true,
      review: null,
      response_turn_id: null,
      status: "pending",
      source: "model",
    },
  });
}

export function signal(turnId: string, frustrated: number, switching = 0.1, overrides: Partial<Signal> = {}): Action {
  return event(
    {
      type: "signal_recorded",
      signal: {
        turn_id: turnId,
        sentiment: frustrated >= 0.5 ? "frustrated" : "neutral",
        explicit_human_request: false,
        explicit_stop: false,
        language_switch_to: null,
        evidence_text: "",
        probabilities: {
          sentiment: { neutral: 1 - frustrated, positive: 0, frustrated, uncertain: 0 },
          language: { es: 1 - switching, en: switching },
        },
        ...overrides,
      },
    },
    turnId,
  );
}

export function userTurn(turnId: string, text = "Hola"): Action {
  return event({ type: "turn_started", turn_id: turnId, language: "es", text }, turnId);
}
