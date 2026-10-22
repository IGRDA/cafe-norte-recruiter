// @vitest-environment node
// The page's rules, without a browser: each case is (state, actions) → (state, effects).
import { describe, expect, it } from "vitest";
import type { SessionState } from "../api/contracts";
import { active, booted, event, LANGUAGES, pendingBrief, run, signal, STORE, stateUpdated, userTurn, VERSIONS } from "./fixtures";
import {
  canAnswer,
  canDelete,
  canEnd,
  canSend,
  canTalk,
  exportHref,
  initial,
  isRtl,
  languageBars,
  latestSignal,
  MAX_REVIEW_ENTRIES,
  MAX_SIGNAL_POINTS,
  signalStatus,
  showAccess,
  storeName,
  talkPressed,
} from "./reducer";

describe("boot", () => {
  it("opens a session for a known store", () => {
    const { state, effects } = run(initial({ store: "chamberi", language: "en", resumeToken: null, code: null }), {
      type: "booted",
      voiceOffered: false,
      signalsMode: "off",
      languages: [],
      stores: [STORE],
    });
    expect(state.page).toBe("loading");
    expect(effects).toEqual([{ type: "create-session", store: "chamberi", language: "en" }]);
  });

  it("waits for the chooser when no store was asked for, creating nothing", () => {
    const state = booted(null);
    expect(state.page).toBe("choosing");
    expect(state.chooser.store).toBe("chamberi");
    expect(state.status).toBe("Elige una tienda y pulsa Empezar.");
  });

  it("fails when the stores could not be loaded", () => {
    const { state, effects } = run(initial({ store: null, language: "es", resumeToken: null, code: null }), {
      type: "booted",
      voiceOffered: false,
      signalsMode: "off",
      languages: [],
      stores: [],
    });
    expect(state.page).toBe("failed");
    expect(state.error).toMatch(/tiendas/);
    expect(effects).toEqual([]);
  });

  it("resumes from the fragment and removes it from the address bar first", () => {
    const { effects } = run(initial({ store: null, language: "es", resumeToken: "tok", code: null }), {
      type: "booted",
      voiceOffered: false,
      signalsMode: "off",
      languages: [],
      stores: [STORE],
    });
    expect(effects).toEqual([{ type: "clear-fragment" }, { type: "resume", token: "tok" }]);
  });

  it("a dead resume link falls back to a new session with a notice", () => {
    const start = run(initial({ store: "chamberi", language: "es", resumeToken: "tok", code: null }), {
      type: "booted",
      voiceOffered: false,
      signalsMode: "off",
      languages: [],
      stores: [STORE],
    }).state;
    const { state, effects } = run(start, { type: "resume-failed" });
    expect(effects).toEqual([{ type: "create-session", store: "chamberi", language: "es" }]);
    expect(state.error).toMatch(/ya no es válido/);
  });

  it("a resumed session takes its store and language from the snapshot", () => {
    const resuming = run(initial({ store: null, language: "es", resumeToken: "tok", code: null }), {
      type: "booted",
      voiceOffered: false,
      signalsMode: "off",
      languages: [],
      stores: [STORE],
    }).state;
    const resumed = run(resuming, { type: "resumed", sessionId: "s9" });
    expect(resumed.effects).toEqual([
      { type: "load-snapshot", sessionId: "s9" },
      { type: "open-stream", sessionId: "s9" },
    ]);
    expect(resumed.state.status).toBe("Conversación recuperada.");
    const { state } = run(resumed.state, {
      type: "snapshot-loaded",
      snapshot: {
        session_id: "s9",
        last_seq: 4,
        state: { config_id: "chamberi", language: "en" } as SessionState,
        transcript: [],
        versions: VERSIONS,
      },
    });
    expect(storeName(state)).toBe("Café Norte Chamberí");
    expect(state.chooser).toEqual({ store: "chamberi", language: "en" });
    expect(state.versions).toEqual(VERSIONS);
  });
});

