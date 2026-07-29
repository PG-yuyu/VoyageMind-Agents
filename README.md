# 行知旅策 VoyageMind Agents

行知旅策是一个面向天津自由行场景的多智能体旅行规划系统。项目使用 Vue 3 + Vite 构建前端，使用 FastAPI 构建后端，结合大模型、RAG 知识库、旅游资源推荐、高德地图、路线规划、预算校验、行程调整、语音输入和 AI 导游，让用户可以用自然语言完成旅行规划、途中修改和旅行问答。

当前版本聚焦天津旅游场景，主要是为了让地点库、路线数据、知识资料和演示流程足够稳定。后续如果扩展城市资料、地图资源和 RAG 知识库，可以继续支持更多城市。

## 功能概览

### 智能规划

用户可以直接输入自然语言需求，例如：

```text
帮我规划天津两日游，预算 1800 元，喜欢近代建筑和海河夜景，步行不要超过 7 公里。
```

系统会自动完成：

- 意图识别：判断是新建行程、修改行程还是旅行问答。
- 需求抽取：抽取城市、天数、人数、预算、兴趣偏好、必去地点、饮食偏好、步行上限等字段。
- 资源推荐：筛选天津景点、酒店、餐厅和路线资源。
- 行程生成：生成 1-5 天的每日时间线。
- 进度展示：展示“理解需求、筛选地点、安排路线、检查预算与强度”的规划过程。
- 结果同步：把行程、预算、地图资源、推荐依据和历史记录同步到前端页面。

### 我的行程

- 按天展示行程，支持第 1 天到第 5 天切换。
- 每天包含多个具体时间点，而不是简单的上午、下午、晚上三段。
- 行程卡片包含类型、地点名、简要介绍、路线衔接、费用和调整状态。
- 行程大标题统一显示为“第一天行程”“第二天行程”等，避免用景点名拼接标题。
- 景点卡片遵循“类型 / 景点名 / 简要介绍”的展示规则。
- 步行距离只统计步行、游览、散步等真实步行路段，不把公交、地铁、打车距离算进去。
- 费用会根据人数换算，同时会控制在用户预算以内。

### 智能修改行程

用户可以在“我的行程”页输入修改需求，例如：

```text
第二天如果下雨，帮我替换成室内景点。
第一天太贵了，改便宜一点。
把第 2 天改得轻松一点，减少步行。
```

系统会先生成可确认的调整建议，不会直接覆盖行程。用户点击应用后：

- 应用后的变更和预览建议保持一致。
- 右侧建议有几条，应用后就显示几项变更。
- 被修改的行程卡片会标记“已调整”。
- 预算、步行距离、地图资源和历史记录会同步刷新。
- 调整过程不会再混入旅行问答消息流。

### 预算概览

- 预算页严格从当前行程卡片费用汇总，不单独编造预算。
- 支持按人数换算费用，例如 2 人出行时，门票、餐饮等按人数倍计算。
- 如果总费用超过用户预算，会按比例压缩到预算以内。
- 分类展示酒店、门票、餐饮、交通等费用。
- 每日行程费用、右侧摘要费用和预算页总额使用同一套数据来源。

### 路线地图

- 展示当天行程地点、地图 Marker 和路线。
- 支持高德地图 JS API 渲染真实地图。
- 支持高德 Web Service 获取 POI、坐标校验、逆地理编码和路线规划。
- 地图按当前选中的行程天数筛选，只展示当天地点和路线。
- 为演示效果隐藏了高德默认提示、版权浮层和默认工具控件，只保留项目自己的地图标记、路线和信息面板。

### AI 导游

地图页面支持“基本信息”和“AI 导游”两种模式。在 AI 导游模式中：

- 用户可以点击地图上的地点或路线。
- 系统会生成导游式介绍。
- 用户可以继续追问，例如“这里适合拍照吗？”“附近有什么吃的？”“适合停留多久？”
- 支持流式文本输出。
- 支持生成语音讲解并播放。
- 播放控件已做演示优化，播放图标和语音气泡保持稳定居中。

### 旅行问答

- 提供类似 ChatGPT 的旅行问答界面。
- 支持旅游知识问答、行程细节追问和资料来源提示。
- 支持流式输出和语音提问。
- 规划消息、智能修改消息和工作流状态不会混入问答历史。
- 本地历史恢复时会过滤旧的规划类气泡，保证问答区只保留真实问答。

### 语音输入

