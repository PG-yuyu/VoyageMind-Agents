"""Prompt 模板 —— 所有 LLM 调用的 System / User Prompt 集中管理。

中文 system prompt + 英文技术术语保留。
"""

from contracts.models import (
    GraphEdge,
    GraphNode,
    IntentType,
    RetrievedChunk,
    SourceReference,
)

# ══════════════════════════════════════════════════════════════
# 实体与关系抽取
# ══════════════════════════════════════════════════════════════

_SYSTEM_ENTITY_EXTRACTION = """你是一个专业的知识图谱实体抽取助手。请从以下文本中提取所有实体和它们之间的关系。

## 实体类型
- Person（人物）
- Organization（组织）
- Concept（概念/理论）
- Location（地点）
- Event（事件）
- Technology（技术/算法）
- Product（产品/工具）

## 关系类型（使用标准化名称）
- is_a（属于/是一个）
- part_of（组成部分）
- related_to（相关）
- located_in（位于）
- developed_by（开发/提出者）
- used_for（用于）
- subfield_of（子领域）
- application_of（应用）

## 要求
1. 输出必须为严格 JSON 格式，包含 "entities" 和 "relations" 两个数组
2. 每个实体必须有: id（格式 entity_序号，如 entity_1）, name, type
3. 每个关系必须有: source_entity_id, relation_type, target_entity_id, confidence（0-1 浮点数）
4. 合并同义实体（如 "AI" 和 "人工智能" 应合并，name 用较完整的那个，aliases 列出其他名称）
5. 只抽取文本中明确提到的实体和关系，不要编造
6. 如果文本没有明确的实体和关系，返回空的 entities 和 relations 数组"""


def build_entity_extraction_prompt(chunk_text: str) -> list[dict]:
    """构建实体关系抽取的 messages。"""
    return [
        {"role": "system", "content": _SYSTEM_ENTITY_EXTRACTION},
        {"role": "user", "content": f"文本内容：\n{chunk_text}\n\n请以 JSON 格式输出抽取的实体和关系。"},
    ]


# ══════════════════════════════════════════════════════════════
# 意图识别
# ══════════════════════════════════════════════════════════════

_SYSTEM_INTENT_DETECTION = """你是一个意图识别助手。请判断用户问题的意图类型。

## 意图类型
- normal_chat：普通对话、问候、闲聊，或与知识库文档完全无关的问题
- document_search：基于文档内容的问答，例如"某文档讲了什么""总结一下""解释概念"
- graph_query：实体关系或路径查询，例如"A和B有什么关系""某个概念包含哪些子领域""从X到Y的路径"

## 规则
1. 输出严格 JSON：{"intent": "意图类型"}
2. 只输出这三个类型之一
3. 不要任何解释文字"""


def build_intent_detection_prompt(query: str) -> list[dict]:
    """构建意图识别的 messages。"""
    return [
        {"role": "system", "content": _SYSTEM_INTENT_DETECTION},
        {"role": "user", "content": f"用户问题：{query}"},
    ]


# ══════════════════════════════════════════════════════════════
# 问题改写
# ══════════════════════════════════════════════════════════════

_SYSTEM_QUERY_REWRITE = """你是一个问题改写助手。请根据对话历史，将用户的问题改写为独立、完整、清晰的表述。

## 要求
1. 将代词（它、它们、这个、那个等）替换为具体的指代对象
2. 补全省略的上下文信息
3. 保持原问题的核心意图不变
4. 如果不需要改写，直接返回原问题
5. 只输出改写后的问题文本，不要任何解释或标记"""


def build_query_rewrite_prompt(
    original_query: str,
    history: list[dict] | None = None,
) -> list[dict]:
    """构建问题改写的 messages。"""
    messages = [{"role": "system", "content": _SYSTEM_QUERY_REWRITE}]

    if history:
        # 取最近 4 条对话作为上下文
        for msg in history[-4:]:
            messages.append(msg)

    messages.append({"role": "user", "content": f"请改写以下问题：{original_query}"})
    return messages


# ══════════════════════════════════════════════════════════════
# 查询实体抽取
# ══════════════════════════════════════════════════════════════

_SYSTEM_QUERY_ENTITY = """你是一个实体识别助手。从用户问题中提取所有实体名称。

## 要求
1. 输出严格 JSON：{"entities": ["实体名1", "实体名2", ...]}
2. 只提取明确提到的实体（人物、组织、概念、技术、地点等）
3. 使用完整名称，不要缩写
4. 包括中文和英文名称
5. 如果没有实体，返回空数组"""


def build_query_entity_prompt(query: str) -> list[dict]:
    """构建查询实体抽取的 messages。"""
    return [
        {"role": "system", "content": _SYSTEM_QUERY_ENTITY},
        {"role": "user", "content": f"问题：{query}"},
    ]


# ══════════════════════════════════════════════════════════════
# 答案生成（普通对话）
# ══════════════════════════════════════════════════════════════

_SYSTEM_NORMAL_CHAT = """你是一个智能文档检索助手。用户正在与你进行普通对话。

## 回答要求
1. 用中文回答，简洁友好
2. 如果是关于你自身的问题，介绍你是一个智能文档检索助手
3. 如果用户问你能做什么，说明你可以帮助检索和分析已上传的文档"""


