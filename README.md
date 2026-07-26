# 行知旅策 - 成员一前端与工作流 API

这是成员一负责的代码：协调总控 Agent、意图识别 Agent、对话入口、会话状态、工作流分支调度，以及前端总体集成。

当前项目已经内置成员一需要使用的 Chatbot 核心能力：

- `backend/vendor/langchain_chat`：从 `langchain-chat-main` 搬入的 Chatbot 核心模块，保留 core / storage / models / interface / config，不包含教学文档、测试、UI 和示例。
- `LangChain_RAG-main`：后续只通过 RAGService 接口调用，不在成员一模块里改 RAG 本体。

## 启动前端

```bash
cd D:\许宁远\学习\企业实训\实训项目\实训项目
npm install
npm run dev
```

访问 `http://127.0.0.1:5174`。

## 启动 FastAPI 成员一服务

```bash
cd D:\许宁远\学习\企业实训\实训项目\实训项目
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

前端会通过 Vite 代理访问 `/api/v1`，对应后端 `http://127.0.0.1:8000/api/v1`。

## DeepSeek Key

不要把 API Key 写进前端或源码。推荐在本地 `.env` 中配置：

```powershell
cd D:\许宁远\学习\企业实训\实训项目\实训项目
copy .env.example .env
```

然后编辑 `.env`：

```text
DEEPSEEK_API_KEY=你的 DeepSeek Key
DEFAULT_MODEL=deepseek-v4-flash
```

也可以临时在 PowerShell 中设置：

```powershell
$env:DEEPSEEK_API_KEY="你的 DeepSeek Key"
$env:DEFAULT_MODEL="deepseek-v4-flash"
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

## 已实现的成员一接口

```text
GET  /api/v1/health
POST /api/v1/sessions
GET  /api/v1/sessions/{session_id}
POST /api/v1/chat/messages
POST /api/v1/intent/detect
POST /api/v1/requirements/extract
PUT  /api/v1/sessions/{session_id}/requirements
POST /api/v1/workflows/travel-plan
GET  /api/v1/sessions/{session_id}/agent-traces
POST /api/v1/rag/query
```

## 当前边界

新分工下，成员一只负责：

- 对话入口
- 三类一级意图识别
- 会话状态
- 协调总控和工作流编排
- Chatbot / RAG 接口封装入口
- Agent 执行轨迹
- 前端总体集成

需求提取、推荐、路线、行程、预算等能力通过公共适配器或其他成员接口调用，不作为成员一核心 Agent。

## 成员一智能体结构

```text
backend/agents/
├─ coordinator_agent.py    协调总控 Agent，负责 Workflow / Branch / Tool Call 调度
└─ intent_agent.py         意图识别 Agent，优先调用封装后的 Chatbot 输出 JSON
```

辅助适配器：

```text
backend/services/requirement_adapter.py
```

它只是为了让总控流程能产生统一的 `TravelRequest` 给成员二、成员三联调用，不作为成员一的核心 Agent。

`ChatbotService` 位于 `backend/services/chatbot_service.py`，它优先复用
`backend/vendor/langchain_chat/src/core/chat_engine.py` 的 `ChatEngine`。如果本机模型依赖或 Key 未配置，会自动规则兜底，
方便先和成员二、成员三联调接口；配置好 DeepSeek 后，意图识别和回复组织会优先走 Chatbot。

地图、路线、地点推荐属于成员二；行程生成、预算核算、规则校验和动态调整属于成员三。
