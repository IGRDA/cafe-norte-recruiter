# Signals: 2026-10-22T11:30:23+00:00

83 synthetic cases × 2 repetitions; production classifier prompt ana_v17. A failed call counts as neutral and the session language, as the runtime would. Latency is the call alone, off the turn's critical path in every design here.

| System | Model | Sentiment acc. | Macro-F1 | Frustrated/uncertain P | R | Language acc. | False switches | Missed requests | Stable | p50 | p95 | € / 1000 turns | Errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| regex | explicit_controls | – | – | – | – | 138/166 (83%) | 0/118 (0%) | 16/36 (44%) | 83/83 (100%) | 0 ms | 0 ms | 0 | 0/166 (0%) |
| production | gpt-4o-mini | 140/166 (84%) | 0.83 | 44/55 (80%) | 44/52 (85%) | – | – | – | 79/83 (95%) | 796 ms | 1117 ms | 0.0462 | 0/166 (0%) |
| llm | gpt-4o-mini | 134/166 (81%) | 0.80 | 40/45 (89%) | 40/52 (77%) | 159/166 (96%) | 7/118 (6%) | 0/36 (0%) | 76/83 (92%) | 774 ms | 1075 ms | 0.0498 | 0/166 (0%) |
| jev | typesafe/jev-1.14 | 153/166 (92%) | 0.90 | 46/47 (98%) | 46/52 (88%) | 166/166 (100%) | 0/118 (0%) | 0/36 (0%) | 82/83 (99%) | 279 ms | 461 ms | 0.0229 | 0/166 (0%) |

## regex

Reply language by kind (right / cases): stay 88/88 (100%), explicit 16/16 (100%), indirect 4/20 (20%), written_other 0/12 (0%), mention 16/16 (100%), borrowed 14/14 (100%).

## production

Sentiment, expected (rows) × predicted (columns):

| | neutral | positive | frustrated | uncertain | recall | precision |
| --- | --- | --- | --- | --- | --- | --- |
| neutral | 78 | 5 | 0 | 11 | 78/94 (83%) | 78/86 (91%) |
| positive | 2 | 18 | 0 | 0 | 18/20 (90%) | 18/25 (72%) |
| frustrated | 5 | 2 | 17 | 0 | 17/24 (71%) | 17/17 (100%) |
| uncertain | 1 | 0 | 0 | 27 | 27/28 (96%) | 27/38 (71%) |


## llm

Sentiment, expected (rows) × predicted (columns):

| | neutral | positive | frustrated | uncertain | recall | precision |
| --- | --- | --- | --- | --- | --- | --- |
| neutral | 76 | 13 | 0 | 5 | 76/94 (81%) | 76/90 (84%) |
| positive | 2 | 18 | 0 | 0 | 18/20 (90%) | 18/31 (58%) |
| frustrated | 6 | 0 | 18 | 0 | 18/24 (75%) | 18/18 (100%) |
| uncertain | 6 | 0 | 0 | 22 | 22/28 (79%) | 22/27 (81%) |

Reply language by kind (right / cases): stay 88/88 (100%), explicit 16/16 (100%), indirect 20/20 (100%), written_other 12/12 (100%), mention 11/16 (69%), borrowed 12/14 (86%).

## jev

Sentiment, expected (rows) × predicted (columns):

| | neutral | positive | frustrated | uncertain | recall | precision |
| --- | --- | --- | --- | --- | --- | --- |
| neutral | 87 | 6 | 0 | 1 | 87/94 (93%) | 87/91 (96%) |
| positive | 0 | 20 | 0 | 0 | 20/20 (100%) | 20/28 (71%) |
| frustrated | 4 | 2 | 18 | 0 | 18/24 (75%) | 18/18 (100%) |
| uncertain | 0 | 0 | 0 | 28 | 28/28 (100%) | 28/29 (97%) |

Brier score: 0.112 (0 is perfect, 2 the worst).

Frustrated or uncertain acted on when its probability ≥ t:

| t | caught | false alarms |
| --- | --- | --- |
| 0.50 | 46/52 (88%) | 1/114 (1%) |
| 0.70 | 42/52 (81%) | 0/114 (0%) |
| 0.80 | 42/52 (81%) | 0/114 (0%) |
| 0.90 | 42/52 (81%) | 0/114 (0%) |
| 0.95 | 42/52 (81%) | 0/114 (0%) |

Reply language by kind (right / cases): stay 88/88 (100%), explicit 16/16 (100%), indirect 20/20 (100%), written_other 12/12 (100%), mention 16/16 (100%), borrowed 14/14 (100%).

Brier score: 0.003.

Switch when p(other language) ≥ t; requests caught (explicit and indirect) and false alarms (stay, mention, borrowed):

