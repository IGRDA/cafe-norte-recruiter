# Signals: 2026-10-22T11:19:29+00:00

122 synthetic cases × 2 repetitions; production classifier prompt ana_v17. A failed call counts as neutral and the session language, as the runtime would. Latency is the call alone, off the turn's critical path in every design here.

| System | Model | Sentiment acc. | Macro-F1 | Frustrated/uncertain P | R | Language acc. | False switches | Missed requests | Stable | p50 | p95 | € / 1000 turns | Errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| regex | explicit_controls | – | – | – | – | 210/244 (86%) | 6/190 (3%) | 12/38 (32%) | 122/122 (100%) | 0 ms | 0 ms | 0 | 0/244 (0%) |
| production | gpt-4o-mini | 219/244 (90%) | 0.89 | 73/86 (85%) | 73/74 (99%) | – | – | – | 119/122 (98%) | 816 ms | 1120 ms | 0.0462 | 0/244 (0%) |
| llm | gpt-4o-mini | 199/244 (82%) | 0.82 | 74/89 (83%) | 74/74 (100%) | 233/244 (95%) | 0/190 (0%) | 0/38 (0%) | 118/122 (97%) | 807 ms | 1205 ms | 0.0427 | 0/244 (0%) |
| jev | typesafe/jev-1.14 | 230/244 (94%) | 0.93 | 70/70 (100%) | 70/74 (95%) | 232/244 (95%) | 0/190 (0%) | 8/38 (21%) | 122/122 (100%) | 279 ms | 401 ms | 0.0207 | 0/244 (0%) |

## regex

Reply language by kind (right / cases): stay 146/146 (100%), explicit 20/22 (91%), indirect 6/16 (38%), written_other 0/16 (0%), mention 16/22 (73%), borrowed 22/22 (100%).

## production

Sentiment, expected (rows) × predicted (columns):

| | neutral | positive | frustrated | uncertain | recall | precision |
| --- | --- | --- | --- | --- | --- | --- |
| neutral | 120 | 11 | 2 | 11 | 120/144 (83%) | 120/121 (99%) |
| positive | 0 | 26 | 0 | 0 | 26/26 (100%) | 26/37 (70%) |
| frustrated | 1 | 0 | 39 | 0 | 39/40 (98%) | 39/41 (95%) |
| uncertain | 0 | 0 | 0 | 34 | 34/34 (100%) | 34/45 (76%) |


## llm

Sentiment, expected (rows) × predicted (columns):

| | neutral | positive | frustrated | uncertain | recall | precision |
| --- | --- | --- | --- | --- | --- | --- |
| neutral | 99 | 30 | 5 | 10 | 99/144 (69%) | 99/99 (100%) |
| positive | 0 | 26 | 0 | 0 | 26/26 (100%) | 26/56 (46%) |
| frustrated | 0 | 0 | 40 | 0 | 40/40 (100%) | 40/45 (89%) |
| uncertain | 0 | 0 | 0 | 34 | 34/34 (100%) | 34/44 (77%) |

Reply language by kind (right / cases): stay 146/146 (100%), explicit 22/22 (100%), indirect 16/16 (100%), written_other 5/16 (31%), mention 22/22 (100%), borrowed 22/22 (100%).

## jev

Sentiment, expected (rows) × predicted (columns):

| | neutral | positive | frustrated | uncertain | recall | precision |
| --- | --- | --- | --- | --- | --- | --- |
| neutral | 134 | 10 | 0 | 0 | 134/144 (93%) | 134/138 (97%) |
| positive | 0 | 26 | 0 | 0 | 26/26 (100%) | 26/36 (72%) |
| frustrated | 2 | 0 | 38 | 0 | 38/40 (95%) | 38/38 (100%) |
| uncertain | 2 | 0 | 0 | 32 | 32/34 (94%) | 32/32 (100%) |

Brier score: 0.094 (0 is perfect, 2 the worst).

Frustrated or uncertain acted on when its probability ≥ t:

| t | caught | false alarms |
| --- | --- | --- |
| 0.50 | 70/74 (95%) | 0/170 (0%) |
| 0.70 | 68/74 (92%) | 0/170 (0%) |
| 0.80 | 64/74 (86%) | 0/170 (0%) |
| 0.90 | 62/74 (84%) | 0/170 (0%) |
| 0.95 | 59/74 (80%) | 0/170 (0%) |

Reply language by kind (right / cases): stay 146/146 (100%), explicit 20/22 (91%), indirect 10/16 (62%), written_other 12/16 (75%), mention 22/22 (100%), borrowed 22/22 (100%).

Brier score: 0.074.

Switch when p(other language) ≥ t; requests caught (explicit and indirect) and false alarms (stay, mention, borrowed):

| t | caught | false alarms |
| --- | --- | --- |
| 0.50 | 30/38 (79%) | 0/190 (0%) |
| 0.70 | 27/38 (71%) | 0/190 (0%) |
| 0.80 | 23/38 (61%) | 0/190 (0%) |
| 0.90 | 18/38 (47%) | 0/190 (0%) |
| 0.95 | 11/38 (29%) | 0/190 (0%) |

## Misses (first repetition)

