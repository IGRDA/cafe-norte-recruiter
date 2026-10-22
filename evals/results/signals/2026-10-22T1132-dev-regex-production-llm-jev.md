# Signals: 2026-10-22T11:32:23+00:00

122 synthetic cases × 2 repetitions; production classifier prompt ana_v17. A failed call counts as neutral and the session language, as the runtime would. Latency is the call alone, off the turn's critical path in every design here.

| System | Model | Sentiment acc. | Macro-F1 | Frustrated/uncertain P | R | Language acc. | False switches | Missed requests | Stable | p50 | p95 | € / 1000 turns | Errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| regex | explicit_controls | – | – | – | – | 210/244 (86%) | 6/190 (3%) | 12/38 (32%) | 122/122 (100%) | 0 ms | 0 ms | 0 | 0/244 (0%) |
| production | gpt-4o-mini | 222/244 (91%) | 0.90 | 74/86 (86%) | 74/74 (100%) | – | – | – | 118/122 (97%) | 787 ms | 1096 ms | 0.0462 | 0/244 (0%) |
| llm | gpt-4o-mini | 208/244 (85%) | 0.82 | 63/68 (93%) | 63/74 (85%) | 223/244 (91%) | 20/190 (11%) | 0/38 (0%) | 113/122 (93%) | 792 ms | 1026 ms | 0.0496 | 0/244 (0%) |
| jev | typesafe/jev-1.14 | 230/244 (94%) | 0.93 | 70/70 (100%) | 70/74 (95%) | 243/244 (100%) | 1/190 (1%) | 0/38 (0%) | 121/122 (99%) | 275 ms | 406 ms | 0.0229 | 0/244 (0%) |

## regex

Reply language by kind (right / cases): stay 146/146 (100%), explicit 20/22 (91%), indirect 6/16 (38%), written_other 0/16 (0%), mention 16/22 (73%), borrowed 22/22 (100%).

## production

Sentiment, expected (rows) × predicted (columns):

| | neutral | positive | frustrated | uncertain | recall | precision |
| --- | --- | --- | --- | --- | --- | --- |
| neutral | 122 | 10 | 2 | 10 | 122/144 (85%) | 122/122 (100%) |
| positive | 0 | 26 | 0 | 0 | 26/26 (100%) | 26/36 (72%) |
| frustrated | 0 | 0 | 40 | 0 | 40/40 (100%) | 40/42 (95%) |
| uncertain | 0 | 0 | 0 | 34 | 34/34 (100%) | 34/44 (77%) |


## llm

Sentiment, expected (rows) × predicted (columns):

| | neutral | positive | frustrated | uncertain | recall | precision |
| --- | --- | --- | --- | --- | --- | --- |
| neutral | 122 | 17 | 2 | 3 | 122/144 (85%) | 122/133 (92%) |
| positive | 0 | 26 | 0 | 0 | 26/26 (100%) | 26/43 (60%) |
| frustrated | 0 | 0 | 39 | 1 | 39/40 (98%) | 39/43 (91%) |
| uncertain | 11 | 0 | 2 | 21 | 21/34 (62%) | 21/25 (84%) |

Reply language by kind (right / cases): stay 141/146 (97%), explicit 22/22 (100%), indirect 16/16 (100%), written_other 15/16 (94%), mention 11/22 (50%), borrowed 18/22 (82%).

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
| 0.80 | 65/74 (88%) | 0/170 (0%) |
| 0.90 | 62/74 (84%) | 0/170 (0%) |
| 0.95 | 60/74 (81%) | 0/170 (0%) |

Reply language by kind (right / cases): stay 146/146 (100%), explicit 22/22 (100%), indirect 16/16 (100%), written_other 16/16 (100%), mention 22/22 (100%), borrowed 21/22 (95%).

Brier score: 0.009.

Switch when p(other language) ≥ t; requests caught (explicit and indirect) and false alarms (stay, mention, borrowed):

| t | caught | false alarms |
| --- | --- | --- |
| 0.50 | 38/38 (100%) | 1/190 (1%) |
| 0.70 | 38/38 (100%) | 0/190 (0%) |
| 0.80 | 37/38 (97%) | 0/190 (0%) |
| 0.90 | 36/38 (95%) | 0/190 (0%) |
| 0.95 | 34/38 (89%) | 0/190 (0%) |

## Misses (first repetition)

