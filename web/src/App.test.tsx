// The page rendered against fake ports: the API, the stream and the dialog are in-memory.
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it, vi } from "vitest";
import type { SessionEvent } from "./api/contracts";
import { App } from "./App";
import type { Ports } from "./page/effects";
import { pendingBrief, STORE, VERSIONS } from "./page/fixtures";

class FakeStream {
  listeners = new Map<string, (message: MessageEvent<string>) => void>();
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;
  addEventListener(name: string, listener: (message: MessageEvent<string>) => void) {
    this.listeners.set(name, listener);
  }
  close() {}
  emit(seq: number, payload: SessionEvent["payload"], turnId = "t1") {
    const event: SessionEvent = { session_id: "s1", seq, turn_id: turnId, at: "2026-10-22T10:00:00Z", payload };
    act(() => this.listeners.get(payload.type)?.(new MessageEvent(payload.type, { data: JSON.stringify(event) })));
  }
}

/** "Conectada." renders before the effect that opens the stream runs: wait for both, or an
 * event emitted on a slow machine reaches no listener. */
async function opened(stream: FakeStream) {
  await screen.findByText("Conectada.");
  await waitFor(() => expect(stream.listeners.size).toBeGreaterThan(0));
}

function json(status: number, body: unknown = null): Response {
  return new Response(body === null ? null : JSON.stringify(body), { status });
}

function setup({ needsCode = false, code = null as string | null } = {}) {
  const stream = new FakeStream();
  const posted: { url: string; body: unknown }[] = [];
  let open = !needsCode;
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (init?.body) posted.push({ url, body: JSON.parse(String(init.body)) });
    if (url === "/api/runtime") return json(200, { voice: "off", signals: "jev", config_ids: ["chamberi"], access_required: needsCode, commit_sha: "x" });
    if (url === "/api/configurations") return json(200, [STORE]);
    if (url === "/api/access") {
      open = (init?.body && JSON.parse(String(init.body)).code === "1234") || false;
      return json(open ? 204 : 401);
    }
    if (url === "/api/sessions" && method === "POST")
      return open ? json(201, { session_id: "s1", resume_url: "/#resume=abc", versions: VERSIONS }) : json(401, { code: "unauthorized", message: "x" });
    if (url.endsWith("/turns")) return json(202, { input_id: "id" });
    if (url.includes("/confirmations/")) return json(202, { input_id: "id" });
    throw new Error(`unexpected ${method} ${url}`);
  });
  const ports: Ports = {
    fetch: fetcher,
    openStream: () => stream as unknown as EventSource,
    createVoice: vi.fn(),
    confirm: () => true,
    clearFragment: vi.fn(),
    navigate: vi.fn(),
    focus: (id) => document.getElementById(id)?.focus(),
    newId: () => "id-1",
  };
  const view = render(<App requested={{ store: "chamberi", language: "es", resumeToken: null, code }} ports={ports} />);
  return { ...view, stream, posted, ports };
}

describe("App", () => {
  it("opens a session, shows Ana's words from the stream and sends a turn", async () => {
    const { stream, posted } = setup();
    await opened(stream);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Ana · Café Norte Chamberí");
    stream.emit(1, { type: "turn_started", turn_id: "t1", language: "es", text: "" });
    stream.emit(2, { type: "assistant_text", text: "Hola, soy Ana.", spoken_form: "" });
    expect(screen.getByText("Hola, soy Ana.")).toBeInTheDocument();

    const input = screen.getByLabelText("Tu mensaje");
    await userEvent.type(input, "Me llamo Iker{Enter}");
    await waitFor(() => expect(posted.at(-1)).toEqual({ url: "/api/sessions/s1/turns", body: { input_id: "id-1", text: "Me llamo Iker" } }));
    await waitFor(() => expect(input).toHaveValue(""));
  });

  it("asks for the access code, then opens the session", async () => {
    setup({ needsCode: true });
    const code = await screen.findByLabelText("Código de acceso");
    await waitFor(() => expect(code).toHaveFocus());
    await userEvent.type(code, "0000{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("Código incorrecto.");
    await userEvent.clear(code);
    await userEvent.type(code, "1234{Enter}");
    await screen.findByText("Conectada.");
    expect(screen.queryByLabelText("Código de acceso")).not.toBeInTheDocument();
  });

  it("a link with #code= opens the session without showing the form", async () => {
    const { posted, ports } = setup({ needsCode: true, code: "1234" });
    await screen.findByText("Conectada.");
    expect(ports.clearFragment).toHaveBeenCalled();
    expect(posted[0]).toEqual({ url: "/api/access", body: { code: "1234" } });
    expect(screen.queryByLabelText("Código de acceso")).not.toBeInTheDocument();
  });

  it("answers a pending read-back with Sí", async () => {
    const { stream, posted } = setup();
    await opened(stream);
    stream.emit(1, pendingBrief(3));
    await userEvent.click(screen.getByRole("button", { name: "Sí" }));
    await waitFor(() =>
      expect(posted.at(-1)).toEqual({
        url: "/api/sessions/s1/confirmations/c1",
        body: { input_id: "id-1", answer: "affirm", expected_revision: 3 },
      }),
    );
    expect(screen.getByRole("button", { name: "Sí" })).toBeDisabled();
  });

  it("speaks the session's language: <html lang> follows a switch", async () => {
    const { stream } = setup();
    await opened(stream);
    expect(document.documentElement.lang).toBe("es");
    stream.emit(1, { ...pendingBrief(), language: "en" });
    expect(document.documentElement.lang).toBe("en");
  });

  it("shows the latest message's tone and language probabilities as they arrive", async () => {
    const { stream } = setup();
    await opened(stream);
    expect(screen.getByText("Aparecerán con tu primer mensaje.")).toBeInTheDocument();
    stream.emit(1, { type: "turn_started", turn_id: "t1", language: "es", text: "esto es lentísimo" });
    expect(screen.getByText("Leyendo tu último mensaje…")).toBeInTheDocument();
    stream.emit(2, {
      type: "signal_recorded",
      signal: {
        turn_id: "t1",
        sentiment: "frustrated",
        explicit_human_request: false,
        explicit_stop: false,
        language_switch_to: null,
        evidence_text: "esto es lentísimo",
        probabilities: {
          sentiment: { neutral: 0.1, positive: 0, frustrated: 0.86, uncertain: 0.04 },
          language: { keep: 0.97, switch: 0.03 },
        },
      },
    });
    expect(screen.getByRole("meter", { name: "frustrado" })).toHaveAttribute("value", "0.86");
    expect(screen.getByRole("meter", { name: "mantener" })).toHaveAttribute("value", "0.97");
    expect(screen.getByRole("meter", { name: "frustrado" })).toHaveAttribute("value", "0.86");
    expect(screen.getByRole("meter", { name: "mantener" })).toHaveAttribute("value", "0.97");
    expect(screen.getByText("86 %")).toBeInTheDocument();
    expect(screen.queryByText(/Jev/)).not.toBeInTheDocument();
  });

  it("has no accessibility violations axe can find", async () => {
    const { container, stream } = setup();
    await opened(stream);
    stream.emit(1, pendingBrief(3));
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(" | ")}`)).toEqual([]);
  });
});
