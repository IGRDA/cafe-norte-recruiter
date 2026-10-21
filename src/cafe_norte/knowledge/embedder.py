"""FastEmbed adapter: a local multilingual model, loaded once, run off the event loop with
bounded concurrency. Needs the ``knowledge`` extra; nothing else in the package imports it."""

import asyncio
from collections.abc import Sequence
from typing import Any

from cafe_norte.knowledge.contracts import Vector

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CONCURRENCY = 2


class FastEmbedEmbedder:
    def __init__(self, model_name: str = DEFAULT_MODEL, *, cache_dir: str | None = None) -> None:
        self._name = model_name
        self._cache_dir = cache_dir
        self._model: Any = None
        self._lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(CONCURRENCY)

    @property
    def name(self) -> str:
        return self._name

    @property
    def revision(self) -> str:
        """FastEmbed pins one ONNX export per model name; its package version is the revision."""
        from importlib.metadata import version

        return f"fastembed-{version('fastembed')}"

    async def warm_up(self) -> None:
        """Load the model and embed one word so the first candidate question pays nothing."""
        await self.embed(["hola"])

    async def embed(self, texts: Sequence[str]) -> tuple[Vector, ...]:
        model = await self._loaded()
        async with self._slots:
            vectors = await asyncio.to_thread(lambda: list(model.embed(list(texts))))
        return tuple(tuple(float(x) for x in v) for v in vectors)

    async def _loaded(self) -> Any:
        async with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._model = await asyncio.to_thread(
                    TextEmbedding, model_name=self._name, cache_dir=self._cache_dir
                )
        return self._model
