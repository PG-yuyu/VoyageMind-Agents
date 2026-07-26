"""Chroma client wrapper with parent and child collections."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from neo4j_chroma.config import GraphDBConfig
from neo4j_chroma.embedding import create_embedding_function


ClientFactory = Callable[[str], Any]


@dataclass(slots=True)
class ChromaClient:
    """Lazy Chroma client that owns the parent and child collections.

    When ``embedding_function`` is ``None``, collections are created **without**
    an explicit embedding function, which means Chroma uses its built-in
    ``DefaultEmbeddingFunction`` (ONNX-based ``all-MiniLM-L6-v2``).  In that
    case callers must **not** pass the ``embeddings`` kwarg to ``upsert`` /
    ``query`` — Chroma computes embeddings from ``documents`` automatically.
    """

    persist_directory: str
    parent_collection_name: str = "parent_documents"
    child_collection_name: str = "child_documents"
    embedding_function: Any | None = None  # callable or None (use Chroma default)
    client: Any | None = None
    client_factory: ClientFactory | None = None

    # ── Whether to skip manual embeddings ────────────────────────────────

    _skip_manual_embed: bool = field(default=False, init=False)

    @classmethod
    def from_config(cls, config: GraphDBConfig) -> "ChromaClient":
        provider = (config.embedding_provider or "chroma_default").lower().strip()

        if provider == "chroma_default":
            # Try Chroma's built-in DefaultEmbeddingFunction (ONNX).
            # If it works → skip manual embeddings; Chroma auto-computes.
            try:
                ef = create_embedding_function(provider, config.embedding_dimension)
                skip_manual = ef is not None  # True when ONNX loaded
            except Exception:
                ef = None
                skip_manual = False
        else:
            # "hash" or explicit embedding function
            ef = create_embedding_function(provider, config.embedding_dimension)
            skip_manual = False

        # When chroma_default ONNX loader failed, fall back to hash
        if ef is None and not skip_manual:
            ef = create_embedding_function("hash", config.embedding_dimension)

        inst = cls(
            persist_directory=config.chroma_persist_directory,
            parent_collection_name=config.chroma_parent_collection,
            child_collection_name=config.chroma_child_collection,
            embedding_function=ef if not skip_manual else None,
        )
        inst._skip_manual_embed = skip_manual
        return inst

    @classmethod
    def from_env(cls) -> "ChromaClient":
        return cls.from_config(GraphDBConfig.from_env())

    def connect(self) -> Any:
        if self.client is None:
            if self.client_factory is None:
                try:
                    import chromadb
                except ImportError as exc:
                    raise RuntimeError(
                        "chromadb package is required for a real Chroma connection",
                    ) from exc
                self.client_factory = chromadb.PersistentClient
            self.client = self.client_factory(path=self.persist_directory)
        return self.client

    def get_collection(self, name: str) -> Any:
        """Get or create a Chroma collection, passing the embedding function.

        When ``embedding_function`` is ``None``, Chroma falls back to its
        built-in ONNX-based ``DefaultEmbeddingFunction``.
        """
        kwargs = {"name": name}
        if self.embedding_function is not None:
            kwargs["embedding_function"] = self.embedding_function
        return self.connect().get_or_create_collection(**kwargs)

    @property
    def parent_collection(self) -> Any:
        return self.get_collection(self.parent_collection_name)

    @property
    def child_collection(self) -> Any:
        return self.get_collection(self.child_collection_name)

    def health_check(self) -> bool:
        try:
            self.parent_collection.count()
            self.child_collection.count()
            return True
        except Exception:
            return False

    def close(self) -> None:
        self.client = None
