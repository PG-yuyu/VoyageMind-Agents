# 行知旅策 VoyageMind Agents

基于 Vue 3 + FastAPI + 多智能体协作的天津自由行智能规划系统。项目面向实训场景，围绕“用户自然语言提出旅行需求，系统理解意图、抽取约束、推荐地点、生成行程、支持问答和动态调整”这一完整流程进行设计。

当前版本以天津旅游为主要范围，避免城市范围过大导致资料收集、RAG 检索和地点推荐不稳定。系统支持智能规划、我的行程、旅行历史、路线地图、预算、旅行问答、资料库、AI 导游、语音输入等页面与功能。

## 核心能力

- 自然语言旅行规划：用户可以直接输入“帮我规划天津两日游，预算 1800 元，喜欢近代建筑和海河夜景”。
- 意图识别与需求抽取：识别新建行程、修改行程、旅行问答、资料管理等意图，并抽取天数、预算、兴趣、步行限制等字段。
- 协调总控工作流：由总控 Agent 组织成员二推荐模块、成员三行程模块、RAG 问答模块以及前端展示。
- Vue 现代化前端：包含登录注册、智能规划、行程时间线、地图、预算、问答、资料库、旅行历史等页面。
- 流式对话输出：问答和 AI 导游支持流式输出、加载动画和平滑显示。
- 语音输入：支持浏览器录音上传，后端通过百度智能云 ASR 识别语音，再交给对应对话流程处理。
- 地图与 AI 导游：地图页面支持基本信息模式和 AI 导游模式，点击地点或路线后可进行导游式介绍和追问。
- 本地持久化：前端会保存当前计划、旅行历史、会话记录和用户登录状态，刷新后不丢失演示数据。

## 成员分工

| 成员 | 负责方向 | 主要工作 |
| --- | --- | --- |
| 成员一 | 对话入口、协调总控、意图识别、前端整合 | 负责用户入口、登录注册、Vue 主界面、自然语言输入、语音输入、流式输出、意图识别 Agent、需求抽取、总控 Agent、Chatbot 封装、工作流编排、RAG/问答入口、AI 导游前端与后端接口封装、状态持久化、API 对接、演示页面美化与交互闭环 |
| 成员二 | 旅游资源推荐与地图路线 | 负责景点、酒店、餐厅推荐，高德 POI 查询，高德路线规划，地图资源结构，地点与路线数据返回 |
| 成员三 | 行程生成、校验、预算与调整 | 负责每日行程生成、预算核算、硬约束校验、软偏好评价、行程修改、版本管理和差异对比 |

成员一在本项目中承担的是用户侧入口和系统编排层，工作量覆盖前端主体验、对话入口、总控 Agent、意图识别 Agent、Chatbot 封装和多个后端接口粘合，是三个成员模块能够串起来运行的入口层。

## 成员一已完成内容

- Vue 3 单页应用主框架。
- 登录 / 注册页面与账号中心入口。
- 智能规划首页，支持文本和语音发起规划。
- 规划进度组件，按理解需求、筛选地点、安排路线、检查预算动态推进。
- 我的行程页面，支持多天行程、地点详情弹窗、智能修改入口、行程校验结果展示。
- 旅行历史页面，支持保存和查看历史方案。
- 旅行问答页面，采用 ChatGPT 式布局，支持资料来源、推荐问题、流式回答。
- 资料库页面，支持上传旅游资料的前端入口。
- 路线地图页面整合，支持基本信息和 AI 导游模式切换。
- AI 导游前端与后端接口，点击地点或路线后可导游介绍并继续追问。
- 语音输入交互，录音后以类似微信语音气泡展示，并上传后端识别。
- 百度智能云语音识别接口配置与后端接入。
- Chatbot 封装接入，包括普通问答、流式问答、AI 导游流式问答。
- 总控 Agent 与意图识别 Agent 对接，负责把用户输入转换为后续模块需要的结构化请求。
- 前端 API 统一封装，连接 `/api/v1` 下的会话、问答、地图、行程、调整、语音等接口。
- 前端状态持久化，刷新后保留旅行计划、旅行历史和会话。

## 技术栈

### 前端

- Vue 3
- Vite
- JavaScript / TypeScript 混合模块
- 高德地图 JS API
- MediaRecorder 浏览器录音
- LocalStorage 本地持久化

### 后端

- Python 3.11+
- FastAPI
- Pydantic
- LangChain / Chatbot 封装
- DeepSeek OpenAI 兼容接口
- 百度智能云语音识别
- 高德 Web Service API
- Neo4j，作为可选图数据库配置