describe("access gate", () => {
  it("a 401 on creation shows the code form and focuses it", () => {
    const { state, effects } = run(booted(), { type: "session-needs-code" });
    expect(state.page).toBe("gate");
    expect(effects).toEqual([{ type: "focus", target: "code" }]);
  });

  it("a valid code creates the session; a wrong one says so", () => {
    const gate = run(booted(), { type: "session-needs-code" }).state;
    const checking = run(gate, { type: "code-submitted", code: "  1234 " });
    expect(checking.effects).toEqual([{ type: "check-code", code: "1234" }]);
    expect(checking.state.access).toBe("checking");

    const refused = run(checking.state, { type: "access-refused" }).state;
    expect(refused.error).toBe("Código incorrecto.");
    expect(refused.page).toBe("gate");

    const limited = run(checking.state, { type: "access-refused", message: "Demasiados intentos." }).state;
    expect(limited.error).toBe("Demasiados intentos.");

    const granted = run(checking.state, { type: "access-granted" });
    expect(granted.effects).toEqual([{ type: "create-session", store: "chamberi", language: "es" }]);
    expect(granted.state.error).toBeNull();
  });

  it("ignores a second submit while a code is being checked", () => {
    const gate = run(booted(), { type: "session-needs-code" }).state;
    const { effects } = run(gate, { type: "code-submitted", code: "1" }, { type: "code-submitted", code: "1" });
    expect(effects).toHaveLength(1);
  });
});

describe("access link (#code=)", () => {
  const withCode = (resumeToken: string | null = null) =>
    run(initial({ store: "chamberi", language: "es", resumeToken, code: "1234" }), {
      type: "booted",
      voiceOffered: false,
      signalsMode: "off",
      languages: [],
      stores: [STORE],
    });

  it("removes the code from the address bar and checks it before anything else", () => {
    const { state, effects } = withCode();
    expect(effects).toEqual([{ type: "clear-fragment" }, { type: "check-code", code: "1234" }]);
    expect(state.access).toBe("checking");
  });

  it("a good code opens the session with no form shown", () => {
    const { state, effects } = run(withCode().state, { type: "access-granted" });
    expect(effects).toEqual([{ type: "create-session", store: "chamberi", language: "es" }]);
    expect(showAccess(state)).toBe(false);
  });

  it("a good code then resumes when the link carries both", () => {
    const { effects } = run(withCode("tok").state, { type: "access-granted" });
    expect(effects).toEqual([{ type: "resume", token: "tok" }]);
  });

  it("a wrong code lands on the form with the error, focused", () => {
    const { state, effects } = run(withCode().state, { type: "access-refused" });
    expect(state.page).toBe("gate");
    expect(state.error).toBe("Código incorrecto.");
    expect(state.status).toBe("Introduce el código de acceso de la demostración.");
    expect(effects).toEqual([{ type: "focus", target: "code" }]);
  });
});

describe("session", () => {
  it("a session that cannot start says why when the server does", () => {
    expect(run(booted(), { type: "session-failed", message: "No hay plazas libres." }).state.error).toBe(
      "No hay plazas libres.",
    );
    expect(run(booted(), { type: "session-failed" }).state.error).toBe(
      "No se pudo crear la conversación. Recarga la página.",
    );
  });

  it("an opened session streams, shows its link once and names its store", () => {
    const { state, effects } = run(booted(), {
      type: "session-opened",
      body: { session_id: "s1", resume_url: "/#resume=abc", versions: VERSIONS },
    });
    expect(effects).toEqual([
      { type: "open-stream", sessionId: "s1" },
      { type: "focus", target: "text" },
    ]);
    expect(state.page).toBe("active");
    expect(state.resumeUrl).toBe("/#resume=abc");
    expect(storeName(state)).toBe("Café Norte Chamberí");
    expect(state.reviews[0].lines).toEqual(["enlace privado de reanudación emitido (válido 7 días)"]);
  });

  it("the chooser navigates with the chosen store and language", () => {
    const { effects } = run(booted(null), { type: "chooser-changed", language: "en" }, { type: "chooser-submitted" });
    expect(effects).toEqual([{ type: "navigate", store: "chamberi", language: "en" }]);
  });
});

