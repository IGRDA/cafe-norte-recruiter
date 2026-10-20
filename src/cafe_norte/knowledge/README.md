# `knowledge`: retrieval that cannot leak between stores

Twelve Spanish Markdown documents in `kb/` with front matter (`doc_id`, `version`, `config_ids`,
`language`). `scripts/build_index.py` chunks them by heading, embeds chunks with a local
multilingual model and writes a versioned artifact (`kb/index/<kb_version>/`) that the image
loads at startup.

| File | Contents |
| --- | --- |
| `contracts.py` | `Document`, `Chunk`, `RetrievalQuery`, `RetrievedChunk`, `IndexManifest`, ports `Retriever` and `Embedder` |
| `loader.py` | Parse front matter, hash content, chunk by heading under the token limit | 
| `index.py` | Build and load the artifact; BM25 and dense vectors side by side |
| `hybrid.py` | `HybridRetriever`: filter by `config_id` and `kb_version` **before** ranking, BM25 + cosine fused by reciprocal rank, top three |
| `fake.py` | `FakeRetriever`: canned results keyed by question, for tests and CI evals |

Retrieved text is reference material for the model, never instructions. A top-ranked chunk is
not proof an answer exists: the runtime's prompt tells Ana to abstain when the snippets do not
answer, and `evals/cases/retrieval/` checks that she does.