def build_normal_chat_prompt(
    query: str,
    history: list[dict] | None = None,
) -> list[dict]:
    """构建普通聊天的 messages。"""
    messages = [{"role": "system", "content": _SYSTEM_NORMAL_CHAT}]
    if history:
        for msg in history[-6:]:
            messages.append(msg)
    messages.append({"role": "user", "content": query})
    return messages


# ══════════════════════════════════════════════════════════════
# 答案生成（文档 + 图谱）
# ══════════════════════════════════════════════════════════════

_SYSTEM_ANSWER = """你是一个智能文档检索助手，基于提供的文档内容和知识图谱信息回答用户问题。

## 回答要求
1. 只基于提供的参考内容回答，不要编造信息
2. **综合所有提供的参考片段，尽可能给出完整的回答**。不同片段可能涵盖不同方面，请把它们组织在一起
3. 如果参考内容包含足够的信息，请全面回答问题的各个角度，不要只回答部分内容
4. 如果参考内容不足以回答问题，明确说明"根据现有资料，未能找到相关信息"
5. 用中文回答，条理清晰、内容充实
6. 不要使用 [1]、[2] 这类方括号引用编号
7. 来源标记只能写成 {{source:编号}}，只能使用参考信息中列出的 source 编号。
8. 来源标记按“小节/段落”添加：一个自然段或一个列表项最多 1 个；一个主要小节最多 1 个；全文通常 1-4 个即可。
9. 来源标记必须放在整段或列表项的最后，且必须放在句号、问号、感叹号、分号等结束标点之后，例如"这是结论。{{source:1}}"
10. 禁止把来源标记放在句子中间，禁止写成"这是结论{{source:1}}。"。
11. 只有当该段核心观点能被某个片段直接支持时才添加来源；总结、过渡、推理整合、没有直接证据的段落不要强行添加来源。
12. 不要在回答末尾添加"来源："或文件名说明
13. 如果涉及实体关系，只说明关系内容，不要额外列出来源文档
14. 对于 graph_query 意图，重点说明实体间的关系路径"""


def build_answer_prompt(
    query: str,
    rewritten_query: str,
    chunks: list[RetrievedChunk],
    graph_nodes: list[GraphNode],
    graph_edges: list[GraphEdge],
    intent: IntentType,
    sources: list[SourceReference] | None = None,
) -> list[dict]:
    """构建最终答案生成的 messages。"""
    context_parts: list[str] = []

    if sources:
        context_parts.append("## 参考文档内容：")
        context_parts.append("### 来源编号：")
        for source in sources:
            page_info = f"第 {source.page_number} 页" if source.page_number else "未知页"
            context_parts.append(
                f"source:{source.citation_index} = {source.filename} ({page_info})\n{source.content}"
            )

    # 文档块上下文
    if chunks and not sources:
        context_parts.append("## 参考文档内容：")
        document_names: dict[str, str] = {}
        for chunk in chunks:
            if chunk.document_id not in document_names:
                document_names[chunk.document_id] = chunk.filename

        source_indexes: dict[str, int] = {}
        context_parts.append("### 来源编号：")
        for document_id, filename in document_names.items():
            source_indexes[document_id] = len(source_indexes) + 1
            context_parts.append(f"source:{source_indexes[document_id]} = {filename}")

        context_parts.append("\n### 检索到的相关片段：")
        for chunk in chunks:
            page_info = f"第{chunk.page_number}页" if chunk.page_number else "未知页"
            context_parts.append(
                f"source:{source_indexes[chunk.document_id]} 文档：{chunk.filename} ({page_info})\n{chunk.content}"
            )

    # 知识图谱上下文
    if graph_nodes:
        context_parts.append("\n## 知识图谱实体：")
        for node in graph_nodes:
            context_parts.append(f"- {node.label} ({node.node_type})")

    if graph_edges:
        context_parts.append("\n## 实体关系：")
        for edge in graph_edges:
            context_parts.append(f"- {edge.source} --[{edge.relation}]--> {edge.target}")

    context = "\n".join(context_parts) if context_parts else "（暂无参考内容）"

    # 意图相关的额外指引
    intent_guidance = ""
    if intent == IntentType.GRAPH_QUERY:
        intent_guidance = "\n请重点说明实体之间的关系和路径。"
    elif intent == IntentType.DOCUMENT_SEARCH:
        intent_guidance = "\n请基于文档内容进行详细回答。"

    user_prompt = (
        f"用户问题：{query}\n"
        f"（改写后：{rewritten_query}）\n\n"
        f"参考信息：\n{context}\n"
        f"{intent_guidance}\n"
        "引用要求：{{source:编号}} 只能使用上面列出的 source 编号；每个 source 编号对应一个具体检索片段和页码，不能自己编造编号。\n"
        "来源标签只用于可被某个片段直接支持的核心段落或列表项；同一小节通常只在最后一个能代表该小节依据的段落末尾标 1 个。\n"
        "不要把来源标签放在句子中间；标签必须放在整段最后一个结束标点之后；总结、过渡、推理整合段落不要强行加标签。\n"
        f"请基于以上参考信息回答问题。不要使用 [1]、[2] 这类方括号编号；"
        f"如需标注观点来源，只使用 {{source:编号}} 这种格式，且不要在末尾添加来源文件名。"
    )

    return [
        {"role": "system", "content": _SYSTEM_ANSWER},
        {"role": "user", "content": user_prompt},
    ]
