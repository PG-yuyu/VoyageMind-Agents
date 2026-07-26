# GraphRAG 智能文档检索问答系统

基于 **GraphRAG + Agentic RAG** 的文档检索与问答系统，前端使用 **Vue 3 + Vite**，后端使用 **FastAPI**，数据库使用 **Chroma + Neo4j**。系统支持多文档上传、用户登录、会话历史、语义检索、知识图谱检索、来源追溯和流式问答。

## 功能特性

### 文档处理
- **多格式支持** — 上传 PDF、DOCX、TXT、MD 格式文档
- **智能切块** — 段落边界感知的固定大小切块 + 重叠策略，保留语义完整性
- **父子块拆分** — 父块（~500 字符）提供完整上下文，子块（~150 字符）用于精细检索
- **元数据保留** — 自动提取页码、文档标题、文件名等来源信息

### 语义检索
- **双集合向量存储** — Chroma 中维护 parent_documents 和 child_documents 两个集合
- **子块高精度召回** — 在子块集合中搜索最相关片段
- **父块上下文回溯** — 通过 parent_id 从父块集合取回完整上下文
- **文档范围过滤** — 支持指定在特定文档范围内检索
- **多文档覆盖** — 多文件检索时按文档分别召回候选片段，并在重排后保留文档多样性，避免单个文件占满上下文

### 知识图谱
- **实体关系抽取** — 自动从文档中识别实体并抽取关系（通过 LLM）
- **Neo4j 图存储** — 实体作为节点、关系作为边持久化
- **实体关系查询** — 支持按实体名称检索关联节点和路径
- **子图展示** — 返回以目标实体为中心的多跳子图

### 问答
- **三种意图路由**：
  - `normal_chat` — 普通对话、问候，直接 LLM 回复
  - `document_search` — 基于文档内容的问答，走完整 RAG 流水线
  - `graph_query` — 实体关系查询，融合图检索结果
- **问题改写** — 基于会话历史的上下文感知改写
- **候选重排** — 语义分数 + 关键词 Jaccard 相似度混合重排，并保留多文档覆盖
- **引用标注** — 答案中使用段落级来源标记，前端渲染为短文件名标签，并提供可展开的来源片段
- **流式输出** — SSE 流式返回生成内容，前端实时渲染

### 前端交互
- **登录 / 注册** — 前端提供独立登录注册页，密码长度不少于 6 位
- **按用户知识库** — 登录后展示当前用户名、知识库、数据库与运行状态
- **文件侧边栏** — 左侧统一管理上传文件，可勾选“所有文件”或单个文件作为本次 RAG 范围
- **对话历史** — 支持新建对话、切换历史对话、删除会话；会话名默认取第一次提问前 20 个字符
- **流式 Markdown 渲染** — 回答实时输出并渲染标题、列表、加粗、代码和来源标签

### 系统集成
- **自动降级** — 无 Neo4j/Chroma 时自动使用 Mock 内存仓库，功能完全可用
- **统一接口层** — 三人各自开发的模块通过 contracts 协议解耦
- **幂等写入** — 重复上传同一文档自动覆盖，不留孤儿数据
- **完整清理** — 删除文档时同时清理 Neo4j 节点 + Chroma 向量 + 实体图
- **环境变量加载** — 后端自动读取项目根目录 `.env`，并兼容 UTF-8 BOM 文件头

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + Vite |
| 后端 | FastAPI + Pydantic + Uvicorn |
| 结构化存储 | Neo4j（文档块拓扑关系 + 实体图） |
| 向量存储 | Chroma（父子文档块双集合语义检索） |
| LLM 调用 | OpenAI 兼容 API（DeepSeek Chat） |
| Embedding | 确定性 Hash Embedding（无需下载模型） |

## 项目结构

