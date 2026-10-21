# Prompts

Plain Markdown, versioned with the code. `PROMPT_VERSION` is recorded on every session and
evaluation run. Facts about pay, hours and shifts are never written here: they come from the
configuration and the knowledge base, which are their single source.

Instructions to the model are one Spanish file; the language it answers in is a session fact
(D28). Text the system says itself, word for word, has one file per language,
`<name>.<lang>.md`, loaded with `load(name, language)` / `table(name, language)`; the
`es` and `en` tables keep identical keys, and a test holds them to it.

| File | Purpose |
| --- | --- |
| `opening.<lang>.md` | The spec's disclosure greeting, journaled at session creation without a model call (D19) |
| `system.md` | Ana's role, disclosure, one-question-at-a-time rules, confirmation discipline, language policy, what she must never infer |
| `fake_model.md` | The one sentence the fake model says in `make run` without a real model |
| `brief.<lang>.md` | `key: sentence` table for the brief and the read-backs, including the date layout |
| `voice.<lang>.md` | The filler and idle sentences the voice channel speaks |
| `language.<lang>.md` | The closing line of the system message, written in that language: which language every reply is in. Without it a Spanish prompt pulls the model back to Spanish |
| `summary.md` | Post-session narrative summary (structured generation, optional) |
| `classifier.md` | Sentiment and explicit-request classification |
| `simulator.md` | The candidate persona used by live evaluations (not shipped to production) |
