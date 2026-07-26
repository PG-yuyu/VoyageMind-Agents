# 行知旅策 (VoyageMind) — 多智能体自由行规划系统

基于 **FastAPI + Vue 3 + 大语言模型** 的城市自由行智能规划系统，采用三智能体协作架构，支持天津（及北京）旅游资源的智能推荐、行程编排、预算核算与动态调整。

---

## 项目架构

### 三成员分工

| 成员 | 角色 | 核心职责 | 核心模块 |
|------|------|---------|---------|
| **成员一** | 对话入口与工作流编排 | 意图识别、需求提取、会话管理、协调总控、Chatbot/RAG 封装、前端框架集成 | `backend/agents/coordinator_agent.py` `intent_agent.py` `workflow/` `vendor/` |
| **成员二** | 旅游资源推荐与地图 | 景点/酒店/餐厅推荐、高德 POI 搜索、路线规划、地图可视化 | `backend/app/`（agents / api / services / tools / clients） |
| **成员三** | 行程规划与校验调整 | 行程编排、预算核算、硬约束校验、软偏好评价、版本管理、修改调整 | `backend/agents/planning_agent.py` `services/` `validators/` `schemas/` |

### 数据流

```
用户输入
   ↓
[成员一] 意图识别 → 需求提取
   ↓  TravelRequest
[成员二] 景点/酒店/餐厅推荐 → 路线规划
   ↓  Place[] + RouteResult[]
[成员三] 生成行程 → 硬约束校验 → 软偏好评价 → 输出
   ↓  Itinerary + Budget + Evaluation
[成员一] 组织回复 → 前端展示
```

三种意图流程：

| 意图 | 流程 |
|------|------|
| **新建行程** `create_trip` | 成员一 → 成员二 → 成员三 → 前端 |
| **修改行程** `modify_trip` | 成员一 → 成员三（必要时调成员二获取替代地点）→ 前端 |
| **旅游问答** `travel_qa` | 成员一 → RAGService → 前端 |

---

## 目录结构

```
Agent/
├── backend/                          # Python 后端（三人合并）
│   ├── agents/                       # Agent 层
│   │   ├── coordinator_agent.py      # [成员一] 协调总控
│   │   ├── intent_agent.py           # [成员一] 意图识别
│   │   ├── planning_agent.py         # [成员三] 行程规划主控
│   │   ├── adjustment_agent.py       # [成员三] 修改调整
│   │   ├── evaluation_agent.py       # [成员三] 双轨评价
│   │   └── itinerary_preference_critic.py  # [成员三] 软偏好评价
│   ├── api/                          # FastAPI 路由
│   │   ├── chat_api.py               # [成员一] 对话/会话 API
│   │   ├── auth_api.py               # [成员一] 认证 API
│   │   ├── itinerary_api.py          # [成员三] 行程 API
│   │   ├── validation_api.py         # [成员三] 校验 API
│   │   ├── adjustment_api.py         # [成员三] 调整 API
│   │   └── version_api.py            # [成员三] 版本 API
│   ├── app/                          # [成员二] 推荐/地图/路线
│   │   ├── agents/                   # 推荐 Agent
│   │   ├── api/                      # 地图/路线/推荐 API
│   │   ├── clients/                  # 高德地图 / RAG 客户端
│   │   ├── services/                 # 推荐/路线/地图服务
│   │   ├── tools/                    # 搜索/路线工具
│   │   ├── repositories/             # 数据访问层
│   │   ├── schemas/                  # 推荐相关模型
│   │   ├── prompts/                  # 推荐 LLM 提示词
│   │   └── validators/               # 推荐校验器
│   ├── services/                     # 业务服务层
│   │   ├── chatbot_service.py        # [成员一] Chatbot 封装
│   │   ├── session_store.py          # [成员一] 会话存储
│   │   ├── itinerary_planner.py      # [成员三] 行程编排
│   │   ├── budget_service.py         # [成员三] 预算核算
│   │   ├── version_service.py        # [成员三] 版本管理
│   │   ├── diff_service.py           # [成员三] 版本差异
│   │   ├── adjustment_service.py     # [成员三] 结构调整
│   │   └── local_replan_service.py   # [成员三] 局部重规划
│   ├── schemas/                      # 统一数据模型
│   │   ├── common.py                 # 通用枚举/约束模型
│   │   ├── itinerary.py              # 行程核心模型
│   │   ├── budget.py                 # 预算模型
│   │   ├── evaluation.py             # 校验评价模型
│   │   └── ... (9 个领域模型文件)
│   ├── validators/                   # [成员三] 校验器
│   │   ├── hard_constraint_validator.py  # 硬约束总调度
│   │   ├── opening_time_validator.py     # 开放时间校验
│   │   ├── route_time_validator.py       # 路线时间校验
│   │   ├── explicit_budget_validator.py  # 预算上限校验
│   │   ├── explicit_walking_validator.py # 步行距离校验
│   │   ├── food_safety_validator.py      # 饮食禁忌校验
│   │   └── factual_consistency_validator.py # 事实一致性校验
│   ├── prompts/                      # [成员三] LLM 提示模板
│   ├── clients/                      # [成员三] 外部客户端
│   ├── workflow/                     # [成员一] 旅行工作流
│   ├── vendor/                       # [成员一] Chatbot 核心
│   ├── main.py                       # FastAPI 应用入口
│   └── requirements.txt
├── src/                              # Vue 3 前端 SPA
│   ├── App.vue                       # 主应用（7 个页面）
│   ├── main.js                       # 入口
│   ├── api.js                        # [成员一] API 封装
│   ├── components/
│   │   ├── TripMap.vue               # [成员二] 高德地图
│   │   ├── PlaceCard.vue             # [成员二] 地点卡片
│   │   ├── TripTimeline.vue          # [成员三] 行程时间轴
│   │   ├── BudgetPanel.vue           # [成员三] 预算面板
│   │   ├── ValidationPanel.vue       # [成员三] 校验结果
│   │   ├── PreferenceEvaluationPanel.vue  # [成员三] 软偏好评价
│   │   ├── AdjustmentPanel.vue       # [成员三] 调整说明
│   │   ├── TripDiff.vue              # [成员三] 版本差异对比
│   │   └── ...
│   ├── api/                          # [成员三] TypeScript API
│   └── stores/                       # Pinia 状态管理
├── frontend/                         # [成员二] TS 前端（开发中）
├── data/                             # 种子数据（景点/酒店/餐厅）
├── tests/                            # 测试套件
├── mock/                             # [成员三] Mock 数据（9 文件）
├── docs/                             # 团队文档
├── demo_verify.py                    # 端到端验证脚本
├── demo_call_agent.py                # Agent 调用演示
├── package.json                      # 前端依赖
├── vite.config.js                    # Vite 配置
└── index.html                        # SPA 入口
```

