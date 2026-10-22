// The page's logic in one pure function (D61): (state, action, exec) => state. Actions are what
// happened (a click, a server reply, a stream event); effects are what the page asks the outside
// world to do, run by effects.ts. Nothing here touches the DOM, fetch, EventSource or Daily, so
// every rule is tested without a browser. Components read selectors and dispatch actions.
import type {
  ConfigurationSummary,
  CreateSessionResponse,
  SessionEvent,
  RuntimeInfo,
  SessionSnapshotResponse,
  Signal,
  SourcesShown,
  StateUpdated,
  VersionStamp,
} from "../api/contracts";
import type { Language } from "../api/client";
import { finishedTurn, sourceLines, TERMINAL } from "./format";

// ---- state ---------------------------------------------------------------------------------

/** Where the page is. Each phase allows a fixed set of actions; the rest are ignored. */
export type Page =
  | "loading" // booting, or creating / resuming a session
  | "gate" // the shared access code is needed
  | "choosing" // no store chosen yet: nothing is created until Empezar
  | "active"
  | "ended" // the session reached a terminal state; the export is offered
  | "deleted"
  | "failed"; // nothing more can happen without a reload

/** off → connecting → live → (closing →) off. Never on without an active session. */
export type Voice = "off" | "connecting" | "live" | "closing";

export type Access = "idle" | "checking" | "refused";

export interface Bubble {
  id: string;
  role: "user" | "assistant";
  sentences: string[];
}

/** The classifier's reading of one candidate message (D62): advisory, never a hiring input. */
export interface SignalPoint {
  turnId: string;
  sentiment: Signal["sentiment"];
  probabilities: Signal["probabilities"]; // null from a label-only classifier
  switchTo: Signal["language_switch_to"];
}

export type SignalsMode = RuntimeInfo["signals"];

/** One collapsed reviewer entry per turn and one for the session itself. */
export interface ReviewEntry {
  key: string; // turn id, or "session"
  label: string;
  detail: string; // "· 812 ms · 1200 tokens" once the turn finished
  lines: string[];
}

export interface State {
  page: Page;
  voice: Voice;
  access: Access;
  // From the address: ?store= and ?lang= open a session, #resume= resumes one, #code= is the
  // shared access code (D60), checked before anything else.
  requested: { store: string | null; language: Language; resumeToken: string | null; code: string | null };
  voiceOffered: boolean;
  signalsMode: SignalsMode;
  stores: ConfigurationSummary[];
  chooser: { store: string; language: Language };
  sessionId: string | null;
  sessionStore: string | null;
  language: Language;
  resumeUrl: string | null; // shown once, when the session is created
  versions: VersionStamp | null;
  lastSeq: number;
  status: string;
  error: string | null;
  draft: string;
  sending: boolean;
  answering: boolean;
  transcript: Bubble[];
  candidate: StateUpdated | null;
  sources: SourcesShown | null;
  reviews: ReviewEntry[];
  turnCount: number;
  signals: SignalPoint[]; // the last MAX_SIGNAL_POINTS candidate messages
  lastUserTurn: string | null; // the latest turn that carried candidate words
}

export const MAX_REVIEW_ENTRIES = 40;
export const MAX_SIGNAL_POINTS = 12;
const GATE = "Introduce el código de acceso de la demostración.";

export function initial(requested: State["requested"]): State {
  return {
    page: "loading",
    voice: "off",
    access: "idle",
    requested,
    voiceOffered: false,
    signalsMode: "off",
    stores: [],
    chooser: { store: requested.store ?? "", language: requested.language },
    sessionId: null,
    sessionStore: null,
    language: requested.language,
    resumeUrl: null,
    versions: null,
    lastSeq: 0,
    status: "Conectando…",
    error: null,
    draft: "",
    sending: false,
    answering: false,
    transcript: [],
    candidate: null,
    sources: null,
    reviews: [],
    turnCount: 0,
    signals: [],
    lastUserTurn: null,
  };
}

// ---- actions -------------------------------------------------------------------------------

