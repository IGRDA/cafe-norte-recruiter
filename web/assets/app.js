// Entry module: one state object, an SSE client, one POST per turn, and small renderers.
// Everything is rendered as text, never HTML.
import { createVoice } from "./voice.js";

// The store and the opening language come from ?store= and ?lang=; the chooser reloads the
// page into a new session with the choice.
const PARAMS = new URLSearchParams(location.search);
const CONFIG_ID = PARAMS.get("store");
const LANGUAGE = PARAMS.get("lang") === "en" ? "en" : "es";

const state = {
  sessionId: null,
  lastSeq: 0,
  status: "Conectando…",
  turns: new Map(), // turn_id -> { role, sentences: [] }
  order: [],
  candidate: null,
  stores: [], // GET /api/configurations
  reviews: new Map(), // turn_id | "session" -> { summary, list }
  turnCount: 0,
  voiceOn: false,
  ended: false,
};

const el = {
  status: document.getElementById("status"),
  transcript: document.getElementById("transcript"),
  composer: document.getElementById("composer"),
  access: document.getElementById("access"),
  code: document.getElementById("code"),
  text: document.getElementById("text"),
  send: document.getElementById("send"),
  talk: document.getElementById("talk"),
  error: document.getElementById("error"),
  chooser: document.getElementById("chooser"),
  store: document.getElementById("store"),
  storeName: document.getElementById("store-name"),
  start: document.getElementById("start"),
  language: document.getElementById("language"),
  candidate: document.getElementById("candidate"),
  confirmation: document.getElementById("confirmation"),
  confirmActions: document.getElementById("confirm-actions"),
  confirmYes: document.getElementById("confirm-yes"),
  confirmNo: document.getElementById("confirm-no"),
  booking: document.getElementById("booking"),
  bookingWhen: document.getElementById("booking-when"),
  review: document.getElementById("review"),
  versions: document.getElementById("versions"),
  sources: document.getElementById("sources"),
  export: document.getElementById("export"),
  exportLink: document.getElementById("export-link"),
  resume: document.getElementById("resume"),
  resumeLink: document.getElementById("resume-link"),
  end: document.getElementById("end"),
  delete: document.getElementById("delete"),
};

let voice = { start() {}, stop() {}, closing() {} }; // until the server offers hosted voice

