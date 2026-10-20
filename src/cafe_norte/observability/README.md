# `observability`: evidence without transcripts

Structured JSON lines on stdout for Cloud Logging, keyed by session and turn, metadata only.
Transcripts live in the database, never in logs. Optional OpenTelemetry export to Langfuse
(EU) for production traces; `CAFE_NORTE_TRACE_CONTENT=on` opts into truncated, regex-redacted
content for debugging with synthetic data.

| File | Contents |
| --- | --- |
| `contracts.py` | `VersionStamp`, `StageTiming`, `UsageRecord`, `PriceTable`, `CostEstimate`, `StructuredEvent` |
| `events.py` | `emit(event)`: one JSON line, redaction applied to free text |
| `cost.py` | Versioned price table with currency and verification date; marginal session cost vs shared cost |
| `telemetry.py` | Span ownership, bounded flush, Langfuse OTLP endpoint resolution (ported from luzia) |

Every session and evaluation run carries a `VersionStamp`; a number without one is not evidence.
