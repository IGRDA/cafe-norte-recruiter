# Runbook

Written at the deployment stage. Sections it will contain:

- Restart or revision replacement: what happens to active sessions (pause, resume link), how
  to verify no duplicate ownership.
- Failed call: where to look (session events, Cloud Logging by session id, Langfuse trace),
  how to offer the candidate text mode.
- Cleanup: retention job, manual delete endpoint, backup retention.
- Overload: admission counters, reducing voice capacity to one.
- Secrets rotation: `scripts/set_secrets.py` and a new Cloud Run revision.
- Teardown: `scripts/teardown.sh`, what is kept, what keeps billing.
