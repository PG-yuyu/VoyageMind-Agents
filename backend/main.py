from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.api.auth_api import router as auth_router
from backend.api.chat_api import router as chat_router
from backend.app.api.map_resource_api import router as map_resource_router

try:
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:
    pass

app = FastAPI(title="天津自由行智能规划系统 - 成员一 API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(chat_router)

# 成员二地图资源接口依赖 FastAPI，可用时注册到主应用。
if map_resource_router is not None:
    app.include_router(map_resource_router)
