from backend.agents.intent_agent import IntentAgent
from backend.schemas import ChatResponse
from backend.services.chatbot_service import ChatbotService
from backend.services.rag_service import RAGService
from backend.services.recommendation_integration_service import (
    RecommendationIntegrationService,
)
from backend.services.requirement_adapter import RequirementAdapter
from backend.services.session_store import store
from backend.services.workflow_service import WorkflowService


class CoordinatorAgent:
    """成员一协调总控 Agent。

    这是项目中的总控智能体，负责：
    - 接收 Chatbot 对话输入；
    - 调用 IntentAgent 做三类意图识别；
    - 调用需求提取适配器产出 TravelRequest；
    - 按 create_trip / modify_trip / travel_qa 分支编排工作流；
    - 记录 Agent 执行轨迹；
    - 为成员二和成员三预留 Tool Call 接口位置。
    """

    def __init__(
        self,
        chatbot_service: ChatbotService | None = None,
        rag_service: RAGService | None = None,
        recommendation_integration_service: RecommendationIntegrationService
        | None = None,
    ) -> None:
        self.chatbot_service = chatbot_service or ChatbotService()
        self.intent_agent = IntentAgent(self.chatbot_service)
        self.requirement_adapter = RequirementAdapter()
        self.workflow_service = WorkflowService()
        self.rag_service = rag_service or RAGService()
        self.recommendation_integration_service = (
            recommendation_integration_service or RecommendationIntegrationService()
        )

    def run(self, session_id: str, message: str) -> ChatResponse:
        store.ensure_session(session_id)
        user_message = store.add_message(session_id, "user", message)

        intent = self.intent_agent.run(message)
        if intent.intent == "travel_qa":
            trace = self.workflow_service.build_trace(
                session_id=session_id,
                intent=intent.intent,
                has_missing_fields=False,
            )
            store.agent_traces[session_id] = trace.model_dump()
            rag_result = self.rag_service.query(question=message, top_k=5)
            reply = self.chatbot_service.answer_travel_question(message, rag_result)
            store.add_message(session_id, "assistant", reply)
            return ChatResponse(
                message_id=user_message.message_id,
                intent=intent,
                reply=reply,
                workflow_status="completed",
                requirements=store.requirements.get(session_id),
                itinerary=None,
                agent_trace=trace.model_dump(),
            )

        extraction = self.requirement_adapter.extract(
            session_id=session_id,
            message=message,
            existing_requirements=store.requirements.get(session_id),
        )
        store.update_requirements(session_id, extraction.requirements)

        trace = self.workflow_service.build_trace(
            session_id=session_id,
            intent=intent.intent,
            has_missing_fields=extraction.need_follow_up,
        )
        store.agent_traces[session_id] = trace.model_dump()

        recommendation_output = None

        if extraction.need_follow_up:
            reply = extraction.follow_up_question or "还需要补充关键信息。"
            workflow_status = "waiting_for_user"
        elif intent.intent == "modify_trip":
            reply = self.chatbot_service.summarize_agent_reply(
                message,
                {
                    "branch": "modify_trip",
                    "intent": intent.model_dump(),
                    "requirements": extraction.model_dump(),
                    "next_tool_calls": [
                        "itineraries.modify",
                        "recommendations.alternatives",
                        "itineraries.local_replan",
                    ],
                },
            )
            workflow_status = "planning"
        else:
            try:
                recommendation_output = (
                    self.recommendation_integration_service.recommend_for_request(
                        requirements=extraction.requirements,
                        original_text=message,
                        conversation_context=self._conversation_context(session_id),
                        assumptions=extraction.assumptions,
                    )
                )
            except Exception as exc:
                trace = self.workflow_service.build_trace(
                    session_id=session_id,
                    intent=intent.intent,
                    has_missing_fields=False,
                    member2_recommendation_status="failed",
                    member2_route_status="failed",
                )
                reply = (
                    "成员二推荐模块调用失败，请检查大模型、RAG 或高德地图配置后重试："
                    f"{exc}"
                )
                workflow_status = "failed"
            else:
                trace = self.workflow_service.build_trace(
                    session_id=session_id,
                    intent=intent.intent,
                    has_missing_fields=False,
                    member2_recommendation_status="success",
                    member2_route_status="success",
                )
                reply = self.chatbot_service.summarize_agent_reply(
                    message,
                    {
                        "branch": "create_trip",
                        "intent": intent.model_dump(),
                        "requirements": extraction.model_dump(),
                        "recommendation_result": recommendation_output[
                            "recommendation_result"
                        ],
                        "map_resources": recommendation_output["map_resources"],
                        "routes": recommendation_output["routes"],
                        "next_tool_calls": [
                            "itineraries.generate",
                            "itineraries.validate",
                        ],
                    },
                )
                workflow_status = "planning"
            store.agent_traces[session_id] = trace.model_dump()

        if recommendation_output is not None:
            recommendation_result = recommendation_output["recommendation_result"]
            map_resources = recommendation_output["map_resources"]
            routes = recommendation_output["routes"]
        else:
            recommendation_result = None
            map_resources = None
            routes = None

        store.add_message(session_id, "assistant", reply)

        return ChatResponse(
            message_id=user_message.message_id,
            intent=intent,
            reply=reply,
            workflow_status=workflow_status,
            requirements=extraction.requirements,
            itinerary=None,
            recommendation_result=recommendation_result,
            map_resources=map_resources,
            routes=routes,
            agent_trace=trace.model_dump(),
        )

    def _conversation_context(self, session_id: str) -> list[str]:
        """读取当前会话历史，传给成员二保留上下文。"""

        return [
            message.content
            for message in store.messages.get(session_id, [])
            if message.role in {"user", "assistant"} and message.content.strip()
        ]

    def _is_smalltalk(self, message: str) -> bool:
        text = message.strip()
        return text in {"你好", "您好", "hi", "hello", "嗨", "你猜"} or len(text) <= 2

    async def stream_run(self, session_id: str, message: str):
        store.ensure_session(session_id)

        intent = self.intent_agent.run(message)
        if intent.intent != "travel_qa":
            response = self.run(session_id, message)
            yield response.reply
            return

        store.add_message(session_id, "user", message)

        trace = self.workflow_service.build_trace(
            session_id=session_id,
            intent=intent.intent,
            has_missing_fields=False,
        )
        store.agent_traces[session_id] = trace.model_dump()

        rag_result = self.rag_service.query(question=message, top_k=5)
        parts: list[str] = []
        async for chunk in self.chatbot_service.stream_travel_question(
            message, rag_result
        ):
            parts.append(chunk)
            yield chunk
        store.add_message(session_id, "assistant", "".join(parts))
