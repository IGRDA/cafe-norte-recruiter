// Entry module: one state object, an SSE client, one POST per turn, and small renderers.
// Everything is rendered as text, never HTML.
import { createVoice } from "./voice.js";

const CONFIG_ID = "chamberi_barista_v1";

const state = {
  sessionId: null,
  lastSeq: 0,
  status: "Conectando…",
  turns: new Map(), // turn_id -> { role, sentences: [] }
  order: [],
  candidate: null,
  voiceOn: false,
  voiceMode: "off",
  ended: false,
};

const el = {
  status: document.getElementById("status"),
  transcript: document.getElementById("transcript"),
  interim: document.getElementById("interim"),
  composer: document.getElementById("composer"),
  access: document.getElementById("access"),
  code: document.getElementById("code"),
  text: document.getElementById("text"),
  send: document.getElementById("send"),
  talk: document.getElementById("talk"),
  error: document.getElementById("error"),
  candidate: document.getElementById("candidate"),
  confirmation: document.getElementById("confirmation"),
  review: document.getElementById("review"),
  sources: document.getElementById("sources"),
  export: document.getElementById("export"),
  exportLink: document.getElementById("export-link"),
};

let voice = { supported: false, start() {}, stop() {}, speak() {}, turnEnded() {}, closing() {} };

