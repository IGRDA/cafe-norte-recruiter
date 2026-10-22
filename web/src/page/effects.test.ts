// @vitest-environment node
// The runner only maps replies to actions; a fake fetch stands in for the API.
import { describe, expect, it, vi } from "vitest";
import { createRunner, type Ports } from "./effects";
import type { Action } from "./reducer";

function reply(status: number, body: unknown = null): Response {
  return new Response(body === null ? null : JSON.stringify(body), { status });
}

function setup(responses: Record<string, Response | Error>) {
  const actions: Action[] = [];
  const calls: { url: string; init?: RequestInit }[] = [];
  const ports: Ports = {
    fetch: vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init });
      const response = responses[`${init?.method ?? "GET"} ${url}`];
      if (!response) throw new Error(`unexpected ${url}`);
      if (response instanceof Error) throw response;
      return response;
    }),
    openStream: vi.fn(),
    createVoice: vi.fn(),
    confirm: vi.fn(() => true),
    clearFragment: vi.fn(),
    navigate: vi.fn(),
    focus: vi.fn(),
    newId: () => "id-1",
  };
  const runner = createRunner(ports, (action) => actions.push(action));
  const settled = () => vi.waitFor(() => expect(actions.length).toBeGreaterThan(0));
  return { runner, ports, actions, calls, settled };
}

describe("effect runner", () => {
  it("boots with hosted voice and the stores", async () => {
    const { runner, actions, settled } = setup({
      "GET /api/runtime": reply(200, { voice: "pipecat", config_ids: [], access_required: true, commit_sha: "x" }),
      "GET /api/configurations": reply(200, [{ config_id: "chamberi" }]),
    });
    runner.run({ type: "load-boot" });
    await settled();
    expect(actions).toEqual([{ type: "booted", voiceOffered: true, stores: [{ config_id: "chamberi" }] }]);
  });

  it("a 401 on session creation asks for the code", async () => {
    const { runner, actions, settled } = setup({ "POST /api/sessions": reply(401, { code: "unauthorized", message: "x" }) });
    runner.run({ type: "create-session", store: "chamberi", language: "es" });
    await settled();
    expect(actions).toEqual([{ type: "session-needs-code" }]);
  });

  it("posts a turn with a fresh input id and passes the server's message on a refusal", async () => {
    const { runner, actions, calls, settled } = setup({
      "POST /api/sessions/s1/turns": reply(409, { code: "busy", message: "Ana sigue con el turno anterior." }),
    });
    runner.run({ type: "post-turn", sessionId: "s1", text: "Hola" });
    await settled();
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ input_id: "id-1", text: "Hola" });
    expect(actions).toEqual([{ type: "turn-rejected", message: "Ana sigue con el turno anterior." }]);
  });

  it("a network failure is 'no connection', not a crash", async () => {
    const { runner, actions, settled } = setup({ "POST /api/sessions/s1/turns": new TypeError("offline") });
    runner.run({ type: "post-turn", sessionId: "s1", text: "Hola" });
    await settled();
    expect(actions).toEqual([{ type: "turn-rejected", message: "Sin conexión con el servidor." }]);
  });

  it("answers at the expected revision", async () => {
    const { runner, actions, calls, settled } = setup({ "POST /api/sessions/s1/confirmations/c1": reply(202, {}) });
    runner.run({ type: "post-answer", sessionId: "s1", confirmationId: "c1", answer: "deny", revision: 7 });
    await settled();
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ input_id: "id-1", answer: "deny", expected_revision: 7 });
    expect(actions).toEqual([{ type: "answer-accepted" }]);
  });

  it("asks before acting, and a no dispatches nothing", () => {
    const { runner, ports, actions } = setup({});
    runner.run({ type: "ask", question: "¿Seguro?", then: { type: "end-confirmed" } });
    expect(actions).toEqual([{ type: "end-confirmed" }]);
    vi.mocked(ports.confirm).mockReturnValue(false);
    runner.run({ type: "ask", question: "¿Seguro?", then: { type: "end-confirmed" } });
    expect(actions).toHaveLength(1);
  });
});
