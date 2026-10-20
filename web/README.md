# Browser UI

Vanilla ES modules served by FastAPI; no build step, no Node. `daily-js` is pinned and vendored
under `vendor/` for audio. One SSE stream carries assistant text, state updates, sources and
voice status; one POST per text turn.

| File | Responsibility |
| --- | --- |
| `index.html` | Entry: demo disclosure, status line, transcript, composer with Enviar/Hablar, candidate card, reviewer panel. Access code, store and language choice: later |
| `assets/app.js` | State store, SSE client with `Last-Event-ID`, turn submission with `input_id`, renderers |
| `assets/voice.js` | Today (D18): Web Speech recognition in, `speechSynthesis` out, microphone only after **Hablar**. Later: Daily join, barge-in and timing events |
| `assets/app.css` | Compact responsive layout, readable contrast, visible errors |
| `vendor/` | Pinned third-party scripts with their version and hash recorded in `vendor/README.md` |

Rendered as text, never HTML. Interim STT text is provisional and styled as such. The reviewer
panel shows source turns, corrections, retrieval excerpts, validation errors, tool outcomes,
versions, timings and estimated usage; never hidden reasoning.