| Case | Text | Expected | regex | production | llm | jev |
| --- | --- | --- | --- | --- | --- | --- |
| es-02 | De lunes a viernes, por las mañanas. | neutral · es (stay) | es | neutral | positive · es | neutral · es |
| es-04 | A partir del 3 de noviembre. | neutral · es (stay) | es | neutral | positive · es | neutral · es |
| es-06 | Dos años de camarera en un bar de Lavapiés. | neutral · es (stay) | es | neutral | positive · es | neutral · es |
| es-07 | Sí, el jueves por la tarde si puede ser. | neutral · es (stay) | es | neutral | positive · es | neutral · es |
| es-15 | No, está mal, es el 699 112 334. | neutral · es (stay) | es | frustrated | frustrated · es | neutral · es |
| es-37 | que no que es el martes | frustrated · es (stay) | es | frustrated | frustrated · es | neutral · es |
| es-54 | I already told you I don't speak Spanish! English please. | frustrated · en (explicit) | es | frustrated | frustrated · en | frustrated · en |
| es-55 | ¡Genial! ¿Lo podemos hacer en inglés? | positive · en (explicit) | en | positive | positive · en | positive · es |
| es-56 | Sorry, my Spanish is not very good. | neutral · en (indirect) | es | uncertain | uncertain · en | neutral · es |
| es-57 | I don't understand, I only speak English. | uncertain · en (indirect) | en | uncertain | uncertain · en | neutral · en |
| es-58 | Perdona, no hablo bien español, soy de Londres. | neutral · en (indirect) | es | uncertain | uncertain · en | neutral · es |
| es-59 | Mi español es muy malo, ¿hablas inglés? | neutral · en (indirect) | es | uncertain | uncertain · en | neutral · en |
| es-61 | No entiendo bien el español, lo siento. | uncertain · en (indirect) | es | uncertain | uncertain · en | uncertain · en |
| es-62 | Monday to Friday, mornings only. | neutral · en (written_other) | es | neutral | neutral · es | neutral · es |
| es-63 | My name is Tom Baker. | neutral · en (written_other) | es | neutral | neutral · es | neutral · en |
| es-64 | I can start next Monday. | neutral · en (written_other) | es | neutral | positive · es | neutral · en |
| es-65 | How much is the hourly pay? | neutral · en (written_other) | es | neutral | neutral · en | neutral · en |
| es-66 | This is taking forever. | frustrated · en (written_other) | es | frustrated | frustrated · es | frustrated · en |
| es-67 | ¿Hace falta saber inglés para el puesto? | neutral · es (mention) | es | uncertain | uncertain · es | neutral · es |
| es-72 | No hace falta que me hables en inglés, entiendo bien. | neutral · es (mention) | en | neutral | neutral · es | neutral · es |
| es-74 | Ok, perfecto. | neutral · es (borrowed) | es | positive | positive · es | positive · es |
| es-75 | Vale, thanks. | neutral · es (borrowed) | es | positive | positive · es | positive · es |
| es-76 | Sí, cool, me vale el jueves. | neutral · es (borrowed) | es | positive | positive · es | positive · es |
| es-77 | Trabajé de barista en un coffee shop en Londres. | neutral · es (borrowed) | es | neutral | positive · es | neutral · es |
| es-78 | Sorry, me he equivocado, es el 612 334 556. | neutral · es (borrowed) | es | neutral | frustrated · es | neutral · es |
| en-02 | Weekends and Wednesday evenings. | neutral · en (stay) | en | neutral | positive · en | neutral · en |
| en-03 | Yes, I have an EU passport. | neutral · en (stay) | en | neutral | positive · en | neutral · en |
| en-04 | From the first of December. | neutral · en (stay) | en | neutral | positive · en | neutral · en |
| en-07 | Yes, that's all correct. | neutral · en (stay) | en | neutral | positive · en | neutral · en |
| en-09 | Can I talk to a real person? | neutral · en (stay) | en | neutral | frustrated · en | neutral · en |
| en-30 | Actually I'm Spanish, it's easier for me in Spanish. | neutral · es (indirect) | es | neutral | neutral · es | neutral · en |
| en-31 | Perdona, es que no entiendo mucho inglés. | uncertain · es (indirect) | en | uncertain | uncertain · es | uncertain · es |
| en-32 | Los fines de semana, sobre todo los sábados. | neutral · es (written_other) | en | neutral | neutral · es | neutral · en |
| en-33 | Me llamo Ana García. | neutral · es (written_other) | en | neutral | neutral · en | neutral · es |
| en-34 | ¿Cuánto se paga la hora? | neutral · es (written_other) | en | neutral | neutral · es | neutral · es |
| en-35 | Do I need to speak Spanish for this job? | neutral · en (mention) | es | uncertain | uncertain · en | neutral · en |
| en-38 | No need to switch to Spanish, English is fine. | neutral · en (mention) | es | neutral | neutral · en | neutral · en |
| en-39 | Vale, sounds good. | neutral · en (borrowed) | en | positive | positive · en | positive · en |
| en-40 | Sí, Thursday works. | neutral · en (borrowed) | en | positive | positive · en | neutral · en |
| en-41 | Gracias, that's everything. | neutral · en (borrowed) | en | positive | positive · en | positive · en |
