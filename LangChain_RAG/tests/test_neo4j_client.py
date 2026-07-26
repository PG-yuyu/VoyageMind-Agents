import os
import unittest
from unittest.mock import patch

from neo4j_chroma.config import GraphDBConfig
from neo4j_chroma.neo4j_client import Neo4jClient


class FakeRecord:
    def __init__(self, data):
        self._data = data

    def data(self):
        return self._data


class FakeSession:
    def __init__(self):
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query, parameters=None):
        self.queries.append((query, parameters or {}))
        return [FakeRecord({"ok": 1})]


class FakeDriver:
    def __init__(self):
        self.session_obj = FakeSession()
        self.closed = False

    def session(self, database=None):
        self.database = database
        return self.session_obj

    def close(self):
        self.closed = True


class Neo4jClientTest(unittest.TestCase):
    def test_health_check_uses_configured_database(self):
        driver = FakeDriver()
        client = Neo4jClient(
            uri="bolt://example:7687",
            username="neo4j",
            password="secret",
            database="rag",
            driver=driver,
        )

        self.assertTrue(client.health_check())
        self.assertEqual(driver.database, "rag")
        self.assertEqual(driver.session_obj.queries[0][0], "RETURN 1 AS ok")

    def test_execute_returns_record_dicts(self):
        client = Neo4jClient(
            uri="bolt://example:7687",
            username="neo4j",
            password="secret",
            driver=FakeDriver(),
        )

        rows = client.execute("RETURN 1 AS ok")

        self.assertEqual(rows, [{"ok": 1}])

    def test_config_reads_environment(self):
        env = {
            "NEO4J_URI": "bolt://db:7687",
            "NEO4J_USERNAME": "alice",
            "NEO4J_PASSWORD": "pw",
            "NEO4J_DATABASE": "docs",
            "CHROMA_PERSIST_DIRECTORY": "tmp/chroma",
            "EMBEDDING_DIMENSION": "32",
        }
        with patch.dict(os.environ, env, clear=False):
            config = GraphDBConfig.from_env()

        self.assertEqual(config.neo4j_uri, "bolt://db:7687")
        self.assertEqual(config.neo4j_username, "alice")
        self.assertEqual(config.neo4j_database, "docs")
        self.assertEqual(config.chroma_persist_directory, "tmp/chroma")
        self.assertEqual(config.embedding_dimension, 32)


if __name__ == "__main__":
    unittest.main()
