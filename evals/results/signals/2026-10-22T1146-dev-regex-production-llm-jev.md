# Signals: 2026-10-22T11:46:16+00:00

122 synthetic cases × 2 repetitions; production classifier prompt ana_v18. A failed call counts as neutral and the session language, as the runtime would. Latency is the call alone, off the turn's critical path in every design here.

| System | Model | Sentiment acc. | Macro-F1 | Frustrated/uncertain P | R | Language acc. | False switches | Missed requests | Stable | p50 | p95 | € / 1000 turns | Errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| regex | explicit_controls | – | – | – | – | 216/244 (89%) | 0/190 (0%) | 12/38 (32%) | 122/122 (100%) | 0 ms | 0 ms | 0 | 0/244 (0%) |
| production | gpt-4o-mini | 220/244 (90%) | 0.89 | 73/86 (85%) | 73/74 (99%) | – | – | – | 120/122 (98%) | 823 ms | 1125 ms | 0.0463 | 0/244 (0%) |
| llm | gpt-4o-mini | 209/244 (86%) | 0.83 | 65/71 (92%) | 65/74 (88%) | 224/244 (92%) | 19/190 (10%) | 0/38 (0%) | 111/122 (91%) | 784 ms | 1076 ms | 0.0496 | 0/244 (0%) |
| jev | typesafe/jev-1.14 | 230/244 (94%) | 0.93 | 70/70 (100%) | 70/74 (95%) | 244/244 (100%) | 0/190 (0%) | 0/38 (0%) | 122/122 (100%) | 292 ms | 483 ms | 0.0229 | 0/244 (0%) |

## regex

Reply language by kind (right / cases): stay 146/146 (100%), explicit 22/22 (100%), indirect 4/16 (25%), written_other 0/16 (0%), mention 22/22 (100%), borrowed 22/22 (100%).

## production

Sentiment, expected (rows) × predicted (columns):

| | neutral | positive | frustrated | uncertain | recall | precision |
| --- | --- | --- | --- | --- | --- | --- |
| neutral | 121 | 10 | 2 | 11 | 121/144 (84%) | 121/122 (99%) |
| positive | 0 | 26 | 0 | 0 | 26/26 (100%) | 26/36 (72%) |
| frustrated | 1 | 0 | 39 | 0 | 39/40 (98%) | 39/41 (95%) |
| uncertain | 0 | 0 | 0 | 34 | 34/34 (100%) | 34/45 (76%) |


## llm

Sentiment, expected (rows) × predicted (columns):

| | neutral | positive | frustrated | uncertain | recall | precision |
| --- | --- | --- | --- | --- | --- | --- |
| neutral | 121 | 17 | 3 | 3 | 121/144 (84%) | 121/130 (93%) |
| positive | 0 | 26 | 0 | 0 | 26/26 (100%) | 26/43 (60%) |
| frustrated | 0 | 0 | 39 | 1 | 39/40 (98%) | 39/44 (89%) |
| uncertain | 9 | 0 | 2 | 23 | 23/34 (68%) | 23/27 (85%) |

Reply language by kind (right / cases): stay 141/146 (97%), explicit 22/22 (100%), indirect 16/16 (100%), written_other 15/16 (94%), mention 12/22 (55%), borrowed 18/22 (82%).

## jev

Sentiment, expected (rows) × predicted (columns):

| | neutral | positive | frustrated | uncertain | recall | precision |
| --- | --- | --- | --- | --- | --- | --- |
| neutral | 134 | 10 | 0 | 0 | 134/144 (93%) | 134/138 (97%) |
| positive | 0 | 26 | 0 | 0 | 26/26 (100%) | 26/36 (72%) |
| frustrated | 2 | 0 | 38 | 0 | 38/40 (95%) | 38/38 (100%) |
| uncertain | 2 | 0 | 0 | 32 | 32/34 (94%) | 32/32 (100%) |

Brier score: 0.095 (0 is perfect, 2 the worst).

Frustrated or uncertain acted on when its probability ≥ t:

| t | caught | false alarms |
| --- | --- | --- |
| 0.50 | 70/74 (95%) | 0/170 (0%) |
| 0.70 | 69/74 (93%) | 0/170 (0%) |
| 0.80 | 64/74 (86%) | 0/170 (0%) |
| 0.90 | 62/74 (84%) | 0/170 (0%) |
| 0.95 | 59/74 (80%) | 0/170 (0%) |

Reply language by kind (right / cases): stay 146/146 (100%), explicit 22/22 (100%), indirect 16/16 (100%), written_other 16/16 (100%), mention 22/22 (100%), borrowed 22/22 (100%).

Brier score: 0.005.

Switch when p(other language) ≥ t; requests caught (explicit and indirect) and false alarms (stay, mention, borrowed):

| t | caught | false alarms |
| --- | --- | --- |
| 0.50 | 38/38 (100%) | 0/190 (0%) |
| 0.70 | 38/38 (100%) | 0/190 (0%) |
| 0.80 | 38/38 (100%) | 0/190 (0%) |
| 0.90 | 36/38 (95%) | 0/190 (0%) |
| 0.95 | 34/38 (89%) | 0/190 (0%) |

## Misses (first repetition)

