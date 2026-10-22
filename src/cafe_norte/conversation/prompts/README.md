# Prompts

Plain Markdown, versioned with the code; one YAML file holds the decision model's questions
(D52). `PROMPT_VERSION` is recorded on every session and
evaluation run. Facts about pay, hours and shifts are never written here: they come from the
configuration and the knowledge base, which are their single source.

Instructions to the model are one Spanish file; the language it answers in is a session fact
(D28), named by one closing line for every language (D63). Text the system says itself, word
for word, has one file per tabled language (es, en), `<name>.<lang>.md`, loaded with
`load(name, language)` / `table(name, language)`; any other language reads the English file and
the runtime has the model word it (D63); the
`es` and `en` tables keep identical keys, and a test holds them to it.

| File | Purpose |
| --- | --- |
| `opening.<lang>.md` | The spec's disclosure greeting, journaled at session creation without a model call (D19) |
| `resume.<lang>.md` | What Ana says when a private resume link reopens the session, followed by the pending read-back if one is open; journaled, no model call (D32) |
| `system.md` | Ana's role, disclosure, one-question-at-a-time rules, confirmation discipline (with the one offer to go over a read-back the candidate cut, D39), language policy, what she must never infer |
| `fake_model.md` | The one sentence the fake model says in `make run` without a real model |
| `brief.<lang>.md` | `key: sentence` table for the brief and the read-backs, including the date layout and `review.check`, the short check after each part of a read-back that is gone over (D39) |
| `voice.<lang>.md` | The filler and idle sentences the voice channel speaks |
| `language.md` | The closing line of the system message: which language every reply is in, one English template naming the language in English and natively (D63; D28 measured that without it a Spanish prompt pulls the model back to Spanish) |
| `languages.yaml` | The ten languages Ana answers in (D63): native and English names for the closing line and the page, the words an explicit request may use, text direction |
| `controls.<lang>.md` | `key: sentence` table, spoken word for word by the runtime: `human` (the fixed reply to an explicit request for a person) `time_cap` (the goodbye when the active-time cap ends the session, D37) and `goodbye` (said when the candidate says goodbye after booking, D46) |
| `ui.<lang>.md` | `key: label` table: the words recorded for a Sí / No button press on a read-back card |
| `summary.md` | Post-session narrative summary (structured generation, optional) |
| `signal_questions.yaml` | The two `choice` questions the decision-model analyzer asks about one message (sentiment; keep or switch the language), with one criterion per option (D52). Measured with `make evals-signals` on both case sets |
| `classifier.md` | Sentiment of one candidate message as JSON with verbatim evidence (`ModelSignalAnalyzer`); explicit requests are not the model's job |
| `simulator.md` | The candidate persona used by live evaluations (not shipped to production) |
