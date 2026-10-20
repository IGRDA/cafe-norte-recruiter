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
  pendingUser: [], // user texts acknowledged by the server, shown before their turn_started
  candidate: null,
  voiceOn: false,
};

const el = {
  status: document.getElementById("status"),
  transcript: document.getElementById("transcript"),
  interim: document.getElementById("interim"),
  composer: document.getElementById("composer"),
  text: document.getElementById("text"),
  send: document.getElementById("send"),
  talk: document.getElementById("talk"),
  error: document.getElementById("error"),
  candidate: document.getElementById("candidate"),
  review: document.getElementById("review"),
};

const voice = createVoice({
  onInterim: (text) => {
    el.interim.textContent = text ? `… ${text}` : "";
  },
  onFinal: (text) => {
    el.interim.textContent = "";
    submitTurn(text);
  },
  onStatus: setStatus,
  onError: showError,
});

async function main() {
  const response = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config_id: CONFIG_ID, language: "es", channel: "text" }),
  });
  if (!response.ok) {
    showError("No se pudo crear la conversación. Recarga la página.");
    return;
  }
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
      const userText = state.pendingUser.shift();
      if (userText !== undefined) addTurn(`${event.turn_id}:user`, "user", [userText]);
      addTurn(event.turn_id, "assistant", []);
      setStatus("Ana está pensando…");
      break;
    }
    case "assistant_text": {
      const turn = state.turns.get(event.turn_id) ?? addTurn(event.turn_id, "assistant", []);
      turn.sentences.push(payload.text);
      renderTranscript();
      if (state.voiceOn) voice.speak(payload.spoken_form);
      setStatus("Ana está hablando…");
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
      review(`estado guardado, revisión ${payload.revision}`);
      break;
    case "turn_finished": {
      const ms = Object.fromEntries(payload.timings.map((t) => [t.stage, t.milliseconds]));
      const tokens = payload.usage.map((u) => `${u.unit_detail} ${u.quantity}`).join(", ");
      review(`turno terminado · primer token ${ms.llm_first_output ?? "–"} ms · total ${ms.llm_total ?? "–"} ms · tokens ${tokens || "–"}`);
      setStatus(state.voiceOn ? "Escuchando…" : "Tu turno.");
      if (state.voiceOn) voice.turnEnded();
      break;
    }
    case "turn_failed":
      review(`turno fallido · ${payload.code}`);
      showError(payload.message);
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
    state.pendingUser.push(trimmed);
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
  if (state.voiceOn) {
    hideError();
    voice.start();
  } else {
    voice.stop();
    setStatus("Tu turno.");
  }
});

main();
