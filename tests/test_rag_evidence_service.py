"""RAG 推荐依据接入测试。"""

from __future__ import annotations

from backend.app.agents import RecommendationState
from backend.app.clients import LangChainRagServiceAdapter, RagClient
from backend.app.repositories import PlaceRepository
from backend.app.schemas import RecommendationContext, RecommendationResult, TravelRequest
from backend.app.services import EvidenceEnrichmentService
from backend.app.services.evidence_service import MISSING_EVIDENCE_SOURCE
from backend.app.tools import get_place_evidence
from backend.app.workflows import run_recommendation_with_evidence_workflow


class FakeQueryRequest:
    """测试用 QueryRequest，模拟 LangChain_RAG 合约对象。"""

    def __init__(self, **kwargs) -> None:
        """保存请求字段。"""

        self.__dict__.update(kwargs)


class FakeSource:
    """测试用 RAG 来源对象。"""

    filename = "北京历史文化资料.pdf"
    page_number = 2
    document_id = "doc_beijing_history"
    chunk_id = "chunk_001"
    content = "故宫是明清两代皇家宫殿，具有重要历史文化价值。"
    score = 0.91
    citation_index = 1


class FakeResponse:
    """测试用 RAG 响应对象。"""

    answer = "故宫具有重要历史文化价值，适合作为历史文化主题旅行依据。"
    sources = [FakeSource()]
    trace_id = "trace_rag_001"
    session_id = "session_rag_001"


class FakeBackendService:
    """测试用 LangChain_RAG 后端服务。"""

    def __init__(self) -> None:
        """记录 answer 调用。"""

        self.requests = []

    def answer(self, request) -> FakeResponse:
        """模拟 LangChain_RAG 的 answer(QueryRequest) 调用。"""

        self.requests.append(request)
        return FakeResponse()


class FakeRagService:
    """测试用成员二 RAG 适配服务。"""

    def __init__(self, with_sources: bool = True) -> None:
        """保存是否返回来源。"""

        self.with_sources = with_sources
        self.calls = []

    def query_place_evidence(self, place, evidence_types, top_k):
        """模拟地点推荐依据查询。"""

        self.calls.append((place.place_id, evidence_types, top_k))
        if not self.with_sources:
            return {
                "answer": "当前知识库中没有找到足够依据。",
                "sources": [],
                "sufficient": False,
                "missing_reason": "没有检索到相关文档片段",
            }
        return {
            "answer": f"{place.name} 适合作为本次旅行推荐资源。",
            "sources": [
                {
                    "filename": "旅游资源知识库.md",
                    "page_number": 3,
                    "content": f"{place.name} 的知识库片段。",
                    "score": 0.88,
                }
            ],
            "sufficient": True,
        }


class FakeRecommendationAgent:
    """测试用推荐 Agent，避免流程测试调用真实大模型。"""

    def __init__(self) -> None:
        """初始化执行状态。"""

        self.last_state: RecommendationState | None = None

    def recommend(self, context: RecommendationContext) -> RecommendationResult:
        """返回固定推荐结果，并记录工作流状态。"""

        state = RecommendationState(context=context)
        state.add_trace("生成推荐结果")
        result = build_result()
        state.record_result(result)
        self.last_state = state
        return result


def build_context() -> RecommendationContext:
    """构造流程级测试使用的推荐上下文。"""

    requirements = TravelRequest(
        session_id="session_rag_flow",
        city="北京",
        days=3,
        people=2,
    )
    return RecommendationContext(
        session_id="session_rag_flow",
        requirements=requirements,
        original_text="两个人去北京三天，想看历史文化，也想吃本地风味。",
    )


