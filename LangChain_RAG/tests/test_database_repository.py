import unittest

from neo4j_chroma import cypher_queries as queries
from neo4j_chroma.database_repository import (
    ChildChunkNode,
    DatabaseRepository,
    DocumentNode,
    ParentChunkNode,
)


class FakeNeo4jClient:
    def __init__(self):
        self.calls = []

    def health_check(self):
        return True

    def execute(self, query, parameters=None):
        params = parameters or {}
        self.calls.append((query, params))
        if query == queries.LIST_DOCUMENTS:
            return [
                {
                    "document_id": "doc-1",
                    "filename": "guide.txt",
                    "file_path": "/tmp/guide.txt",
                    "content": "full text",
                    "chunk_count": 2,
                    "created_at": "2026-07-20T00:00:00+00:00",
                    "is_active": True,
                },
            ]
        if query == queries.GET_PARENT_CHUNKS_BY_IDS:
            return [
                {
                    "parent_id": "p-1",
                    "document_id": "doc-1",
                    "content": "parent text",
                    "chunk_index": 0,
                    "vector_id": "pv-1",
                    "metadata": '{"page_number": 3}',
                },
            ]
        if query == queries.DELETE_DOCUMENT:
            return [{"deleted_count": 1}]
        if query == queries.CLEAR_ALL_DOCUMENTS:
            return [{"deleted_count": 3}]
        return []


class DatabaseRepositoryTest(unittest.TestCase):
    def test_health_check_delegates_to_client(self):
        repository = DatabaseRepository(FakeNeo4jClient())

        self.assertTrue(repository.health_check())

    def test_upsert_document_writes_document_chunks_and_next_links(self):
        fake_client = FakeNeo4jClient()
        repository = DatabaseRepository(fake_client)
        document = DocumentNode(
            document_id="doc-1",
            filename="guide.txt",
            content="full text",
            created_at="2026-07-20T00:00:00+00:00",
        )
        parents = [
            ParentChunkNode("p-1", "doc-1", "parent 1", 0, "pv-1"),
            ParentChunkNode("p-2", "doc-1", "parent 2", 1, "pv-2"),
        ]
        children = [
            ChildChunkNode("c-1", "doc-1", "p-1", "child 1", 0, "cv-1"),
            ChildChunkNode("c-2", "doc-1", "p-2", "child 2", 1, "cv-2"),
        ]

        saved = repository.upsert_document(document, parents, children)
        executed_queries = [query for query, _ in fake_client.calls]

        self.assertEqual(saved.chunk_count, 2)
        self.assertEqual(executed_queries[0], queries.DELETE_DOCUMENT)
        self.assertIn(queries.UPSERT_DOCUMENT, executed_queries)
        self.assertEqual(executed_queries.count(queries.UPSERT_PARENT_CHUNK), 2)
        self.assertEqual(executed_queries.count(queries.UPSERT_CHILD_CHUNK), 2)
        self.assertIn(queries.CREATE_PARENT_NEXT_TO, executed_queries)
        self.assertIn(queries.CREATE_CHILD_NEXT_TO, executed_queries)

    def test_list_documents_maps_rows_to_document_nodes(self):
        repository = DatabaseRepository(FakeNeo4jClient())

        documents = repository.list_documents()

        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].document_id, "doc-1")
        self.assertEqual(documents[0].filename, "guide.txt")
        self.assertEqual(documents[0].chunk_count, 2)

    def test_delete_document_returns_true_when_neo4j_deletes_a_row(self):
        repository = DatabaseRepository(FakeNeo4jClient())

        self.assertTrue(repository.delete_document("doc-1"))

    def test_get_parent_chunks_by_ids_parses_metadata(self):
        repository = DatabaseRepository(FakeNeo4jClient())

        chunks = repository.get_parent_chunks_by_ids(["p-1", "p-1"])

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].metadata["page_number"], 3)

    def test_clear_all_documents_returns_deleted_count(self):
        repository = DatabaseRepository(FakeNeo4jClient())

        self.assertEqual(repository.clear_all_documents(), 3)


if __name__ == "__main__":
    unittest.main()
