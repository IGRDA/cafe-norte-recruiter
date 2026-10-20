# Store configurations

Two versioned configurations, same engine, no editor. Each file is validated into
`domain.contracts.StoreConfiguration` at startup; a session snapshots the id and version it
started with and never switches.

| File | Store | Variation |
| --- | --- | --- |
| `chamberi_barista_v1.yaml` | Café Norte Chamberí, Madrid | 35 h/week; morning and afternoon shifts |
| `arganzuela_barista_v1.yaml` | Café Norte Arganzuela, Madrid | 20 h/week; afternoon and weekend shifts |

Pay, hours and addresses are fictional and have exactly one source: these files plus the
knowledge documents they reference. Prompts never restate them.
