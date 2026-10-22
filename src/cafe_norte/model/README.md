# `model`: the LLM behind one port

`contracts.py` defines `Model`, the only thing the conversation runtime knows about an LLM:
a stream of typed events for one call, with tool schemas passed as data. It also defines
`DecisionModel` (D52): typed `ChoiceQuestion`s about a state in, a `Decision` with one
probability per option out, no text. Adapters:

| File | Adapter | Status |
| --- | --- | --- |
| `fake.py` | `FakeModel`: scripted events, deterministic, used by every offline test and the CI evals; optional fallback script; `fail_next()` makes the next call raise as an outage would; a `policy` (messages and tools in, events out) for a model that must react to the prompt; `FakeDecisionModel` replays decisions or errors and records each state | done |
| `chat_completions.py` | Streaming Chat Completions over HTTP (Groq); serial tool calls; usage; reasoning deltas dropped | done, tested against a scripted transport |
| `decisions.py` | `DecisionsModel`: OpenRouter's Decisions API (alpha) for TypeSafe's Jev; `choice` questions only; an answer outside the criteria, a 4xx or a malformed body is a `ModelError`; one retry on a 429 or a 5xx | done, tested against a scripted transport |
| `select.py` | `model_from_env("groq/openai/gpt-oss-120b", env)`; `openai/<model>` with `OPENAI_API_KEY` as a local alternative; `decision_model_from_env("openrouter/typesafe/jev-1.14", env)` with `OPENROUTER_API_KEY` | done |

Rules: the adapter never sees domain types; the runtime never sees provider JSON. Malformed,
incomplete or oversized provider output raises `ModelError` with a stable code. Reasoning
tokens are counted in usage, never surfaced as text. The 120B/20B comparison is a config
change, not a code change.