export type Action =
  // Boot
  | { type: "booted"; voiceOffered: boolean; signalsMode: SignalsMode; stores: ConfigurationSummary[] }
  // Access
  | { type: "code-submitted"; code: string }
  | { type: "access-granted" }
  | { type: "access-refused" }
  // Chooser
  | { type: "chooser-changed"; store?: string; language?: Language }
  | { type: "chooser-submitted" }
  // Session
  | { type: "session-opened"; body: CreateSessionResponse }
  | { type: "session-needs-code" }
  | { type: "session-failed" }
  | { type: "resumed"; sessionId: string }
  | { type: "resume-failed" }
  | { type: "snapshot-loaded"; snapshot: SessionSnapshotResponse }
  // Stream
  | { type: "event-received"; event: SessionEvent }
  | { type: "stream-opened" }
  | { type: "stream-failed" }
  // Turn
  | { type: "draft-changed"; text: string }
  | { type: "text-submitted" }
  | { type: "turn-accepted" }
  | { type: "turn-rejected"; message: string }
  // Confirmation
  | { type: "confirmation-answered"; answer: "affirm" | "deny" }
  | { type: "answer-accepted" }
  | { type: "answer-rejected"; message: string }
  // Voice
  | { type: "talk-pressed" }
  | { type: "voice-joined" }
  | { type: "voice-status"; text: string }
  | { type: "voice-error"; message: string }
  | { type: "voice-failed" }
  | { type: "voice-closed" }
  // Lifecycle
  | { type: "end-pressed" }
  | { type: "end-confirmed" }
  | { type: "end-accepted" }
  | { type: "end-rejected" }
  | { type: "delete-pressed" }
  | { type: "delete-confirmed" }
  | { type: "deleted" }
  | { type: "delete-rejected" };

// ---- effects -------------------------------------------------------------------------------

export type Effect =
  | { type: "load-boot" }
  | { type: "clear-fragment" }
  | { type: "check-code"; code: string }
  | { type: "create-session"; store: string; language: Language }
  | { type: "resume"; token: string }
  | { type: "load-snapshot"; sessionId: string }
  | { type: "open-stream"; sessionId: string }
  | { type: "post-turn"; sessionId: string; text: string }
  | {
      type: "post-answer";
      sessionId: string;
      confirmationId: string;
      answer: "affirm" | "deny";
      revision: number;
    }
  | { type: "start-voice"; sessionId: string }
  | { type: "stop-voice" }
  | { type: "close-voice" } // the session ended: wait for Ana's goodbye, then leave
  | { type: "end-session"; sessionId: string }
  | { type: "delete-session"; sessionId: string }
  | { type: "ask"; question: string; then: Action } // window.confirm, then dispatch
  | { type: "navigate"; store: string; language: Language }
  | { type: "focus"; target: "code" | "text" };

export type Exec = (effect: Effect) => void;

// ---- reducer -------------------------------------------------------------------------------