describe("stream", () => {
  it("builds the transcript from the stream alone", () => {
    const { state } = run(
      active(),
      event({ type: "turn_started", turn_id: "t1", language: "es", text: "Hola" }),
      event({ type: "assistant_text", text: "Hola, soy Ana.", spoken_form: "" }),
      event({ type: "assistant_text", text: "¿Cómo te llamas?", spoken_form: "" }),
    );
    expect(state.transcript).toEqual([
      { id: "t1:user", role: "user", sentences: ["Hola"] },
      { id: "t1", role: "assistant", sentences: ["Hola, soy Ana.", "¿Cómo te llamas?"] },
    ]);
    expect(state.status).toBe("Ana está hablando…");
    expect(state.reviews.find((r) => r.key === "t1")?.label).toBe("Turno 1");
  });

  it("ignores events replayed after a reconnect", () => {
    const first = event({ type: "assistant_text", text: "Uno.", spoken_form: "" });
    const { state } = run(active(), first, first);
    expect(state.transcript[0].sentences).toEqual(["Uno."]);
  });

  it("a finished turn hands the turn back and summarises timings and tokens", () => {
    const { state } = run(
      active(),
      event({ type: "turn_started", turn_id: "t1", language: "es", text: "" }),
      event({
        type: "turn_finished",
        turn_id: "t1",
        interrupted: false,
        usage: [
          { session_id: "s1", turn_id: "t1", kind: "llm_tokens", quantity: 120, unit_detail: "in", estimated: false },
        ],
        timings: [{ session_id: "s1", turn_id: "t1", stage: "llm_total", milliseconds: 800, source: "server", tool_name: "" }],
      }),
    );
    expect(state.status).toBe("Tu turno.");
    expect(state.reviews.find((r) => r.key === "t1")?.detail).toBe("800 ms · 120 tokens");
  });

  it("a failed turn shows its message and keeps the session open", () => {
    const { state } = run(
      active(),
      event({ type: "turn_failed", turn_id: "t1", code: "timeout", message: "Ana tarda demasiado." }),
    );
    expect(state.error).toBe("Ana tarda demasiado.");
    expect(state.page).toBe("active");
  });

  it("keeps at most forty reviewer entries", () => {
    const actions = Array.from({ length: MAX_REVIEW_ENTRIES + 5 }, (_, i) =>
      event({ type: "tool_started", name: "search_knowledge", arguments: "" }, `t${i}`),
    );
    const { state } = run(active(), ...actions);
    expect(state.reviews).toHaveLength(MAX_REVIEW_ENTRIES);
    expect(state.reviews.at(-1)?.key).toBe(`t${MAX_REVIEW_ENTRIES + 4}`);
  });

  it("follows a language switch from the state", () => {
    const { state } = run(active(), event({ ...stateUpdated(), language: "en" }));
    expect(state.language).toBe("en");
  });
});

describe("turns", () => {
  it("sends the trimmed draft once and clears it when accepted", () => {
    const typed = run(active(), { type: "draft-changed", text: "  Me llamo Ana  " }).state;
    const sent = run(typed, { type: "text-submitted" }, { type: "text-submitted" });
    expect(sent.effects).toEqual([{ type: "post-turn", sessionId: "s1", text: "Me llamo Ana" }]);
    expect(canSend(sent.state)).toBe(false);
    const accepted = run(sent.state, { type: "turn-accepted" });
    expect(accepted.state.draft).toBe("");
    expect(canSend(accepted.state)).toBe(true);
    expect(accepted.effects).toEqual([{ type: "focus", target: "text" }]); // Enviar may have taken it
  });

  it("a rejected turn keeps the draft and shows why", () => {
    const typed = run(active(), { type: "draft-changed", text: "Hola" }, { type: "text-submitted" }).state;
    const { state } = run(typed, { type: "turn-rejected", message: "Sin conexión con el servidor." });
    expect(state.draft).toBe("Hola");
    expect(state.error).toBe("Sin conexión con el servidor.");
  });

  it("a turn the stream finished before the POST replied stays 'Tu turno.'", () => {
    const sent = run(active(), { type: "draft-changed", text: "Hola" }, { type: "text-submitted" }).state;
    expect(sent.status).toBe("Enviado…");
    const { state } = run(
      sent,
      event({ type: "turn_finished", turn_id: "t1", interrupted: false, usage: [], timings: [] }),
      { type: "turn-accepted" },
    );
    expect(state.status).toBe("Tu turno.");
  });

  it("sends nothing empty", () => {
    const { effects } = run(active(), { type: "draft-changed", text: "   " }, { type: "text-submitted" });
    expect(effects).toEqual([]);
  });
});

