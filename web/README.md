# Browser UI

Vanilla ES modules served by FastAPI; no build step, no Node. `daily-js` 0.94.0 is pinned and vendored
under `vendor/` for audio. One SSE stream carries assistant text, state updates, sources and
voice status; one POST per text turn.

| File | Responsibility |
| --- | --- |
| `index.html` | Entry: demo disclosure, status line, transcript, composer with Enviar/Hablar, candidate card with every field's value or status, notes, lifecycle and outcome, the pending confirmation and its status, reviewer panel; composer and mic disabled once the session ends, a link to download the session's JSON export, the private resume link shown once, and the delete action. A chooser (`?store=<config_id>&lang=es|en`) from `GET /api/configurations`: nothing is created until Empezar, and a new choice reloads into a new session (D28, D38); the header names the store. Sí / No on the pending read-back, Terminar and Borrar. Access code: on a 401 |
| `assets/app.js` | State store, SSE client with `Last-Event-ID`, turn submission with `input_id`, confirmation answers at the revision on screen, the chooser, renderers |
| `assets/voice.js` | Hosted voice, offered when `GET /api/runtime` says `pipecat`: joins the session's Daily room with the vendored `daily-js` (audio only, mic only after **Hablar**), plays Ana's track, posts `connected` and `first_audio` timings. Three calls for `app.js`: `start`, `stop`, `closing` (the session ended: wait for Ana to leave after her goodbye, at most 20 s, then leave, D48). With voice `off` the **Hablar** button is hidden. The browser's own speech mode was removed (D45) |
| `assets/app.css` | Compact responsive layout, readable contrast, visible errors |
| `vendor/` | Pinned third-party scripts with their version and hash recorded in `vendor/README.md` |

Rendered as text, never HTML. The reviewer
panel is a collapsible block: the versions (configuration, model, prompt, knowledge base,
schema, commit) from the create reply or the snapshot, then one collapsed entry per turn with
its tool calls with their redacted arguments (D44) and outcomes, retrieval excerpts, timings and usage; never hidden reasoning. The page has
no inline script or style, which is what the CSP of D38 relies on.