---

## 功能特性

### 完整功能清单

| 功能 | 说明 | 归属 |
|------|------|------|
| 💬 **智能对话** | 自然语言输入，理解旅行需求 | 成员一 |
| 🎯 **意图识别** | 三类意图：新建/修改行程、旅游问答 | 成员一 |
| 📋 **需求提取** | 从对话中提取城市、天数、预算、兴趣等 | 成员一 |
| 🏛️ **景点推荐** | 基于兴趣和约束推荐景点 | 成员二 |
| 🏨 **酒店推荐** | 匹配预算和区域的住宿推荐 | 成员二 |
| 🍽️ **餐厅推荐** | 就近餐饮推荐，支持饮食禁忌 | 成员二 |
| 🗺️ **路线规划** | 高德地图路线计算（步行/公交/驾车） | 成员二 |
| 📍 **地图可视化** | 高德地图展示地点标记和路线 | 成员二 |
| 📅 **行程编排** | LLM 主导的每日行程组合 | 成员三 |
| 💰 **预算核算** | Python 确定性预算计算 | 成员三 |
| ✅ **硬约束校验** | 开放时间、路线时间、预算上限、步行距离等 7 项校验 | 成员三 |
| ⭐ **软偏好评价** | LLM 评价行程是否太累、是否同质化等 | 成员三 |
| 🔄 **修改调整** | 响应式替换景点/餐厅、调整顺序 | 成员三 |
| 📊 **版本管理** | 每次修改保存新版本，支持差异对比 | 成员三 |
| 📈 **量化指标** | 预算匹配率、兴趣覆盖率、必去覆盖率等 | 成员三 |
| 🧪 **端到端验证** | `demo_verify.py` 一键验证全部功能 | 成员三 |

### API 端点一览

#### 成员一接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 健康检查 |
| POST | `/api/v1/sessions` | 创建会话 |
| GET | `/api/v1/sessions/{id}` | 获取会话 |
| POST | `/api/v1/chat/messages` | 发送消息 |
| POST | `/api/v1/chat/messages/stream` | 流式消息 |
| POST | `/api/v1/intent/detect` | 意图识别 |
| POST | `/api/v1/requirements/extract` | 需求提取 |
| POST | `/api/v1/workflows/travel-plan` | 旅行工作流 |

#### 成员二接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/member2/map/resources/by-place-ids` | 地图资源 |
| POST | `/api/v1/member2/routes/plan` | 单路线规划 |
| POST | `/api/v1/member2/routes/batch-plan` | 批量路线规划 |

#### 成员三接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/itineraries/generate` | 生成行程 |
| GET | `/api/v1/itineraries/{id}` | 获取行程 |
| POST | `/api/v1/itineraries/validate` | 校验行程 |
| POST | `/api/v1/itineraries/calculate-budget` | 预算核算 |
| POST | `/api/v1/itineraries/modify` | 修改行程 |
| GET | `/api/v1/itineraries/{id}/versions` | 版本列表 |
| GET | `/api/v1/itineraries/{id}/diff` | 版本差异 |

