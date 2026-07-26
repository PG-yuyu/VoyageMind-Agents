"""实体与关系抽取 —— 使用 LLM 从文档块中抽取实体和关系。

特性：
- 分批处理 chunk（每批 3 个，避免上下文溢出）
- 并行处理各批次（ThreadPoolExecutor）
- 同义实体合并
- 关系名称规范化
- 稳定的 ID 生成
"""

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from contracts.errors import (
    ENTITY_EXTRACTION_FAILED,
    ServiceError,
)
from contracts.models import ChunkRecord, EntityRecord, RelationRecord
from rag.llm_client import LLMClient
from rag.prompt_builder import (
    build_entity_extraction_prompt,
    build_query_entity_prompt,
)

logger = logging.getLogger("rag.entity_extractor")

# 并行抽取的工作线程数（LLM API 调用是 IO 密集型，线程池即可）
_EXTRACT_WORKERS = 4


class EntityExtractor:
    """基于 LLM 的实体和关系抽取器。"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    # ── 主抽取入口 ──────────────────────────────────────────

    def extract(
        self,
        chunks: list[ChunkRecord],
    ) -> tuple[list[EntityRecord], list[RelationRecord]]:
        """从文档块列表中抽取实体和关系。

        策略：
        1. 每 3 个 chunk 为一组，**并行**调用 LLM
        2. 合并各组结果
        3. 合并同义实体（跨批去重）
        4. 规范化关系名称

        Returns:
            (entities, relations)
        """
        if not chunks:
            return [], []

        all_entities: list[EntityRecord] = []
        all_relations: list[RelationRecord] = []

        batch_size = 3
        batches = list(range(0, len(chunks), batch_size))
        total_batches = (len(chunks) + batch_size - 1) // batch_size

        # 并行抽取各批次（IO 密集型 LLM 调用）
        with ThreadPoolExecutor(max_workers=_EXTRACT_WORKERS) as executor:
            futures = {}
            for i in batches:
                batch = chunks[i:i + batch_size]
                batch_text = "\n\n---\n\n".join(
                    f"[Chunk {c.chunk_id}] (Page {c.page_number or '?'}):\n{c.content}"
                    for c in batch
                )
                doc_id = batch[0].document_id
                future = executor.submit(self._extract_from_text, batch_text, doc_id)
                futures[future] = i

            for future in as_completed(futures):
                i = futures[future]
                try:
                    entities, relations = future.result()
                    all_entities.extend(entities)
                    all_relations.extend(relations)
                    logger.info("Batch %d/%d: extracted %d entities, %d relations",
                                i // batch_size + 1, total_batches,
                                len(entities), len(relations))
                except ServiceError:
                    logger.warning("Entity extraction failed for batch starting at chunk %d, skipping", i)
                except Exception as e:
                    logger.warning("Entity extraction error for batch %d: %s", i, e)

        # 合并同义实体
        merged_entities = self._merge_synonyms(all_entities)

        # 更新关系中的 entity_id 指向合并后的实体
        merged_relations = self._update_relation_entities(all_relations, merged_entities)

        # 规范化关系名称
        merged_relations = self._normalize_relations(merged_relations)

        logger.info("Final extraction: %d entities, %d relations (after merge, %d batches parallel)",
                     len(merged_entities), len(merged_relations), total_batches)
        return merged_entities, merged_relations

    def _extract_from_text(
        self,
        text: str,
        document_id: str,
    ) -> tuple[list[EntityRecord], list[RelationRecord]]:
        """从单段文本中抽取实体和关系。"""
        messages = build_entity_extraction_prompt(text)

        try:
            result = self.llm.chat_json(messages, temperature=0.2)
        except ServiceError:
            raise
        except Exception as e:
            raise ServiceError(
                code=ENTITY_EXTRACTION_FAILED,
                message=f"实体抽取失败: {e}",
                details={"text_preview": text[:200]},
            ) from e

        raw_entities: list[dict] = result.get("entities", [])
        raw_relations: list[dict] = result.get("relations", [])

        entities: list[EntityRecord] = []
        for i, ent in enumerate(raw_entities):
            name = str(ent.get("name", "")).strip()
            if not name:
                continue
            entity_type = str(ent.get("type", "Concept")).strip()
            aliases = ent.get("aliases", [])
            if isinstance(aliases, str):
                aliases = [aliases]
            entity_id = self._generate_entity_id(name, document_id)

            entities.append(EntityRecord(
                entity_id=entity_id,
                name=name,
                entity_type=entity_type,
                aliases=[a.strip() for a in aliases if a.strip()],
            ))

        relations: list[RelationRecord] = []
        for rel in raw_relations:
            source = str(rel.get("source_entity_id", "")).strip()
            target = str(rel.get("target_entity_id", "")).strip()
            rel_type = str(rel.get("relation_type", "related_to")).strip()
            confidence = float(rel.get("confidence", 0.5))
            chunk_id = str(rel.get("chunk_id", ""))

            if not source or not target:
                continue

            relation_id = self._generate_relation_id(source, rel_type, target, chunk_id)
            relations.append(RelationRecord(
                relation_id=relation_id,
                source_entity_id=source,
                relation_type=rel_type,
                target_entity_id=target,
                source_chunk_id=chunk_id,
                confidence=min(max(confidence, 0.0), 1.0),
            ))

        return entities, relations

    # ── 同义实体合并 ────────────────────────────────────────

    def _merge_synonyms(
        self,
        entities: list[EntityRecord],
    ) -> list[EntityRecord]:
        """合并同义实体：按规范化名称分组，保留最完整的名称为主名。"""
        groups: dict[str, list[EntityRecord]] = {}

        for ent in entities:
            key = self._normalize_name(ent.name)
            if key not in groups:
                groups[key] = []
            groups[key].append(ent)

        merged: list[EntityRecord] = []
        for key, group in groups.items():
            if len(group) == 1:
                merged.append(group[0])
            else:
                # 选最长的名称为主名
                best = max(group, key=lambda e: len(e.name))
                all_aliases: set[str] = set()
                for e in group:
                    all_aliases.add(e.name)
                    all_aliases.update(e.aliases)
                all_aliases.discard(best.name)
                best.aliases = sorted(all_aliases)
                merged.append(best)

        return merged

    @staticmethod
    def _normalize_name(name: str) -> str:
        """规范化实体名称用于比较。"""
        return name.lower().strip().replace(" ", "").replace("-", "").replace("_", "")

    # ── 关系处理 ────────────────────────────────────────────

    def _update_relation_entities(
        self,
        relations: list[RelationRecord],
        merged_entities: list[EntityRecord],
    ) -> list[RelationRecord]:
        """将关系中的 source/target entity_id 更新为合并后的实体 ID。"""
        # 构建名称 → 合并后 entity_id 的映射
        name_to_id: dict[str, str] = {}
        for ent in merged_entities:
            name_to_id[self._normalize_name(ent.name)] = ent.entity_id
            for alias in ent.aliases:
                name_to_id[self._normalize_name(alias)] = ent.entity_id

        updated: list[RelationRecord] = []
        seen: set[str] = set()
        for rel in relations:
            # 尝试用规范化名称匹配
            src_normalized = self._normalize_name(rel.source_entity_id)
            tgt_normalized = self._normalize_name(rel.target_entity_id)

            new_src = name_to_id.get(src_normalized, rel.source_entity_id)
            new_tgt = name_to_id.get(tgt_normalized, rel.target_entity_id)

            # 去重
            dedup_key = f"{new_src}:{rel.relation_type}:{new_tgt}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            rel.source_entity_id = new_src
            rel.target_entity_id = new_tgt
            rel.relation_id = self._generate_relation_id(
                new_src, rel.relation_type, new_tgt, rel.source_chunk_id,
            )
            updated.append(rel)

        return updated

    def _normalize_relations(
        self,
        relations: list[RelationRecord],
    ) -> list[RelationRecord]:
        """规范化关系类型名称。"""
        norm_map = {
            "part_of": "part_of",
            "belongs_to": "part_of",
            "is_a": "is_a",
            "type_of": "is_a",
            "related_to": "related_to",
            "associated_with": "related_to",
            "subfield_of": "subfield_of",
            "application_of": "used_for",
            "used_for": "used_for",
            "developed_by": "developed_by",
            "created_by": "developed_by",
            "proposed_by": "developed_by",
            "located_in": "located_in",
        }
        for rel in relations:
            key = rel.relation_type.lower().strip()
            rel.relation_type = norm_map.get(key, rel.relation_type)
        return relations

    # ── 查询实体抽取 ────────────────────────────────────────

    def extract_from_query(self, query: str) -> list[str]:
        """从用户查询中抽取实体名称（用于 GraphDB 检索）。"""
        messages = build_query_entity_prompt(query)
        try:
            result = self.llm.chat_json(messages, temperature=0.1)
            entities = result.get("entities", [])
            if isinstance(entities, list):
                return [str(e).strip() for e in entities if str(e).strip()]
            return []
        except (ServiceError, Exception) as e:
            logger.warning("Query entity extraction failed: %s", e)
            return []

    # ── ID 生成 ─────────────────────────────────────────────

    @staticmethod
    def _generate_entity_id(name: str, document_id: str) -> str:
        raw = f"entity:{name}:{document_id}"
        return "entity_" + hashlib.sha256(raw.encode()).hexdigest()[:10]

    @staticmethod
    def _generate_relation_id(
        source_id: str,
        relation_type: str,
        target_id: str,
        chunk_id: str,
    ) -> str:
        raw = f"rel:{source_id}:{relation_type}:{target_id}:{chunk_id}"
        return "rel_" + hashlib.sha256(raw.encode()).hexdigest()[:10]
