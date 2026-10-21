# `observability`: evidence without transcripts

Structured JSON lines on stdout for Cloud Logging, keyed by session and turn, metadata only.
Transcripts live in the database, never in logs. Optional OpenTelemetry export to Langfuse
(EU) for production traces; `CAFE_NORTE_TRACE_CONTENT=on` opts into truncated, regex-redacted
content for debugging with synthetic data.

| File | Contents |
| --- | --- |
| `contracts.py` | `VersionStamp`, `StageTiming`, `UsageRecord`, `PriceTable`, `CostEstimate`, `StructuredEvent` |
| `events.py` | `emit(event)`: one JSON line on stdout keyed by session and turn (the envelope wins over the payload); every string in the payload goes through `redact`, which masks emails, phones, DNI/NIE, IBANs, cards and secrets before it truncates. A payload key named `text`, `transcript`, `content` or `message` is refused. `StdoutTelemetry` is the port with events and no traces |
| `fakes.py` | `NullTelemetry` (traces nothing) and `RecordingTelemetry` (keeps events and spans; `outline()` prints the trace as a tree) beside the `Telemetry` and `Span` ports in `contracts.py`. Spans take their parent explicitly (`span.child(...)`): a turn is an async generator, and ambient context does not survive its `yield` |
| `cost.py` | `load_prices` reads `prices/v1.yaml` (USD with source page, converted to EUR at the recorded rate); `estimate` is pure and lists unpriced usage instead of counting it as zero. Token usage is keyed `<model_id>:input` / `:output` |
| `telemetry.py` | `configure(env, process)` returns the `Telemetry` and a bounded shutdown flush. With both `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` it exports plain OpenTelemetry to Langfuse (`LANGFUSE_BASE_URL`, EU by default) on a private provider; without them it is `StdoutTelemetry`. One trace per turn; every span carries the trace name, session, release, environment, tags and the whole `VersionStamp` as metadata; a generation carries model, tokens and our EUR cost. Content only with `CAFE_NORTE_TRACE_CONTENT=on`, redacted |

Every session and evaluation run carries a `VersionStamp`; a number without one is not evidence.