```text
project/
├── app.py                      # FastAPI 主入口
├── pyproject.toml              # uv / Python 项目依赖声明
├── requirements.txt            # pip 依赖清单
├── uv.lock                     # uv 锁文件
├── .env.example                # 环境变量示例
├── contracts/                  # 共享接口层（三人共同维护）
│   ├── models.py               # 数据模型（Pydantic）
│   ├── backend_service.py      # 前端调用的统一业务接口
│   ├── graph_repository.py     # RAG 调用的图数据库抽象接口
│   └── errors.py               # 统一错误结构和错误码
│
├── neo4j_chroma/               # 成员2：Neo4j + Chroma 数据库模块
│   ├── neo4j_client.py         # Neo4j 驱动封装
│   ├── chroma_client.py        # Chroma 客户端封装
│   ├── database_repository.py  # 文档/块结构化存储（Cypher）
│   ├── vector_store.py         # 父子文档块向量存储
│   ├── hybrid_retriever.py     # 子块召回 → 父块回溯检索闭环
│   ├── graph_repository_adapter.py  # GraphRepository 协议适配器
│   ├── cypher_queries.py       # Cypher 语句集
│   ├── embedding.py            # Hash Embedding 实现
│   └── config.py               # 数据库配置
│
├── rag/                        # 成员3：RAG / Agent 模块
│   ├── backend_service_impl.py # BackendService 实现（含自动降级）
│   ├── rag_pipeline.py         # RAG 主流程编排
│   ├── document_processor.py   # 文档解析与切块
│   ├── document_loader.py      # PDF/DOCX/TXT 文件读取
│   ├── entity_extractor.py     # LLM 实体关系抽取
│   ├── intent_router.py        # 意图识别（规则 + LLM）
│   ├── query_rewriter.py       # 基于会话历史的问题改写
│   ├── retriever.py            # 检索编排
│   ├── reranker.py             # 关键词重排
│   ├── prompt_builder.py       # Prompt 模板管理
│   ├── llm_client.py           # LLM API 调用（含重试和流式）
│   └── session_store.py        # 会话历史内存存储
│
├── api/                        # FastAPI 路由层
│   ├── routes.py               # REST 端点定义
│   ├── dependencies.py         # 依赖注入
│   └── schemas.py              # API 请求/响应模型
│
├── backend/                    # 兼容旧入口与轻量后端封装
│   ├── main.py                 # 旧版 FastAPI 入口
│   ├── models.py               # 旧版请求/响应模型
│   ├── services.py             # 旧版服务封装
│   └── requirements.txt        # 后端依赖清单
│
├── graphdb/                    # 模拟层
│   └── mock_graph_repository.py # 内存 Mock 仓库
│
├── frontend/                   # 成员1：Vue 前端
│   ├── package.json            # 前端依赖与脚本
│   ├── package-lock.json       # npm 锁文件
│   ├── index.html              # Vite HTML 入口
│   ├── vite.config.js          # Vite 配置（含代理）
│   ├── src/
│   │   ├── App.vue             # 主页面
│   │   ├── main.js             # Vue 挂载入口
│   │   ├── api.js              # 后端 API 调用
│   │   └── styles.css          # 样式
│
├── scripts/
│   ├── init_neo4j.py           # Neo4j schema 初始化
│   ├── clear_neo4j.py          # Neo4j 数据清理
│   └── clear_chroma.py         # Chroma 数据清理
│
├── tests/
│   ├── test_rag_pipeline.py    # RAG 流程集成测试
│   ├── test_document_processor.py
│   ├── test_entity_extractor.py
│   ├── test_neo4j_client.py
│   ├── test_chroma_client.py
│   ├── test_database_repository.py
│   ├── test_vector_store.py
│   ├── test_hybrid_retriever.py
│   └── test_neo4j_chroma_integration.py  # 真实闭环冒烟测试
│
└── docs/
    ├── 分工.md                 # 成员分工详细说明
    ├── 接口设计.md             # 接口合同与数据规范
    └── neo4j_chroma.md         # Neo4j + Chroma 模块设计
```