- 支持浏览器录音。
- 支持规划页、问答页和 AI 导游中的语音输入。
- 前端使用 MediaRecorder 采集音频。
- 后端使用 ffmpeg 转码。
- 可接入百度智能云短语音识别。
- 识别后的文本会进入对应场景：智能规划、旅行问答或 AI 导游。

### 资料库与 RAG

- 支持上传 PDF、DOCX、TXT、Markdown 等旅游资料。
- 上传后的资料可写入知识库，用于问答和推荐理由增强。
- 项目中包含 `LangChain_RAG/` 模块，提供文档处理、向量检索、图谱检索和 RAG 管线的扩展基础。

### 历史记录与持久化

- 前端使用 LocalStorage 保存当前行程、旅行历史、问答记录、资料库状态和登录状态。
- 刷新页面后可以恢复当前演示进度。
- 历史记录会保存完整行程快照，点击历史项可以恢复对应方案。

## 系统架构

```text
用户输入
  ↓
Vue 前端
  ↓
成员一：Coordinator Agent / Intent Agent / Requirement Adapter
  ↓
成员二：旅游资源推荐 / 地图资源 / 高德路线
  ↓
成员三：行程生成 / 预算校验 / 约束校验 / 智能调整 / 版本管理
  ↓
成员一：整理最终响应和页面状态
  ↓
Vue 前端展示行程、预算、地图、问答和导游
```

## 成员分工

| 成员   | 负责模块                     | 主要职责                                                                                                                                                     |
| ------ | ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 成员一 | 前端整合、对话入口、协调总控 | Vue 主界面、智能规划入口、旅行问答、语音输入、流式输出、AI 导游交互、登录注册、前端持久化、API 封装、Intent Agent、Coordinator Agent、需求抽取和工作流编排。 |
| 成员二 | 推荐、地图、路线             | 天津景点、酒店、餐厅等资源推荐；高德 POI、坐标校验、逆地理编码、路线规划、地图资源结构、路线缓存和地图展示数据接口。                                         |
| 成员三 | 行程、预算、校验、调整       | 行程生成、预算核算、步行上限校验、开放时间校验、路线时间校验、饮食禁忌校验、软偏好评价、行程修改、版本管理和差异对比。                                       |

## 技术栈

### 前端

- Vue 3
- Vite
- Pinia
- JavaScript / TypeScript
- 高德地图 JS API
- MediaRecorder 浏览器录音
- LocalStorage 持久化

### 后端

- Python 3.11+
- FastAPI
- Uvicorn
- Pydantic v2
- LangChain Core
- LangChain OpenAI
- ChromaDB
- Neo4j
- PyMuPDF
- python-docx
- python-dotenv
- python-multipart
- aiosqlite / aiomysql

### 外部服务

- DeepSeek API：大模型对话、意图识别、需求抽取、规划和导游。
- 高德地图 Web Service API：POI、地理编码、逆地理编码和路线规划。
- 高德地图 JS API：前端真实地图渲染。
- 百度智能云短语音识别：语音输入识别。
- ffmpeg：音频格式转换。
- Neo4j：可选，用于知识关系和地点关系扩展。

## 目录结构

