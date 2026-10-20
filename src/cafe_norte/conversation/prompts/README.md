# Prompts

Plain Markdown, versioned with the code. `PROMPT_VERSION` is recorded on every session and
evaluation run. Facts about pay, hours and shifts are never written here: they come from the
configuration and the knowledge base, which are their single source.

| File | Purpose |
| --- | --- |
| `opening.md` | The spec's disclosure greeting, journaled at session creation without a model call (D19) |
| `system.md` | Ana's role, disclosure, one-question-at-a-time rules, confirmation discipline, language policy, what she must never infer |
| `fake_model.md` | The one sentence the fake model says in `make run` without a real model |
| `brief.md` | `key: sentence` table for the brief and the read-backs (Spanish; English with the language stage) |
| `summary.md` | Post-session narrative summary (structured generation, optional) |
| `classifier.md` | Sentiment and explicit-request classification |
| `simulator.md` | The candidate persona used by live evaluations (not shipped to production) |
