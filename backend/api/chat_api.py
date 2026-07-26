from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.schemas import (
    ApiResponse,
    ChatRequest,
    CreateSessionRequest,
    IntentDetectRequest,
    RequirementExtractRequest,
    TravelRequest,
    WorkflowRequest,
)
from backend.services.rag_service import RAGService
from backend.services.session_store import store
from backend.workflow.travel_workflow import TravelWorkflow

router = APIRouter(prefix="/api/v1")
workflow = TravelWorkflow()
rag_service = RAGService()


def ok(data=None, message: str = "操作成功") -> ApiResponse:
    return ApiResponse(data=data, message=message)


@router.get("/health")
def health() -> ApiResponse:
    chatbot = workflow.chatbot_service
    return ok(
        {
            "status": "degraded" if not chatbot.available else "ok",
            "services": {
                "llm": "up" if chatbot.available else "fallback",
                "rag": "adapter_ready",
                "chroma": "external",
                "neo4j": "external",
                "sqlite": "in_memory_demo",
                "amap": "external",
            },
            "chatbot_error": chatbot.error,
        }
    )


@router.post("/sessions")
def create_session(body: CreateSessionRequest) -> ApiResponse:
    return ok(store.create_session(body.user_id).model_dump())


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> ApiResponse:
    session = store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")
    return ok(
        {
            "session": session.model_dump(),
            "messages": [
                item.model_dump() for item in store.messages.get(session_id, [])
            ],
            "current_itinerary": None,
            "requirements": store.requirements.get(session_id),
        }
    )


@router.post("/chat/messages")
def send_chat_message(body: ChatRequest) -> ApiResponse:
    return ok(workflow.handle_message(body.session_id, body.message).model_dump())


@router.post("/chat/messages/stream")
async def stream_chat_message(body: ChatRequest):
    async def generate():
        async for chunk in workflow.stream_message(body.session_id, body.message):
            yield chunk

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")


@router.post("/intent/detect")
def detect_intent(body: IntentDetectRequest) -> ApiResponse:
    store.ensure_session(body.session_id)
    return ok(workflow.intent_agent.run(body.message).model_dump())


@router.post("/requirements/extract")
def extract_requirements(body: RequirementExtractRequest) -> ApiResponse:
    store.ensure_session(body.session_id)
    result = workflow.requirement_adapter.extract(
        session_id=body.session_id,
        message=body.message,
        existing_requirements=body.existing_requirements
        or store.requirements.get(body.session_id),
    )
    store.update_requirements(body.session_id, result.requirements)
    return ok(result.model_dump())


@router.put("/sessions/{session_id}/requirements")
def update_requirements(session_id: str, body: TravelRequest) -> ApiResponse:
    if session_id != body.session_id:
        raise HTTPException(status_code=400, detail="SESSION_ID_MISMATCH")
    return ok(store.update_requirements(session_id, body).model_dump())


@router.post("/workflows/travel-plan")
def run_travel_workflow(body: WorkflowRequest) -> ApiResponse:
    store.update_requirements(body.session_id, body.requirements)
    trace = workflow.workflow_service.build_trace(body.session_id, "create_trip", False)
    itinerary = workflow.workflow_service.demo_itinerary_shell(body.requirements)
    store.agent_traces[body.session_id] = trace.model_dump()
    return ok(
        {
            "workflow_id": trace.trace_id,
            "status": "completed",
            "itinerary": itinerary,
            "evaluation": None,
            "agent_trace": trace.model_dump(),
        }
    )


@router.get("/sessions/{session_id}/agent-traces")
def get_agent_traces(session_id: str) -> ApiResponse:
    store.ensure_session(session_id)
    return ok(
        store.agent_traces.get(
            session_id, {"trace_id": None, "session_id": session_id, "steps": []}
        )
    )


@router.post("/rag/query")
def rag_query(body: dict) -> ApiResponse:
    return ok(
        rag_service.query(
            question=body.get("question", ""),
            category=body.get("category"),
            place_name=body.get("place_name"),
            top_k=body.get("top_k", 5),
        )
    )


@router.post("/rag/recommendation-evidence")
def recommendation_evidence(body: dict) -> ApiResponse:
    return ok(
        rag_service.recommendation_evidence(
            place_name=body.get("place_name", ""),
            evidence_types=body.get("evidence_types", []),
        )
    )
