// Browser voice for the tracer bullet: the Web Speech API in, speechSynthesis out.
// Temporary by decision D18; the hosted path (Daily + Pipecat) replaces this module and
// leaves app.js untouched. Microphone permission is requested only when "Hablar" is pressed.

const LANG = "es-ES";

export function createVoice({ onInterim, onFinal, onStatus, onError }) {
  const Recognition = globalThis.SpeechRecognition || globalThis.webkitSpeechRecognition;
  const synth = globalThis.speechSynthesis;
  const supported = Boolean(Recognition && synth);

  let recognition = null;
  let active = false; // the user wants the voice loop on
  let listening = false;
  let queued = 0; // utterances not yet finished

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
      for (const result of event.results) {
        if (result.isFinal) finalText += result[0].transcript;
        else interim += result[0].transcript;
      }
      if (finalText) {
        onInterim("");
        onFinal(finalText);
      } else {
        onInterim(interim);
      }
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