export function reduce(state: State, action: Action, exec: Exec): State {
  switch (action.type) {
    // Boot
    case "booted": {
      if (state.page !== "loading") return state;
      const next: State = {
        ...state,
        voiceOffered: action.voiceOffered,
        signalsMode: action.signalsMode,
        stores: action.stores,
        chooser: { ...state.chooser, store: state.chooser.store || action.stores[0]?.config_id || "" },
      };
      const { code, resumeToken } = state.requested;
      if (code || resumeToken) exec({ type: "clear-fragment" }); // a secret never stays in the bar
      if (code) {
        exec({ type: "check-code", code });
        return { ...next, access: "checking" };
      }
      return proceed(next, exec);
    }

    // Access
    case "code-submitted": {
      if (state.page !== "gate" || state.access === "checking") return state;
      const code = action.code.trim();
      if (!code) return state;
      exec({ type: "check-code", code });
      return { ...state, access: "checking" };
    }
    case "access-granted":
      if (state.access !== "checking") return state;
      return proceed({ ...state, access: "idle", error: null, page: "loading" }, exec);
    case "access-refused":
      // A wrong code in the link lands on the form, as a wrong typed one does.
      if (state.access !== "checking") return state;
      if (state.page !== "gate") exec({ type: "focus", target: "code" });
      return { ...state, page: "gate", access: "refused", error: "Código incorrecto.", status: GATE };

    // Chooser
    case "chooser-changed":
      return {
        ...state,
        chooser: {
          store: action.store ?? state.chooser.store,
          language: action.language ?? state.chooser.language,
        },
      };
    case "chooser-submitted":
      if (!state.chooser.store) return state;
      exec({ type: "navigate", store: state.chooser.store, language: state.chooser.language });
      return state;

    // Session
    case "session-opened": {
      if (state.page !== "loading") return state;
      const { body } = action;
      exec({ type: "open-stream", sessionId: body.session_id });
      exec({ type: "focus", target: "text" });
      return review(
        {
          ...state,
          page: "active",
          sessionId: body.session_id,
          sessionStore: state.requested.store,
          resumeUrl: body.resume_url,
          versions: body.versions,
          status: "Conectada.",
        },
        "enlace privado de reanudación emitido (válido 7 días)",
      );
    }
    case "session-needs-code":
      if (state.page !== "loading") return state;
      exec({ type: "focus", target: "code" });
      return { ...state, page: "gate", status: GATE };
    case "session-failed":
      if (state.page !== "loading") return state;
      return { ...state, page: "failed", error: "No se pudo crear la conversación. Recarga la página." };
    case "resumed": {
      if (state.page !== "loading") return state;
      exec({ type: "load-snapshot", sessionId: action.sessionId });
      exec({ type: "open-stream", sessionId: action.sessionId });
      return review(
        { ...state, page: "active", sessionId: action.sessionId, status: "Conversación recuperada." },
        "conversación recuperada con el enlace privado",
      );
    }
    case "resume-failed": {
      if (state.page !== "loading") return state;
      const next = openOrChoose(state, exec);
      return { ...next, error: "Este enlace ya no es válido. Empieza una conversación nueva." };
    }
    case "snapshot-loaded": {
      // After a resume the page knows the session only by its cookie: the snapshot says which
      // store and language it was, and the versions it ran with.
      const { snapshot } = action;
      if (snapshot.session_id !== state.sessionId) return state;
      return {
        ...state,
        sessionStore: snapshot.state.config_id,
        language: snapshot.state.language,
        chooser: { store: snapshot.state.config_id, language: snapshot.state.language },
        versions: snapshot.versions,
      };
    }

    // Stream
    case "event-received":
      return received(state, action.event, exec);
    case "stream-opened":
      return state.lastSeq && isLive(state) ? { ...state, status: "Conectada de nuevo." } : state;
    case "stream-failed":
      return isLive(state) ? { ...state, status: "Reconectando…" } : state;

    // Turn
    case "draft-changed":
      return { ...state, draft: action.text };
    case "text-submitted": {
      const text = state.draft.trim();
      if (state.page !== "active" || state.sending || !text || !state.sessionId) return state;
      exec({ type: "post-turn", sessionId: state.sessionId, text });
      // "Sent" is said now: the stream can finish the turn before the POST's reply arrives.
      return { ...state, sending: true, error: null, status: "Enviado…" };
    }
    case "turn-accepted":
      if (isLive(state)) exec({ type: "focus", target: "text" });
      return { ...state, sending: false, draft: "" };
    case "turn-rejected":
      return yourTurn({ ...state, sending: false, error: action.message });

    // Confirmation: the card's Sí / No, an explicit answer at the revision on screen. The server
    // runs it through the same rules as a spoken answer; the stream shows the result.
    case "confirmation-answered": {
      const update = state.candidate;
      const pending = update?.pending_confirmation;
      if (!canAnswer(state) || !update || !pending || !state.sessionId) return state;
      exec({
        type: "post-answer",
        sessionId: state.sessionId,
        confirmationId: pending.confirmation_id,
        answer: action.answer,
        revision: update.revision,
      });
      return { ...state, answering: true, error: null, status: "Enviado…" };
    }
    case "answer-accepted":
      return state;
    case "answer-rejected":
      return yourTurn({ ...state, answering: false, error: action.message });

    // Voice
    case "talk-pressed":
      if (state.voice === "off") {
        if (!canTalk(state) || !state.sessionId) return state;
        exec({ type: "start-voice", sessionId: state.sessionId });
        return { ...state, voice: "connecting", error: null, status: "Conectando…" };
      }
      if (state.voice === "connecting" || state.voice === "live") {
        exec({ type: "stop-voice" });
        return { ...state, voice: "off", status: "Tu turno." };
      }
      return state;
    case "voice-joined":
      return state.voice === "connecting" ? { ...state, voice: "live" } : state;
    case "voice-status":
      return state.voice === "off" || !isLive(state) ? state : { ...state, status: action.text };
    case "voice-error":
      return state.voice === "off" ? state : { ...state, error: action.message };
    case "voice-failed":
      return state.voice === "connecting" ? { ...state, voice: "off" } : state;
    case "voice-closed":
      return { ...state, voice: "off" };

    // Lifecycle
    case "end-pressed":
      if (state.page !== "active") return state;
      exec({ type: "ask", question: "¿Terminar la conversación?", then: { type: "end-confirmed" } });
      return state;
    case "end-confirmed":
      if (state.page !== "active" || !state.sessionId) return state;
      exec({ type: "end-session", sessionId: state.sessionId });
      return state;
    case "end-accepted":
      return ended(state, exec);
    case "end-rejected":
      return { ...state, error: "No se pudo terminar la conversación." };
    case "delete-pressed":
      if (!canDelete(state)) return state;
      exec({
        type: "ask",
        question: "¿Borrar esta conversación y todos sus datos?",
        then: { type: "delete-confirmed" },
      });
      return state;
    case "delete-confirmed":
      if (!canDelete(state) || !state.sessionId) return state;
      exec({ type: "delete-session", sessionId: state.sessionId });
      return state;
    case "deleted":
      // The session, its export, its link and its simulated reservation go together.
      if (state.voice !== "off") exec({ type: "stop-voice" });
      return {
        ...state,
        page: "deleted",
        voice: "off",
        resumeUrl: null,
        status: "Conversación borrada. Recarga la página para empezar otra.",
      };
    case "delete-rejected":
      return { ...state, error: "No se pudo borrar la conversación." };
  }
}

