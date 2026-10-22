// Hosted voice for the page: join the session's Daily room; STT, VAD, barge-in and TTS
// run on the server. The page only carries audio and reports timings. The effect runner
// uses three calls: start(), stop() and closing(); everything else arrives through callbacks.
import type { DailyCall } from "@daily-co/daily-js";
import type { VoiceStartResponse, VoiceTimingReport } from "./api/contracts";

const GOODBYE_TIMEOUT_MS = 20000; // Ana's goodbye is one or two sentences

export interface VoiceCallbacks {
  onJoined: () => void;
  onStatus: (text: string) => void;
  onError: (message: string) => void;
  startVoice: () => Promise<VoiceStartResponse>; // POST /api/sessions/{id}/voice
  postTiming: (event: VoiceTimingReport["event"], monotonicMs: number) => void;
}

export interface Voice {
  /** Resolves false when no call was joined; the page goes back to text. */
  start: () => Promise<boolean>;
  stop: () => Promise<void>;
  closing: () => Promise<void>;
}

export function createVoice({ onJoined, onStatus, onError, startVoice, postTiming }: VoiceCallbacks): Voice {
  let call: DailyCall | null = null;
  let audio: HTMLAudioElement | null = null;
  const t0 = performance.now();
  const ms = () => Math.round(performance.now() - t0);

  async function start(): Promise<boolean> {
    let grant: VoiceStartResponse;
    try {
      grant = await startVoice();
    } catch (error) {
      onError(error instanceof Error && error.message ? error.message : "No se pudo iniciar la voz.");
      return false;
    }
    const { default: Daily } = await import("@daily-co/daily-js");
    const joined = Daily.createCallObject({ audioSource: true, videoSource: false });
    call = joined;
    joined.on("joined-meeting", () => {
      onJoined();
      onStatus("Conectada. Escuchando…");
      postTiming("connected", ms());
    });
    joined.on("track-started", (event) => {
      if (event.participant?.local || event.track.kind !== "audio") return;
      audio = audio ?? new Audio();
      audio.autoplay = true;
      audio.srcObject = new MediaStream([event.track]);
      postTiming("first_audio", ms());
      audio
        .play()
        .then(() => onStatus("Audio de Ana activo. Escuchando…"))
        .catch((error: Error) =>
          onError(`El navegador bloqueó el audio de Ana (${error.name}). Pulsa en la página y vuelve a intentarlo.`),
        );
    });
    // The local microphone track state is the one diagnostic the server cannot see: a
    // "blocked" or "off" track means no audio ever reaches Ana.
    joined.on("participant-updated", (event) => {
      if (!event.participant.local) return;
      const track = event.participant.tracks.audio;
      if (track.state === "playable" || track.state === "sendable") {
        onStatus("Conectada. Micrófono activo. Escuchando…");
      } else {
        const reasons = track.blocked ?? track.off;
        const reason = reasons ? Object.keys(reasons).join(", ") : "";
        onError(
          `Micrófono ${track.state}${reason ? ` (${reason})` : ""}: Ana no te oye. Revisa el permiso del micrófono o la VPN.`,
        );
      }
    });
    joined.on("camera-error", (event) => {
      onError(`Error de micrófono: ${event.errorMsg.errorMsg ?? event.error?.type ?? "desconocido"}.`);
    });
    joined.on("nonfatal-error", (event) => {
      if (event.type) onStatus(`Aviso de la llamada: ${event.type}`);
    });
    joined.on("participant-left", (event) => {
      if (!event.participant.local) onStatus("Ana ha salido de la sala.");
    });
    joined.on("left-meeting", () => onStatus("Llamada terminada."));
    joined.on("error", (event) => onError(`Error de la llamada: ${event.errorMsg ?? "desconocido"}`));
    try {
      await joined.join({ url: grant.room_url, token: grant.candidate_token });
      return true;
    } catch {
      onError("No se pudo entrar en la sala. Puedes seguir por texto.");
      await stop();
      return false;
    }
  }

  // The session ended: Ana says goodbye and leaves the room herself once it has played, so the
  // page waits for her and only leaves on its own if she never does.
  async function closing(): Promise<void> {
    const current = call;
    if (!current) return;
    const left = new Promise<void>((resolve) =>
      current.on("participant-left", (event) => {
        if (!event.participant.local) resolve();
      }),
    );
    await Promise.race([left, new Promise((resolve) => setTimeout(resolve, GOODBYE_TIMEOUT_MS))]);
    await stop();
  }

  async function stop(): Promise<void> {
    if (call) {
      const current = call;
      call = null;
      await current.leave().catch(() => {});
      await current.destroy().catch(() => {});
    }
    if (audio) {
      audio.srcObject = null;
      audio = null;
    }
  }

  return { start, stop, closing };
}
