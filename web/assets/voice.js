// Voice for the page, in two modes chosen by the server (GET /api/runtime):
//   pipecat  hosted voice: join the session's Daily room; STT, VAD, barge-in and TTS run on the
//            server (D01). The browser only carries audio and reports timings.
//   browser  the Web Speech API, free and local, kept until hosted voice is verified (D18).
// Both expose the same small surface to app.js: supported, start(), stop(), speak(), turnEnded(),
// closing(), setLanguage(), and events through the callbacks.

const LOCALES = { es: "es-ES", en: "en-GB" };

export function createVoice(options) {
  return options.mode === "pipecat" ? createDailyVoice(options) : createBrowserVoice(options);
}

// ---- hosted voice through Daily ------------------------------------------------------------------

function createDailyVoice({ onStatus, onError, startVoice, postTiming }) {
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

  return {
    supported: true,
    start,
    stop,
    speak() {}, // the server speaks
    turnEnded() {},
    setLanguage() {}, // the server's STT is multilingual and TTS follows the text
    closing() {
      stop();
    },
  };
}

// ---- browser speech (temporary, D18) ---------------------------------------------------------------

const MIN_CONFIDENCE = 0.4;
const MIN_CHARACTERS = 2;
const PREFERRED_VOICES = [
  /M[oó]nica.*(Enhanced|Premium|Mejorada)/i,
  /Paulina.*(Enhanced|Premium|Mejorada)/i,
  /Google español/i,
  /Microsoft (Elvira|Alvaro).*Online/i,
  /M[oó]nica/i,
  /Paulina/i,
];

function pickVoice(synth, locale) {
  const prefix = locale.slice(0, 2);
  const voices = synth.getVoices().filter((v) => v.lang.toLowerCase().startsWith(prefix));
  for (const pattern of prefix === "es" ? PREFERRED_VOICES : []) {
    const match = voices.find((v) => pattern.test(v.name));
    if (match) return match;
  }
  return voices.find((v) => v.lang === locale) ?? voices[0] ?? null;
}

function createBrowserVoice({ onInterim, onFinal, onStatus, onError }) {
  const Recognition = globalThis.SpeechRecognition || globalThis.webkitSpeechRecognition;
  const synth = globalThis.speechSynthesis;
  const supported = Boolean(Recognition && synth);

  let recognition = null;
  let active = false;
  let listening = false;
  let queued = 0;
  let anaTalking = false;
  let closing = false;
  let voice = null;
  let locale = LOCALES.es;
  const refreshVoice = () => {
    voice = supported ? pickVoice(synth, locale) : null;
  };
  if (supported) {
    refreshVoice();
    synth.addEventListener?.("voiceschanged", refreshVoice);
  }

  function listen() {
    if (!active || closing || listening || queued > 0 || anaTalking) return;
    recognition = new Recognition();
    recognition.lang = locale;
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.maxAlternatives = 1;
    recognition.onstart = () => {
      listening = true;
      onStatus("Escuchando…");
    };
    recognition.onresult = (event) => {
      let interim = "";
      let finalText = "";
      let confidence = 1;
      for (const result of event.results) {
        if (result.isFinal) {
          finalText += result[0].transcript;
          if (result[0].confidence) confidence = Math.min(confidence, result[0].confidence);
        } else {
          interim += result[0].transcript;
        }
      }
      if (!finalText) {
        onInterim(interim);
        return;
      }
      onInterim("");
      const text = finalText.trim();
      if (text.length < MIN_CHARACTERS || confidence < MIN_CONFIDENCE) {
        onStatus(`Descartado (${confidence.toFixed(2)}): "${text}". Escuchando…`);
        return;
      }
      onFinal(text);
    };
    recognition.onerror = (event) => {
      listening = false;
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        active = false;
        onError("Sin permiso de micrófono. Puedes seguir por texto.");
      } else if (event.error !== "no-speech" && event.error !== "aborted") {
        onError(`Error de voz (${event.error}). Puedes seguir por texto.`);
      }
    };
    recognition.onend = () => {
      listening = false;
      if (active) setTimeout(listen, 250);
    };
    recognition.start();
  }

  function stopListening() {
    if (recognition) {
      recognition.onend = null;
      recognition.abort();
      recognition = null;
    }
    listening = false;
    onInterim("");
  }

  return {
    supported,
    start() {
      active = true;
      listen();
    },
    stop() {
      active = false;
      stopListening();
      synth.cancel();
      queued = 0;
      anaTalking = false;
    },
    closing() {
      closing = true;
      stopListening();
    },
    speak(text) {
      if (!active) return;
      anaTalking = true;
      if (listening) stopListening();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = locale;
      if (voice) utterance.voice = voice;
      utterance.rate = 1.05;
      queued += 1;
      const done = () => {
        queued = Math.max(0, queued - 1);
        if (queued === 0 && closing) active = false;
        else if (queued === 0 && !anaTalking) setTimeout(listen, 150);
      };
      utterance.onend = done;
      utterance.onerror = done;
      synth.speak(utterance);
    },
    turnEnded() {
      anaTalking = false;
      if (queued === 0) listen();
    },
    // Each turn says which language it is in; the next recognition and utterance follow it.
    setLanguage(language) {
      const next = LOCALES[language] ?? locale;
      if (next === locale) return;
      locale = next;
      if (supported) refreshVoice();
      if (listening) stopListening();
    },
  };
}