function buildVoice(mode) {
  return createVoice({
    mode,
    onInterim: (text) => {
      el.interim.textContent = text ? `… ${text}` : "";
    },
    onFinal: (text) => {
      el.interim.textContent = "";
      submitTurn(text);
    },
    onStatus: setStatus,
    onError: showError,
    startVoice: async () => {
      const response = await fetch(`/api/sessions/${state.sessionId}/voice`, { method: "POST" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.message ?? "No se pudo iniciar la voz.");
      return body;
    },
    postTiming: (event, monotonic_ms) => {
      fetch(`/api/sessions/${state.sessionId}/voice/timings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ turn_id: null, event, monotonic_ms }),
      }).catch(() => {});
    },
  });
}

async function main() {
  const runtime = await fetch("/api/runtime").then((r) => r.json()).catch(() => ({ voice: "off" }));
  state.voiceMode = runtime.voice;
  if (runtime.voice === "off") el.talk.hidden = true;
  else voice = buildVoice(runtime.voice);
  await openSession();
}

// A shared demo code guards the hosted page; the server says whether one is needed. A 401 on
// session creation shows the code box; a valid code sets a cookie and we try again.
async function openSession() {
  const response = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config_id: CONFIG_ID, language: "es", channel: "text" }),
  });
  if (response.status === 401) {
    el.access.hidden = false;
    setStatus("Introduce el código de acceso de la demostración.");
    el.code.focus();
    return;
  }
  if (!response.ok) {
    showError("No se pudo crear la conversación. Recarga la página.");
    return;
  }
  el.access.hidden = true;
  const body = await response.json();
  state.sessionId = body.session_id;
  renderCandidate();
  openStream();
  setStatus("Conectada.");
  el.text.focus();
}

function openStream() {
  const source = new EventSource(`/api/sessions/${state.sessionId}/events`);
  for (const type of [
    "turn_started",
    "assistant_text",
    "tool_started",
    "tool_finished",
    "state_updated",
    "sources_shown",
    "turn_finished",
    "turn_failed",
    "voice_state",
  ]) {
    source.addEventListener(type, (message) => handle(JSON.parse(message.data)));
  }
  source.onerror = () => setStatus("Reconectando…");
  source.onopen = () => {
    if (state.lastSeq) setStatus("Conectada de nuevo.");
  };
}

function handle(event) {
  if (event.seq <= state.lastSeq) return; // replayed after a reconnect
  state.lastSeq = event.seq;
  const payload = event.payload;
  switch (payload.type) {
    case "turn_started": {
      // The stream carries the user's words: bubbles never depend on the POST reply's timing.
      if (payload.text) addTurn(`${event.turn_id}:user`, "user", [payload.text]);
      addTurn(event.turn_id, "assistant", []);
      setStatus("Ana está pensando…");
      break;
    }
    case "sources_shown":
      renderSources(payload);
      review(`fuentes para «${payload.question}»: ${payload.chunk_ids.length}`);
      break;
    case "assistant_text": {
      const turn = state.turns.get(event.turn_id) ?? addTurn(event.turn_id, "assistant", []);
      turn.sentences.push(payload.text);
      renderTranscript();
      if (state.voiceOn) voice.speak(payload.spoken_form);
      if (!state.ended) setStatus("Ana está hablando…");
      break;
    }
    case "tool_started":
      review(`herramienta ${payload.name} → iniciada`);
      break;
    case "tool_finished":
      review(`herramienta ${payload.name} → ${payload.ok ? "ok" : "rechazada"} (${payload.summary})`);
      break;
    case "state_updated":
      state.candidate = payload;
      renderCandidate();
      renderConfirmation(payload.pending_confirmation);
      review(`estado guardado, revisión ${payload.revision}`);
      if (TERMINAL.has(payload.lifecycle)) endConversation();
      break;
    case "turn_finished": {
      const ms = Object.fromEntries(payload.timings.map((t) => [t.stage, t.milliseconds]));
      const tokens = payload.usage.map((u) => `${u.unit_detail} ${u.quantity}`).join(", ");
      review(`turno terminado · primer token ${ms.llm_first_output ?? "–"} ms · total ${ms.llm_total ?? "–"} ms · tokens ${tokens || "–"}`);
      if (state.ended) {
        voice.turnEnded();
        break;
      }
      setStatus(state.voiceOn ? "Escuchando…" : "Tu turno.");
      if (state.voiceOn) voice.turnEnded();
      break;
    }
    case "turn_failed":
      review(`turno fallido · ${payload.code}`);
      showError(payload.message);
      if (payload.code === "session_ended") endConversation();
      if (state.ended) break;
      setStatus(state.voiceOn ? "Escuchando…" : "Tu turno.");
      if (state.voiceOn) voice.turnEnded();
      break;
    default:
      review(`evento ${payload.type}`);
  }
}

async function submitTurn(text) {
  const trimmed = text.trim();
  if (!trimmed || !state.sessionId) return;
  hideError();
  el.send.disabled = true;
  try {
    const response = await fetch(`/api/sessions/${state.sessionId}/turns`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input_id: crypto.randomUUID(), text: trimmed }),
    });
    if (response.status !== 202) {
      const body = await response.json().catch(() => ({}));
      showError(body.message ?? "No se pudo enviar el mensaje.");
      return;
    }
    el.text.value = "";
    setStatus("Enviado…");
  } catch {
    showError("Sin conexión con el servidor.");
  } finally {
    el.send.disabled = false;
  }
}

// ---- renderers ---------------------------------------------------------------------------------

function addTurn(id, role, sentences) {
  const turn = { role, sentences: [...sentences] };
  state.turns.set(id, turn);
  state.order.push(id);
  renderTranscript();
  return turn;
}

function renderTranscript() {
  el.transcript.replaceChildren(
    ...state.order.map((id) => {
      const turn = state.turns.get(id);
      const item = document.createElement("li");
      item.className = turn.role;
      const who = document.createElement("span");
      who.className = "who";
      who.textContent = turn.role === "user" ? "Tú" : "Ana";
      const text = document.createElement("p");
      text.textContent = turn.sentences.join(" ") || "…";
      item.append(who, text);
      return item;
    }),
  );
  el.transcript.lastElementChild?.scrollIntoView({ block: "end" });
}

const FIELDS = [
  ["name", "Nombre"],
  ["interest", "Interés"],
  ["work_authorization", "Permiso de trabajo"],
  ["availability_days", "Días"],
  ["availability_shifts", "Turnos"],
  ["hours_per_week", "Horas/semana"],
  ["earliest_start_date", "Inicio"],
  ["experience", "Experiencia"],
  ["contact_phone", "Teléfono"],
];
const STATUS_TEXT = { unknown: "no lo sabe", declined: "no quiere decirlo", unset: "—" };
const CONFIRMATION_TEXT = {
  pending: "pendiente",
  confirmed: "confirmada",
  rejected: "rechazada",
  invalidated: "invalidada",
  expired: "caducada",
};
const TERMINAL = new Set(["completed", "stopped", "abandoned", "failed"]);

function fieldText(field) {
  if (!field) return "—";
  if (field.status === "captured" || field.status === "confirmed") {
    const value = Array.isArray(field.value) ? field.value.join(", ") : String(field.value);
    return field.status === "confirmed" ? `${value} ✓` : value;
  }
  return STATUS_TEXT[field.status] ?? field.status;
}

function renderCandidate() {
  const update = state.candidate;
  const candidate = update?.candidate;
  const rows = FIELDS.map(([key, label]) => [label, fieldText(candidate?.[key])]);
  rows.push(["Notas", candidate?.notes?.length ? candidate.notes.join(" · ") : "—"]);
  rows.push(["Revisión", String(update?.revision ?? 0)]);
  rows.push(["Estado", update ? `${update.lifecycle}${update.outcome ? ` · ${update.outcome}` : ""}` : "active"]);
  el.candidate.replaceChildren(
    ...rows.flatMap(([label, value]) => {
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.textContent = value;
      return [dt, dd];
    }),
  );
}

function renderConfirmation(confirmation) {
  if (!confirmation) {
    el.confirmation.textContent = "—";
    el.confirmation.removeAttribute("data-status");
    return;
  }
  const label = CONFIRMATION_TEXT[confirmation.status] ?? confirmation.status;
  el.confirmation.textContent = `${label} (rev. ${confirmation.target.revision ?? "–"}): ${confirmation.presentation_text}`;
  el.confirmation.dataset.status = confirmation.status;
}

function endConversation() {
  // The goodbye arrives after the terminal state: keep speaking, stop listening, freeze the UI.
  state.ended = true;
  el.text.disabled = true;
  el.send.disabled = true;
  el.talk.disabled = true;
  voice.closing();
  setStatus("Conversación terminada. Gracias.");
  el.exportLink.href = `/api/sessions/${state.sessionId}/export`;
  el.export.hidden = false;
}

function renderSources(payload) {
  // Title › section and an excerpt per chunk, as text. Replaced on every search.
  el.sources.replaceChildren();
  if (!payload.chunk_ids.length) {
    const item = document.createElement("li");
    item.textContent = "Sin fragmentos para esta pregunta.";
    el.sources.append(item);
    return;
  }
  payload.chunk_ids.forEach((id, i) => {
    const item = document.createElement("li");
    const head = document.createElement("strong");
    head.textContent = `${payload.titles[i].split(" / ")[0]} › ${payload.sections[i]}`;
    const body = document.createElement("span");
    body.textContent = ` ${payload.excerpts[i]}`;
    item.append(head, body);
    el.sources.append(item);
  });
}

function review(line) {
  const item = document.createElement("li");
  item.textContent = line;
  el.review.append(item);
  while (el.review.children.length > 30) el.review.firstElementChild.remove();
}

function setStatus(text) {
  state.status = text;
  el.status.textContent = text;
}

function showError(text) {
  el.error.textContent = text;
  el.error.hidden = false;
}

function hideError() {
  el.error.hidden = true;
}

// ---- wiring ------------------------------------------------------------------------------------

el.access.addEventListener("submit", async (event) => {
  event.preventDefault();
  const response = await fetch("/api/access", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code: el.code.value.trim() }),
  });
  if (response.status === 204) {
    hideError();
    await openSession();
  } else {
    showError("Código incorrecto.");
  }
});

el.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  submitTurn(el.text.value);
});

el.talk.addEventListener("click", () => {
  if (!voice.supported) {
    showError("Este navegador no soporta reconocimiento de voz. Puedes seguir por texto.");
    return;
  }
  state.voiceOn = !state.voiceOn;
  el.talk.setAttribute("aria-pressed", String(state.voiceOn));
  el.talk.textContent = state.voiceOn ? "⏹ Parar" : "🎙 Hablar";
  if (state.voiceMode === "pipecat") el.talk.title = "Voz alojada: Daily + Deepgram + ElevenLabs";
  if (state.voiceOn) {
    hideError();
    voice.start();
  } else {
    voice.stop();
    setStatus("Tu turno.");
  }
});

main();
