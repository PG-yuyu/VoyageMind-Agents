# Neo4j + Chroma 数据库与检索模块说明

## 需求依据

本轮开发只以 `E:\Desktop\实习实训\RAG Project\02-05_01-Rag Project.md` 为准，不采用 `docs/分工.md`、`docs/接口设计.md` 或此前 GraphDB / RDF / SPARQL 说明中的冲突内容。

代码包和正式文档分别命名为 `neo4j_chroma/` 与 `docs/neo4j_chroma.md`，避免和 Ontotext GraphDB、RDF 或 SPARQL 方向混淆。

## 设计取舍

原参考方案使用 MySQL + Chroma：MySQL 负责文档元数据、父子 chunk 结构和删除管理，Chroma 负责向量召回和父块上下文回溯。本轮用 Neo4j 替代 MySQL，是因为 Document -> ParentChunk -> ChildChunk 天然是图结构，后续还可以继续扩展 Entity / Relation / Concept，用同一结构化数据库支持知识图谱展示和关系检索。

本轮不使用 Ontotext GraphDB、RDF、SPARQL 或 Microsoft GraphRAG 框架。

## 模块职责

Neo4j 负责：

- 保存 `Document` 文档元数据。
- 保存 `ParentChunk` 父块和 `ChildChunk` 子块。
- 保存 `(:Document)-[:HAS_PARENT_CHUNK]->(:ParentChunk)` 与 `(:ParentChunk)-[:HAS_CHILD_CHUNK]->(:ChildChunk)`。
- 保存 `NEXT_TO` 顺序关系。
- 保存 `document_id`、`parent_id`、`child_id`、`vector_id` 等索引字段。
- 支持文档列表、按 `document_id` 查询 chunk、按 `document_id` 删除文档及关联 chunk。

Chroma 负责：

- 创建并维护 `parent_documents` collection。
- 创建并维护 `child_documents` collection。
- 父块和子块向量写入。
- 使用 `child_documents` 进行高精度语义召回。
- 使用 `parent_id` 从 `parent_documents` 回溯完整父块上下文。
- 使用 `document_id` metadata 进行检索范围过滤。
- 文档删除时同步清理该 `document_id` 对应的父/子向量。

## 父子 chunk 检索闭环

1. 文档处理模块产出父块和子块。
2. Neo4j 保存 Document、ParentChunk、ChildChunk 和结构关系。
3. Chroma 同步写入父块 collection 与子块 collection。
4. 查询时先在 `child_documents` 中召回最相关子块。
5. 读取子块 metadata 中的 `parent_id`。
6. 在 `parent_documents` 中按 `parent_id` 取回父块上下文。
7. `HybridRetriever` 组装 `sources / retrieved_docs`，保留 `document_id`、`filename`、`parent_id`、`child_id`、`page_number`、`chunk_index`、`content` 和 `score`。

## 写入流程

`DatabaseRepository.upsert_document()` 写入 Neo4j。重复写入同一个 `document_id` 时，先删除旧 Document、ParentChunk、ChildChunk，再重新写入，避免重复节点。

`VectorStore.upsert_document()` 写入 Chroma。重复写入同一个 `document_id` 时，先删除 `parent_documents` 和 `child_documents` 中旧向量，再重新写入，避免旧向量残留。

完整业务联调时，应先生成稳定的 `document_id / parent_id / child_id`，再分别写入 Neo4j 与 Chroma。

## 删除流程

删除指定文档时：

1. `DatabaseRepository.delete_document(document_id)` 删除 Neo4j 中 Document、ParentChunk、ChildChunk 及其关系。
2. `VectorStore.delete_document(document_id)` 删除 Chroma 两个 collection 中该 `document_id` 的向量。
3. 上层联调时应在同一删除流程中依次调用两者，确保无孤儿 chunk 或旧向量。

## 向量检索流程

`VectorStore.query_child_chunks(query, top_k, document_ids)` 使用 hash embedding 生成查询向量，在 `child_documents` 中检索。`document_ids` 为空时检索全部文档；非空时生成 `document_id` metadata 过滤条件。

`HybridRetriever.retrieve()` 负责完整闭环：子块召回、父块回溯、Neo4j source 字段补齐、上下文拼接。

## 知识图谱扩展

当前已为 Neo4j 结构化文档层保留扩展点。后续可增加：

- `(:ChildChunk)-[:MENTIONS]->(:Entity)`
- `(:Entity)-[:RELATED_TO]->(:Entity)`
- `(:Entity)-[:BELONGS_TO]->(:Concept)`

`HybridRetriever` 已预留 `entity_names` 和 `max_hops` 参数。如果后续 `DatabaseRepository` 增加 `retrieve_entity_context()`，检索器会自动合并内部图检索结果。

## 环境变量

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password
NEO4J_DATABASE=neo4j

CHROMA_PERSIST_DIRECTORY=.chroma
CHROMA_PARENT_COLLECTION=parent_documents
CHROMA_CHILD_COLLECTION=child_documents

EMBEDDING_PROVIDER=hash
EMBEDDING_DIMENSION=384
```

本轮默认只实现 deterministic hash embedding，不联网下载模型。后续可以替换为 DashScope、OpenAI 或 HuggingFace embedding。

## 运行测试

当前环境没有安装 `pytest`，本轮测试使用标准库 `unittest`：

```bash
python -m unittest tests.test_neo4j_client tests.test_chroma_client tests.test_database_repository tests.test_vector_store tests.test_hybrid_retriever tests.test_neo4j_chroma_integration
```

真实集成测试默认 skip。如需开启：

```bash
set NEO4J_CHROMA_RUN_INTEGRATION=1
python -m unittest tests.test_neo4j_chroma_integration
```

开启后会执行真实 Neo4j / Chroma health check，以及写入测试文档、检索父子 chunk、校验 source、删除并确认清理完成的 smoke test。

## 初始化 Neo4j

```bash
python scripts/init_neo4j.py
```

该脚本会检查 Neo4j 连接，并创建 Document、ParentChunk、ChildChunk 的唯一约束与索引。

## 清理 Neo4j

清理全部 Document / ParentChunk / ChildChunk：

```bash
python scripts/clear_neo4j.py
```

按文档清理：

```bash
python scripts/clear_neo4j.py --document-id doc-001
```

## 清理 Chroma

重建父/子 collection：

```bash
python scripts/clear_chroma.py
```

按文档清理：

```bash
python scripts/clear_chroma.py --document-id doc-001
```

## 当前模块边界

本轮只新增和修改数据库与检索模块相关文件，没有修改前端 / UI、RAG / Agent、文档处理、LLM 调用、Prompt 构造或聊天历史模块。

## 后续接口对齐事项

- 文档处理模块需要输出稳定的 `document_id`、`parent_id`、`child_id`、`chunk_index`、`page_number` 和原始文件名。
- RAG / Agent 模块后续可调用 `HybridRetriever.retrieve()`，使用返回的 `context` 交给 LLM，并将 `sources` 作为引用来源。
- 删除文档的上层服务需要同时调用 Neo4j 和 Chroma 删除，或封装一个统一服务方法。
- 如果要启用图检索，需要确定实体抽取模块输出的 Entity / Relation schema，并在 `DatabaseRepository` 中补 `retrieve_entity_context()`。

## 前端可展示来源字段

后续前端可以展示：

- `document_id`
- `filename`
- `parent_id`
- `child_id`
- `page_number`
- `chunk_index`
- `score`
- `content`