---

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- 高德地图 API Key（地图功能）
- DeepSeek API Key（LLM 功能，可选）

### 1. 配置环境变量

```bash
# 复制模板
copy .env.example .env
```

编辑 `.env`：

```text
DEEPSEEK_API_KEY=sk-your-key-here
DEFAULT_MODEL=deepseek-v4-flash
AMAP_WEB_SERVICE_KEY=your-amap-key
VITE_AMAP_JS_KEY=your-amap-js-key
VITE_AMAP_SECURITY_CODE=your-security-code
```

> 不配置 DeepSeek Key 时，系统会自动使用规则兜底（Mock 模式），便于功能调试。

### 2. 启动后端

```bash
# 安装依赖
pip install -r backend/requirements.txt

# 启动 FastAPI 服务
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

### 3. 启动前端

```bash
# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

访问 `http://127.0.0.1:5174`。前端通过 Vite 代理将 `/api/v1` 转发到后端 `http://127.0.0.1:8000`。

### 4. 运行端到端验证

```bash
# CLI 模式（无需 API Key）
python demo_verify.py

# API 服务模式
python demo_verify.py --api

# 生成 HTML 报告
python demo_verify.py --html    # 或 demo_verify.py 运行后自动生成
```

### 5. Agent 调用演示

```bash
# Mock LLM 模式
python demo_call_agent.py

# 真实 LLM 模式（需配置 DeepSeek Key）
python demo_call_agent.py --llm

# FastAPI 模式
python demo_call_agent.py --api
```

---

## 数据规范

| 项目 | 约定 |
|------|------|
| 日期格式 | `YYYY-MM-DD` |
| 时间格式 | `HH:MM` |
| 距离单位 | 米 |
| 时长单位 | 分钟 |
| 金额单位 | 元 (CNY) |
| 坐标系 | GCJ-02 |
| 坐标顺序 | [经度, 纬度] |
| 地点主键 | `place_id` |
| 缺失值 | `null`（禁止使用 `""`、`"未知"`、`"N/A"`） |
| 枚举命名 | 英文小写下划线（如 `create_trip`） |

---

## 开发说明

### 成员职责边界

**成员一（对话/协调）：**
- 意图识别与需求提取
- 会话管理与状态维护
- 工作流编排与 Agent 轨迹记录
- Chatbot / RAG 接口封装
- 前端框架集成与页面布局

**成员二（推荐/地图）：**
- 景点/酒店/餐厅资源推荐
- 高德 POI 搜索与路线规划
- 地图可视化与地点展示
- 路线缓存服务

**成员三（行程/校验）：**
- 行程编排（LLM 主导 + 规则循环）
- 预算计算（Python 确定性规则）
- 硬约束校验（7 项规则检查）
- 软偏好评价（LLM 评价隐含偏好）
- 版本管理与差异对比
- 修改调整与局部重规划

### 技术栈

- **后端**: Python 3.11+, FastAPI, Pydantic v2, LangChain
- **前端**: Vue 3, Vite, Pinia, 高德地图 JS API
- **AI**: DeepSeek API (OpenAI 兼容接口)
- **地图**: 高德地图 Web Service API + JS API
- **数据**: JSON 种子数据（开发阶段） / Neo4j（目标生产）

---

## 演示效果

### 新建行程

```
用户： "我们两个人去天津玩两天，喜欢历史建筑，预算 2500"

→ 成员一识别意图 → 提取需求
→ 成员二推荐景点/酒店/餐厅 → 规划路线
→ 成员三生成行程 → 校验预算/步行/时间
→ 前端展示行程时间轴 + 预算面板 + 校验结果
```

### 修改行程

```
用户： "第二天太累了，换成室内景点"

→ 成员一识别修改意图
→ 成员三分析影响范围 → 调用成员二获取替代地点
→ 局部重规划 Day2 → 重新校验 → 保存版本 2
→ 前端展示调整说明 + 版本差异对比
```

---

## 种子数据

项目内置了天津和北京的景点、酒店、餐厅示例数据，位于 `data/` 目录：

| 文件 | 内容 |
|------|------|
| `places.json` | 7 个景点（天津五大道/天津之眼/古文化街/瓷房子等 + 北京故宫/天坛） |
| `hotels.json` | 4 家酒店（天津+北京各 2 家） |
| `restaurants.json` | 4 家餐厅（天津+北京各 2 家） |

---

## Team

- **成员一** — 对话/意图/工作流/前端集成
- **成员二** — 旅游资源推荐/地图/路线
- **成员三** — 行程规划/校验/调整/版本管理

---

> 项目基于三智能体协作架构设计，各成员模块通过明确定义的接口进行对接，实现解耦开发与集成运行。
