"""智能旅游规划后端主应用入口。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.auth_api import router as auth_router
from backend.api.chat_api import router as chat_router
from backend.app.api.map_resource_api import router as map_resource_router
from backend.app.api.recommendation_api import router as recommendation_router
from backend.app.api.routes_api import router as route_router


app = FastAPI(title="智能旅游规划 API", version="0.1.0")

# 前端本地联调使用宽松跨域配置，正式部署时可按域名收紧。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(chat_router)

# 成员二地图、路线和成员三对接接口依赖 FastAPI，可用时注册到主应用。
if map_resource_router is not None:
    app.include_router(map_resource_router)

if route_router is not None:
    app.include_router(route_router)

if recommendation_router is not None:
    app.include_router(recommendation_router)


__all__ = ["app"]