describe("confirmation", () => {
  it("answers the pending read-back at the revision on screen, once", () => {
    const pending = run(active(), event(pendingBrief(3))).state;
    expect(canAnswer(pending)).toBe(true);
    const { state, effects } = run(
      pending,
      { type: "confirmation-answered", answer: "affirm" },
      { type: "confirmation-answered", answer: "affirm" },
    );
    expect(effects).toEqual([
      { type: "post-answer", sessionId: "s1", confirmationId: "c1", answer: "affirm", revision: 3 },
    ]);
    expect(canAnswer(state)).toBe(false);
  });

  it("the next state from the stream re-opens the buttons", () => {
    const answered = run(active(), event(pendingBrief()), { type: "confirmation-answered", answer: "deny" }).state;
    const { state } = run(answered, event(pendingBrief(4)));
    expect(canAnswer(state)).toBe(true);
  });

  it("there is nothing to answer without a pending read-back", () => {
    const { effects } = run(active(), event(stateUpdated()), { type: "confirmation-answered", answer: "affirm" });
    expect(effects).toEqual([]);
  });
});

describe("voice", () => {
  it("talk starts the call and a second press stops it", () => {
    const started = run(active(), { type: "talk-pressed" });
    expect(started.effects).toEqual([{ type: "start-voice", sessionId: "s1" }]);
    expect(talkPressed(started.state)).toBe(true);
    const joined = run(started.state, { type: "voice-joined" }).state;
    expect(joined.voice).toBe("live");
    const stopped = run(joined, { type: "talk-pressed" });
    expect(stopped.effects).toEqual([{ type: "stop-voice" }]);
    expect(stopped.state.voice).toBe("off");
    expect(stopped.state.status).toBe("Tu turno.");
  });

  it("a call that never joined goes back to text", () => {
    const started = run(active(), { type: "talk-pressed" }).state;
    expect(run(started, { type: "voice-failed" }).state.voice).toBe("off");
  });

  it("a finished turn says it is listening while the call is on", () => {
    const live = run(active(), { type: "talk-pressed" }, { type: "voice-joined" }).state;
    const { state } = run(
      live,
      event({ type: "turn_finished", turn_id: "t1", interrupted: false, usage: [], timings: [] }),
    );
    expect(state.status).toBe("Escuchando…");
  });

  it("is not offered without a session or when the server has no hosted voice", () => {
    expect(canTalk(booted(null))).toBe(false);
    const { state, effects } = run({ ...active(), voiceOffered: false }, { type: "talk-pressed" });
    expect(effects).toEqual([]);
    expect(state.voice).toBe("off");
  });
});

describe("lifecycle", () => {
  it("a terminal state ends the page, waits for Ana's goodbye on a call, and offers the export", () => {
    const live = run(active(), { type: "talk-pressed" }, { type: "voice-joined" }).state;
    const { state, effects } = run(live, event(stateUpdated({ lifecycle: "completed", outcome: "reserved" })));
    expect(state.page).toBe("ended");
    expect(state.voice).toBe("closing");
    expect(effects).toEqual([{ type: "close-voice" }]);
    expect(exportHref(state)).toBe("/api/sessions/s1/export");
    expect(canEnd(state)).toBe(false);
    expect(canSend(state)).toBe(false);
    expect(run(state, { type: "voice-closed" }).state.voice).toBe("off");
  });

  it("an ended session takes no more text, answers or calls", () => {
    const ended = run(active(), event(pendingBrief()), event(stateUpdated({ lifecycle: "stopped" }))).state;
    const { effects } = run(
      ended,
      { type: "draft-changed", text: "Hola" },
      { type: "text-submitted" },
      { type: "confirmation-answered", answer: "affirm" },
      { type: "talk-pressed" },
      { type: "end-pressed" },
    );
    expect(effects).toEqual([]);
  });

  it("session_ended on a turn ends the page too, once", () => {
    const { state } = run(
      active(),
      event({ type: "turn_failed", turn_id: "t1", code: "session_ended", message: "La conversación ha terminado." }),
      event(stateUpdated({ lifecycle: "completed" })),
    );
    expect(state.page).toBe("ended");
    expect(state.status).toBe("Conversación terminada. Gracias.");
  });

  it("Terminar asks first, then ends", () => {
    const asked = run(active(), { type: "end-pressed" });
    expect(asked.effects).toEqual([
      { type: "ask", question: "¿Terminar la conversación?", then: { type: "end-confirmed" } },
    ]);
    const confirmed = run(asked.state, { type: "end-confirmed" }, { type: "end-accepted" });
    expect(confirmed.effects).toEqual([{ type: "end-session", sessionId: "s1" }]);
    expect(confirmed.state.page).toBe("ended");
  });

  it("Borrar asks first, then deletes everything and hangs up", () => {
    const live = run(active(), { type: "talk-pressed" }, { type: "voice-joined" }).state;
    const { state, effects } = run(live, { type: "delete-pressed" }, { type: "delete-confirmed" }, { type: "deleted" });
    expect(effects).toEqual([
      { type: "ask", question: "¿Borrar esta conversación y todos sus datos?", then: { type: "delete-confirmed" } },
      { type: "delete-session", sessionId: "s1" },
      { type: "stop-voice" },
    ]);
    expect(state.page).toBe("deleted");
    expect(state.voice).toBe("off");
    expect(state.resumeUrl).toBeNull();
    expect(canDelete(state)).toBe(false);
    expect(exportHref(state)).toBeNull();
  });
});

