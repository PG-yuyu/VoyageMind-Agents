"""Thin Neo4j driver wrapper for the graph database module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from neo4j_chroma.config import GraphDBConfig


DriverFactory = Callable[[str, tuple[str, str]], Any]


@dataclass(slots=True)
class Neo4jClient:
    """Lazy Neo4j client with a small testable surface."""

    uri: str
    username: str
    password: str
    database: str = "neo4j"
    driver: Any | None = None
    driver_factory: DriverFactory | None = None

    @classmethod
    def from_config(cls, config: GraphDBConfig) -> "Neo4jClient":
        return cls(
            uri=config.neo4j_uri,
            username=config.neo4j_username,
            password=config.neo4j_password,
            database=config.neo4j_database,
        )

    @classmethod
    def from_env(cls) -> "Neo4jClient":
        return cls.from_config(GraphDBConfig.from_env())

    def connect(self) -> Any:
        """Create or return the underlying Neo4j driver."""

        if self.driver is None:
            if self.driver_factory is None:
                try:
                    from neo4j import GraphDatabase
                except ImportError as exc:
                    raise RuntimeError(
                        "neo4j package is required for a real Neo4j connection",
                    ) from exc

                self.driver_factory = GraphDatabase.driver
            self.driver = self.driver_factory(
                self.uri,
                auth=(self.username, self.password),
            )
        return self.driver

    def session(self) -> Any:
        return self.connect().session(database=self.database)

    def health_check(self) -> bool:
        try:
            self.execute("RETURN 1 AS ok")
            return True
        except Exception:
            return False

    def execute(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Run a Cypher query and return row dictionaries."""

        params = parameters or {}
        with self.session() as session:
            result = session.run(query, params)
            return [self._record_to_dict(record) for record in result]

    def close(self) -> None:
        if self.driver is not None:
            self.driver.close()
            self.driver = None

    @staticmethod
    def _record_to_dict(record: Any) -> dict[str, Any]:
        if hasattr(record, "data"):
            return record.data()
        return dict(record)
