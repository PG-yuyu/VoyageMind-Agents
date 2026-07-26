"""Embedding implementations \u2014 Chroma default (ONNX) with hash fallback.

Priority:
1. ``chroma_default`` \u2014 Chroma's built-in ``all-MiniLM-L6-v2`` via ONNX Runtime.
   No extra dependencies beyond chromadb itself.  Good multilingual support.
2. ``hash`` \u2014 Deterministic hash embedding (bag-of-words).  Used only when
   no real embedding model is available (testing / offline).

To re-embed existing documents after switching provider, run:
    python scripts/clear_chroma.py
    python scripts/clear_neo4j.py
Then re-upload your documents.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import Iterable

logger = logging.getLogger("neo4j_chroma.embedding")


# \u2500\u2500 Chroma default embedding function (ONNX-based, multilingual) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500


def _create_chroma_ef():
    """Lazy-import and return a Chroma ``DefaultEmbeddingFunction``.

    The underlying model (``all-MiniLM-L6-v2``) runs on ONNX Runtime and
    supports 50+ languages including Chinese.  Model weights are downloaded
    on first use (~80 MB).
    """
    try:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        ef = DefaultEmbeddingFunction()
        logger.info("Using Chroma DefaultEmbeddingFunction (ONNX, all-MiniLM-L6-v2)")
        return ef
    except Exception as exc:
        logger.warning(
            "Chroma DefaultEmbeddingFunction unavailable (%s), falling back to hash.",
            exc,
        )
        return None


# \u2500\u2500 Hash embedding (legacy fallback) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500


class HashEmbeddingFunction:
    """Stable hash embedding used when no online model is configured."""

    def __init__(self, dimension: int = 384):
        if dimension <= 0:
            raise ValueError("embedding dimension must be positive")
        self.dimension = dimension

    def __call__(self, input: Iterable[str]) -> list[list[float]]:
        """Chroma-compatible callable interface."""
        return self.embed_documents(list(input))

    def name(self) -> str:
        """Chroma 1.x expects embedding functions to expose a stable name."""
        return "hash"

    def embed_query(self, text: str) -> list[float]:
        return self.embed(text)

    def embed_documents(self, texts: Iterable[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]

    def embed(self, text: str) -> list[float]:
        tokens = self._tokenize(text)
        vector = [0.0] * self.dimension
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
            bucket = int.from_bytes(digest[:8], "big") % self.dimension
            sign = 1.0 if digest[8] % 2 == 0 else -1.0
            weight = 1.0 + digest[9] / 255.0
            vector[bucket] += sign * weight

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        normalized = (text or "").lower()
        tokens = re.findall(r"[\w\u4e00-\u9fff]+", normalized)
        return tokens or ["__empty__"]


# \u2500\u2500 Factory \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500


def create_embedding_function(
    provider: str = "chroma_default",
    dimension: int = 384,
) -> HashEmbeddingFunction | None:
    """Create an embedding function by provider name.

    Returns ``None`` when the provider wants Chroma to auto-compute embeddings
    (i.e. the ``DefaultEmbeddingFunction`` passed at collection creation time).
    Callers must handle ``None`` by **not** passing the ``embeddings`` kwarg
    to Chroma's ``upsert`` / ``query`` methods.
    """
    provider_name = (provider or "chroma_default").lower().strip()

    if provider_name == "chroma_default":
        ef = _create_chroma_ef()
        # Return the callable for unit tests that call embed() directly,
        # but signal "None" to VectorStore so it skips manual embeddings.
        return ef  # may be None (fallback)

    if provider_name == "hash":
        logger.info("Using HashEmbeddingFunction (dim=%d)", dimension)
        return HashEmbeddingFunction(dimension=dimension)

    raise ValueError(
        f"unsupported embedding provider '{provider}'; "
        f"expected 'chroma_default' or 'hash'",
    )
