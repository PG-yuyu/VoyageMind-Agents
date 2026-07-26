"""Clear Neo4j document/chunk data for the neo4j_chroma module."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from neo4j_chroma.database_repository import DatabaseRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clear Neo4j neo4j_chroma data.")
    parser.add_argument(
        "--document-id",
        help="Only clear one document and its ParentChunk/ChildChunk nodes.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repository = DatabaseRepository.from_env()
    if not repository.health_check():
        print("Neo4j health check failed. Please verify NEO4J_* environment variables.")
        return 1

    if args.document_id:
        deleted = repository.delete_document(args.document_id)
        print(f"Neo4j document {args.document_id} cleared: {deleted}")
    else:
        deleted_count = repository.clear_all_documents()
        print(f"Neo4j document/chunk nodes cleared: {deleted_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
