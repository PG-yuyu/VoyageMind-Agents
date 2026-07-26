from backend.schemas import RequirementExtractionResult, TravelRequest
from backend.services.requirement_service import RequirementService


class RequirementAdapter:
    """需求提取适配器。

    新分工下，成员一核心交付是 CoordinatorAgent 和 IntentAgent。
    需求提取作为总控工作流需要调用的公共能力保留，方便向成员二、成员三输出
    TravelRequest，但不再作为成员一负责的独立 Agent 展示。
    """

    def __init__(self) -> None:
        self.requirement_service = RequirementService()

    def extract(
        self,
        session_id: str,
        message: str,
        existing_requirements: TravelRequest | None = None,
    ) -> RequirementExtractionResult:
        return self.requirement_service.extract(
            session_id, message, existing_requirements
        )
