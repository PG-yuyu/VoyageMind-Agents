from fastapi import APIRouter

from backend.schemas import ApiResponse, AuthLoginRequest, AuthRegisterRequest, AuthUser, new_id


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=ApiResponse)
def login(payload: AuthLoginRequest) -> ApiResponse:
    user = AuthUser(
        user_id=f"user_{payload.username}",
        username=payload.username,
        nickname=payload.username,
        token=new_id("token"),
    )
    return ApiResponse(data=user.model_dump(), message="登录成功")


@router.post("/register", response_model=ApiResponse)
def register(payload: AuthRegisterRequest) -> ApiResponse:
    user = AuthUser(
        user_id=f"user_{payload.username}",
        username=payload.username,
        nickname=payload.nickname or payload.username,
        token=new_id("token"),
    )
    return ApiResponse(data=user.model_dump(), message="注册成功")