def build_result() -> RecommendationResult:
    """构造带三个推荐地点的推荐结果。"""

    repository = PlaceRepository()
    attraction = repository.get_by_id("place_001")
    hotel = repository.get_by_id("hotel_001")
    restaurant = repository.get_by_id("restaurant_001")
    assert attraction is not None
    assert hotel is not None
    assert restaurant is not None
    return RecommendationResult(
        policy_summary="模型已完成资源推荐。",
        attractions=[attraction],
        hotels=[hotel],
        restaurants=[restaurant],
        agent_trace=["生成推荐结果"],
    )


def test_langchain_rag_adapter_calls_existing_backend_answer() -> None:
    """适配器应直接调用已有 LangChain_RAG 的 answer(QueryRequest) 入口。"""

    place = PlaceRepository().get_by_id("place_001")
    assert place is not None
    fake_backend = FakeBackendService()
    adapter = LangChainRagServiceAdapter(
        project_root=".",
        backend_service=fake_backend,
        query_request_cls=FakeQueryRequest,
    )

    result = adapter.query_place_evidence(
        place=place,
        evidence_types=["历史文化信息"],
        top_k=2,
    )

    assert fake_backend.requests
    assert "故宫博物院" in fake_backend.requests[0].query
    assert fake_backend.requests[0].top_k == 2
    assert result["sources"][0]["title"] == "北京历史文化资料.pdf"
    assert result["sufficient"] is True


def test_rag_client_normalizes_langchain_sources() -> None:
    """RagClient 能把 LangChain_RAG 来源转成统一依据结果。"""

    place = PlaceRepository().get_by_id("place_001")
    assert place is not None
    client = RagClient(rag_service=FakeRagService(), top_k=2)

    result = client.get_place_evidence(place)

    assert result.sufficient is True
    assert result.sources[0].title == "旅游资源知识库.md"
    assert result.sources[0].page == 3


def test_evidence_service_enriches_every_recommended_place() -> None:
    """依据补充服务会为每个推荐地点补充一条 Evidence。"""

    service = EvidenceEnrichmentService(
        rag_client=RagClient(rag_service=FakeRagService())
    )

    enriched = service.enrich_result(build_result())

    assert len(enriched.evidence) == 3
    assert all(evidence.sufficient for evidence in enriched.evidence)
    assert "补充RAG推荐依据 3 条" in enriched.agent_trace[-1]


def test_evidence_service_marks_missing_sources_without_fabrication() -> None:
    """知识库证据不足时，应明确标记缺少来源，不能伪造文档名。"""

    service = EvidenceEnrichmentService(
        rag_client=RagClient(rag_service=FakeRagService(with_sources=False))
    )

    enriched = service.enrich_result(build_result())

    assert len(enriched.evidence) == 3
    assert all(not evidence.sufficient for evidence in enriched.evidence)
    assert all(evidence.source == MISSING_EVIDENCE_SOURCE for evidence in enriched.evidence)
    assert all(evidence.missing_reason for evidence in enriched.evidence)


def test_rag_evidence_tool_returns_single_place_evidence() -> None:
    """RAG 工具可以为单个地点返回依据模型。"""

    place = PlaceRepository().get_by_id("place_001")
    assert place is not None
    service = EvidenceEnrichmentService(
        rag_client=RagClient(rag_service=FakeRagService())
    )
    evidence = get_place_evidence(place, evidence_service=service)

    assert evidence.place_id == "place_001"
    assert evidence.sufficient is True


def test_recommendation_with_evidence_workflow_enriches_result() -> None:
    """Step 8 工作流入口会给推荐结果补充 RAG 依据。"""

    service = EvidenceEnrichmentService(
        rag_client=RagClient(rag_service=FakeRagService())
    )

    result = run_recommendation_with_evidence_workflow(
        build_context(),
        agent=FakeRecommendationAgent(),
        evidence_service=service,
    )

    recommended_count = (
        len(result.attractions)
        + len(result.hotels)
        + len(result.restaurants)
    )
    assert len(result.evidence) == recommended_count
    assert all(evidence.sufficient for evidence in result.evidence)
    assert "补充RAG推荐依据" in result.agent_trace[-1]
