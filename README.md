# 行知旅策 VoyageMind Agents

行知旅策是一个面向天津自由行场景的多智能体旅游规划系统。项目使用 Vue 3 + FastAPI 构建，结合大模型、RAG、地图服务、地点推荐、行程生成、预算校验和语音输入，让用户可以像聊天一样完成旅行规划、修改和问答。

本项目当前聚焦天津旅游，原因是实训阶段需要保证资料库、地点数据、地图路线和推荐结果足够稳定。如果后续资料和知识库完善，可以扩展到更多城市。

## 一、项目功能

### 1. 智能规划

用户可以用自然语言输入旅行需求，例如：

```text
帮我规划天津两日游，预算 1800 元，喜欢近代建筑和海河夜景，步行不要超过 7 公里。
```

系统会完成：

- 识别用户意图。
- 抽取目的地、天数、人数、预算、兴趣偏好、必去地点、饮食偏好、步行上限等字段。
- 调用推荐模块获取景点、酒店、餐饮和路线资源。
- 调用行程模块生成每日安排。
- 在前端展示规划进度、行程时间线、预算、地图和校验结果。

### 2. 我的行程

- 支持 1-5 天天津行程展示。
- 每天包含多个时间点，而不是简单的四段式安排。
- 每个景点或安排可以点击查看详情。
- 支持智能修改入口，例如“今天下午下雨了，把露天景点改成室内安排”。
- 支持校验预算、步行距离、开放时间和行程强度。

### 3. 旅行问答

- 采用类似 ChatGPT 的问答布局。
- 支持旅游知识问答、行程细节追问和资料来源展示。
- 支持流式输出和加载动画。
- 当 RAG 没有找到足够资料时，仍然会由大模型给出常识性回答，并提示资料来源不足。

### 4. 路线地图

- 展示推荐地点、地图 Marker 和高德路线。
- 支持高德 JS API 地图渲染。
- 支持高德 Web Service 进行坐标校验、逆地理编码和路线规划。
- 地图页面包含“基本信息”和“AI 导游”两种模式。

### 5. AI 导游

- 在地图的 AI 导游模式下，用户可以点击地点或路线。
- 系统会先展示该地点或路线的导游式介绍。
- 用户可以继续追问，例如“这里适合拍照吗”“附近有什么吃的”“适合停留多久”。
- 后续问答通过大模型流式输出。

### 6. 语音输入

- 支持浏览器录音。
- 录音后以类似微信的语音气泡展示，用户可以回放。
- 前端上传音频，后端使用 ffmpeg 转码，再调用百度智能云短语音识别。
- 识别结果会进入规划、问答或 AI 导游流程。

### 7. 资料库与 RAG

- 支持上传旅游资料的前端入口。
- 当前问答流程预留 RAG 检索入口。
- 项目中包含 `LangChain_RAG/` 目录，用于后续接入资料切分、向量检索和来源追踪。

### 8. 旅行历史与持久化

- 前端会保存当前计划、旅行历史、对话记录和登录状态。
- 刷新页面后不会立刻丢失演示数据。
- 当前演示版主要使用 LocalStorage，后续可接入真实用户数据库。

## 二、成员分工

| 成员 | 负责模块 | 具体职责 |
| --- | --- | --- |
| 成员一 | 对话入口、协调总控、意图识别、前端整合 | 负责 Vue 主界面、登录注册、智能规划入口、旅行问答、语音输入、流式输出、AI 导游交互、前端持久化、前端 API 封装；负责 Chatbot 封装接入、Intent Agent、Coordinator Agent、需求抽取、工作流编排、会话管理，以及把成员二、成员三和 RAG 的结果组织成用户可见的回复与页面状态。 |
| 成员二 | 旅游资源推荐、地图与路线 | 负责天津景点、酒店、餐厅等资源推荐；负责高德 POI、坐标校验、逆地理编码、路线规划、地图资源结构、路线缓存和地图展示所需的数据接口；为行程生成提供候选地点、餐饮、住宿和路线事实。 |
| 成员三 | 行程生成、预算、校验与调整 | 负责根据 TravelRequest、推荐地点和路线结果生成 1-5 天行程；负责预算核算、开放时间校验、步行上限校验、路线时间校验、饮食禁忌校验、软偏好评价、行程修改、版本管理和差异对比。 |

