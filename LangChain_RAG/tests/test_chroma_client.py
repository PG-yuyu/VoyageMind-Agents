import unittest

from neo4j_chroma.chroma_client import ChromaClient
from neo4j_chroma.embedding import HashEmbeddingFunction


class FakeCollection:
    def __init__(self, name):
        self.name = name

    def count(self):
        return 0


class FakePersistentClient:
    def __init__(self, path):
        self.path = path
        self.collections = {}

    def get_or_create_collection(self, name):
        self.collections.setdefault(name, FakeCollection(name))
        return self.collections[name]


class ChromaClientTest(unittest.TestCase):
    def test_health_check_touches_parent_and_child_collections(self):
        client = ChromaClient(
            persist_directory="tmp/chroma",
            parent_collection_name="parent_documents",
            child_collection_name="child_documents",
            client=FakePersistentClient("tmp/chroma"),
        )

        self.assertTrue(client.health_check())
        self.assertEqual(
            set(client.client.collections),
            {"parent_documents", "child_documents"},
        )

    def test_hash_embedding_is_deterministic_and_normalized(self):
        embedding = HashEmbeddingFunction(dimension=16)

        first = embedding.embed_query("Neo4j stores parent chunks")
        second = embedding.embed_query("Neo4j stores parent chunks")

        self.assertEqual(first, second)
        self.assertEqual(len(first), 16)
        self.assertAlmostEqual(sum(value * value for value in first), 1.0)


if __name__ == "__main__":
    unittest.main()
