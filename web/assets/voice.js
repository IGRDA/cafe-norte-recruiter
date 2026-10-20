// Browser voice for the tracer bullet: the Web Speech API in, speechSynthesis out.
// Temporary by decision D18; the hosted path (Daily + Pipecat) replaces this module and
// leaves app.js untouched. Microphone permission is requested only when "Hablar" is pressed.

const LANG = "es-ES";
// A final transcript below this confidence, or shorter than this, is treated as background
// speech and discarded. "Sí" and "no" are two characters and must pass. Browsers that report
// no confidence (Safari) pass the first check. Discarded text is shown, never silently lost.
const MIN_CONFIDENCE = 0.4;
const MIN_CHARACTERS = 2;
// Preferred synthesis voices, best first; anything else falls back to the first es-* voice.
const PREFERRED_VOICES = [
  /M[oó]nica.*(Enhanced|Premium|Mejorada)/i,
  /Paulina.*(Enhanced|Premium|Mejorada)/i,
  /Google español/i,
  /Microsoft (Elvira|Alvaro).*Online/i,
  /M[oó]nica/i,
  /Paulina/i,
];

function pickVoice(synth) {
  const voices = synth.getVoices().filter((v) => v.lang.toLowerCase().startsWith("es"));
  for (const pattern of PREFERRED_VOICES) {
    const match = voices.find((v) => pattern.test(v.name));
    if (match) return match;
  }
  return voices.find((v) => v.lang === LANG) ?? voices[0] ?? null;
}

export function createVoice({ onInterim, onFinal, onStatus, onError }) {
  const Recognition = globalThis.SpeechRecognition || globalThis.webkitSpeechRecognition;
  const synth = globalThis.speechSynthesis;
  const supported = Boolean(Recognition && synth);

  let recognition = null;
  let active = false; // the user wants the voice loop on
  let listening = false;
  let queued = 0; // utterances not yet finished
  let voice = null;
  const refreshVoice = () => {
    voice = supported ? pickVoice(synth) : null;
  };
  if (supported) {
    refreshVoice();
    synth.addEventListener?.("voiceschanged", refreshVoice);
  }

  function listen() {
    if (!active || listening || queued > 0) return;
    recognition = new Recognition();
    recognition.lang = LANG;
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
        return; // onend will listen again
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
      // No final result (silence) and nothing being spoken: listen again.
      if (active && queued === 0) setTimeout(listen, 250);
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
    },
    // Speak one sentence as soon as it arrives; stop the microphone so Ana does not hear herself.
    speak(text) {
      if (!active) return;
      stopListening();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = LANG;
      if (voice) utterance.voice = voice;
      utterance.rate = 1.05;
      queued += 1;
      const done = () => {
        queued = Math.max(0, queued - 1);
        if (queued === 0) setTimeout(listen, 150);
      };
      utterance.onend = done;
      utterance.onerror = done;
      synth.speak(utterance);
    },
    // Called at the end of a turn: resume listening once the queue has drained.
    listenWhenQuiet() {
      if (queued === 0) listen();
    },
  };
}
