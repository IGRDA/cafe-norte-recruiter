// Hosted voice for the page (D22, D45): join the session's Daily room; STT, VAD, barge-in and TTS
// run on the server (D01). The page only carries audio and reports timings. app.js uses three
// calls: start(), stop() and closing(); everything else arrives through the callbacks.

const GOODBYE_TIMEOUT_MS = 20000; // Ana's goodbye is one or two sentences

export function createVoice({ onStatus, onError, startVoice, postTiming }) {
  let call = null;
  let audio = null;
  const t0 = performance.now();
  const ms = () => Math.round(performance.now() - t0);

  async function start() {
    onStatus("Conectando…");
    let grant;
    try {
      grant = await startVoice(); // POST /api/sessions/{id}/voice → room_url, candidate_token
    } catch (error) {
      onError(error.message || "No se pudo iniciar la voz.");
      return;
    }
    const { default: Daily } = await import("/vendor/daily-js.esm.js");
    call = Daily.createCallObject({ audioSource: true, videoSource: false });
    call.on("joined-meeting", () => {
      onStatus("Conectada. Escuchando…");
      postTiming("connected", ms());
    });
    call.on("track-started", (event) => {
      if (event.participant?.local || event.track.kind !== "audio") return;
      audio = audio ?? new Audio();
      audio.autoplay = true;
      audio.srcObject = new MediaStream([event.track]);
      postTiming("first_audio", ms());
      audio
        .play()
        .then(() => onStatus("Audio de Ana activo. Escuchando…"))
        .catch((error) => onError(`El navegador bloqueó el audio de Ana (${error.name}). Pulsa en la página y vuelve a intentarlo.`));
    });
    // The local microphone track state is the one diagnostic the server cannot see: a
    // "blocked" or "off" track means no audio ever reaches Ana.
    call.on("participant-updated", (event) => {
      if (!event.participant?.local) return;
      const track = event.participant.tracks?.audio;
      if (!track) return;
      if (track.state === "playable" || track.state === "sendable") {
        onStatus("Conectada. Micrófono activo. Escuchando…");
      } else {
        const reason = track.blocked ? Object.keys(track.blocked).join(", ") : track.off ? Object.keys(track.off).join(", ") : "";
        onError(`Micrófono ${track.state}${reason ? ` (${reason})` : ""}: Ana no te oye. Revisa el permiso del micrófono o la VPN.`);
      }
    });
    call.on("camera-error", (event) => {
      onError(`Error de micrófono: ${event.errorMsg?.errorMsg ?? event.error?.type ?? "desconocido"}.`);
    });
    call.on("nonfatal-error", (event) => {
      if (event.type) onStatus(`Aviso de la llamada: ${event.type}`);
    });
    call.on("participant-left", (event) => {
      if (!event.participant?.local) onStatus("Ana ha salido de la sala.");
    });
    call.on("left-meeting", () => onStatus("Llamada terminada."));
    call.on("error", (event) => onError(`Error de la llamada: ${event.errorMsg ?? "desconocido"}`));
    try {
      await call.join({ url: grant.room_url, token: grant.candidate_token });
    } catch (error) {
      onError("No se pudo entrar en la sala. Puedes seguir por texto.");
    }
  }

  // The session ended: Ana says goodbye and leaves the room herself once it has played, so the
  // page waits for her and only leaves on its own if she never does.
  async function closing() {
    if (!call) return;
    const left = new Promise((resolve) => call.on("participant-left", (event) => event.participant?.local || resolve()));
    await Promise.race([left, new Promise((resolve) => setTimeout(resolve, GOODBYE_TIMEOUT_MS))]);
    await stop();
  }

  async function stop() {
    if (call) {
      await call.leave().catch(() => {});
      await call.destroy().catch(() => {});
      call = null;
    }
    if (audio) {
      audio.srcObject = null;
      audio = null;
    }
  }

  return { start, stop, closing };
}