成员一比其他成员多承担了一部分前端整合和入口编排工作，因此 README 中成员一内容会稍微多一些；但推荐、地图、行程、校验等核心能力仍然分别由成员二和成员三负责。

## 三、技术栈

### 前端

- Vue 3
- Vite
- Pinia
- JavaScript / TypeScript
- 高德地图 JS API
- MediaRecorder 浏览器录音
- LocalStorage 前端持久化

### 后端

- Python 3.11+
- FastAPI
- Uvicorn
- Pydantic v2
- LangChain Core
- LangChain OpenAI
- python-dotenv
- python-multipart
- PyYAML
- aiosqlite / aiomysql

### 外部服务

- DeepSeek API：大模型对话、意图识别、需求抽取、问答和导游。
- 高德地图 Web Service API：POI、地理编码、逆地理编码、路线规划。
- 高德地图 JS API：前端真实地图渲染。
- 百度智能云短语音识别：语音输入识别。
- Neo4j：可选图数据库，用于后续地点关系、知识关系和推荐增强。
- ffmpeg：音频格式转换，语音识别前置依赖。

## 四、目录结构

```text
实训项目/
├─ backend/
│  ├─ agents/
│  │  ├─ coordinator_agent.py          # 成员一：协调总控 Agent
│  │  ├─ intent_agent.py               # 成员一：意图识别 Agent
│  │  ├─ planning_agent.py             # 成员三：行程生成 Agent
│  │  ├─ adjustment_agent.py           # 成员三：行程调整 Agent
│  │  └─ evaluation_agent.py           # 成员三：行程评价 Agent
│  ├─ api/
│  │  ├─ chat_api.py                   # 成员一：聊天、流式输出、需求抽取接口
│  │  ├─ auth_api.py                   # 成员一：登录注册接口
│  │  ├─ guide_api.py                  # 成员一：AI 导游接口
│  │  ├─ voice_api.py                  # 成员一：语音输入接口
│  │  ├─ itinerary_api.py              # 成员三：行程接口
│  │  ├─ validation_api.py             # 成员三：校验接口
│  │  └─ ...
│  ├─ app/
│  │  ├─ agents/                       # 成员二：推荐 Agent
│  │  ├─ clients/                      # 成员二：高德客户端等
│  │  ├─ services/                     # 成员二：推荐、地图、路线服务
│  │  ├─ schemas/                      # 成员二：推荐相关数据模型
│  │  └─ ...
│  ├─ services/
│  │  ├─ chatbot_service.py            # 成员一：Chatbot 封装
│  │  ├─ requirement_service.py        # 成员一：需求抽取
│  │  ├─ session_store.py              # 成员一：会话状态
│  │  ├─ itinerary_planner.py          # 成员三：规则行程编排
│  │  ├─ budget_service.py             # 成员三：预算核算
│  │  └─ ...
│  ├─ validators/                      # 成员三：硬约束校验
│  ├─ workflow/                        # 成员一：工作流编排
│  ├─ vendor/langchain_chat/           # 成员一：封装后的 Chatbot
│  ├─ main.py                          # FastAPI 入口
│  └─ requirements.txt
├─ LangChain_RAG/                      # RAG 资料检索模块
├─ src/
│  ├─ App.vue                          # 成员一：主前端应用
│  ├─ api.js                           # 成员一：前端 API 封装
│  ├─ components/
│  │  ├─ TripMap.vue                   # 地图与 AI 导游页面
│  │  ├─ TripTimeline.vue              # 行程时间线
│  │  ├─ BudgetPanel.vue               # 预算展示
│  │  ├─ ValidationPanel.vue           # 校验结果展示
│  │  └─ ...
│  ├─ styles.css
│  └─ main.js
├─ data/                               # 天津旅游示例数据
├─ docs/                               # 项目文档
├─ mock/                               # Mock 数据
├─ tests/                              # 测试
├─ package.json
├─ vite.config.js
├─ .env.example
└─ README.md
```

