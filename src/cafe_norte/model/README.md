# `model`: the LLM behind one port

`contracts.py` defines `Model`, the only thing the conversation runtime knows about an LLM:
a stream of typed events for one call, with tool schemas passed as data. Adapters:

| File | Adapter | Status |
| --- | --- | --- |
| `fake.py` | `FakeModel`: scripted events, deterministic, used by every offline test and the CI evals; optional fallback script | done |
| `chat_completions.py` | Streaming Chat Completions over HTTP (Groq); serial tool calls; usage; reasoning deltas dropped | done, tested against a scripted transport |
| `select.py` | `model_from_env("groq/openai/gpt-oss-120b", env)`; `openai/<model>` with `OPENAI_API_KEY` as a local alternative | done |

Rules: the adapter never sees domain types; the runtime never sees provider JSON. Malformed,
incomplete or oversized provider output raises `ModelError` with a stable code. Reasoning
tokens are counted in usage, never surfaced as text. The 120B/20B comparison is a config
change, not a code change.
