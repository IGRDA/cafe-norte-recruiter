# Prompts

Plain Markdown, versioned with the code. `PROMPT_VERSION` is recorded on every session and
evaluation run. Facts about pay, hours and shifts are never written here: they come from the
configuration and the knowledge base, which are their single source.

| File | Purpose |
| --- | --- |
| `system.md` | Ana's role, disclosure, one-question-at-a-time rules, confirmation discipline, language policy, what she must never infer |
| `brief.md` | Template for the deterministic brief, both languages |
| `summary.md` | Post-session narrative summary (structured generation, optional) |
| `classifier.md` | Sentiment and explicit-request classification |
| `simulator.md` | The candidate persona used by live evaluations (not shipped to production) |
