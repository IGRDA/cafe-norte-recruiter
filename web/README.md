# Browser UI

Vanilla ES modules served by FastAPI; no build step, no Node. `daily-js` 0.94.0 is pinned and vendored
under `vendor/` for audio. One SSE stream carries assistant text, state updates, sources and
voice status; one POST per text turn.

| File | Responsibility |
| --- | --- |
| `index.html` | Entry: demo disclosure, status line, transcript, composer with Enviar/Hablar, candidate card with every field's value or status, notes, lifecycle and outcome, the pending confirmation and its status, reviewer panel; composer and mic disabled once the session ends, and a link to download the session's JSON export appears. A language picker (`?lang=es|en`) reloads into a new session in that language (D28). Access code: on a 401. Store choice: later |
| `assets/app.js` | State store, SSE client with `Last-Event-ID`, turn submission with `input_id`, renderers |
| `assets/voice.js` | Two modes chosen by `GET /api/runtime`: `pipecat` joins the session's Daily room with the vendored `daily-js` (audio only, mic only after **Hablar**), plays Ana's track, posts `connected` and `first_audio` timings; `browser` is the Web Speech path of D18, kept until hosted voice is verified, its recognition and synthesis locale following each `turn_started.language` |
| `assets/app.css` | Compact responsive layout, readable contrast, visible errors |
| `vendor/` | Pinned third-party scripts with their version and hash recorded in `vendor/README.md` |

Rendered as text, never HTML. Interim STT text is provisional and styled as such. The reviewer
panel shows source turns, corrections, retrieval excerpts, validation errors, tool outcomes,
versions, timings and estimated usage; never hidden reasoning.
