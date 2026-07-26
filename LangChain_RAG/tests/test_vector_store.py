import math
import unittest

from neo4j_chroma.chroma_client import ChromaClient
from neo4j_chroma.database_repository import ChildChunkNode, ParentChunkNode
from neo4j_chroma.embedding import HashEmbeddingFunction
from neo4j_chroma.vector_store import VectorStore


class InMemoryCollection:
    def __init__(self, name):
        self.name = name
        self.rows = {}
        self.deleted_where = []

    def count(self):
        return len(self.rows)

    def upsert(self, ids, documents, metadatas, embeddings):
        for index, vector_id in enumerate(ids):
            self.rows[vector_id] = {
                "document": documents[index],
                "metadata": metadatas[index],
                "embedding": embeddings[index],
            }

    def delete(self, where):
        self.deleted_where.append(where)
        for vector_id in list(self.rows):
            if _matches(self.rows[vector_id]["metadata"], where):
                del self.rows[vector_id]

    def get(self, where=None, include=None):
        ids = []
        documents = []
        metadatas = []
        for vector_id, row in self.rows.items():
            if _matches(row["metadata"], where):
                ids.append(vector_id)
                documents.append(row["document"])
                metadatas.append(row["metadata"])
        return {"ids": ids, "documents": documents, "metadatas": metadatas}

    def query(self, query_embeddings, n_results, where=None, include=None):
        query_embedding = query_embeddings[0]
        matches = []
        for vector_id, row in self.rows.items():
            if not _matches(row["metadata"], where):
                continue
            distance = _cosine_distance(query_embedding, row["embedding"])
            matches.append((distance, vector_id, row))
        matches.sort(key=lambda item: item[0])
        limited = matches[:n_results]
        return {
            "ids": [[vector_id for _, vector_id, _ in limited]],
            "documents": [[row["document"] for _, _, row in limited]],
            "metadatas": [[row["metadata"] for _, _, row in limited]],
            "distances": [[distance for distance, _, _ in limited]],
        }


class InMemoryChromaBackend:
    def __init__(self):
        self.collections = {}

    def get_or_create_collection(self, name):
        self.collections.setdefault(name, InMemoryCollection(name))
        return self.collections[name]


class VectorStoreTest(unittest.TestCase):
    def setUp(self):
        backend = InMemoryChromaBackend()
        self.chroma_client = ChromaClient(
            persist_directory="tmp/chroma",
            client=backend,
            embedding_function=HashEmbeddingFunction(dimension=32),
        )
        self.vector_store = VectorStore(self.chroma_client)

    def test_upsert_writes_parent_and_child_collections(self):
        result = self.vector_store.upsert_document(
            document_id="doc-1",
            filename="guide.txt",
            parent_chunks=[
                ParentChunkNode("p-1", "doc-1", "parent text", 0, "pv-1"),
            ],
            child_chunks=[
                ChildChunkNode("c-1", "doc-1", "p-1", "child text", 0, "cv-1"),
            ],
        )

        self.assertEqual(result.parent_vector_ids, ["pv-1"])
        self.assertEqual(result.child_vector_ids, ["cv-1"])
        self.assertEqual(self.chroma_client.parent_collection.count(), 1)
        self.assertEqual(self.chroma_client.child_collection.count(), 1)
        child = self.chroma_client.child_collection.rows["cv-1"]
        self.assertEqual(child["metadata"]["document_id"], "doc-1")
        self.assertEqual(child["metadata"]["parent_id"], "p-1")
        self.assertEqual(child["metadata"]["child_id"], "c-1")
        self.assertEqual(child["metadata"]["filename"], "guide.txt")

    def test_query_child_chunks_supports_document_id_filter(self):
        self.vector_store.upsert_document(
            document_id="doc-1",
            filename="a.txt",
            parent_chunks=[ParentChunkNode("p-1", "doc-1", "Neo4j guide", 0, "pv-1")],
            child_chunks=[ChildChunkNode("c-1", "doc-1", "p-1", "Neo4j graph storage", 0, "cv-1")],
        )
        self.vector_store.upsert_document(
            document_id="doc-2",
            filename="b.txt",
            parent_chunks=[ParentChunkNode("p-2", "doc-2", "Chroma guide", 0, "pv-2")],
            child_chunks=[ChildChunkNode("c-2", "doc-2", "p-2", "Chroma vector search", 0, "cv-2")],
        )

        results = self.vector_store.query_child_chunks(
            "Neo4j",
            top_k=5,
            document_ids=["doc-2"],
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].metadata["document_id"], "doc-2")

    def test_get_parent_documents_by_ids_backtracks_context(self):
        self.vector_store.upsert_document(
            document_id="doc-1",
            filename="guide.txt",
            parent_chunks=[
                ParentChunkNode("p-1", "doc-1", "parent one", 0, "pv-1"),
                ParentChunkNode("p-2", "doc-1", "parent two", 1, "pv-2"),
            ],
            child_chunks=[],
        )

        parents = self.vector_store.get_parent_documents_by_ids(["p-2", "p-1"])

        self.assertEqual([doc.metadata["parent_id"] for doc in parents], ["p-2", "p-1"])
        self.assertEqual(parents[0].content, "parent two")

    def test_upsert_is_idempotent_for_same_document_id(self):
        self.vector_store.upsert_document(
            document_id="doc-1",
            parent_chunks=[ParentChunkNode("p-1", "doc-1", "old parent", 0, "pv-old")],
            child_chunks=[ChildChunkNode("c-1", "doc-1", "p-1", "old child", 0, "cv-old")],
        )
        self.vector_store.upsert_document(
            document_id="doc-1",
            parent_chunks=[ParentChunkNode("p-2", "doc-1", "new parent", 0, "pv-new")],
            child_chunks=[ChildChunkNode("c-2", "doc-1", "p-2", "new child", 0, "cv-new")],
        )

        self.assertEqual(list(self.chroma_client.parent_collection.rows), ["pv-new"])
        self.assertEqual(list(self.chroma_client.child_collection.rows), ["cv-new"])

    def test_delete_document_removes_parent_and_child_vectors(self):
        self.vector_store.upsert_document(
            document_id="doc-1",
            parent_chunks=[ParentChunkNode("p-1", "doc-1", "parent", 0, "pv-1")],
            child_chunks=[ChildChunkNode("c-1", "doc-1", "p-1", "child", 0, "cv-1")],
        )

        self.vector_store.delete_document("doc-1")

        self.assertEqual(self.chroma_client.parent_collection.count(), 0)
        self.assertEqual(self.chroma_client.child_collection.count(), 0)


def _matches(metadata, where):
    if not where:
        return True
    for key, expected in where.items():
        actual = metadata.get(key)
        if isinstance(expected, dict) and "$in" in expected:
            if actual not in expected["$in"]:
                return False
        elif actual != expected:
            return False
    return True


def _cosine_distance(left, right):
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 1.0
    return 1.0 - dot / (left_norm * right_norm)


if __name__ == "__main__":
    unittest.main()