```text
VoyageMind-Agents/
├─ backend/
│  ├─ main.py                              # FastAPI 入口
│  ├─ requirements.txt                     # 后端依赖
│  ├─ agents/
│  │  ├─ coordinator_agent.py              # 协调总控 Agent
│  │  ├─ intent_agent.py                   # 意图识别 Agent
│  │  ├─ planning_agent.py                 # 行程规划 Agent
│  │  ├─ adjustment_agent.py               # 行程调整 Agent
│  │  └─ planning_state.py                 # 规划状态
│  ├─ api/
│  │  ├─ chat_api.py                       # 对话、规划进度、资料库接口
│  │  ├─ itinerary_api.py                  # 行程生成、预算、校验接口
│  │  ├─ adjustment_api.py                 # 行程调整接口
│  │  ├─ voice_api.py                      # 语音识别和讲解接口
│  │  └─ version_api.py                    # 版本和差异接口
│  ├─ app/                                 # 成员二推荐、地图、路线模块
│  │  ├─ agents/
│  │  │  ├─ recommendation_agent.py         # 推荐主 Agent
│  │  │  └─ recommendation_policy_agent.py  # 推荐策略 Agent
│  │  ├─ api/
│  │  │  ├─ recommendation_api.py           # 地点推荐接口
│  │  │  ├─ poi_api.py                      # POI 接口
│  │  │  └─ routes_api.py                   # 路线接口
│  │  ├─ clients/
│  │  │  ├─ amap_client.py                  # 高德客户端
│  │  │  └─ rag_client.py                   # RAG 客户端
│  │  ├─ services/
│  │  │  ├─ route_service.py                # 路线规划服务
│  │  │  ├─ map_data_service.py             # 地图数据服务
│  │  │  ├─ poi_service.py                  # POI 服务
│  │  │  └─ recommendation_guard.py         # 推荐结果过滤与兜底
│  │  ├─ tools/                            # 景点、酒店、餐厅、路线等工具
│  │  └─ schemas/                          # 推荐、地点、路线数据模型
│  ├─ clients/
│  │  ├─ deepseek_llm.py                   # DeepSeek 调用封装
│  │  └─ recommendation_agent_client.py    # 推荐 Agent 客户端
│  ├─ prompts/
│  │  ├─ itinerary_planning_prompt.py      # 行程规划提示词
│  │  ├─ local_replan_prompt.py            # 局部重规划提示词
│  │  └─ hard_constraint_repair_prompt.py  # 硬约束修复提示词
│  ├─ schemas/
│  │  ├─ itinerary.py                      # 行程模型
│  │  ├─ budget.py                         # 预算模型
│  │  ├─ modification.py                   # 修改请求模型
│  │  └─ version.py                        # 版本模型
│  ├─ services/
│  │  ├─ chatbot_service.py                # 问答组织
│  │  ├─ itinerary_planner.py              # 规则兜底行程生成
│  │  ├─ budget_service.py                 # 预算计算
│  │  ├─ local_replan_service.py           # 局部重规划合并
│  │  ├─ guide_service.py                  # AI 导游文本
│  │  ├─ rag_service.py                    # RAG 查询
│  │  ├─ tts_service.py                    # 语音合成
│  │  └─ version_service.py                # 行程版本存储
│  ├─ validators/
│  │  ├─ explicit_budget_validator.py      # 预算约束
│  │  ├─ explicit_walking_validator.py     # 步行约束
│  │  ├─ route_time_validator.py           # 路线时间校验
│  │  └─ itinerary_validator.py            # 行程结构校验
│  ├─ workflow/
│  │  └─ travel_workflow.py                # 旅行工作流编排
│  └─ vendor/langchain_chat/               # 聊天引擎封装
├─ src/
│  ├─ App.vue                              # 主前端页面
│  ├─ main.js                              # Vue 入口
│  ├─ api.js                               # 通用 API 封装
│  ├─ styles.css                           # 全局样式
│  ├─ api/
│  │  ├─ itineraryApi.ts                   # 行程接口封装
│  │  ├─ adjustmentApi.ts                  # 调整接口封装
│  │  └─ versionApi.ts                     # 版本接口封装
│  ├─ components/
│  │  ├─ TripMap.vue                       # 路线地图与 AI 导游
│  │  ├─ TripTimeline.vue                  # 行程时间线
│  │  ├─ BudgetPanel.vue                   # 预算面板
│  │  ├─ AdjustmentPanel.vue               # 调整面板
│  │  └─ PlaceCard.vue                     # 地点卡片
│  ├─ stores/
│  │  ├─ itineraryStore.ts                 # 行程状态
│  │  └─ mapStore.js                       # 地图状态
│  └─ utils/
│     └─ amapLoader.js                     # 高德 JS API 加载
├─ LangChain_RAG/
│  ├─ app.py                               # RAG 独立服务入口
│  ├─ rag/
│  │  ├─ rag_pipeline.py                   # RAG 主流程
│  │  ├─ retriever.py                      # 检索器
│  │  └─ document_processor.py             # 文档处理
│  ├─ neo4j_chroma/                        # Neo4j + Chroma 混合检索
│  ├─ api/                                 # RAG 接口
│  └─ tests/                               # RAG 测试
├─ data/
│  ├─ places.json                          # 天津景点数据
│  ├─ hotels.json                          # 天津酒店数据
│  └─ restaurants.json                     # 天津餐厅数据
├─ pictures/                              # 景点、酒店、餐厅图片
├─ mock/                                  # 示例行程、预算、差异等 Mock 数据
├─ tests/
│  ├─ test_recommendation_api.py           # 推荐接口测试
│  ├─ test_route_service.py                # 路线服务测试
│  ├─ test_map_data_service.py             # 地图数据测试
│  └─ ...                                  # 其他推荐、POI、RAG、集成测试
├─ index.html
├─ package.json
├─ vite.config.js
├─ .env.example
└─ README.md
```

## 环境准备

### 必装环境

- Git
- Python 3.11 或更高版本
- Node.js 18 或更高版本
- npm
- ffmpeg，语音输入必须单独安装

