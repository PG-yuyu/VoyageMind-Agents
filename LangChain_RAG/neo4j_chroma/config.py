"""Configuration helpers for the graph database module."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _getenv(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def _getint(name: str, default: int) -> int:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return int(value)


@dataclass(slots=True)
class GraphDBConfig:
    """Runtime settings for Neo4j, Chroma, and embeddings."""

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "password"
    neo4j_database: str = "neo4j"
    chroma_persist_directory: str = ".chroma"
    chroma_parent_collection: str = "parent_documents"
    chroma_child_collection: str = "child_documents"
    embedding_provider: str = "chroma_default"
    embedding_dimension: int = 384
    top_k: int = 5

    @classmethod
    def from_env(cls) -> "GraphDBConfig":
        """Build config from environment variables."""
        _load_dotenv()

        persist_dir = os.getenv("CHROMA_PERSIST_DIRECTORY") or os.getenv(
            "CHROMA_PERSIST_DIR",
            ".chroma",
        )
        return cls(
            neo4j_uri=_getenv("NEO4J_URI", "bolt://localhost:7687"),
            neo4j_username=_getenv("NEO4J_USERNAME", "neo4j"),
            neo4j_password=_getenv("NEO4J_PASSWORD", "password"),
            neo4j_database=_getenv("NEO4J_DATABASE", "neo4j"),
            chroma_persist_directory=persist_dir,
            chroma_parent_collection=_getenv(
                "CHROMA_PARENT_COLLECTION",
                "parent_documents",
            ),
            chroma_child_collection=_getenv(
                "CHROMA_CHILD_COLLECTION",
                "child_documents",
            ),
            embedding_provider=_getenv("EMBEDDING_PROVIDER", "chroma_default"),
            embedding_dimension=_getint("EMBEDDING_DIMENSION", 384),
            top_k=_getint("RAG_TOP_K", 5),
        )