describe("signals (D62)", () => {
  it("waits for the verdict on the latest message, then shows it", () => {
    expect(signalStatus(active())).toBe("idle");
    const waiting = run(active(), userTurn("t1")).state;
    expect(signalStatus(waiting)).toBe("waiting");
    const ready = run(waiting, signal("t1", 0.8)).state;
    expect(signalStatus(ready)).toBe("ready");
    expect(latestSignal(ready)?.probabilities?.sentiment.frustrated).toBe(0.8);
    expect(signalStatus(run(ready, userTurn("t2")).state)).toBe("waiting");
  });

  it("Ana's opening turn has no candidate words, so nothing is awaited", () => {
    const { state } = run(active(), userTurn("t0", ""));
    expect(signalStatus(state)).toBe("idle");
  });

  it("a second verdict for the same message replaces the first", () => {
    const { state } = run(active(), signal("t1", 0.2), signal("t1", 0.9));
    expect(state.signals).toHaveLength(1);
    expect(latestSignal(state)?.probabilities?.sentiment.frustrated).toBe(0.9);
  });

  it("keeps the last twelve verdicts, oldest first", () => {
    const actions = Array.from({ length: MAX_SIGNAL_POINTS + 3 }, (_, i) => signal(`t${i}`, i / 100, 0.5));
    const { state } = run(active(), ...actions);
    expect(state.signals).toHaveLength(MAX_SIGNAL_POINTS);
    expect(state.signals[0].turnId).toBe("t3");
  });

  it("a label-only verdict is shown without bars", () => {
    const { state } = run(active(), userTurn("t1"), signal("t1", 0, 0, { probabilities: null }));
    expect(signalStatus(state)).toBe("ready");
    expect(latestSignal(state)?.probabilities).toBeNull();
  });

  it("says when no classifier runs", () => {
    expect(signalStatus({ ...active(), signalsMode: "off" })).toBe("off");
  });
});

describe("languages (D63)", () => {
  it("shows the three likeliest languages by their own names, then the rest as otros", () => {
    const bars = languageBars(active(), { es: 0.05, fr: 0.8, en: 0.1, other: 0.03, de: 0.02 });
    expect(bars.map((b) => b.label)).toEqual(["français", "English", "español", "otros"]);
    expect(bars[3].value).toBeCloseTo(0.05);
  });

  it("drops otros when the rest is nothing, and calls the unlisted option otro", () => {
    const bars = languageBars(active(), { other: 0.9, es: 0.1 });
    expect(bars.map((b) => b.label)).toEqual(["otro", "español"]);
  });

  it("reads right to left only in a language that does", () => {
    expect(isRtl(active())).toBe(false);
    const arabic = run(active(), event({ ...stateUpdated(), language: "ar" })).state;
    expect(isRtl(arabic)).toBe(true);
    expect(LANGUAGES.find((l) => l.code === "ar")?.rtl).toBe(true);
  });
});
