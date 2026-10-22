// Typed calls to the API. Each returns what the effect runner needs to pick the next action;
// a network failure throws, and the runner turns it into the page's "no connection" text.
import type {
  AccessRequest,
  ConfigurationSummary,
  ConfirmationAnswer,
  CreateSessionRequest,
  CreateSessionResponse,
  ErrorResponse,
  ResumeRequest,
  ResumeResponse,
  RuntimeInfo,
  SessionEvent,
  SessionSnapshotResponse,
  TurnRequest,
  VoiceStartResponse,
  VoiceTimingReport,
} from "./contracts";

export type Fetch = typeof fetch;
export type Language = CreateSessionRequest["language"];

// The codes Ana answers in (D63), for reading ?lang= before the server has listed them. A
// record keyed by the union makes the compiler fail when the API adds or drops one.
const LANGUAGE_CODES: Record<Language, true> = {
  es: true, en: true, fr: true, pt: true, it: true, de: true, ro: true, ar: true, zh: true, uk: true,
};

export function asLanguage(code: string | null): Language {
  return code !== null && code in LANGUAGE_CODES ? (code as Language) : "es";
}

type Reply<T> = { ok: true; body: T } | { ok: false; status: number; message: string | null };

async function send<T>(fetcher: Fetch, path: string, method: string, body?: unknown, okStatus?: number): Promise<Reply<T>> {
  const response = await fetcher(path, {
    method,
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  const ok = okStatus === undefined ? response.ok : response.status === okStatus;
  const json: unknown = response.status === 204 ? null : await response.json().catch(() => null);
  if (ok) return { ok: true, body: json as T };
  return { ok: false, status: response.status, message: (json as Partial<ErrorResponse> | null)?.message ?? null };
}

export function createClient(fetcher: Fetch) {
  return {
    runtime: () => send<RuntimeInfo>(fetcher, "/api/runtime", "GET"),
    configurations: () => send<ConfigurationSummary[]>(fetcher, "/api/configurations", "GET"),
    access: (body: AccessRequest) => send<null>(fetcher, "/api/access", "POST", body, 204),
    createSession: (body: CreateSessionRequest) =>
      send<CreateSessionResponse>(fetcher, "/api/sessions", "POST", body),
    resume: (body: ResumeRequest) => send<ResumeResponse>(fetcher, "/api/resume", "POST", body),
    snapshot: (sessionId: string) =>
      send<SessionSnapshotResponse>(fetcher, `/api/sessions/${sessionId}`, "GET"),
    turn: (sessionId: string, body: TurnRequest) =>
      send<unknown>(fetcher, `/api/sessions/${sessionId}/turns`, "POST", body, 202),
    answer: (sessionId: string, confirmationId: string, body: ConfirmationAnswer) =>
      send<unknown>(fetcher, `/api/sessions/${sessionId}/confirmations/${confirmationId}`, "POST", body, 202),
    startVoice: (sessionId: string) =>
      send<VoiceStartResponse>(fetcher, `/api/sessions/${sessionId}/voice`, "POST"),
    voiceTiming: (sessionId: string, body: VoiceTimingReport) =>
      send<null>(fetcher, `/api/sessions/${sessionId}/voice/timings`, "POST", body),
    end: (sessionId: string) => send<null>(fetcher, `/api/sessions/${sessionId}/end`, "POST", undefined, 204),
    remove: (sessionId: string) => send<null>(fetcher, `/api/sessions/${sessionId}`, "DELETE", undefined, 204),
  };
}

export type Client = ReturnType<typeof createClient>;

// EventSource only delivers the event names it listens for. A record keyed by the payload union
// makes the compiler fail when the server adds an event the page does not listen for.
const STREAM_EVENT_NAMES: Record<SessionEvent["payload"]["type"], true> = {
  turn_started: true,
  assistant_text: true,
  tool_started: true,
  tool_finished: true,
  state_updated: true,
  sources_shown: true,
  signal_recorded: true,
  turn_finished: true,
  turn_failed: true,
  voice_state: true,
};
export const STREAM_EVENTS = Object.keys(STREAM_EVENT_NAMES);
