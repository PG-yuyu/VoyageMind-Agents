"""成员一真实调用成员二推荐模块的集成测试。"""

from __future__ import annotations

from dataclasses import replace

from backend.agents.coordinator_agent import CoordinatorAgent
from backend.app.repositories import PlaceRepository
from backend.app.schemas import RecommendationContext, RecommendationResult, RouteInfo
from backend.schemas import (
    Assumption,
    ChatResponse,
    IntentResult,
    RequirementExtractionResult,
    TravelRequest,
)
from backend.services.recommendation_integration_service import (
    RecommendationIntegrationService,
)


def _travel_request(session_id: str = "session_member1_member2") -> TravelRequest:
    """构造成员一输出给成员二的旅行需求。"""

    return TravelRequest(
        session_id=session_id,
        city="天津",
        days=2,
        people=2,
        total_budget=1500,
        interests=["近代建筑"],
        food_preferences=["天津菜"],
    )


def _recommendation_result() -> RecommendationResult:
    """从样例数据中构造一个合法的成员二推荐结果。"""

    repository = PlaceRepository()
    return RecommendationResult(
        policy_summary="根据成员一需求选择天津近代建筑和本地餐饮资源。",
        attractions=[repository.list_attractions()[0]],
        hotels=[repository.list_hotels()[0]],
        restaurants=[repository.list_restaurants()[0]],
        agent_trace=["测试用成员二推荐结果"],
    )


class RecordingRecommendationAgent:
    """记录成员一是否把 RecommendationContext 交给成员二。"""

    def __init__(self, result: RecommendationResult) -> None:
        self.result = result
        self.context: RecommendationContext | None = None

    def recommend(self, context: RecommendationContext) -> RecommendationResult:
        """保存上下文并返回测试推荐结果。"""

        self.context = context
        return self.result


class PassThroughEvidenceService:
    """测试中不真实查询 RAG，只验证集成链路。"""

    def enrich_result(self, result: RecommendationResult) -> RecommendationResult:
        """直接返回推荐结果。"""

        return result


class FixedRouteService:
    """测试中返回固定路线，避免调用高德地图。"""

    def plan_recommendation_routes(
        self,
        result: RecommendationResult,
        travel_mode: str = "walking",
    ) -> RecommendationResult:
        """给酒店到首个景点补一条路线事实。"""

        route = RouteInfo(
            origin_place_id=result.hotels[0].place_id,
            destination_place_id=result.attractions[0].place_id,
            distance_meters=1200,
            duration_minutes=18,
            source="manual",
            verified=True,
            polyline=[
                (
                    result.hotels[0].coordinate.longitude,
                    result.hotels[0].coordinate.latitude,
                ),
                (
                    result.attractions[0].coordinate.longitude,
                    result.attractions[0].coordinate.latitude,
                ),
            ],
        )
        return replace(
            result,
            routes=[route],
            agent_trace=[*result.agent_trace, "测试补充路线"],
        )


class FixedMapCollection:
    """测试用地图资源集合。"""

    def __init__(self, resources: list[dict]) -> None:
        self.resources = resources

    def to_dict(self) -> dict:
        """返回前端可消费的地图资源结构。"""

        return {
            "resources": self.resources,
            "center": {"longitude": 117.2, "latitude": 39.12},
            "bounds": {
                "min_longitude": 117.1,
                "max_longitude": 117.3,
                "min_latitude": 39.0,
                "max_latitude": 39.2,
            },
            "warnings": [],
        }


class FixedMapDataService:
    """测试中返回固定地图资源，避免调用高德逆地理编码。"""

    def build_from_recommendation_result(
        self,
        result: RecommendationResult,
    ) -> FixedMapCollection:
        """把推荐地点转换为最小地图资源。"""

        places = [*result.attractions, *result.hotels, *result.restaurants]
        return FixedMapCollection(
            [
                {
                    "place_id": place.place_id,
                    "name": place.name,
                    "place_type": place.place_type,
                    "longitude": place.coordinate.longitude,
                    "latitude": place.coordinate.latitude,
                    "address": f"{place.city}{place.area}{place.name}",
                    "short_description": place.description,
                    "recommend_reason": result.policy_summary,
                    "verified": True,
                    "warning": None,
                    "source": "test",
                }
                for place in places
            ]
        )


class FakeChatbotService:
    """测试总控时替换成员一 Chatbot。"""

    def __init__(self) -> None:
        self.context: dict | None = None

    def summarize_agent_reply(self, message: str, context: dict) -> str:
        """记录总控传给回复生成器的上下文。"""

        self.context = context
        return "已调用成员二推荐模块，等待成员三生成完整行程。"


class FakeIntentAgent:
    """固定识别为新建行程。"""

    def run(self, message: str) -> IntentResult:
        """返回 create_trip 意图。"""

        return IntentResult(
            intent="create_trip",
            confidence=1.0,
            original_text=message,
        )


class FakeRequirementAdapter:
    """固定返回合法 TravelRequest。"""

    def __init__(self, requirements: TravelRequest) -> None:
        self.requirements = requirements

    def extract(
        self,
        session_id: str,
        message: str,
        existing_requirements: TravelRequest | None = None,
    ) -> RequirementExtractionResult:
        """返回成员一已完成需求理解的结果。"""

        return RequirementExtractionResult(
            requirements=self.requirements,
            assumptions=[
                Assumption(
                    field="transport_modes",
                    value=["walking", "transit"],
                    reason="用户未指定交通方式，默认步行加公共交通",
                )
            ],
        )