## 五、需要下载或准备的东西

### 1. 必装

- Python 3.11+
- Node.js 18+
- npm
- Git
- ffmpeg

### 2. 需要申请的 API

- DeepSeek API Key
- 高德地图 Web 服务 Key
- 高德地图 Web 端 JS API Key
- 高德地图安全密钥 Security Code
- 百度智能云语音识别 App ID、API Key、Secret Key

### 3. 可选

- Neo4j Desktop 或 Neo4j Server
- MySQL，当前 requirements 中包含 `aiomysql`，后续可接真实数据库

## 六、环境变量配置

复制 `.env.example` 为 `.env`：

```powershell
copy .env.example .env
```

然后填写：

```env
# DeepSeek 大模型
DEEPSEEK_API_KEY=你的_deepseek_key
DEFAULT_MODEL=deepseek-v4-flash

# 高德 Web 服务 Key，后端使用
AMAP_WEB_SERVICE_KEY=你的高德_web服务_key

# 高德 JS API，前端地图使用
VITE_AMAP_JS_KEY=你的高德_js_key
VITE_AMAP_SECURITY_CODE=你的高德安全密钥

# 语音识别
ASR_PROVIDER=baidu
BAIDU_APP_ID=你的百度_app_id
BAIDU_ASR_API_KEY=你的百度_api_key
BAIDU_ASR_SECRET_KEY=你的百度_secret_key
BAIDU_ASR_DEV_PID=1537

# ffmpeg，如果没有加入 PATH，就写绝对路径
FFMPEG_BINARY=C:\ffmpeg\bin\ffmpeg.exe

# Neo4j，可选
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=你的_neo4j_密码
NEO4J_DATABASE=neo4j
```

注意：

- `.env` 里都是密钥，不要提交到 Git。
- 修改 `.env` 后需要重启后端。
- 修改 `VITE_` 开头的变量后，需要重启前端。

## 七、安装依赖

### 1. 后端

```powershell
cd D:\许宁远\学习\企业实训\实训项目\实训项目
python -m venv .venv
.\.venv\Scripts\activate
pip install -r backend\requirements.txt
```

后端主要依赖包括：

- `fastapi`
- `uvicorn`
- `langchain-core`
- `langchain-openai`
- `python-dotenv`
- `pydantic`
- `pyyaml`
- `python-multipart`
- `aiosqlite`
- `aiomysql`
- `pytest`

### 2. 前端

```powershell
cd D:\许宁远\学习\企业实训\实训项目\实训项目
npm install
```

前端主要依赖包括：

- `vue`
- `vite`
- `pinia`
- `@vitejs/plugin-vue`

### 3. ffmpeg

语音输入必须依赖 ffmpeg。安装后检查：

```powershell
ffmpeg -version
```

如果提示找不到命令，把 `ffmpeg.exe` 的完整路径写入 `.env`：

```env
FFMPEG_BINARY=C:\你的路径\ffmpeg\bin\ffmpeg.exe
```

## 八、启动项目

需要开两个终端。

### 终端一：启动后端

```powershell
cd D:\许宁远\学习\企业实训\实训项目\实训项目
.\.venv\Scripts\activate
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

后端接口文档：

```text
http://127.0.0.1:8000/docs
```

### 终端二：启动前端

```powershell
cd D:\许宁远\学习\企业实训\实训项目\实训项目
npm run dev
```

前端地址：

```text
http://127.0.0.1:5174
```

如果端口被占用，以终端实际输出为准。

## 九、主要接口

### 成员一接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/v1/health` | 健康检查 |
| POST | `/api/v1/auth/login` | 登录 |
| POST | `/api/v1/auth/register` | 注册 |
| POST | `/api/v1/sessions` | 创建会话 |
| POST | `/api/v1/chat/messages` | 普通聊天与规划入口 |
| POST | `/api/v1/chat/messages/stream` | 流式问答 |
| POST | `/api/v1/intent/detect` | 意图识别 |
| POST | `/api/v1/requirements/extract` | 需求抽取 |
| PUT | `/api/v1/sessions/{session_id}/requirements` | 更新需求 |
| POST | `/api/v1/guide/chat/stream` | AI 导游问答 |
| POST | `/api/v1/voice/understand` | 语音识别与理解 |

