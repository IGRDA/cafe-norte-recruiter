// The effect runner: performs what the reducer asked for and dispatches what came back. Only
// I/O lives here (fetch, EventSource, Daily, the address bar, focus); every rule is in reducer.ts.
import { createClient, STREAM_EVENTS, type Fetch } from "../api/client";
import type { SessionEvent } from "../api/contracts";
import type { Voice, VoiceCallbacks } from "../voice";
import type { Action, Effect } from "./reducer";

export type Dispatch = (action: Action) => void;

/** Everything the runner touches in the browser, so tests can hand it fakes. */
export interface Ports {
  fetch: Fetch;
  openStream: (url: string) => EventSource;
  createVoice: (callbacks: VoiceCallbacks) => Voice;
  confirm: (question: string) => boolean;
  clearFragment: () => void;
  navigate: (search: string) => void;
  focus: (id: string) => void;
  newId: () => string;
}

export interface Runner {
  run: (effect: Effect) => void;
  dispose: () => void;
}

const OFFLINE = "Sin conexión con el servidor.";

export function createRunner(ports: Ports, dispatch: Dispatch): Runner {
  const api = createClient(ports.fetch);
  let stream: EventSource | null = null;
  let voice: Voice | null = null;

  async function perform(effect: Effect): Promise<void> {
    switch (effect.type) {
      case "load-boot": {
        const [runtime, stores] = await Promise.all([
          api.runtime().catch(() => null),
          api.configurations().catch(() => null),
        ]);
        dispatch({
          type: "booted",
          voiceOffered: runtime?.ok === true && runtime.body.voice === "pipecat",
          stores: stores?.ok ? stores.body : [],
        });
        return;
      }
      case "clear-fragment":
        ports.clearFragment();
        return;
      case "check-code": {
        const reply = await api.access({ code: effect.code }).catch(() => null);
        dispatch(reply?.ok ? { type: "access-granted" } : { type: "access-refused" });
        return;
      }
      case "create-session": {
        const reply = await api
          .createSession({ config_id: effect.store, language: effect.language, channel: "text" })
          .catch(() => null);
        if (reply?.ok) dispatch({ type: "session-opened", body: reply.body });
        else if (reply?.status === 401) dispatch({ type: "session-needs-code" });
        else dispatch({ type: "session-failed" });
        return;
      }
      case "resume": {
        const reply = await api.resume({ token: effect.token }).catch(() => null);
        dispatch(reply?.ok ? { type: "resumed", sessionId: reply.body.session_id } : { type: "resume-failed" });
        return;
      }
      case "load-snapshot": {
        const reply = await api.snapshot(effect.sessionId).catch(() => null);
        if (reply?.ok) dispatch({ type: "snapshot-loaded", snapshot: reply.body });
        return;
      }
      case "open-stream": {
        stream?.close();
        const source = ports.openStream(`/api/sessions/${effect.sessionId}/events`);
        stream = source;
        for (const name of STREAM_EVENTS) {
          source.addEventListener(name, (message) => {
            const event = JSON.parse((message as MessageEvent<string>).data) as SessionEvent;
            dispatch({ type: "event-received", event });
          });
        }
        source.onerror = () => dispatch({ type: "stream-failed" });
        source.onopen = () => dispatch({ type: "stream-opened" });
        return;
      }
      case "post-turn": {
        const reply = await api.turn(effect.sessionId, { input_id: ports.newId(), text: effect.text }).catch(() => null);
        if (reply?.ok) dispatch({ type: "turn-accepted" });
        else dispatch({ type: "turn-rejected", message: reply ? (reply.message ?? "No se pudo enviar el mensaje.") : OFFLINE });
        return;
      }
      case "post-answer": {
        const reply = await api
          .answer(effect.sessionId, effect.confirmationId, {
            input_id: ports.newId(),
            answer: effect.answer,
            expected_revision: effect.revision,
          })
          .catch(() => null);
        if (reply?.ok) dispatch({ type: "answer-accepted" });
        else
          dispatch({
            type: "answer-rejected",
            message: reply ? (reply.message ?? "No se pudo enviar tu respuesta.") : OFFLINE,
          });
        return;
      }
      case "start-voice": {
        const { sessionId } = effect;
        voice = ports.createVoice({
          onJoined: () => dispatch({ type: "voice-joined" }),
          onStatus: (text) => dispatch({ type: "voice-status", text }),
          onError: (message) => dispatch({ type: "voice-error", message }),
          startVoice: async () => {
            const reply = await api.startVoice(sessionId);
            if (!reply.ok) throw new Error(reply.message ?? "No se pudo iniciar la voz.");
            return reply.body;
          },
          postTiming: (event, monotonic_ms) => {
            api.voiceTiming(sessionId, { turn_id: null, event, monotonic_ms }).catch(() => {});
          },
        });
        if (!(await voice.start())) dispatch({ type: "voice-failed" });
        return;
      }
      case "stop-voice": {
        const current = voice;
        voice = null;
        await current?.stop();
        return;
      }
      case "close-voice": {
        const current = voice;
        voice = null;
        await current?.closing();
        dispatch({ type: "voice-closed" });
        return;
      }
      case "end-session": {
        const reply = await api.end(effect.sessionId).catch(() => null);
        dispatch(reply?.ok ? { type: "end-accepted" } : { type: "end-rejected" });
        return;
      }
      case "delete-session": {
        const reply = await api.remove(effect.sessionId).catch(() => null);
        dispatch(reply?.ok ? { type: "deleted" } : { type: "delete-rejected" });
        return;
      }
      case "ask":
        if (ports.confirm(effect.question)) dispatch(effect.then);
        return;
      case "navigate":
        ports.navigate(new URLSearchParams({ store: effect.store, lang: effect.language }).toString());
        return;
      case "focus":
        ports.focus(effect.target);
        return;
    }
  }

  return {
    run: (effect) => void perform(effect),
    dispose: () => {
      stream?.close();
      stream = null;
      void voice?.stop();
      voice = null;
    },
  };
}