| Case | Text | Expected | regex | production | llm | jev |
| --- | --- | --- | --- | --- | --- | --- |
| es-07 | Sí, el jueves por la tarde si puede ser. | neutral · es (stay) | es | neutral | positive · es | neutral · es |
| es-15 | No, está mal, es el 699 112 334. | neutral · es (stay) | es | frustrated | frustrated · es | neutral · es |
| es-20 | ¿Me puedes pasar con una persona? | neutral · es (stay) | es | neutral | neutral · en | neutral · es |
| es-37 | que no que es el martes | frustrated · es (stay) | es | neutral | frustrated · es | neutral · es |
| es-43 | Creo que sí, pero tendría que mirarlo. | uncertain · es (stay) | es | uncertain | neutral · es | uncertain · es |
| es-48 | Eh... ¿perdona? No te he oído bien. | uncertain · es (stay) | es | uncertain | frustrated · en | uncertain · es |
| es-53 | ¿Me lo puedes decir en inglés? | neutral · en (explicit) | en | uncertain | neutral · en | neutral · en |
| es-56 | Sorry, my Spanish is not very good. | neutral · en (indirect) | es | uncertain | neutral · en | neutral · en |
| es-57 | I don't understand, I only speak English. | uncertain · en (indirect) | es | uncertain | neutral · en | neutral · en |
| es-58 | Perdona, no hablo bien español, soy de Londres. | neutral · en (indirect) | es | uncertain | neutral · en | neutral · en |
| es-59 | Mi español es muy malo, ¿hablas inglés? | neutral · en (indirect) | es | uncertain | neutral · en | neutral · en |
| es-60 | Is there any chance we could do this in English? I'm struggling a bit. | uncertain · en (indirect) | en | uncertain | neutral · en | uncertain · en |
| es-61 | No entiendo bien el español, lo siento. | uncertain · en (indirect) | es | uncertain | uncertain · en | uncertain · en |
| es-62 | Monday to Friday, mornings only. | neutral · en (written_other) | es | neutral | neutral · en | neutral · en |
| es-63 | My name is Tom Baker. | neutral · en (written_other) | es | neutral | neutral · en | neutral · en |
| es-64 | I can start next Monday. | neutral · en (written_other) | es | neutral | neutral · en | neutral · en |
| es-65 | How much is the hourly pay? | neutral · en (written_other) | es | neutral | neutral · en | neutral · en |
| es-66 | This is taking forever. | frustrated · en (written_other) | es | frustrated | frustrated · es | frustrated · en |
| es-67 | ¿Hace falta saber inglés para el puesto? | neutral · es (mention) | es | uncertain | uncertain · en | neutral · es |
| es-71 | Mi madre es inglesa, pero yo prefiero hablar en español. | neutral · es (mention) | es | neutral | neutral · en | neutral · es |
| es-73 | No, en inglés no, sigue en español. | neutral · es (mention) | es | neutral | neutral · en | neutral · es |
| es-74 | Ok, perfecto. | neutral · es (borrowed) | es | positive | positive · es | positive · es |
| es-75 | Vale, thanks. | neutral · es (borrowed) | es | positive | positive · es | positive · es |
| es-76 | Sí, cool, me vale el jueves. | neutral · es (borrowed) | es | positive | positive · es | positive · es |
| es-77 | Trabajé de barista en un coffee shop en Londres. | neutral · es (borrowed) | es | neutral | positive · es | neutral · es |
| es-78 | Sorry, me he equivocado, es el 612 334 556. | neutral · es (borrowed) | es | neutral | neutral · en | neutral · es |
| en-03 | Yes, I have an EU passport. | neutral · en (stay) | en | neutral | positive · en | neutral · en |
| en-09 | Can I talk to a real person? | neutral · en (stay) | en | neutral | frustrated · en | neutral · en |
| en-29 | ¡Que no te entiendo! Háblame en español. | frustrated · es (explicit) | es | frustrated | uncertain · es | frustrated · es |
| en-31 | Perdona, es que no entiendo mucho inglés. | uncertain · es (indirect) | en | uncertain | neutral · es | uncertain · es |
| en-32 | Los fines de semana, sobre todo los sábados. | neutral · es (written_other) | en | neutral | neutral · es | neutral · es |
| en-33 | Me llamo Ana García. | neutral · es (written_other) | en | neutral | neutral · es | neutral · es |
| en-34 | ¿Cuánto se paga la hora? | neutral · es (written_other) | en | neutral | neutral · es | neutral · es |
| en-35 | Do I need to speak Spanish for this job? | neutral · en (mention) | en | uncertain | uncertain · es | neutral · en |
| en-36 | I studied Spanish in Valencia for a year. | neutral · en (mention) | en | neutral | neutral · es | neutral · en |
| en-37 | My Spanish is okay but English is easier for me. | neutral · en (mention) | en | neutral | neutral · es | neutral · en |
| en-39 | Vale, sounds good. | neutral · en (borrowed) | en | positive | positive · en | positive · en |
| en-40 | Sí, Thursday works. | neutral · en (borrowed) | en | neutral | neutral · es | neutral · en |
| en-41 | Gracias, that's everything. | neutral · en (borrowed) | en | positive | positive · en | positive · en |