### 成员二接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/v1/recommendations/attractions` | 景点推荐 |
| POST | `/api/v1/member2/map/resources/by-place-ids` | 根据地点 ID 获取地图资源 |
| POST | `/api/v1/member2/routes/plan` | 单段路线规划 |
| POST | `/api/v1/member2/routes/batch-plan` | 批量路线规划 |

### 成员三接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/v1/itineraries/generate` | 生成行程 |
| POST | `/api/v1/itineraries/validate` | 校验行程 |
| POST | `/api/v1/itineraries/calculate-budget` | 计算预算 |
| POST | `/api/v1/itineraries/modify` | 修改行程 |
| GET | `/api/v1/itineraries/{id}` | 获取行程 |
| GET | `/api/v1/itineraries/{id}/versions` | 获取版本 |
| GET | `/api/v1/itineraries/{id}/diff` | 对比版本差异 |

## 十、工作流

### 新建行程

```text
用户输入
  ↓
成员一：Chatbot 接收消息
  ↓
成员一：Intent Agent 识别 create_trip
  ↓
成员一：抽取 TravelRequest
  ↓
成员二：推荐地点、酒店、餐厅、路线
  ↓
成员三：生成行程、预算、校验
  ↓
成员一：整理回复和前端状态
  ↓
Vue 前端展示
```

### 修改行程

```text
用户输入修改要求
  ↓
成员一：识别 modify_trip，并判断影响范围
  ↓
成员三：局部重排或整体重排
  ↓
必要时调用成员二获取替代地点
  ↓
成员三：重新校验和保存版本
  ↓
前端展示修改结果和差异
```

### 旅行问答

```text
用户提问
  ↓
成员一：识别 travel_qa
  ↓
RAG 检索资料
  ↓
Chatbot 组织回答
  ↓
前端流式输出
```

### AI 导游

```text
用户点击地图地点或路线
  ↓
前端传入当前资源
  ↓
AI 导游接口获取地点上下文
  ↓
Chatbot 生成导游介绍或回答
  ↓
前端流式输出
```

## 十一、验证方式

### 前端构建

```powershell
npm run build
```

### 后端语法检查

```powershell
python -m py_compile backend\main.py backend\api\voice_api.py
```

### API 文档

启动后端后打开：

```text
http://127.0.0.1:8000/docs
```

## 十二、常见问题

### 1. 前端显示演示数据，没有真实规划结果

一般是后端没有启动，或者成员二、成员三接口没有正常返回。先确认：

```powershell
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

再刷新前端。

### 2. 大模型调用失败

检查 `.env`：

```env
DEEPSEEK_API_KEY=...
DEFAULT_MODEL=deepseek-v4-flash
```

### 3. 地图不显示

检查：

```env
VITE_AMAP_JS_KEY=...
VITE_AMAP_SECURITY_CODE=...
```

修改后重启前端。

### 4. 高德路线或坐标失败

检查：

```env
AMAP_WEB_SERVICE_KEY=...
```

修改后重启后端。

### 5. 语音识别失败

检查：

```env
ASR_PROVIDER=baidu
BAIDU_APP_ID=...
BAIDU_ASR_API_KEY=...
BAIDU_ASR_SECRET_KEY=...
FFMPEG_BINARY=...
```

如果 ffmpeg 没加入系统 PATH，就必须配置 `FFMPEG_BINARY`。

### 6. 刷新后数据丢失

演示版使用 LocalStorage 保存状态。清理浏览器缓存、换浏览器、隐私模式都会导致数据丢失。正式版本可以接入真实用户数据库。

## 十三、当前阶段说明

当前项目已经具备完整演示链路：前端页面、对话入口、意图识别、总控编排、地图展示、AI 导游、语音输入和行程展示都可以运行。部分推荐、RAG 和行程生成结果会受到成员二、成员三模块合并情况影响；当接口不可用时，前端会使用演示数据兜底，方便展示页面效果。
