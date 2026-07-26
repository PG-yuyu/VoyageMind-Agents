class RAGService:
    """现有混合 RAG 项目的成员一侧适配入口。

    RAG 本体由公共模块复用，这里只定义成员一需要调用的稳定方法。
    后续可在此处转发到 LangChain_RAG-main 的实际 FastAPI 或 Python 服务。
    """

    def query(
        self,
        question: str,
        category: str | None = None,
        place_name: str | None = None,
        top_k: int = 5,
    ) -> dict:
        return {
            "answer": "当前知识库中没有找到足够依据。",
            "sources": [],
            "sufficient": False,
            "request": {
                "question": question,
                "category": category,
                "place_name": place_name,
                "top_k": top_k,
            },
        }

    def recommendation_evidence(
        self, place_name: str, evidence_types: list[str]
    ) -> dict:
        return {
            "place_name": place_name,
            "summary": "推荐依据等待 RAG 服务接入。",
            "sources": [],
            "evidence_types": evidence_types,
        }