检查命令：

```bash
git --version
python --version
node --version
npm --version
ffmpeg -version
```

### 单独安装 ffmpeg

语音输入需要后端把浏览器录音转换成语音识别接口可接受的格式，所以必须单独安装 ffmpeg。只安装 Python 和 Node.js 不会自动带上 ffmpeg。

Windows 推荐方式：

```powershell
winget install Gyan.FFmpeg
```

安装完成后关闭当前终端，重新打开终端，检查：

```powershell
ffmpeg -version
```

macOS 推荐方式：

```bash
brew install ffmpeg
ffmpeg -version
```

Ubuntu / Debian 推荐方式：

```bash
sudo apt update
sudo apt install ffmpeg
ffmpeg -version
```

如果安装后 `ffmpeg -version` 仍然无法识别，需要把 ffmpeg 的可执行文件目录加入系统 PATH，或者在 `.env` 中配置 `FFMPEG_BINARY`。

### 可选环境

- Neo4j Desktop 或 Neo4j Server：用于图数据库和知识关系扩展。
- MySQL：项目依赖中预留了 `aiomysql`，后续可以接入真实数据库。

## 环境变量

复制 `.env.example` 为 `.env`：

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

macOS / Linux：

```bash
cp .env.example .env
```

然后根据需要填写：

```env
# 大模型
DEEPSEEK_API_KEY=your_deepseek_api_key
DEFAULT_MODEL=deepseek-v4-flash

# 高德 Web Service，后端使用
AMAP_WEB_SERVICE_KEY=your_amap_web_service_key

# 高德 JS API，前端使用
VITE_AMAP_JS_KEY=your_amap_js_key
VITE_AMAP_SECURITY_CODE=your_amap_security_code

# 语音识别
ASR_PROVIDER=baidu
BAIDU_APP_ID=your_baidu_app_id
BAIDU_ASR_API_KEY=your_baidu_asr_api_key
BAIDU_ASR_SECRET_KEY=your_baidu_asr_secret_key
BAIDU_ASR_DEV_PID=1537

# ffmpeg；如果 ffmpeg 已加入 PATH 可以不填
FFMPEG_BINARY=

# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_neo4j_password
NEO4J_DATABASE=neo4j
```

注意：

- `.env` 中包含密钥，不要提交到 Git。
- 修改后端环境变量后，需要重启后端。
- 修改 `VITE_` 开头的前端环境变量后，需要重启前端。

## 安装依赖

以下命令都在项目根目录执行，也就是包含 `package.json`、`vite.config.js`、`backend/` 和 `src/` 的目录。

### 1. 克隆项目

```bash
git clone https://github.com/PG-yuyu/VoyageMind-Agents.git
cd VoyageMind-Agents
```

如果已经下载或解压项目，只需要进入项目根目录：

```bash
cd VoyageMind-Agents
```

