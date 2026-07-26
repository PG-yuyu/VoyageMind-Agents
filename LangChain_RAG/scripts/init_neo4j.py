"""Initialize Neo4j constraints and indexes for the neo4j_chroma module."""

from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from neo4j_chroma.database_repository import DatabaseRepository


def main() -> int:
    repository = DatabaseRepository.from_env()
    if not repository.health_check():
        print("Neo4j health check failed. Please verify NEO4J_* environment variables.")
        return 1
    repository.initialize_schema()
    print("Neo4j constraints and indexes initialized.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
