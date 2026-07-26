"""Clear Chroma parent_documents and child_documents collections."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from neo4j_chroma.chroma_client import ChromaClient
from neo4j_chroma.vector_store import VectorStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clear Chroma neo4j_chroma collections.")
    parser.add_argument(
        "--document-id",
        help="Only delete vectors whose metadata.document_id matches this value.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    chroma_client = ChromaClient.from_env()
    if args.document_id:
        vector_store = VectorStore(chroma_client)
        vector_store.delete_document(args.document_id)
        print(f"Chroma vectors for document {args.document_id} cleared.")
        return 0

    backend = chroma_client.connect()
    for collection_name in (
        chroma_client.parent_collection_name,
        chroma_client.child_collection_name,
    ):
        try:
            backend.delete_collection(name=collection_name)
        except Exception:
            pass
        backend.get_or_create_collection(name=collection_name)
    print("Chroma parent_documents and child_documents collections cleared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