## 三人分工

| 成员 | 核心角色 | 负责模块 | 工作量 |
|---|---|---|---|
| **成员1** | Gradio/Vue 前端 + 系统集成 | `frontend/`、`app.py`、集成测试 | 30% |
| **成员2** | Neo4j + Chroma 数据库 | `neo4j_chroma/`、`scripts/`、数据库测试 | 35% |
| **成员3** | RAG / Agent / 大模型 | `rag/`、实体抽取、意图识别、Prompt | 35% |

### 依赖关系

```text
前端（成员1）                   只调用 BackendService 接口
    │
    ▼
RAG/Agent（成员3）             实现 BackendService，只调用 GraphRepository 接口
    │
    ▼
Neo4j + Chroma（成员2）       实现 GraphRepository，封装 Cypher/向量操作
```

**关键原则：**
- 成员1 只认识 `BackendService`，不导入任何内部模块
- 成员3 只认识 `GraphRepository`，不直接操作数据库
- 成员2 只认识 `DocumentGraphPayload` 和 `RetrievalResult`，不调用 LLM

## 快速启动

### 1. 环境配置

```bash
cd project/
cp .env.example .env
```

编辑 `.env`，至少填入 `LLM_API_KEY`（DeepSeek / OpenAI 兼容 API 密钥），其余保持默认。

### 2. 安装依赖

```bash
# 后端依赖（推荐 uv）
uv sync

# 或使用 pip
pip install -r requirements.txt

# 前端依赖
cd frontend && npm install && cd ..
```

> **提示**：当前完整模式需要 `neo4j` 和 `chromadb`。若数据库不可用，后端会自动降级为 Mock 模式，便于前端和接口联调。

### 3. 启动后端

```bash
uv run uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

API 文档：http://localhost:8000/docs

### 4. 启动前端

```bash
cd frontend
npm run dev
```

打开 http://localhost:5173

## 完整模式（Neo4j + Chroma）

### 前置条件

- Docker（推荐）或本地安装的 Neo4j 5.x 数据库
- Python ≥ 3.11
- 已安装所有依赖：`uv sync` 或 `pip install -r requirements.txt`

### 1. 启动 Neo4j 数据库

**方式 A：Docker（推荐）**

```bash
# 拉取并启动 Neo4j 5 社区版
首次完整命令：docker run -d --name neo4j-rag -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/password -e 'NEO4J_PLUGINS=["apoc"]' -v neo4j-data:/data neo4j:5-community
拆分解释：
docker run -d \
  --name neo4j \
  -p 7474:7474 \    # HTTP 管理界面
  -p 7687:7687 \    # Bolt 协议端口
  -e NEO4J_AUTH=neo4j/password \
  -e NEO4J_PLUGINS='["apoc"]' \  # 可选：安装 APOC 插件
  neo4j:5-community

  以后再次运行：docker start neo4j-rag
```

> **参数说明：**
> - `7474` — Neo4j 浏览器管理界面（http://localhost:7474）
> - `7687` — Bolt 协议端口，Python 驱动通过此端口连接
> - `NEO4J_AUTH=neo4j/password` — 用户名 `neo4j`，密码 `password`
> - `NEO4J_PLUGINS` — 可选，自动安装 APOC 等插件

**方式 B：Windows 本地安装**

1. 下载 Neo4j 5 Community：[https://neo4j.com/download/](https://neo4j.com/download/)
2. 解压到本地目录
3. 以管理员身份运行 PowerShell，进入 Neo4j 目录的 `bin/` 子目录
4. 执行 `.\neo4j.bat console`
5. 默认用户名密码均为 `neo4j`，首次访问会要求修改密码

**验证 Neo4j 是否启动成功：**

```bash
# 方法一：命令行检测
python -c "from neo4j import GraphDatabase; driver=GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j','password')); driver.verify_connectivity(); print('Neo4j OK'); driver.close()"