// ---- helpers -------------------------------------------------------------------------------

// Past the gate: a resume link resumes, a chosen store opens a session, otherwise the chooser.
function proceed(state: State, exec: Exec): State {
  const { resumeToken } = state.requested;
  if (!resumeToken) return openOrChoose(state, exec);
  exec({ type: "resume", token: resumeToken });
  return { ...state, page: "loading" };
}

// A chosen store opens a session; otherwise the chooser waits for Empezar.
function openOrChoose(state: State, exec: Exec): State {
  const { store, language } = state.requested;
  if (store && state.stores.some((s) => s.config_id === store)) {
    exec({ type: "create-session", store, language });
    return { ...state, page: "loading" };
  }
  if (!state.stores.length) {
    return { ...state, page: "failed", error: "No se pudieron cargar las tiendas. Recarga la página." };
  }
  return { ...state, page: "choosing", status: "Elige una tienda y pulsa Empezar." };
}

// The goodbye arrives after the terminal state: Ana says it and hangs up, the page freezes now.
function ended(state: State, exec: Exec): State {
  if (state.page !== "active") return state;
  const voiceOn = state.voice === "connecting" || state.voice === "live";
  if (voiceOn) exec({ type: "close-voice" });
  return {
    ...state,
    page: "ended",
    voice: voiceOn ? "closing" : state.voice,
    answering: false,
    status: "Conversación terminada. Gracias.",
  };
}

function yourTurn(state: State): State {
  if (!isLive(state)) return state;
  const listening = state.voice === "connecting" || state.voice === "live";
  return { ...state, status: listening ? "Escuchando…" : "Tu turno." };
}

function received(state: State, event: SessionEvent, exec: Exec): State {
  if (event.seq <= state.lastSeq) return state; // replayed after a reconnect
  state = { ...state, lastSeq: event.seq };
  const turnId = event.turn_id;
  const payload = event.payload;
  switch (payload.type) {
    case "turn_started": {
      // The stream carries the user's words: bubbles never depend on the POST reply's timing.
      const turnCount = state.turnCount + 1;
      const bubbles: Bubble[] = payload.text
        ? [{ id: `${turnId}:user`, role: "user", sentences: [payload.text] }]
        : [];
      bubbles.push({ id: payload.turn_id, role: "assistant", sentences: [] });
      state = labelReview(
        { ...state, turnCount, lastUserTurn: payload.text ? payload.turn_id : state.lastUserTurn },
        turnId,
        `Turno ${turnCount}`,
      );
      state = { ...state, transcript: [...state.transcript, ...bubbles] };
      return isLive(state) ? { ...state, status: "Ana está pensando…" } : state;
    }
    case "assistant_text": {
      const id = turnId ?? "";
      const known = state.transcript.some((b) => b.id === id);
      const transcript = known
        ? state.transcript.map((b) =>
            b.id === id ? { ...b, sentences: [...b.sentences, payload.text] } : b,
          )
        : [...state.transcript, { id, role: "assistant" as const, sentences: [payload.text] }];
      state = { ...state, transcript };
      return isLive(state) ? { ...state, status: "Ana está hablando…" } : state;
    }
    case "sources_shown":
      return review({ ...state, sources: payload }, sourceLines(payload), turnId);
    case "signal_recorded": {
      const { signal } = payload;
      const evidence = signal.evidence_text ? ` («${signal.evidence_text}»)` : "";
      const point: SignalPoint = {
        turnId: signal.turn_id,
        sentiment: signal.sentiment,
        probabilities: signal.probabilities,
        switchTo: signal.language_switch_to,
      };
      const signals = [...state.signals.filter((s) => s.turnId !== point.turnId), point];
      return review(
        { ...state, signals: signals.slice(-MAX_SIGNAL_POINTS) },
        `señal del turno: ${signal.sentiment}${evidence}`,
        turnId,
      );
    }
    case "tool_started":
      return review(state, `herramienta ${payload.name}(${payload.arguments}) → iniciada`, turnId);
    case "tool_finished":
      return review(
        state,
        `herramienta ${payload.name} → ${payload.ok ? "ok" : "rechazada"} (${payload.summary})`,
        turnId,
      );
    case "state_updated": {
      state = review(
        { ...state, candidate: payload, answering: false, language: payload.language ?? state.language },
        `estado guardado, revisión ${payload.revision}`,
        turnId,
      );
      return TERMINAL.has(payload.lifecycle) ? ended(state, exec) : state;
    }
    case "turn_finished": {
      const { detail, lines } = finishedTurn(payload);
      state = review({ ...state, error: null, answering: false }, lines, turnId);
      state = {
        ...state,
        reviews: state.reviews.map((r) => (r.key === (turnId ?? "session") ? { ...r, detail } : r)),
      };
      return yourTurn(state);
    }
    case "turn_failed": {
      state = review(
        { ...state, error: payload.message, answering: false },
        `turno fallido · ${payload.code}`,
        turnId,
      );
      if (payload.code === "session_ended") state = ended(state, exec);
      return yourTurn(state);
    }
    case "voice_state":
      return review(state, `evento ${payload.type}`, turnId);
  }
}