| Case | Text | Expected | regex | production | llm | jev |
| --- | --- | --- | --- | --- | --- | --- |
| es-07 | Sí, el jueves por la tarde si puede ser. | neutral · es (stay) | es | neutral | positive · es | neutral · es |
| es-15 | No, está mal, es el 699 112 334. | neutral · es (stay) | es | frustrated | neutral · es | neutral · es |
| es-20 | ¿Me puedes pasar con una persona? | neutral · es (stay) | es | neutral | neutral · en | neutral · es |
| es-37 | que no que es el martes | frustrated · es (stay) | es | frustrated | frustrated · es | neutral · es |
| es-39 | Déjalo, es imposible hablar contigo. | frustrated · es (stay) | es | frustrated | frustrated · en | frustrated · es |
| es-43 | Creo que sí, pero tendría que mirarlo. | uncertain · es (stay) | es | uncertain | neutral · es | uncertain · es |
| es-46 | Igual por las tardes... o no, depende de la uni. | uncertain · es (stay) | es | uncertain | neutral · es | uncertain · es |
| es-48 | Eh... ¿perdona? No te he oído bien. | uncertain · es (stay) | es | uncertain | frustrated · en | uncertain · es |
| es-53 | ¿Me lo puedes decir en inglés? | neutral · en (explicit) | en | uncertain | neutral · en | neutral · en |
| es-54 | I already told you I don't speak Spanish! English please. | frustrated · en (explicit) | es | frustrated | frustrated · en | frustrated · en |
| es-56 | Sorry, my Spanish is not very good. | neutral · en (indirect) | es | uncertain | neutral · en | neutral · en |
| es-57 | I don't understand, I only speak English. | uncertain · en (indirect) | en | uncertain | neutral · en | neutral · en |
| es-58 | Perdona, no hablo bien español, soy de Londres. | neutral · en (indirect) | es | uncertain | neutral · en | neutral · en |
| es-59 | Mi español es muy malo, ¿hablas inglés? | neutral · en (indirect) | es | uncertain | neutral · en | neutral · en |
| es-61 | No entiendo bien el español, lo siento. | uncertain · en (indirect) | es | uncertain | uncertain · en | uncertain · en |
| es-62 | Monday to Friday, mornings only. | neutral · en (written_other) | es | neutral | neutral · en | neutral · en |
| es-63 | My name is Tom Baker. | neutral · en (written_other) | es | neutral | neutral · en | neutral · en |
| es-64 | I can start next Monday. | neutral · en (written_other) | es | neutral | neutral · en | neutral · en |
| es-65 | How much is the hourly pay? | neutral · en (written_other) | es | neutral | neutral · en | neutral · en |
| es-66 | This is taking forever. | frustrated · en (written_other) | es | frustrated | frustrated · en | frustrated · en |
| es-67 | ¿Hace falta saber inglés para el puesto? | neutral · es (mention) | es | neutral | neutral · en | neutral · es |
| es-70 | ¿Los clientes son turistas que hablan inglés? | neutral · es (mention) | es | neutral | neutral · en | neutral · es |
| es-72 | No hace falta que me hables en inglés, entiendo bien. | neutral · es (mention) | en | neutral | neutral · es | neutral · es |
| es-73 | No, en inglés no, sigue en español. | neutral · es (mention) | es | neutral | neutral · en | neutral · es |
| es-74 | Ok, perfecto. | neutral · es (borrowed) | es | positive | positive · es | positive · es |
| es-75 | Vale, thanks. | neutral · es (borrowed) | es | positive | positive · es | positive · es |
| es-76 | Sí, cool, me vale el jueves. | neutral · es (borrowed) | es | positive | positive · es | positive · es |
| es-77 | Trabajé de barista en un coffee shop en Londres. | neutral · es (borrowed) | es | neutral | positive · es | neutral · es |
| es-78 | Sorry, me he equivocado, es el 612 334 556. | neutral · es (borrowed) | es | neutral | neutral · es | neutral · en |
| en-03 | Yes, I have an EU passport. | neutral · en (stay) | en | neutral | positive · en | neutral · en |
| en-05 | None really, this would be my first job. | neutral · en (stay) | en | uncertain | neutral · en | neutral · en |
| en-07 | Yes, that's all correct. | neutral · en (stay) | en | neutral | positive · en | neutral · en |
| en-09 | Can I talk to a real person? | neutral · en (stay) | en | neutral | frustrated · en | neutral · en |
| en-24 | I think so, but I'd have to check with my current job. | uncertain · en (stay) | en | uncertain | neutral · en | uncertain · en |
| en-31 | Perdona, es que no entiendo mucho inglés. | uncertain · es (indirect) | en | uncertain | neutral · es | uncertain · es |
| en-32 | Los fines de semana, sobre todo los sábados. | neutral · es (written_other) | en | neutral | neutral · es | neutral · es |
| en-33 | Me llamo Ana García. | neutral · es (written_other) | en | neutral | neutral · es | neutral · es |
| en-34 | ¿Cuánto se paga la hora? | neutral · es (written_other) | en | neutral | neutral · es | neutral · es |
| en-35 | Do I need to speak Spanish for this job? | neutral · en (mention) | es | uncertain | uncertain · es | neutral · en |
| en-36 | I studied Spanish in Valencia for a year. | neutral · en (mention) | en | neutral | neutral · es | neutral · en |
| en-37 | My Spanish is okay but English is easier for me. | neutral · en (mention) | en | neutral | neutral · es | neutral · en |
| en-38 | No need to switch to Spanish, English is fine. | neutral · en (mention) | es | neutral | neutral · en | neutral · en |
| en-39 | Vale, sounds good. | neutral · en (borrowed) | en | positive | positive · en | positive · en |
| en-40 | Sí, Thursday works. | neutral · en (borrowed) | en | neutral | neutral · es | neutral · en |
| en-41 | Gracias, that's everything. | neutral · en (borrowed) | en | positive | positive · en | positive · en |