# 方法二：浏览器打开管理界面
# http://localhost:7474
# 使用 neo4j/password 登录
```

### 2. 初始化 Neo4j Schema

创建数据库的索引和唯一约束（只需执行一次）：

```bash
uv run python scripts/init_neo4j.py
```

若成功会输出 `Schema initialized successfully`。此脚本会创建以下约束和索引：

| 类型 | 名称 | 说明 |
|---|---|---|
| 唯一约束 | `document_id_unique` | Document 节点 ID 唯一 |
| 唯一约束 | `parent_id_unique` | ParentChunk 节点 ID 唯一 |
| 唯一约束 | `child_id_unique` | ChildChunk 节点 ID 唯一 |
| 索引 | `document_filename_index` | 文档文件名检索 |
| 索引 | `parent_document_id_index` | 父块按文档 ID 检索 |
| 索引 | `child_document_id_index` | 子块按文档 ID 检索 |
| 索引 | `child_parent_id_index` | 子块按父块 ID 检索 |

### 3. 配置环境变量

确保 `.env` 中 Neo4j/Chroma 配置正确：

```env
# --- Neo4j 结构化存储 ---
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password
NEO4J_DATABASE=neo4j

# --- Chroma 向量存储 ---
CHROMA_PERSIST_DIRECTORY=.chroma
CHROMA_PARENT_COLLECTION=parent_documents
CHROMA_CHILD_COLLECTION=child_documents

# --- Embedding ---
EMBEDDING_PROVIDER=hash
EMBEDDING_DIMENSION=384
```

> **Chroma 说明**：无需额外安装服务端。Chroma 以嵌入式模式运行，数据持久化在 `.chroma/` 目录中，启动后端时会自动创建。

### 4. 启动后端

```bash
uv run uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

启动日志中会显示：

```
INFO - Using Neo4j+Chroma GraphRepository (real backend).
```

若连接失败则自动降级：

```
WARNING - Neo4j/Chroma health check failed, falling back to MockGraphRepository.
```

### 5. 验证完整集成

运行真实集成测试，覆盖写入 → 检索 → 删除的全流程：

```bash
set NEO4J_CHROMA_RUN_INTEGRATION=1
uv run python -m unittest tests.test_neo4j_chroma_integration -v
```

测试内容：
- Neo4j / Chroma 健康检查
- 写入测试文档及其父子块
- 语义检索子块并回溯父块上下文
- 校验返回的 source 字段完整性
- 删除文档并确认数据已清理

### 6. 数据库管理

**查看当前存储的文档列表：**

```bash
uv run python -c "
from neo4j_chroma.database_repository import DatabaseRepository
repo = DatabaseRepository.from_env()
for doc in repo.list_documents():
    print(f'{doc.document_id}: {doc.filename} ({doc.chunk_count} chunks)')
repo.close()
"
```

**按文档 ID 查看块结构：**

```bash
uv run python -c "
from neo4j_chroma.database_repository import DatabaseRepository
repo = DatabaseRepository.from_env()
parents = repo.get_parent_chunks('doc_xxx')
children = repo.get_child_chunks('doc_xxx')
print(f'{len(parents)} parents, {len(children)} children')
for p in parents[:3]:
    print(f'  parent {p.parent_id}: chunk_index={p.chunk_index}')
for c in children[:3]:
    print(f'  child {c.child_id}: parent={c.parent_id}')
repo.close()
"
```

**清理所有数据：**

```bash
# 清理 Neo4j 所有文档/块/实体
uv run python scripts/clear_neo4j.py

# 重建 Chroma 父/子集合
uv run python scripts/clear_chroma.py

# 清理指定文档
uv run python scripts/clear_neo4j.py --document-id doc_001
uv run python scripts/clear_chroma.py --document-id doc_001
```

### 7. 数据库监控