| t | caught | false alarms |
| --- | --- | --- |
| 0.50 | 36/36 (100%) | 0/118 (0%) |
| 0.70 | 36/36 (100%) | 0/118 (0%) |
| 0.80 | 34/36 (94%) | 0/118 (0%) |
| 0.90 | 34/36 (94%) | 0/118 (0%) |
| 0.95 | 34/36 (94%) | 0/118 (0%) |

## Misses (first repetition)

| Case | Text | Expected | regex | production | llm | jev |
| --- | --- | --- | --- | --- | --- | --- |
| h-es-005 | Prefiero turno de mañana. | neutral · es (stay) | es | neutral | positive · es | neutral · es |
| h-es-006 | puedo empezar el lunes que viene | neutral · es (stay) | es | positive | neutral · es | neutral · es |
| h-es-009 | Claro, me llamo Marta García. | positive · es (stay) | es | neutral | neutral · es | positive · es |
| h-es-015 | pues claro que sí lo tendría si no no estaría aquí | frustrated · es (stay) | es | positive | frustrated · es | frustrated · es |
| h-es-027 | Mi español es muy básico. | neutral · en (indirect) | es | uncertain | neutral · en | neutral · en |
| h-es-028 | Sorry, I don't speak much Spanish. | neutral · en (indirect) | es | uncertain | neutral · en | neutral · en |
| h-es-029 | No entiendo mucho español, solo inglés. | neutral · en (indirect) | es | uncertain | neutral · en | neutral · en |
| h-es-030 | Lo siento, no entiendo mucho español. | uncertain · en (indirect) | es | uncertain | neutral · en | uncertain · en |
| h-es-031 | Um... sorry, my Spanish is not very good. | uncertain · en (indirect) | es | uncertain | uncertain · en | uncertain · en |
| h-es-032 | My name is David Miller. | neutral · en (written_other) | es | neutral | neutral · en | neutral · en |
| h-es-033 | It's 645892311. | neutral · en (written_other) | es | neutral | neutral · en | neutral · en |
| h-es-034 | Yes, I have a work permit. | neutral · en (written_other) | es | neutral | neutral · en | neutral · en |
| h-es-037 | ¿Hace falta saber inglés para el puesto? | neutral · es (mention) | es | uncertain | uncertain · en | neutral · es |
| h-es-040 | Sí, tengo permiso de trabajo, thanks. | neutral · es (borrowed) | es | positive | positive · es | positive · es |
| h-en-047 | I worked as a barista for one year. | neutral · en (stay) | en | neutral | positive · en | neutral · en |
| h-en-049 | i can start next monday | neutral · en (stay) | en | neutral | positive · en | neutral · en |
| h-en-050 | i can do afternoons | neutral · en (stay) | en | neutral | positive · en | neutral · en |
| h-en-057 | As many as possible, like I said before. | frustrated · en (stay) | en | neutral | neutral · en | positive · en |
| h-en-059 | Yeah, like I said, three years. | frustrated · en (stay) | en | neutral | neutral · en | neutral · en |
| h-en-060 | Um, I think maybe weekends? But I’m not sure yet. | uncertain · en (stay) | en | neutral | uncertain · en | uncertain · en |
| h-en-067 | Can we just do this in Spanish, please? | frustrated · es (explicit) | es | neutral | neutral · es | neutral · es |
| h-en-069 | Sorry my English not good I speak Spanish. | neutral · es (indirect) | es | uncertain | neutral · es | neutral · es |
| h-en-070 | mi inglés es malo solo hablo español | neutral · es (indirect) | en | neutral | neutral · es | neutral · es |
| h-en-071 | i dont understand english good | neutral · es (indirect) | en | uncertain | uncertain · es | neutral · es |
| h-en-072 | uh sorry my english no good i not understand good | uncertain · es (indirect) | en | uncertain | uncertain · es | uncertain · es |
| h-en-073 | mm lo siento, mi inglés es malo, puedo responder en español? | uncertain · es (indirect) | es | uncertain | neutral · es | uncertain · es |
| h-en-074 | Me llamo Javier Morales. | neutral · es (written_other) | en | neutral | neutral · es | neutral · es |
| h-en-075 | Mi número es 654321987. | neutral · es (written_other) | en | neutral | neutral · es | neutral · es |
| h-en-076 | Sí, tengo permiso de trabajo. | neutral · es (written_other) | en | neutral | neutral · es | neutral · es |
| h-en-079 | Is Spanish required for this position? | neutral · en (mention) | en | neutral | neutral · es | neutral · en |
| h-en-080 | I prefer English, thanks. | neutral · en (mention) | en | neutral | positive · en | positive · en |
| h-en-081 | Carlos Gomez, gracias. | neutral · en (borrowed) | en | positive | positive · en | positive · en |
| h-en-083 | Next semana, vale. | neutral · en (borrowed) | en | neutral | neutral · es | neutral · en |
