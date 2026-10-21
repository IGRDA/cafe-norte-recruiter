# `knowledge`: retrieval that cannot leak between stores

Twelve Spanish Markdown documents in `kb/` with front matter (`doc_id`, `version`, `config_ids`,
`language`). `scripts/build_index.py` chunks them by heading, embeds chunks with a local
multilingual model and writes a versioned artifact (`kb/index/<kb_version>/`) that the image
loads at startup.

| File | Contents |
| --- | --- |
| `contracts.py` | `Document`, `Chunk`, `Index`, `IndexManifest`, `RetrievalQuery` (with the optional `doc_ids` filter), `RetrievedChunk`, `Topic` and `TOPIC_DOCS`, ports `Retriever` and `Embedder` |
| `loader.py` | Front matter to `Document` (sha256 content hash); `## ` sections to `Chunk` (`doc_id#slug`, split by paragraph above 90 words) |
| `bm25.py` | Tokenizer (lowercase, accents stripped, short stop list) and a thirty-line BM25 Okapi; no dependency |
| `index.py` | `lexical_index` / `index_from_documents` in memory; `build_index` / `load_index` for the artifact (`manifest.json`, `chunks.json`, `vectors.json`) |
| `hybrid.py` | `HybridRetriever`: allowed chunks (configuration, KB version, `doc_ids`) ranked by BM25 and dense cosine **among themselves**, fused by reciprocal rank (k = 60), top three; BM25 only without an embedder |
| `embedder.py` | `FastEmbedEmbedder`: local multilingual model, lazy load, `to_thread`, two concurrent embeddings, `warm_up()`; the only file that imports the `knowledge` extra |
| `fake.py` | `FakeRetriever` (canned results keyed by query text) and `FakeEmbedder` (hashed bag of tokens: deterministic, shares no numbers with reality) |

Two modes from the composition root: `CAFE_NORTE_RETRIEVER=lexical` builds the BM25 index
from `kb/` at startup (no extra, no artifact, the `make run` default); `hybrid` loads the
artifact and embeds queries with FastEmbed, warmed up before the first request (the image
default). `make evals-retrieval` runs the 24 fixture questions through either and commits the
numbers under `evals/results/retrieval/`.

Retrieved text is reference material for the model, never instructions. A top-ranked chunk is
not proof an answer exists: the runtime's prompt tells Ana to abstain when the snippets do not
answer, and `evals/cases/retrieval/` checks that she does.