Neo4j 浏览器管理界面：http://localhost:7474

在浏览器中可执行 Cypher 查询验证数据：

```cypher
// 查看所有文档
MATCH (d:Document) RETURN d.document_id, d.filename, d.chunk_count

// 查看实体及关系
MATCH (e:Entity)-[r:RELATED]->(t:Entity)
RETURN e.name, r.relation_type, t.name
LIMIT 20

// 查看文档块拓扑
MATCH path = (d:Document)-[:HAS_PARENT_CHUNK]->(:ParentChunk)-[:HAS_CHILD_CHUNK]->(:ChildChunk)
RETURN path LIMIT 10

// 查看向量总数
MATCH (p:ParentChunk) RETURN count(p) AS parent_chunks
MATCH (c:ChildChunk) RETURN count(c) AS child_chunks
```

### 8. 关闭与清理

```bash
# 停止后端：Ctrl+C

# 停止 Neo4j 容器
docker stop neo4j

# 重新启动 Neo4j 容器（数据保留）
docker start neo4j

# 彻底删除容器（数据丢失）
docker rm neo4j

# 如需清理 Chroma 持久化目录，请先停止后端，再手动删除项目根目录下的 .chroma 目录
```

## API 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/v1/health` | 系统健康检查 |
| `POST` | `/api/v1/documents/ingest` | 上传文档（PDF/DOCX/TXT） |
| `GET` | `/api/v1/documents` | 文档列表 |
| `DELETE` | `/api/v1/documents/{id}` | 删除文档 |
| `POST` | `/api/v1/query` | 问答接口 |
| `POST` | `/api/v1/query/stream` | 流式问答（SSE） |
| `DELETE` | `/api/v1/sessions/{id}` | 清除会话历史 |

### 问答接口请求体

```json
{
  "query": "问题",
  "session_id": "sess_001",
  "knowledge_base_id": "kb_demo",
  "selected_document_ids": [],
  "top_k": 10,
  "max_hops": 2,
  "enable_query_rewrite": true
}
```

### 问答接口响应

```json
{
  "answer": "最终答案（含引用标记）",
  "intent": "document_search",
  "original_query": "原始问题",
  "rewritten_query": "改写后的问题",
  "sources": [
    {
      "citation_index": 1,
      "document_id": "doc_xxx",
      "filename": "example.pdf",
      "chunk_id": "chunk_xxx",
      "page_number": 1,
      "content": "引用片段",
      "score": 0.92
    }
  ],
  "graph_nodes": [],
  "graph_edges": [],
  "graph_paths": [],
  "session_id": "sess_001",
  "trace_id": "trace_xxx"
}
```

### 流式问答事件

`POST /api/v1/query/stream` 使用 SSE 返回：

| 事件 | 说明 |
|---|---|
| `token` | LLM 生成的增量文本，前端实时追加并渲染 Markdown |
| `sources` | 本次回答实际引用到的来源片段 |
| `done` | 回答完成，包含意图、改写问题、图谱节点/边等元信息 |
| `error` | 生成失败时返回错误信息 |

前端会把回答中的 `{{source:编号}}` 渲染为短文件名标签；同一段最多显示一个标签，并统一放在段落末尾。

## RAG 流水线

### 文档上传

```text
上传文件 → 文档解析（PDF/DOCX/TXT）
         → 段落感知切块（固定大小 + 重叠）
         → 父块拆分为子块（150字符含重叠，精细检索）
         → LLM 实体关系抽取
         → Neo4j 写入文档/块拓扑 + 实体图
         → Chroma 写入父子向量
```

### 问答

