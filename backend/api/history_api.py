from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.schemas import ApiResponse
from backend.services.history_store import history_store


router = APIRouter(prefix="/api/v1/history", tags=["history"])


class UserStatePayload(BaseModel):
    user_id: str = Field(min_length=1)
    username: str | None = None
    state: dict[str, Any] = Field(default_factory=dict)


def ok(data=None, message: str = "操作成功") -> ApiResponse:
    return ApiResponse(data=data, message=message)


@router.get("/state/{user_id}", response_model=ApiResponse)
def get_user_state(user_id: str) -> ApiResponse:
    state = history_store.get_state(user_id)
    return ok({"user_id": user_id, "state": state})


@router.put("/state/{user_id}", response_model=ApiResponse)
def save_user_state(user_id: str, payload: UserStatePayload) -> ApiResponse:
    if user_id != payload.user_id:
        raise HTTPException(status_code=400, detail="USER_ID_MISMATCH")
    result = history_store.save_state(
        user_id=user_id,
        username=payload.username,
        state=payload.state,
    )
    history_store.add_event(
        user_id=user_id,
        event_type="state_saved",
        payload={
            "session_id": payload.state.get("sessionId"),
            "trip_count": len(payload.state.get("tripHistory") or []),
            "message_count": len(payload.state.get("messages") or []),
        },
    )
    return ok(result, "历史状态已保存")
