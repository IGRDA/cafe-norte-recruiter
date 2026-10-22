# `api`: the HTTP boundary

FastAPI routes built from injected ports. Every session endpoint checks ownership through the
session cookie; the shared demo code alone opens nothing. Request bodies are validated before
any business call, validation errors never echo content, and responses carry the same security
headers locally and hosted.

| Method and path | Purpose |
| --- | --- |
| `POST /api/access` | Validate the shared demo code; set the access cookie |
| `GET /api/configurations` | Public store and role choices |
| `POST /api/sessions` | Create a session (configuration, language, channel); set the session cookie |
| `GET /api/sessions/{id}` | Consistent snapshot for the owner: state (with the pending confirmation), transcript, versions, `last_seq` |
| `GET /api/sessions/{id}/events` | SSE stream of `SessionEvent`; `Last-Event-ID` replays from a sequence number |
| `POST /api/sessions/{id}/turns` | One text turn with `input_id` and optional `expected_revision`; acknowledged once |
| `POST /api/sessions/{id}/confirmations/{confirmation_id}` | Explicit UI answer, through the same domain rules as the model path |
| `POST /api/sessions/{id}/voice` | Admission, private Daily room, start the voice task |
| `POST /api/sessions/{id}/voice/timings` | Browser-observed audio timings |
| `POST /api/sessions/{id}/end` | Finalize |
| `GET /api/sessions/{id}/export` | `<session_id>.json` download, built on demand from one store snapshot; any lifecycle |
| `DELETE /api/sessions/{id}` | Delete the demo session |
| `POST /api/resume` | Exchange a private resume token for a session cookie |
| `GET /health/live`, `GET /health/ready` | Process and initialized-services health |

| File | Contents |
| --- | --- |
| `contracts.py` | Request and response models, the `SessionEvent` envelope |
| `routes.py` | `build_router(...)` from ports |
| `access.py` | Demo code, cookies, resume token hashing, same-origin checks |
| `events.py` | SSE encoding and replay |
| `boundary.py` | `HttpBoundary`: 64 KiB body limit (413), CSP (`'unsafe-eval'` only for Daily's call machine), `Referrer-Policy`, `X-Content-Type-Options`, frame denial on every response, installed by the app factory (D38) |

Implemented today: `POST /api/sessions` (the reply carries the version stamp), `GET /api/sessions/{id}` (typed snapshot with `last_seq`), `POST …/confirmations/{confirmation_id}` (202; 404 if not the pending read-back, 409 if answered or the revision moved; D38), `POST …/end` (204, idempotent), `POST …/turns` (202, the turn runs in the background
and its events are journaled by the runtime), `GET …/events`, `GET /api/configurations`,
`GET /api/runtime` (which voice mode to offer, and the commit this process runs, which the deploy waits for), `POST …/voice` (admission, private room, bot
start; nothing left behind on failure), `POST …/voice/timings`, `GET …/export` (the snapshot stored at close, or built on demand while open), `POST /api/resume` (the private link's token, exchanged for the session cookie; Ana resumes), `DELETE /api/sessions/{id}` and health. Ownership is a signed session cookie. `ServiceError` maps to `{code, message}` with
fixed public text; request validation errors never echo the body.

On reconnect the browser resumes the stream from its last sequence; after a resume link it replays from the start, so the transcript is rebuilt from the journal;
transient tokens are not replayed.