```text
用户问题 → 意图识别（规则预检 → LLM 分类）
        ├─ normal_chat → 直接 LLM 回复
        ├─ document_search → 问题改写 → 子块语义检索
        │                    → 多文档分别召回，保证不同选中文档都有候选片段
        │                    → 父块回溯获取完整上下文
        │                    → 混合重排并保留文档多样性
        │                    → Prompt 组装 → LLM 流式回答
        │                    → 返回实际引用到的来源片段
        └─ graph_query   → 实体抽取 → Neo4j 实体图查询
                           → 子图路径检索 → 合并证据 → LLM 回答
```

### 来源追溯规则

- 后端为每个检索片段分配 `citation_index`，Prompt 中只暴露这些编号。
- LLM 只在能被某个片段直接支撑的段落末尾输出 `{{source:编号}}`。
- 前端将来源标记渲染为短文件名标签，文件名过长会自动省略。
- 来源面板只展示回答中实际引用到的片段，并按文件页码顺序排列。

## 存储设计

### Neo4j 图结构

```text
(:Document) -[:HAS_PARENT_CHUNK]-> (:ParentChunk)
(:ParentChunk) -[:HAS_CHILD_CHUNK]-> (:ChildChunk)
(:ParentChunk) -[:NEXT_TO]-> (:ParentChunk)
(:ChildChunk) -[:NEXT_TO]-> (:ChildChunk)
(:Entity) -[:RELATED {relation_type, source_chunk_id}]-> (:Entity)
```

### Chroma 集合

| 集合 | 用途 |
|---|---|
| `parent_documents` | 存储父块全文，用于上下文回溯 |
| `child_documents` | 存储子块，用于高精度语义召回 |

### 检索闭环

```
子块 Chroma 召回 → 获取 parent_id → 父块 Chroma 回溯
                                    → Neo4j 补充元数据
                                    → 实体图上下文合并
                                    → 拼接 context → LLM
```

## 测试

```bash
# 运行所有测试
uv run python -m unittest discover tests -p "test_*.py"

# 运行特定模块测试
uv run python -m unittest tests.test_document_processor
uv run python -m unittest tests.test_neo4j_client

# 运行真实集成测试（需 Neo4j + Chroma 运行中）
set NEO4J_CHROMA_RUN_INTEGRATION=1
uv run python -m unittest tests.test_neo4j_chroma_integration
```

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LLM_API_KEY` | — | LLM API 密钥（必填） |
| `LLM_BASE_URL` | `https://api.deepseek.com` | API 地址 |
| `LLM_MODEL` | `deepseek-chat` | 模型名 |
| `LLM_TEMPERATURE` | `0.3` | 生成温度 |
| `LLM_MAX_TOKENS` | `4096` | 最大生成 token 数 |
| `LLM_TIMEOUT` | `60` | LLM 请求超时时间（秒） |
| `RAG_CHUNK_SIZE` | 500 | 文档切块大小（字符） |
| `RAG_CHUNK_OVERLAP` | 50 | 切块重叠（字符） |
| `RAG_TOP_K` | 10 | 检索返回块数 |
| `RAG_RERANK_TOP_K` | 10 | 重排后送入 LLM 的片段数 |
| `RAG_DEFAULT_MAX_HOPS` | 2 | 图谱检索默认最大跳数 |
| `RAG_LOG_LEVEL` | `INFO` | 日志级别 |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j 地址 |
| `NEO4J_USERNAME` | `neo4j` | Neo4j 用户名 |
| `NEO4J_PASSWORD` | `password` | Neo4j 密码 |
| `NEO4J_DATABASE` | `neo4j` | Neo4j 数据库名 |
| `CHROMA_PERSIST_DIRECTORY` | `.chroma` | Chroma 持久化目录 |
| `CHROMA_PARENT_COLLECTION` | `parent_documents` | Chroma 父块集合名 |
| `CHROMA_CHILD_COLLECTION` | `child_documents` | Chroma 子块集合名 |
| `EMBEDDING_PROVIDER` | `hash` | Embedding 类型（当前仅 hash） |
| `EMBEDDING_DIMENSION` | `384` | Hash Embedding 维度 |
