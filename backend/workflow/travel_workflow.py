from backend.agents.coordinator_agent import CoordinatorAgent
from backend.schemas import ChatResponse
from backend.services.chatbot_service import ChatbotService
from backend.services.rag_service import RAGService
from backend.services.workflow_service import WorkflowService


class TravelWorkflow:
    """成员一总工作流。

    负责 Workflow / Branch / Tool Call 调度的壳：
    - create_trip：输出 TravelRequest，并预留成员二、成员三调用步骤；
    - modify_trip：解析修改意图，并预留局部重规划调用；
    - travel_qa：转交 RAGService，不伪造来源。
    """

    def __init__(self) -> None:
        """初始化旅行总工作流依赖。

        这里集中创建 Chatbot、RAG、CoordinatorAgent 和底层工作流服务。
        对外暴露的 handle/stream 方法都委托给 CoordinatorAgent，
        保证意图识别、需求抽取、推荐、规划、调整和问答从同一入口编排。
        """
        self.chatbot_service = ChatbotService()
        self.rag_service = RAGService()
        self.coordinator_agent = CoordinatorAgent(
            self.chatbot_service, self.rag_service
        )
        self.intent_agent = self.coordinator_agent.intent_agent
        self.requirement_adapter = self.coordinator_agent.requirement_adapter
        self.workflow_service = WorkflowService()

    def handle_message(self, session_id: str, message: str) -> ChatResponse:
        """处理一次普通同步聊天请求。

        接收会话 ID 和用户文本，交给 CoordinatorAgent 判断当前应该创建行程、
        修改行程还是旅行问答，最后返回统一的 ChatResponse。
        """
        return self.coordinator_agent.run(session_id, message)

    async def stream_message(self, session_id: str, message: str):
        """处理一次流式聊天请求。

        该方法把 CoordinatorAgent.stream_run 的增量文本原样转发给 API 层，
        用于前端逐字或逐段展示 AI 回复。
        """
        async for chunk in self.coordinator_agent.stream_run(session_id, message):
            yield chunk

    async def stream_plan_progress(self, session_id: str, message: str):
        """处理带规划进度事件的流式请求。

        创建行程时，CoordinatorAgent 会按阶段输出需求理解、推荐、路线、预算校验等进度；
        这个方法负责把这些进度 chunk 继续向前端透传。
        """
        async for chunk in self.coordinator_agent.run_with_progress(session_id, message):
            yield chunk
