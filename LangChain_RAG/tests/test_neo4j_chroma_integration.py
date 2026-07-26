import os
import unittest
import uuid


@unittest.skipUnless(
    os.getenv("NEO4J_CHROMA_RUN_INTEGRATION") == "1",
    "set NEO4J_CHROMA_RUN_INTEGRATION=1 and configure Neo4j/Chroma to run",
)
class Neo4jChromaIntegrationTest(unittest.TestCase):
    def test_real_clients_health_check(self):
        from neo4j_chroma.database_repository import DatabaseRepository
        from neo4j_chroma.vector_store import VectorStore

        repository = DatabaseRepository.from_env()
        vector_store = VectorStore.from_env()
        try:
            self.assertIsInstance(repository.health_check(), bool)
            self.assertIsInstance(vector_store.health_check(), bool)
        finally:
            repository.close()
            vector_store.close()

    def test_real_write_retrieve_delete_smoke(self):
        from neo4j_chroma.database_repository import (
            ChildChunkNode,
            DatabaseRepository,
            DocumentNode,
            ParentChunkNode,
        )
        from neo4j_chroma.hybrid_retriever import HybridRetriever
        from neo4j_chroma.vector_store import VectorStore

        suffix = uuid.uuid4().hex
        document_id = f"smoke-doc-{suffix}"
        parent_id = f"smoke-parent-{suffix}"
        child_id = f"smoke-child-{suffix}"
        parent_vector_id = f"smoke-parent-vector-{suffix}"
        child_vector_id = f"smoke-child-vector-{suffix}"
        filename = "neo4j_chroma_smoke.txt"
        document = DocumentNode(
            document_id=document_id,
            filename=filename,
            file_path="",
            content="Neo4j Aura stores document chunk topology. Chroma stores vectors.",
            chunk_count=1,
            created_at="2026-07-20T00:00:00+00:00",
        )
        parent = ParentChunkNode(
            parent_id=parent_id,
            document_id=document_id,
            content="Neo4j Aura stores document chunk topology for parent context.",
            chunk_index=0,
            vector_id=parent_vector_id,
            metadata={"filename": filename, "page_number": 1},
        )
        child = ChildChunkNode(
            child_id=child_id,
            document_id=document_id,
            parent_id=parent_id,
            content="Aura topology and Chroma vector retrieval smoke test.",
            chunk_index=0,
            vector_id=child_vector_id,
            metadata={"filename": filename, "page_number": 1},
        )

        repository = DatabaseRepository.from_env()
        vector_store = VectorStore.from_env()
        retriever = HybridRetriever(vector_store, repository)
        try:
            repository.initialize_schema()
            repository.delete_document(document_id)
            vector_store.delete_document(document_id)

            repository.upsert_document(document, [parent], [child])
            vector_store.upsert_document(
                document_id=document_id,
                parent_chunks=[parent],
                child_chunks=[child],
                filename=filename,
            )

            self.assertIsNotNone(repository.get_document(document_id))
            self.assertEqual(len(repository.get_parent_chunks(document_id)), 1)
            self.assertEqual(len(repository.get_child_chunks(document_id)), 1)

            result = retriever.retrieve(
                "Aura topology vector retrieval",
                document_ids=[document_id],
                top_k=3,
            )
            self.assertEqual(len(result.sources), 1)
            source = result.sources[0]
            self.assertEqual(source.document_id, document_id)
            self.assertEqual(source.filename, filename)
            self.assertEqual(source.parent_id, parent_id)
            self.assertEqual(source.child_id, child_id)
            self.assertEqual(source.page_number, 1)
            self.assertIn("parent context", result.context)

            repository.delete_document(document_id)
            vector_store.delete_document(document_id)
            self.assertIsNone(repository.get_document(document_id))
            self.assertEqual(
                vector_store.query_child_chunks(
                    "Aura topology vector retrieval",
                    document_ids=[document_id],
                    top_k=3,
                ),
                [],
            )
        finally:
            repository.delete_document(document_id)
            vector_store.delete_document(document_id)
            retriever.close()


if __name__ == "__main__":
    unittest.main()