### 2. 安装后端依赖

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend\requirements.txt
```

macOS / Linux：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

如果 PowerShell 阻止激活虚拟环境，可以临时允许当前用户执行脚本：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### 3. 安装前端依赖

```bash
npm install
```

## 启动项目

开发时需要同时启动后端和前端，建议打开两个终端。

### 终端一：启动后端

Windows PowerShell：

```powershell
cd VoyageMind-Agents
.\.venv\Scripts\Activate.ps1
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8010
```

macOS / Linux：

```bash
cd VoyageMind-Agents
source .venv/bin/activate
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8010
```

后端启动成功后可以访问：

```text
http://127.0.0.1:8010/docs
```

### 终端二：启动前端

```bash
cd VoyageMind-Agents
npm run dev
```

前端默认地址：

```text
http://127.0.0.1:5174
```

如果端口被占用，以终端实际输出为准。

## 构建与预览

### 前端生产构建

```bash
npm run build
```

构建产物会生成到：

```text
dist/
```

### 本地预览生产构建

```bash
npm run preview
```

默认预览地址：

```text
http://127.0.0.1:4174
```

### 后端基础检查

```bash
python -m py_compile backend/main.py backend/agents/coordinator_agent.py backend/api/voice_api.py
```

### 运行测试

```bash
pytest
```

如果只想运行推荐或地图相关测试，可以指定测试文件，例如：

```bash
pytest tests/test_recommendation_api.py
pytest tests/test_route_service.py
```

## 主要接口

### 通用与成员一接口

| 方法 | 路径                             | 用途               |
| ---- | -------------------------------- | ------------------ |
| GET  | `/api/v1/health`                 | 健康检查           |
| POST | `/api/v1/auth/login`             | 登录               |
| POST | `/api/v1/auth/register`          | 注册               |
| POST | `/api/v1/sessions`               | 创建会话           |
| POST | `/api/v1/chat/messages`          | 普通聊天与规划入口 |
| POST | `/api/v1/chat/messages/progress` | 规划进度流         |
| POST | `/api/v1/chat/messages/stream`   | 旅行问答流式输出   |
| POST | `/api/v1/voice/understand`       | 语音识别与场景理解 |
| POST | `/api/v1/guide/chat/stream`      | AI 导游流式问答    |

### 成员二推荐与地图接口

| 方法 | 路径                                         | 用途                     |
| ---- | -------------------------------------------- | ------------------------ |
| POST | `/api/v1/recommendations/attractions`        | 景点推荐                 |
| POST | `/api/v1/member2/map/resources/by-place-ids` | 根据地点 ID 获取地图资源 |
| POST | `/api/v1/member2/routes/plan`                | 单段路线规划             |
| POST | `/api/v1/member2/routes/batch-plan`          | 批量路线规划             |

### 成员三行程接口

| 方法 | 路径                                     | 用途                     |
| ---- | ---------------------------------------- | ------------------------ |
| POST | `/api/v1/itineraries/generate`           | 生成行程                 |
| POST | `/api/v1/itineraries/save-demo`          | 保存前端当前行程到版本库 |
| POST | `/api/v1/itineraries/adjustment-preview` | 生成调整建议预览         |
| POST | `/api/v1/itineraries/modify`             | 应用行程修改             |
| POST | `/api/v1/itineraries/validate`           | 校验行程                 |
| POST | `/api/v1/itineraries/calculate-budget`   | 计算预算                 |
| GET  | `/api/v1/itineraries/{id}`               | 获取行程                 |
| GET  | `/api/v1/itineraries/{id}/versions`      | 获取版本列表             |
| GET  | `/api/v1/itineraries/{id}/diff`          | 对比版本差异             |

### RAG 与资料库接口

| 方法   | 路径                                  | 用途           |
| ------ | ------------------------------------- | -------------- |
| GET    | `/api/v1/rag/documents`               | 获取知识库文档 |
| POST   | `/api/v1/rag/documents/upload`        | 上传并解析文档 |
| DELETE | `/api/v1/rag/documents/{document_id}` | 删除知识库文档 |

## 数据与费用规则

- 预算页只汇总行程卡片中的费用。
- `cost_per_person` 表示人均费用。
- `total_cost` / `cost` 表示当前人数下的总费用。
- 前端会根据 `requirements.people` 进行人数倍换算。
- 如果总费用超过 `requirements.total_budget`，会按比例压缩到预算以内。
- 步行距离优先使用后端 `walking_distance_m`，其次从路线文案中解析步行、游览、散步等步行路段。
- 公交、地铁、打车等交通距离不计入步行距离。

## 常见问题

### 前端启动后接口请求失败

先确认后端是否启动：

```text
http://127.0.0.1:8010/docs
```

如果无法打开，重新启动后端。

### 前端没有显示真实地图

检查 `.env` 中的前端高德配置：

```env
VITE_AMAP_JS_KEY=...
VITE_AMAP_SECURITY_CODE=...
```

修改后重启前端。

### 高德路线、坐标或 POI 失败

检查 `.env` 中的后端高德配置：

```env
AMAP_WEB_SERVICE_KEY=...
```

修改后重启后端。

### 大模型调用失败

检查：

```env
DEEPSEEK_API_KEY=...
DEFAULT_MODEL=deepseek-v4-flash
```

如果没有配置大模型，部分功能会降级或返回错误提示。

### 语音识别失败

检查：

```env
ASR_PROVIDER=baidu
BAIDU_APP_ID=...
BAIDU_ASR_API_KEY=...
BAIDU_ASR_SECRET_KEY=...
```

同时确认 ffmpeg 可用：

```bash
ffmpeg -version
```

### PowerShell 无法激活虚拟环境

执行：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

然后重新打开 PowerShell 或重新执行激活命令。

### `npm run build` 出现 `spawn EPERM`

这是 Windows 本地权限或安全软件拦截 esbuild 子进程的常见问题。可以尝试：

- 关闭占用项目目录的杀毒扫描或安全拦截。
- 使用管理员权限终端重新执行。
- 删除 `node_modules` 后重新 `npm install`。

不要把这个问题误判为 Vue 代码语法错误，需结合完整日志判断。
