import unittest

from neo4j_chroma.database_repository import ChildChunkNode, ParentChunkNode
from neo4j_chroma.hybrid_retriever import HybridRetriever
from neo4j_chroma.vector_store import VectorDocument, VectorSearchResult


class FakeVectorStore:
    def __init__(self):
        self.document_ids = None
        self.top_k = None
        self.parent_ids = None

    def health_check(self):
        return True

    def query_child_chunks(self, query, top_k=5, document_ids=None):
        self.top_k = top_k
        self.document_ids = document_ids
        return [
            VectorSearchResult(
                vector_id="cv-1",
                content="child hit",
                metadata={
                    "document_id": "doc-1",
                    "filename": "guide.txt",
                    "parent_id": "p-1",
                    "child_id": "c-1",
                    "chunk_index": 7,
                    "page_number": 3,
                },
                distance=0.25,
                score=0.8,
            ),
        ]

    def get_parent_documents_by_ids(self, parent_ids):
        self.parent_ids = list(parent_ids)
        return [
            VectorDocument(
                vector_id="pv-1",
                content="parent context",
                metadata={
                    "document_id": "doc-1",
                    "filename": "guide.txt",
                    "parent_id": "p-1",
                    "chunk_index": 1,
                },
            ),
        ]


class FakeRepository:
    def __init__(self):
        self.loaded_parent_ids = None
        self.loaded_child_ids = None

    def health_check(self):
        return True

    def get_parent_chunks_by_ids(self, parent_ids):
        self.loaded_parent_ids = list(parent_ids)
        return [
            ParentChunkNode(
                parent_id="p-1",
                document_id="doc-1",
                content="neo4j parent context",
                chunk_index=1,
                vector_id="pv-1",
                metadata={"filename": "guide.txt"},
            ),
        ]

    def get_child_chunks_by_ids(self, child_ids):
        self.loaded_child_ids = list(child_ids)
        return [
            ChildChunkNode(
                child_id="c-1",
                document_id="doc-1",
                parent_id="p-1",
                content="neo4j child source",
                chunk_index=7,
                vector_id="cv-1",
                metadata={"page_number": 5},
            ),
        ]


class HybridRetrieverTest(unittest.TestCase):
    def test_retrieve_backtracks_parent_context_and_assembles_sources(self):
        vector_store = FakeVectorStore()
        repository = FakeRepository()
        retriever = HybridRetriever(vector_store, repository)

        result = retriever.retrieve("graph storage", document_ids=["doc-1"], top_k=3)

        self.assertEqual(vector_store.document_ids, ["doc-1"])
        # Pool size = max(top_k * 5, 30) = max(15, 30) = 30
        self.assertEqual(vector_store.top_k, 30)
        self.assertEqual(vector_store.parent_ids, ["p-1"])
        self.assertEqual(repository.loaded_parent_ids, ["p-1"])
        self.assertEqual(repository.loaded_child_ids, ["c-1"])
        self.assertEqual(result.context, "parent context")
        self.assertEqual(len(result.sources), 1)
        source = result.sources[0]
        self.assertEqual(source.document_id, "doc-1")
        self.assertEqual(source.filename, "guide.txt")
        self.assertEqual(source.parent_id, "p-1")
        self.assertEqual(source.child_id, "c-1")
        self.assertEqual(source.page_number, 3)
        self.assertEqual(source.chunk_index, 7)
        self.assertEqual(source.content, "parent context")
        self.assertEqual(source.child_content, "neo4j child source")

    def test_health_check_requires_vector_and_repository(self):
        retriever = HybridRetriever(FakeVectorStore(), FakeRepository())

        self.assertTrue(retriever.health_check())

    def test_retrieve_without_repository_still_returns_vector_sources(self):
        retriever = HybridRetriever(FakeVectorStore())

        result = retriever.retrieve("graph storage")

        self.assertEqual(result.context, "parent context")
        self.assertEqual(result.sources[0].filename, "guide.txt")
        self.assertEqual(result.sources[0].score, 0.8)


if __name__ == "__main__":
    unittest.main()
