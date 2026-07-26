from __future__ import annotations


class ServiceError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        retryable: bool = False,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
        }


INVALID_FILE_TYPE = "INVALID_FILE_TYPE"
DOCUMENT_PARSE_FAILED = "DOCUMENT_PARSE_FAILED"
ENTITY_EXTRACTION_FAILED = "ENTITY_EXTRACTION_FAILED"
GRAPHDB_UNAVAILABLE = "GRAPHDB_UNAVAILABLE"
GRAPH_WRITE_FAILED = "GRAPH_WRITE_FAILED"
GRAPH_QUERY_FAILED = "GRAPH_QUERY_FAILED"
MODEL_CALL_FAILED = "MODEL_CALL_FAILED"
EMPTY_RETRIEVAL_RESULT = "EMPTY_RETRIEVAL_RESULT"
INVALID_REQUEST = "INVALID_REQUEST"