## 目录结构

```text
实训项目/
├─ backend/
│  ├─ agents/
│  │  ├─ coordinator_agent.py        # 成员一：协调总控 Agent
│  │  ├─ intent_agent.py             # 成员一：意图识别 Agent
│  │  ├─ planning_agent.py           # 成员三：行程规划 Agent
│  │  └─ ...
│  ├─ api/
│  │  ├─ chat_api.py                 # 成员一：对话与流式接口
│  │  ├─ auth_api.py                 # 成员一：登录注册接口
│  │  ├─ guide_api.py                # 成员一：AI 导游接口
│  │  ├─ voice_api.py                # 成员一：语音识别接口
│  │  ├─ itinerary_api.py            # 成员三：行程接口
│  │  └─ ...
│  ├─ app/                           # 成员二：推荐、地图、高德路线模块
│  ├─ services/
│  │  ├─ chatbot_service.py          # 成员一：Chatbot 封装
│  │  ├─ session_store.py            # 成员一：会话存储
│  │  └─ ...
│  ├─ workflow/                      # 成员一：工作流编排
│  ├─ vendor/                        # 成员一：封装后的 Chatbot 相关代码
│  ├─ main.py                        # FastAPI 入口
│  └─ requirements.txt
├─ src/
│  ├─ App.vue                        # 成员一：主前端页面
│  ├─ api.js                         # 成员一：前端 API 封装
│  ├─ components/
│  │  ├─ TripMap.vue                 # 地图与 AI 导游界面
│  │  ├─ TripTimeline.vue            # 行程时间线
│  │  ├─ BudgetPanel.vue             # 预算面板
│  │  ├─ ValidationPanel.vue         # 校验结果
│  │  └─ ...
│  ├─ styles.css                     # 全局样式
│  └─ main.js
├─ data/                             # 天津旅游示例数据
├─ docs/                             # 项目文档
├─ mock/                             # 演示数据
├─ package.json
├─ vite.config.js
└─ README.md
```

## 环境准备

### 必需环境

- Python 3.11 或更高版本
- Node.js 18 或更高版本
- npm
- ffmpeg，语音上传转码需要

### 可选服务

- DeepSeek API Key，用于大模型对话、意图识别、问答和导游。
- 高德地图 Key，用于地图展示、POI 和路线规划。
- 百度智能云语音识别 Key，用于语音输入。
- Neo4j 数据库，用于图数据库和更完整的知识/地点关系能力。

## 环境变量

在项目根目录创建 `.env` 文件。`.env` 不要提交到 Git。

```env
# 大模型
DEEPSEEK_API_KEY=你的_deepseek_key
DEFAULT_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com

# 高德地图
AMAP_WEB_SERVICE_KEY=你的高德 Web 服务 Key
VITE_AMAP_JS_KEY=你的高德 JS Key
VITE_AMAP_SECURITY_CODE=你的高德安全密钥

# 百度智能云语音识别
BAIDU_ASR_APP_ID=你的 App ID
BAIDU_ASR_API_KEY=你的 App Key
BAIDU_ASR_SECRET_KEY=你的 Secret Key

# ffmpeg，Windows 可以写绝对路径
FFMPEG_BINARY=C:\path\to\ffmpeg.exe

# Neo4j，可选
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=你的数据库密码
NEO4J_DATABASE=neo4j

# 前端代理默认会访问后端 8000 端口
VITE_API_BASE=/api/v1
```

## 安装依赖

### 后端依赖

```powershell
cd D:\许宁远\学习\企业实训\实训项目\实训项目
python -m venv .venv
.\.venv\Scripts\activate
pip install -r backend\requirements.txt
```

### 前端依赖

```powershell
cd D:\许宁远\学习\企业实训\实训项目\实训项目
npm install
```

## 启动方式

需要开两个终端，一个启动后端，一个启动前端。

### 1. 启动后端

