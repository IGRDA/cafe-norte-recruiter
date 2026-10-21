# Knowledge base

Twelve short Spanish Markdown documents with bilingual titles and keywords. Front matter:

```yaml
doc_id: offer_chamberi
version: "1"
config_ids: [chamberi_barista_v1]     # shared documents list both ids
language: es
title: Oferta y retribución, Chamberí / Chamberí offer and pay
keywords: [salario, salary, horas, hours, contrato, contract]
```

| doc_id | Scope | Content |
| --- | --- | --- |
| `company` | both | Company and demo description |
| `barista_role` | both | Responsibilities |
| `offer_chamberi` | chamberi | Offer and compensation |
| `offer_arganzuela` | arganzuela | Offer and compensation |
| `store_chamberi` | chamberi | Shifts and store details |
| `store_arganzuela` | arganzuela | Shifts and store details |
| `training` | both | Training and induction |
| `uniform` | both | Uniform and equipment |
| `benefits` | both | Benefits |
| `interview_process` | both | Interview process and preparation |
| `faq` | both | Frequent candidate questions |
| `unknown_policy` | both | Unknown questions and human follow-up |

`scripts/build_index.py` produces `kb/index/<kb_version>/` (git-ignored, built into the image).
Every body is fictional. Pay, hours and shifts in the offer and store documents must match
`config/*.yaml` (`tests/test_kb.py` checks it): the configuration is the canonical source.
Sections are `## ` headings; each becomes one chunk `doc_id#slug`, at most 90 words.