function review(state: State, lines: string | string[], turnId: string | null = null): State {
  const key = turnId ?? "session";
  const added = typeof lines === "string" ? [lines] : lines;
  const known = state.reviews.some((r) => r.key === key);
  const reviews = known
    ? state.reviews.map((r) => (r.key === key ? { ...r, lines: [...r.lines, ...added] } : r))
    : [...state.reviews, { key, label: turnId ? "Turno" : "Sesión", detail: "", lines: added }];
  return { ...state, reviews: reviews.slice(-MAX_REVIEW_ENTRIES) };
}

function labelReview(state: State, turnId: string | null, label: string): State {
  const key = turnId ?? "session";
  const withEntry = state.reviews.some((r) => r.key === key) ? state : review(state, [], turnId);
  return {
    ...withEntry,
    reviews: withEntry.reviews.map((r) => (r.key === key ? { ...r, label } : r)),
  };
}

// ---- selectors -----------------------------------------------------------------------------

/** The session is open and nothing has frozen it. */
export function isLive(state: State): boolean {
  return state.page === "active";
}

export function canType(state: State): boolean {
  return state.page === "active";
}

export function canSend(state: State): boolean {
  return state.page === "active" && !state.sending;
}

export function canTalk(state: State): boolean {
  return state.page === "active" && state.voiceOffered;
}

export function talkPressed(state: State): boolean {
  return state.voice === "connecting" || state.voice === "live";
}

export function showAccess(state: State): boolean {
  return state.page === "gate";
}

export function confirmationOpen(state: State): boolean {
  return state.page === "active" && state.candidate?.pending_confirmation?.status === "pending";
}

export function canAnswer(state: State): boolean {
  return confirmationOpen(state) && !state.answering;
}

export function canEnd(state: State): boolean {
  return state.page === "active" && state.sessionId !== null;
}

export function canDelete(state: State): boolean {
  return (state.page === "active" || state.page === "ended") && state.sessionId !== null;
}

export function exportHref(state: State): string | null {
  return state.page === "ended" && state.sessionId ? `/api/sessions/${state.sessionId}/export` : null;
}

export function storeName(state: State): string {
  const id = state.sessionStore;
  return state.stores.find((s) => s.config_id === id)?.store_name ?? "Café Norte";
}

export function startLabel(state: State): string {
  return state.sessionId ? "Nueva conversación" : "Empezar";
}

export function latestSignal(state: State): SignalPoint | null {
  return state.signals.at(-1) ?? null;
}

/** off: no classifier runs; idle: nothing said yet; waiting: the latest message has no
 * verdict yet (a late or failed call never gets one); ready: the latest message's is shown. */
export function signalStatus(state: State): "off" | "idle" | "waiting" | "ready" {
  if (state.signalsMode === "off") return "off";
  if (!state.lastUserTurn) return "idle";
  return state.signals.some((s) => s.turnId === state.lastUserTurn) ? "ready" : "waiting";
}