```powershell
cd D:\许宁远\学习\企业实训\实训项目\实训项目
.\.venv\Scripts\activate
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

后端地址：

```text
http://127.0.0.1:8000
```

接口文档：

```text
http://127.0.0.1:8000/docs
```

### 2. 启动前端

```powershell
cd D:\许宁远\学习\企业实训\实训项目\实训项目
npm run dev
```

前端地址通常是：

```text
http://127.0.0.1:5174
```

如果端口被占用，以终端实际输出为准。

## ffmpeg 配置说明

语音输入会从浏览器上传 webm/mp4 音频，后端需要 ffmpeg 转成百度 ASR 更稳定识别的格式。

检查是否配置成功：

```powershell
ffmpeg -version
```

如果命令找不到，可以在 `.env` 中配置绝对路径：

```env
FFMPEG_BINARY=C:\Users\你的用户名\Downloads\ffmpeg\bin\ffmpeg.exe
```

改完 `.env` 后需要重启后端。

## 主要接口

### 成员一接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/v1/health` | 健康检查 |
| POST | `/api/v1/auth/login` | 登录 |
| POST | `/api/v1/auth/register` | 注册 |
| POST | `/api/v1/sessions` | 创建会话 |
| POST | `/api/v1/chat/messages` | 普通对话 |
| POST | `/api/v1/chat/messages/stream` | 流式对话 |
| POST | `/api/v1/intent/detect` | 意图识别 |
| POST | `/api/v1/requirements/extract` | 需求抽取 |
| POST | `/api/v1/guide/chat/stream` | AI 导游流式问答 |
| POST | `/api/v1/voice/understand` | 语音识别与语义理解 |

### 成员二接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/recommendations/attractions` | 景点推荐 |
| POST | `/api/v1/member2/map/resources/by-place-ids` | 地图资源查询 |
| POST | `/api/v1/member2/routes/plan` | 单段路线规划 |
| POST | `/api/v1/member2/routes/batch-plan` | 批量路线规划 |

### 成员三接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/itineraries/generate` | 生成行程 |
| POST | `/api/v1/itineraries/validate` | 校验行程 |
| POST | `/api/v1/itineraries/calculate-budget` | 预算核算 |
| POST | `/api/v1/itineraries/modify` | 修改行程 |
| GET | `/api/v1/itineraries/{id}/versions` | 行程版本 |
| GET | `/api/v1/itineraries/{id}/diff` | 版本差异 |

## 工作流说明

```text
用户输入
  ↓
成员一：Chatbot 接收消息
  ↓
成员一：IntentAgent 识别意图
  ↓
成员一：CoordinatorAgent 抽取需求并判断 workflow_status
  ↓
成员二：推荐景点 / 酒店 / 餐厅 / 路线
  ↓
成员三：生成每日行程、预算、校验、调整
  ↓
成员一：组织回复、流式输出、前端展示
```

如果用户问的是旅游知识问题：

```text
用户问题 → 成员一问答入口 → RAG 检索 → Chatbot 组织回答 → 前端流式展示
```

如果用户点击地图里的 AI 导游：

```text
点击地点或路线 → 前端传入当前资源 → AI 导游接口 → Chatbot 根据地点资料生成导游回答 → 前端流式展示
```

## 验证方式

### 前端构建

```powershell
npm run build
```

### 后端语法检查

```powershell
python -m py_compile backend\main.py backend\api\voice_api.py
```

### 接口检查

启动后端后打开：

```text
http://127.0.0.1:8000/docs
```

可以测试健康检查、会话创建、流式对话、AI 导游、语音识别等接口。

## 常见问题

### 1. 前端没有连上后端

确认后端是否启动在 8000 端口：

```powershell
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

再启动前端：

```powershell
npm run dev
```

### 2. 大模型调用失败

检查 `.env` 中是否配置：

```env
DEEPSEEK_API_KEY=...
DEFAULT_MODEL=deepseek-v4-flash
```

改完后重启后端。

### 3. 地图不显示或路线不对

检查：

```env
AMAP_WEB_SERVICE_KEY=...
VITE_AMAP_JS_KEY=...
VITE_AMAP_SECURITY_CODE=...
```

前端环境变量修改后需要重启 `npm run dev`。

### 4. 语音识别提示 ffmpeg 不存在

安装 ffmpeg 并配置：

```env
FFMPEG_BINARY=C:\path\to\ffmpeg.exe
```

然后重启后端。

### 5. 刷新后历史丢失

当前演示版使用 LocalStorage 保存前端状态。如果清理浏览器缓存、换浏览器或使用隐私模式，历史会丢失。后续可以接入真实用户数据库。

## 当前说明

本项目是实训阶段版本。部分推荐、RAG、图数据库和行程生成能力依赖成员二、成员三模块的最终合并效果；在接口不可用时，前端会使用演示数据保证页面可展示。正式联调时，应优先使用后端真实返回的 `recommendation_result`、`itinerary`、`routes` 和 `rag_sources`。
