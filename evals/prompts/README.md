# Evaluation prompts

Instructions for the models the evaluation itself calls, never shown to a candidate (the
runtime's prompts live in `src/cafe_norte/conversation/prompts/`). English, versioned with
the code that formats them.

| File | Used by | Placeholders |
| --- | --- | --- |
| `judge.md` | `evals/judge.py`: the rubric judge's system message; the rubric and transcript go in the user message | none |
| `simulator.md` | `evals/simulator.py` (`ModelCandidateSimulator`): the system message of the simulated candidate | `{facts}`, `{declines}`, `{interview}`, `{mood}` |

The per-line instructions (language, question to ask, correction, withdrawal) are built from
the cue in `simulator.py`, not here: what the candidate does is code, how it says it is the
model's.
