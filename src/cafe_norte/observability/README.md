# `observability`: evidence without transcripts

Structured JSON lines on stdout for Cloud Logging, keyed by session and turn, metadata only.
Transcripts live in the database, never in logs. Optional OpenTelemetry export to Langfuse
(EU): one trace per candidate turn, with spans for the model rounds, each tool call and the
store writes (D36). `CAFE_NORTE_TRACE_CONTENT=on` opts into redacted content for debugging
with synthetic data.

| Variable | Effect |
| --- | --- |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | both set: traces go to Langfuse; either missing: no tracing, events still on stdout |
| `LANGFUSE_BASE_URL` | the Langfuse host; `https://cloud.langfuse.com` (EU) when empty |
| `CAFE_NORTE_ENVIRONMENT` | `development` (default), `staging` or `production`: keeps test traces out of dashboards |
| `CAFE_NORTE_TRACE_CONTENT` | `on` exports the words (redacted); anything else exports none |

The trace of a turn: `handle-candidate-turn`, then `write-user-turn`, `invoke-agent`, a `step`
per model round (a `chat` generation with model, tokens, EUR cost and time to first token, and
the round's tool calls) and `write-assistant-turn`. Read a call from it before reading the
journal (`docs/runbook.md`).

| File | Contents |
| --- | --- |
| `contracts.py` | `VersionStamp`, `StageTiming`, `UsageRecord` (and `token_usage`, a model call's tokens as the two records every caller writes, D44), `PriceTable`, `CostEstimate`, `StructuredEvent`, and the `Telemetry` and `Span` ports |
| `redaction.py` | `redact(text, limit=2000)`: masks emails, phones, DNI/NIE, IBANs, cards and secrets, then truncates. Pure; `conversation` may import it for the tool arguments it journals (D44) |
| `events.py` | `emit(event)`: one JSON line on stdout keyed by session and turn (the envelope wins over the payload); every string in the payload goes through `redact`. A payload key named `text`, `transcript`, `content` or `message` is refused. `StdoutTelemetry` is the port with events and no traces |
| `fakes.py` | `NullTelemetry` (traces nothing) and `RecordingTelemetry` (keeps events and spans; `outline()` prints the trace as a tree) beside the `Telemetry` and `Span` ports in `contracts.py`. Spans take their parent explicitly (`span.child(...)`): a turn is an async generator, and ambient context does not survive its `yield` |
| `cost.py` | `load_prices` reads `prices/v1.yaml` (USD with source page, converted to EUR at the recorded rate); `estimate` is pure and lists unpriced usage instead of counting it as zero. Token usage is keyed `<model_id>:input` / `:output` |
| `telemetry.py` | `configure(env, process)` returns the `Telemetry` and a bounded shutdown flush. With both `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` it exports plain OpenTelemetry to Langfuse (`LANGFUSE_BASE_URL`, EU by default) on a private provider; without them it is `StdoutTelemetry`. One trace per turn; every span carries the trace name, session, release, environment, tags and the whole `VersionStamp` as metadata; a generation carries model, tokens and our EUR cost. Content only with `CAFE_NORTE_TRACE_CONTENT=on`, redacted |

Every session and evaluation run carries a `VersionStamp`; a number without one is not evidence.