class FakeRecommendationIntegrationService:
    """测试总控是否调用成员二集成服务。"""

    def __init__(self) -> None:
        self.called = False
        self.requirements: TravelRequest | None = None
        self.original_text: str | None = None
        self.conversation_context: list[str] | None = None

    def recommend_for_request(
        self,
        requirements: TravelRequest,
        original_text: str,
        conversation_context: list[str] | None = None,
        assumptions: list[Assumption] | None = None,
    ) -> dict:
        """记录调用参数并返回成员二最小结果。"""

        self.called = True
        self.requirements = requirements
        self.original_text = original_text
        self.conversation_context = conversation_context or []
        return {
            "recommendation_result": {
                "policy_summary": "测试推荐策略",
                "attractions": [{"place_id": "place_001", "place_type": "attraction"}],
                "hotels": [{"place_id": "hotel_001", "place_type": "hotel"}],
                "restaurants": [
                    {"place_id": "restaurant_001", "place_type": "restaurant"}
                ],
                "routes": [],
                "evidence": [],
                "validation_issues": [],
                "need_follow_up": False,
                "follow_up_question": None,
                "agent_trace": ["测试调用成员二"],
            },
            "map_resources": {
                "resources": [{"place_id": "place_001", "name": "测试景点"}],
                "center": {"longitude": 117.2, "latitude": 39.12},
                "bounds": {},
                "warnings": [],
            },
            "routes": [{"origin_place_id": "hotel_001", "destination_place_id": "place_001"}],
        }


def test_member1_travel_request_can_build_recommendation_context() -> None:
    """成员一 TravelRequest 可以转换为成员二 RecommendationContext。"""

    recording_agent = RecordingRecommendationAgent(_recommendation_result())
    service = RecommendationIntegrationService(
        recommendation_agent=recording_agent,
        evidence_service=PassThroughEvidenceService(),
        route_service=FixedRouteService(),
        map_data_service=FixedMapDataService(),
    )
    request = _travel_request()

    output = service.recommend_for_request(
        requirements=request,
        original_text="天津两日游，想看近代建筑，也想吃天津菜。",
        conversation_context=["用户想要天津两日游"],
        assumptions=[
            Assumption(
                field="daily_start_time",
                value="09:00",
                reason="用户未指定每日出发时间",
            )
        ],
    )

    assert recording_agent.context is not None
    assert recording_agent.context.requirements == request
    assert recording_agent.context.original_text == "天津两日游，想看近代建筑，也想吃天津菜。"
    assert any(
        preference.text == "近代建筑"
        for preference in recording_agent.context.semantic_preferences
    )
    assert output["recommendation_result"]["attractions"]
    assert output["map_resources"]["resources"]
    assert output["routes"]


def test_create_trip_branch_calls_member2_integration_service() -> None:
    """新建行程分支会真实调用成员二集成服务。"""

    session_id = "session_member1_member2_coordinator"
    request = _travel_request(session_id)
    chatbot_service = FakeChatbotService()
    integration_service = FakeRecommendationIntegrationService()
    agent = CoordinatorAgent(
        chatbot_service=chatbot_service,
        recommendation_integration_service=integration_service,
    )
    agent.intent_agent = FakeIntentAgent()
    agent.requirement_adapter = FakeRequirementAdapter(request)

    response = agent.run(session_id, "帮我规划天津两日游，想看近代建筑。")

    assert integration_service.called is True
    assert integration_service.requirements == request
    assert integration_service.original_text == "帮我规划天津两日游，想看近代建筑。"
    # 归一化后处理使降级规则引擎也能生成有效行程，因此状态为 completed
    assert response.workflow_status == "completed"
    assert response.recommendation_result is not None
    assert response.map_resources is not None
    assert response.routes is not None
    assert response.itinerary is not None, "归一化后应生成有效行程"
    assert chatbot_service.context is not None
    assert "recommendation_result" in chatbot_service.context
    statuses = {
        step["action"]: step["status"] for step in response.agent_trace["steps"]
    }
    assert statuses["recommend_places"] == "success"
    assert statuses["batch_plan_routes"] == "success"


def test_chat_response_contains_member2_payload_fields() -> None:
    """ChatResponse 可以承载成员二推荐、地图和路线结果。"""

    response = ChatResponse(
        message_id="msg_test",
        intent=IntentResult(
            intent="create_trip",
            confidence=1.0,
            original_text="天津两日游",
        ),
        reply="已生成推荐结果。",
        workflow_status="planning",
        requirements=_travel_request(),
        recommendation_result={"attractions": [{"place_id": "place_001"}]},
        map_resources={"resources": [{"place_id": "place_001"}]},
        routes=[{"origin_place_id": "hotel_001", "destination_place_id": "place_001"}],
    )

    assert response.recommendation_result["attractions"][0]["place_id"] == "place_001"
    assert response.map_resources["resources"][0]["place_id"] == "place_001"
    assert response.routes[0]["origin_place_id"] == "hotel_001"
