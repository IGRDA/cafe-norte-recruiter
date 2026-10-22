# Browser UI

React 19 and strict TypeScript, built by Vite into `dist/`, which FastAPI serves (D61). One SSE
stream carries assistant text, state updates, sources and voice status; one POST per text turn.
Rendered as text, never HTML; no inline script or style, which is what the CSP of D38 relies on.

```bash
npm ci            # once (make setup does it)
npm run dev       # :5173 with hot reload; /api is proxied to make run on :8000
npm run check     # tsc, ESLint (react-hooks, jsx-a11y), Vitest: offline
npm run build     # dist/
npm run types     # src/api/contracts.ts from contracts.schema.json (make export-schema runs both)
```

## How the page is built: one reducer, effects as data

```text
 click / reply / stream event ──▶ Action ──▶ reduce(state, action, exec) ──▶ State ──▶ components
                                                      │ exec(effect)
                                                      ▼
                         effects.ts: fetch · EventSource · Daily · confirm · focus ──▶ Action
```

Every rule of the page lives in `src/page/reducer.ts`, a pure function tested without a
browser. Components read selectors (`canSend`, `confirmationOpen`, `exportHref`…) and dispatch
actions; they never fetch and hold no logic in `useEffect`. The runner only does I/O.

| Phase | Values |
| --- | --- |
| `page` | `loading` → `gate` (access code) → `choosing` (no store yet) → `active` → `ended` (export offered) or `deleted`; `failed` needs a reload |
| `voice` | `off` → `connecting` → `live` → (`closing`, waiting for Ana's goodbye) → `off`; only while `active` |
| `access` | `idle`, `checking`, `refused` |

| File | Responsibility |
| --- | --- |
| `index.html` | Vite entry: title, favicon, the root element |
| `src/main.tsx` | Reads `?store=`, `?lang=`, `#resume=` and `#code=` (D60) once, wires the browser into the runner's ports, renders `App` in StrictMode |
| `src/page/reducer.ts` | State, the `Action` and `Effect` unions, the reducer and the selectors. Boot, access gate (a `#code=` link is checked first and leaves the address bar; a wrong one lands on the form), chooser, create or resume, the SSE event handling (replay by `seq`, the transcript from the stream alone, at most 40 reviewer entries), turns, Sí / No at the revision on screen, voice, end and delete |
| `src/page/effects.ts` | The effect runner: typed API calls, the `EventSource`, the voice call, `confirm`, the address bar, focus. `Ports` makes every browser dependency replaceable in tests |
| `src/page/usePage.ts` | `useReducer` plus the effect queue: each step keeps the effects its action asked for, run once |
| `src/page/format.ts` | Display text from contract values: field values and statuses, the confirmation line, the booking in Madrid time, versions, sources, a finished turn's timings and tokens |
| `src/api/client.ts` | `fetch` wrappers per endpoint, and the SSE event names, checked against the payload union |
| `src/api/contracts.ts` | Generated from `contracts.schema.json` (`browser_schema()` in `api/contracts.py`); do not edit |
| `src/voice.ts` | Hosted voice, offered when `GET /api/runtime` says `pipecat`: joins the session's Daily room with `daily-js` 0.94.0 (audio only, mic only after **Hablar**), plays Ana's track, posts `connected` and `first_audio` timings. `start`, `stop`, `closing` (wait for Ana to leave after her goodbye, at most 20 s, D48). Loaded as its own chunk on the first **Hablar** |
| `src/components/` | `Header` (logo, store, chooser, status, resume link, access form), `Transcript`, `Composer` (Enviar, Hablar), `Signals` (the classifier's tone probabilities and the three likeliest reply languages plus "otros" for the latest message, as native meters, from `latestSignal`, `signalStatus` and `languageBars`, D62, D63), `Panel` (candidate card, confirmation with Sí / No, booking, sources, reviewer panel, export, Terminar, Borrar) |
| `src/app.css` | Compact responsive layout, readable contrast, visible errors |
| `public/logo-mark.svg` | The Café Norte mark (headset and bean) for the header and the favicon; the full logo with the wordmark is `docs/assets/logo.svg`, used by the README |

Tests (`*.test.ts[x]`, Vitest): `reducer.test.ts` asserts the next state and the exact effects
for each rule; `effects.test.ts` maps replies to actions with a fake `fetch`; `App.test.tsx`
renders the page against fake ports and runs axe; `contracts.test.ts` fails when
`contracts.ts` is stale.

The reviewer panel is a collapsible block: the versions (configuration, model, prompt,
knowledge base, schema, commit) from the create reply or the snapshot, then one collapsed entry
per turn with its tool calls with their redacted arguments (D44) and outcomes, retrieval
excerpts, timings and usage; never hidden reasoning.

## Accessibility (WCAG 2.2 AA)

- Landmarks: one `main`, the header, the conversation `section` and the `aside`, each labelled;
  one `h1`. `<html lang>` follows the session's language, which can switch mid-session (D53),
  and `<html dir>` is `rtl` for Arabic (D63). The chooser lists the languages `GET /api/runtime`
  returns, by their own names.
- The transcript is a `log`: new bubbles are announced politely. It follows the newest words
  unless the reader scrolled up, and is reachable by keyboard since it scrolls.
- Errors are `role="alert"`; the status line is `aria-live="polite"`. Focus goes to the access
  field when it appears and back to the message box after a send.
- Contrast: every text pair ≥ 4.5:1 (lowest: `--muted` on the user bubble, 5.9:1); field
  borders `--field` ≥ 3:1. A 3 px `:focus-visible` outline in `--accent`; buttons and fields
  are at least 44 px tall. Emoji on **Hablar** / **Parar** are hidden from screen readers.
- `App.test.tsx` runs axe on the rendered page (contrast is checked by hand: jsdom cannot
  compute it); ESLint runs `jsx-a11y`.