function buildVoice() {
  return createVoice({
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
  const [runtime, stores] = await Promise.all([
    fetch("/api/runtime").then((r) => r.json()).catch(() => ({ voice: "off" })),
    fetch("/api/configurations").then((r) => r.json()).catch(() => []),
  ]);
  state.stores = stores;
  renderChooser();
  if (runtime.voice === "pipecat") voice = buildVoice();
  else el.talk.hidden = true;
  const token = new URLSearchParams(location.hash.slice(1)).get("resume");
  if (token) await resumeSession(token);
  else if (stores.some((store) => store.config_id === CONFIG_ID)) await openSession();
  else waitForChoice(stores.length > 0);
}

// No store chosen yet: nothing is created until the candidate presses Empezar.
function waitForChoice(canChoose) {
  el.text.disabled = true;
  el.send.disabled = true;
  el.talk.disabled = true;
  if (canChoose) setStatus("Elige una tienda y pulsa Empezar.");
  else showError("No se pudieron cargar las tiendas. Recarga la página.");
}

function renderChooser() {
  el.store.replaceChildren(
    ...state.stores.map((store) => {
      const option = document.createElement("option");
      option.value = store.config_id;
      option.textContent = store.store_name;
      return option;
    }),
  );
  if (CONFIG_ID) el.store.value = CONFIG_ID;
  el.language.value = LANGUAGE;
}

// The header names the store of this session.
function showStore(configId) {
  const store = state.stores.find((s) => s.config_id === configId);
  if (store) el.storeName.textContent = store.store_name;
  el.store.value = configId;
  el.start.textContent = "Nueva conversación";
}

function showVersions(versions) {
  const rows = [
    ["Configuración", `${versions.config_id} v${versions.config_version}`],
    ["Modelo", versions.model_id],
    ["Prompt", versions.prompt_version],
    ["Conocimiento", versions.kb_version],
    ["Esquema", versions.schema_version],
    ["Commit", versions.commit_sha],
    ...(versions.stt_model ? [["Voz → texto", versions.stt_model]] : []),
    ...(versions.tts_model ? [["Texto → voz", `${versions.tts_model} · ${versions.voice_id}`]] : []),
  ];
  el.versions.replaceChildren(
    ...rows.flatMap(([label, value]) => {
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.textContent = value;
      return [dt, dd];
    }),
  );
}

// After a resume the page knows the session only by its cookie: the snapshot says which store
// and language it was, and the versions it ran with.
async function loadSnapshot() {
  const response = await fetch(`/api/sessions/${state.sessionId}`);
  if (!response.ok) return;
  const snapshot = await response.json();
  showStore(snapshot.state.config_id);
  el.language.value = snapshot.state.language;
  showVersions(snapshot.versions);
}

// A private resume link: the token travels in the fragment, is exchanged once for the session
// cookie and leaves the address bar. The stream then replays the whole conversation.
async function resumeSession(token) {
  history.replaceState(null, "", location.pathname + location.search);
  const response = await fetch("/api/resume", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  if (!response.ok) {
    showError("Este enlace ya no es válido. Empieza una conversación nueva.");
    await openSession();
    return;
  }
  const body = await response.json();
  state.sessionId = body.session_id;
  renderCandidate();
  await loadSnapshot();
  openStream();
  review("conversación recuperada con el enlace privado");
  el.end.hidden = false;
  el.delete.hidden = false;
  setStatus("Conversación recuperada.");
}

// A shared demo code guards the hosted page; the server says whether one is needed. A 401 on
// session creation shows the code box; a valid code sets a cookie and we try again.
async function openSession() {
  const response = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config_id: CONFIG_ID, language: LANGUAGE, channel: "text" }),
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
  el.resumeLink.href = body.resume_url;
  el.resumeLink.textContent = `${location.origin}${body.resume_url}`;
  el.resume.hidden = false;
  review("enlace privado de reanudación emitido (válido 7 días)");
  showStore(CONFIG_ID);
  showVersions(body.versions);
  el.end.hidden = false;
  el.delete.hidden = false;
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
    "signal_recorded",
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
      state.turnCount += 1;
      reviewEntry(event.turn_id).summary.textContent = `Turno ${state.turnCount}`;
      if (payload.text) addTurn(`${event.turn_id}:user`, "user", [payload.text]);
      addTurn(event.turn_id, "assistant", []);
      setStatus("Ana está pensando…");
      break;
    }
    case "sources_shown":
      renderSources(payload);
      review(`búsqueda «${payload.question}»: ${payload.chunk_ids.length} fragmentos`, event.turn_id);
      payload.chunk_ids.forEach((id, i) => {
        review(`  ${payload.titles[i]} › ${payload.sections[i]}: ${payload.excerpts[i]}`, event.turn_id);
      });
      break;
    case "signal_recorded": {
      const signal = payload.signal;
      const evidence = signal.evidence_text ? ` («${signal.evidence_text}»)` : "";
      review(`señal del turno: ${signal.sentiment}${evidence}`, event.turn_id);
      break;
    }
    case "assistant_text": {
      const turn = state.turns.get(event.turn_id) ?? addTurn(event.turn_id, "assistant", []);
      turn.sentences.push(payload.text);
      renderTranscript();
      if (!state.ended) setStatus("Ana está hablando…");
      break;
    }
    case "tool_started":
      review(`herramienta ${payload.name}(${payload.arguments ?? ""}) → iniciada`, event.turn_id);
      break;
    case "tool_finished":
      review(`herramienta ${payload.name} → ${payload.ok ? "ok" : "rechazada"} (${payload.summary})`, event.turn_id);
      break;
    case "state_updated":
      state.candidate = payload;
      renderCandidate();
      renderConfirmation(payload.pending_confirmation);
      renderBooking(payload.booking);
      review(`estado guardado, revisión ${payload.revision}`, event.turn_id);
      if (TERMINAL.has(payload.lifecycle)) endConversation();
      break;
    case "turn_finished": {
      hideError(); // a later turn went through: an old error no longer applies
      finishReview(event.turn_id, payload);
      renderConfirmation(state.candidate?.pending_confirmation);
      if (state.ended) break;
      setStatus(state.voiceOn ? "Escuchando…" : "Tu turno.");
      break;
    }
    case "turn_failed":
      review(`turno fallido · ${payload.code}`, event.turn_id);
      showError(payload.message);
      renderConfirmation(state.candidate?.pending_confirmation);
      if (payload.code === "session_ended") endConversation();
      if (state.ended) break;
      setStatus(state.voiceOn ? "Escuchando…" : "Tu turno.");
      break;
    default:
      review(`evento ${payload.type}`, event.turn_id);
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

// The card's Sí / No: an explicit answer to the pending read-back, at the revision on screen.
// The server runs it through the same rules as a spoken answer; the stream shows the result.
async function answerConfirmation(answer) {
  const update = state.candidate;
  const pending = update?.pending_confirmation;
  if (!pending || pending.status !== "pending" || state.ended) return;
  hideError();
  setConfirmButtons(false);
  try {
    const response = await fetch(
      `/api/sessions/${state.sessionId}/confirmations/${pending.confirmation_id}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          input_id: crypto.randomUUID(),
          answer,
          expected_revision: update.revision,
        }),
      },
    );
    if (response.status !== 202) {
      const body = await response.json().catch(() => ({}));
      showError(body.message ?? "No se pudo enviar tu respuesta.");
      setConfirmButtons(true);
      return;
    }
    setStatus("Enviado…");
  } catch {
    showError("Sin conexión con el servidor.");
    setConfirmButtons(true);
  }
}

function setConfirmButtons(enabled) {
  el.confirmYes.disabled = !enabled;
  el.confirmNo.disabled = !enabled;
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
  const open = confirmation?.status === "pending" && !state.ended;
  el.confirmActions.hidden = !open;
  if (open) setConfirmButtons(true);
  if (!confirmation) {
    el.confirmation.textContent = "—";
    el.confirmation.removeAttribute("data-status");
    return;
  }
  const label = CONFIRMATION_TEXT[confirmation.status] ?? confirmation.status;
  el.confirmation.textContent = `${label} (rev. ${confirmation.target.revision ?? "–"}): ${confirmation.presentation_text}`;
  el.confirmation.dataset.status = confirmation.status;
}

function renderBooking(booking) {
  // Only a committed reservation reaches the stream, so showing it never runs ahead of storage.
  el.booking.hidden = !booking;
  if (!booking) return;
  const when = new Date(booking.starts_at_utc).toLocaleString("es-ES", {
    timeZone: "Europe/Madrid",
    weekday: "long",
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  });
  el.bookingWhen.textContent = `${when} (hora de Madrid) · ${booking.slot_id}`;
}

function endConversation() {
  // The goodbye arrives after the terminal state: Ana says it and hangs up, the UI freezes now.
  state.ended = true;
  el.text.disabled = true;
  el.send.disabled = true;
  el.talk.disabled = true;
  el.confirmActions.hidden = true;
  el.end.hidden = true;
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

// One collapsed entry per turn (the lines are what a reviewer needs to follow it) and one for
// the session itself. Text only, never hidden reasoning.
function reviewEntry(turnId) {
  const key = turnId ?? "session";
  let entry = state.reviews.get(key);
  if (entry) return entry;
  const item = document.createElement("li");
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  summary.textContent = turnId ? "Turno" : "Sesión";
  const list = document.createElement("ul");
  details.append(summary, list);
  item.append(details);
  el.review.append(item);
  entry = { summary, list };
  state.reviews.set(key, entry);
  while (el.review.children.length > 40) {
    el.review.firstElementChild.remove();
    state.reviews.delete(state.reviews.keys().next().value);
  }
  return entry;
}

function review(line, turnId = null) {
  const item = document.createElement("li");
  item.textContent = line;
  reviewEntry(turnId).list.append(item);
}

function finishReview(turnId, payload) {
  const ms = Object.fromEntries(payload.timings.map((t) => [t.stage, t.milliseconds]));
  const tokens = payload.usage
    .filter((u) => u.kind === "llm_tokens")
    .reduce((sum, u) => sum + u.quantity, 0);
  const entry = reviewEntry(turnId);
  const label = entry.summary.textContent.split(" · ")[0];
  entry.summary.textContent = `${label} · ${ms.llm_total ?? "–"} ms · ${tokens} tokens`;
  const timings = payload.timings
    .map((t) => `${t.stage}${t.tool_name ? `:${t.tool_name}` : ""} ${t.milliseconds} ms`)
    .join(", ");
  review(`tiempos: ${timings || "–"}`, turnId);
  const usage = payload.usage
    .map((u) => `${u.kind} ${u.unit_detail} ${u.quantity}${u.estimated ? " (estimado)" : ""}`)
    .join(", ");
  review(`uso: ${usage || "–"}${payload.interrupted ? " · interrumpido" : ""}`, turnId);
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

// The delete action (spec §8): the session, its export, its link and its simulated reservation
// go together; a new conversation starts on reload.
el.delete.addEventListener("click", async () => {
  if (!state.sessionId || !confirm("¿Borrar esta conversación y todos sus datos?")) return;
  const response = await fetch(`/api/sessions/${state.sessionId}`, { method: "DELETE" });
  if (response.status !== 204) {
    showError("No se pudo borrar la conversación.");
    return;
  }
  state.ended = true;
  el.end.hidden = true;
  el.confirmActions.hidden = true;
  el.delete.hidden = true;
  el.resume.hidden = true;
  el.export.hidden = true;
  el.text.disabled = true;
  el.send.disabled = true;
  el.talk.disabled = true;
  setStatus("Conversación borrada. Recarga la página para empezar otra.");
});

el.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  submitTurn(el.text.value);
});

el.chooser.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!el.store.value) return;
  location.search = new URLSearchParams({ store: el.store.value, lang: el.language.value }).toString();
});

el.confirmYes.addEventListener("click", () => answerConfirmation("affirm"));
el.confirmNo.addEventListener("click", () => answerConfirmation("deny"));

el.end.addEventListener("click", async () => {
  if (!state.sessionId || state.ended || !confirm("¿Terminar la conversación?")) return;
  const response = await fetch(`/api/sessions/${state.sessionId}/end`, { method: "POST" });
  if (response.status !== 204) {
    showError("No se pudo terminar la conversación.");
    return;
  }
  endConversation();
});

el.talk.addEventListener("click", () => {
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
