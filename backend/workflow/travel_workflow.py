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
        self.chatbot_service = ChatbotService()
        self.rag_service = RAGService()
        self.coordinator_agent = CoordinatorAgent(self.chatbot_service, self.rag_service)
        self.intent_agent = self.coordinator_agent.intent_agent
        self.requirement_adapter = self.coordinator_agent.requirement_adapter
        self.workflow_service = WorkflowService()

    def handle_message(self, session_id: str, message: str) -> ChatResponse:
        return self.coordinator_agent.run(session_id, message)

    async def stream_message(self, session_id: str, message: str):
        async for chunk in self.coordinator_agent.stream_run(session_id, message):
            yield chunk
