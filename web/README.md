# Browser UI

Vanilla ES modules served by FastAPI; no build step, no Node. `daily-js` is pinned and vendored
under `vendor/` for audio. One SSE stream carries assistant text, state updates, sources and
voice status; one POST per text turn.

| File | Responsibility |
| --- | --- |
| `index.html` | Entry: demo disclosure, access code, store and language, Talk/Chat buttons, fictional candidate card |
| `assets/app.js` | State store, SSE client with `Last-Event-ID`, turn submission with `input_id`, renderers |
| `assets/voice.js` | Microphone permission on demand, Daily join, barge-in and timing events |
| `assets/app.css` | Compact responsive layout, readable contrast, visible errors |
| `vendor/` | Pinned third-party scripts with their version and hash recorded in `vendor/README.md` |

Rendered as text, never HTML. Interim STT text is provisional and styled as such. The reviewer
panel shows source turns, corrections, retrieval excerpts, validation errors, tool outcomes,
versions, timings and estimated usage; never hidden reasoning.
