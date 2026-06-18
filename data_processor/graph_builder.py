"""
知识图谱构建器 — Graph RAG 基础

从文档中提取实体和关系，构建教育领域知识图谱：
- 实体类型：学科、概念、公式、人物、事件、年级
- 关系类型：包含、相关、前置知识、等价、应用

用于增强检索：当向量检索找到相关chunk后，通过图遍历扩展关联知识。

用法:
    builder = GraphBuilder(llm_client)
    graph = builder.build_from_chunks(chunks)
    # graph.add_entity("一元一次方程", entity_type="概念", subject="数学", grade="初中")
    # graph.add_relation("一元一次方程", "方程", relation="属于")
"""
import re
import os
import json
from typing import List, Dict, Set, Optional, Tuple
from collections import defaultdict, deque
from dataclasses import dataclass, field

from core.logger import get_logger

logger = get_logger("graph_builder")


@dataclass
class Entity:
    """知识图谱实体"""
    name: str                          # 实体名称（唯一标识）
    entity_type: str                   # 实体类型: 概念/公式/人物/事件/学科域/一级知识点...
    subject: str = ""                  # 所属学科
    grade: str = ""                    # 年级
    description: str = ""              # 简要描述
    source_chunks: List[str] = field(default_factory=list)  # 来源chunk ID列表
    display_name: str = ""             # 前端显示名（CK12层级路径的最后一段）

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.entity_type,
            "subject": self.subject,
            "grade": self.grade,
            "description": self.description,
            "display_name": self.display_name or self.name,
        }


@dataclass
class Relation:
    """实体间关系"""
    source: str                        # 源实体名
    target: str                        # 目标实体名
    relation: str                      # 关系类型: 属于/相关/前置知识/等价/应用
    weight: float = 1.0                # 关系权重

    def to_dict(self) -> dict:
        return {"source": self.source, "target": self.target,
                "relation": self.relation, "weight": self.weight}


class KnowledgeGraph:
    """
    教育领域知识图谱

    基于邻接表的内存图，支持：
    - 实体查询（按名称/类型/学科）
    - 关系遍历（1-2跳扩展）
    - 实体到chunk的反向索引（找到实体关联的知识片段）
    """

    def __init__(self):
        self.entities: Dict[str, Entity] = {}               # name → Entity
        self.adjacency: Dict[str, List[Tuple[str, str, float]]] = defaultdict(list)  # source → [(target, relation, weight)]
        self.reverse_adjacency: Dict[str, List[Tuple[str, str, float]]] = defaultdict(list)  # target → [(source, relation, weight)]

    # ─── 构建 ───

    def add_entity(self, entity: Entity):
        """添加实体"""
        if entity.name not in self.entities:
            self.entities[entity.name] = entity
        else:
            # 合并来源
            existing = self.entities[entity.name]
            existing.source_chunks.extend(entity.source_chunks)
            existing.source_chunks = list(set(existing.source_chunks))
            if entity.description and not existing.description:
                existing.description = entity.description

    def add_relation(self, source: str, target: str, relation: str, weight: float = 1.0):
        """添加关系（自动补全缺失的实体）"""
        if source not in self.entities:
            self.add_entity(Entity(name=source, entity_type="未知"))
        if target not in self.entities:
            self.add_entity(Entity(name=target, entity_type="未知"))
        self.adjacency[source].append((target, relation, weight))
        self.reverse_adjacency[target].append((source, relation, weight))

    # ─── 查询 ───

    def get_entity(self, name: str) -> Optional[Entity]:
        return self.entities.get(name)

    def get_neighbors(self, entity_name: str, max_hops: int = 1) -> List[Tuple[Entity, str, float, int]]:
        """
        获取实体的邻居（支持多跳）

        Returns:
            [(Entity, relation, weight, hop_distance), ...]
        """
        if entity_name not in self.entities:
            return []

        visited = {entity_name: 0}
        result = []
        queue = deque([(entity_name, 0)])

        while queue:
            current, hop = queue.popleft()
            if hop >= max_hops:
                continue

            for neighbor, relation, weight in self.adjacency[current]:
                if neighbor not in visited:
                    visited[neighbor] = hop + 1
                    if neighbor in self.entities:
                        result.append((self.entities[neighbor], relation, weight, hop + 1))
                    queue.append((neighbor, hop + 1))

            # 也检查反向邻居
            for source, relation, weight in self.reverse_adjacency[current]:
                if source not in visited:
                    visited[source] = hop + 1
                    if source in self.entities:
                        result.append((self.entities[source], relation, weight, hop + 1))
                    queue.append((source, hop + 1))

        return result

    def expand_query_context(self, query_entities: List[str],
                              max_hops: int = 1, max_expansions: int = 8) -> List[str]:
        """
        从查询中的实体出发，通过图遍历扩展检索上下文。
        支持模糊匹配：如果精确名称不在图谱中，自动用 search_entity 查找。

        Args:
            query_entities: 查询中包含的实体名称列表
            max_hops: 最大跳数
            max_expansions: 最多扩展的实体数

        Returns:
            扩展后的搜索关键词列表（实体名称 + 相关描述）
        """
        expanded_keywords = set(query_entities)
        for entity_name in query_entities:
            # 精确匹配
            neighbors = self.get_neighbors(entity_name, max_hops=max_hops)
            # 精确无结果则模糊匹配
            if not neighbors:
                matched = self.search_entity(entity_name, max_results=2)
                for m in matched:
                    expanded_keywords.add(m.display_name or m.name)
                    neighbors = self.get_neighbors(m.name, max_hops=max_hops)
                    for ent, rel, weight, hop in neighbors[:max_expansions]:
                        expanded_keywords.add(ent.display_name or ent.name)
            else:
                for ent, rel, weight, hop in neighbors[:max_expansions]:
                    expanded_keywords.add(ent.display_name or ent.name)

        result = list(expanded_keywords)
        logger.debug(f"图扩展: {query_entities} → {result}")
        return result

    def get_chunks_for_entities(self, entity_names: List[str]) -> Set[str]:
        """获取实体关联的所有 chunk ID"""
        chunk_ids = set()
        for name in entity_names:
            entity = self.entities.get(name)
            if entity:
                chunk_ids.update(entity.source_chunks)
        return chunk_ids

    def search_entity(self, keyword: str, max_results: int = 5) -> List[Entity]:
        """
        按关键词模糊搜索实体（支持 display_name 和路径段匹配）

        匹配优先级：
        1. 实体名精确匹配
        2. display_name 精确匹配
        3. 路径中任意段包含关键词
        4. display_name 包含关键词
        """
        results = []
        kw_lower = keyword.lower()

        # 优先精确匹配
        if keyword in self.entities:
            results.append(self.entities[keyword])

        for ent in self.entities.values():
            if ent in results:
                continue
            # display_name 精确匹配
            dn = ent.display_name or ""
            if dn == keyword:
                results.append(ent)
                continue
            # 路径段匹配：name 中的任何 "-" 段包含关键词
            parts = ent.name.split("-")
            if any(kw_lower in p.lower() for p in parts):
                results.append(ent)
                continue
            # display_name 包含匹配
            if dn and kw_lower in dn.lower():
                results.append(ent)

            if len(results) >= max_results:
                break

        return results[:max_results]

    # ─── 统计 ───

    @property
    def entity_count(self) -> int:
        return len(self.entities)

    @property
    def relation_count(self) -> int:
        return sum(len(v) for v in self.adjacency.values())

    def get_stats(self) -> dict:
        """获取图谱统计信息"""
        type_dist = defaultdict(int)
        subj_dist = defaultdict(int)
        for ent in self.entities.values():
            type_dist[ent.entity_type] += 1
            if ent.subject:
                subj_dist[ent.subject] += 1

        return {
            "entity_count": self.entity_count,
            "relation_count": self.relation_count,
            "entity_types": dict(type_dist),
            "subject_distribution": dict(subj_dist),
        }

    # ─── 序列化 ───

    def to_dict(self) -> dict:
        """序列化为字典（可 JSON dump）"""
        entities_data = []
        for ent in self.entities.values():
            entities_data.append({
                "name": ent.name,
                "entity_type": ent.entity_type,
                "subject": ent.subject,
                "grade": ent.grade,
                "description": ent.description,
                "source_chunks": ent.source_chunks,
                "display_name": ent.display_name or ent.name,
            })
        relations_data = []
        for source, edges in self.adjacency.items():
            for target, relation, weight in edges:
                relations_data.append({
                    "source": source, "target": target,
                    "relation": relation, "weight": weight,
                })
        return {"entities": entities_data, "relations": relations_data}

    def save(self, filepath: str):
        """保存图谱到 JSON 文件"""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        data = self.to_dict()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"知识图谱已保存: {filepath} ({len(data['entities'])} 实体, {len(data['relations'])} 关系)")

    @classmethod
    def load(cls, filepath: str) -> Optional["KnowledgeGraph"]:
        """从 JSON 文件加载图谱"""
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            graph = cls()
            for e in data.get("entities", []):
                entity = Entity(
                    name=e["name"],
                    entity_type=e.get("entity_type", e.get("type", "未知")),
                    subject=e.get("subject", ""),
                    grade=e.get("grade", ""),
                    description=e.get("description", ""),
                    source_chunks=e.get("source_chunks", []),
                    display_name=e.get("display_name", ""),
                )
                graph.entities[entity.name] = entity
            for r in data.get("relations", []):
                graph.add_relation(r["source"], r["target"],
                                   r.get("relation", "相关"),
                                   r.get("weight", 1.0))
            logger.info(f"知识图谱已加载: {filepath} ({graph.entity_count} 实体, {graph.relation_count} 关系)")
            return graph
        except Exception as e:
            logger.warning(f"加载知识图谱失败: {e}")
            return None


# ========== 图谱构建 ==========

ENTITY_EXTRACTION_PROMPT = """从以下教育文档片段中提取知识实体和关系。

【提取规则】
- 实体: 学科术语、数学公式/定理、历史事件、人名、地名、实验、定律等
- 关系类型: 属于(概念归属)、相关(概念关联)、前置知识(A是学习B的基础)、等价(同义概念)、应用(概念的实际应用)
- 忽略太泛化的词（如"学习"、"学生"、"教育"）
- 每个片段提取1-5个实体

【文档内容】
{content}

请以JSON格式返回：
{{
  "entities": [
    {{"name": "实体名", "type": "概念/公式/人物/事件", "subject": "学科", "grade": "年级", "description": "简短描述"}}
  ],
  "relations": [
    {{"source": "源实体", "target": "目标实体", "relation": "关系类型"}}
  ]
}}

只返回JSON，不要解释。"""


class GraphBuilder:
    """从文档集合构建知识图谱"""

    def __init__(self, llm_client=None):
        from llm.llm_client import LLMClient
        self.llm_client = llm_client or LLMClient()
        self.graph = KnowledgeGraph()
        self._entity_lookup: Dict[str, List[Entity]] = defaultdict(list)  # 简易倒排索引

    def build_from_chunks(self, chunks: list, sample_every: int = 5) -> KnowledgeGraph:
        """
        从 chunks 构建知识图谱

        Args:
            chunks: DocumentChunk 列表
            sample_every: 每隔N个chunk采样一次（控制API成本）

        Returns:
            KnowledgeGraph
        """
        logger.info(f"[Graph] 开始构建知识图谱（{len(chunks)} 个片段，采样间隔={sample_every}）")

        # 采样 + 去重
        sampled = []
        seen = set()
        for i, chunk in enumerate(chunks):
            if i % sample_every != 0:
                continue
            content = chunk.content if hasattr(chunk, 'content') else str(chunk)
            content_hash = hash(content[:100])
            if content_hash not in seen and len(content) > 20:
                seen.add(content_hash)
                sampled.append((i, content))

        logger.info(f"[Graph] 采样 {len(sampled)} 个片段用于实体提取")

        # 批量提取实体和关系
        for chunk_idx, content in sampled[:50]:  # 最多处理50个样本
            entities, relations = self._extract_entities(content, chunk_idx)
            for ent in entities:
                ent.source_chunks = [f"chunk_{chunk_idx}"]
                self.graph.add_entity(ent)
                self._entity_lookup[ent.name].append(ent)
            for rel in relations:
                self.graph.add_relation(rel["source"], rel["target"],
                                        rel.get("relation", "相关"),
                                        rel.get("weight", 1.0))

        logger.info(f"[Graph] 知识图谱构建完成: "
                    f"{self.graph.entity_count} 实体, {self.graph.relation_count} 关系")
        return self.graph

    def _extract_entities(self, content: str, chunk_idx: int = 0) -> Tuple[List[Entity], List[dict]]:
        """从文本中提取实体和关系"""
        content_truncated = content[:2000]
        # 快速规则提取（避免LLM调用失败时没有结果）
        entities = self._rule_extract(content_truncated, chunk_idx)
        relations = []

        # LLM 精确提取
        try:
            prompt = ENTITY_EXTRACTION_PROMPT.format(content=content_truncated)
            response = self.llm_client.generate(prompt, max_tokens=500, temperature=0.1)
            # 提取第一个 { 到最后一个 } 之间的 JSON（避免贪婪匹配误匹配）
            start = response.find('{')
            end = response.rfind('}')
            if start != -1 and end > start:
                data = json.loads(response[start:end+1])
                llm_entities = data.get("entities", [])
                llm_relations = data.get("relations", [])

                # 合并LLM实体（优先LLM）
                llm_names = {e["name"] for e in llm_entities}
                entities = [e for e in entities if e.name not in llm_names]
                for e in llm_entities:
                    entities.append(Entity(
                        name=e.get("name", ""),
                        entity_type=e.get("type", "概念"),
                        subject=e.get("subject", ""),
                        grade=e.get("grade", ""),
                        description=e.get("description", ""),
                        source_chunks=[f"chunk_{chunk_idx}"],
                    ))
                relations.extend(llm_relations)

        except Exception as e:
            logger.debug(f"LLM实体提取失败，使用规则结果: {e}")

        return entities, relations

    def _rule_extract(self, content: str, chunk_idx: int = 0) -> List[Entity]:
        """基于规则的快速实体提取（fallback）"""
        entities = []

        # 数学公式模式: $...$ 或 $$...$$
        formula_patterns = [
            (r'\$([^$]+)\$', "公式"),
            (r'[（(]([^）)]*(?:定理|定律|公式|性质|公理)[^）)]*)[）)]', "公式"),
        ]
        for pattern, etype in formula_patterns:
            for match in re.finditer(pattern, content):
                name = match.group(1).strip()
                if 2 < len(name) < 50:
                    entities.append(Entity(name=name, entity_type=etype,
                                          source_chunks=[f"chunk_{chunk_idx}"]))

        # 中文专业术语: 包含"定理""定律""方程""函数""原理"等
        concept_markers = ["定理", "定律", "方程", "函数", "原理", "法则", "规则",
                          "定义", "概念", "方法", "策略", "模型"]
        for marker in concept_markers:
            # 匹配包含这些标记的词组（前面1-8个汉字 + 标记）
            pattern = re.compile(r'([\u4e00-\u9fff]{1,8}' + marker + r')')
            for match in pattern.finditer(content):
                name = match.group(1)
                if len(name) >= 3:
                    entities.append(Entity(name=name, entity_type="概念",
                                          source_chunks=[f"chunk_{chunk_idx}"]))

        return entities

    def query_graph(self, keywords: List[str], max_hops: int = 1) -> List[str]:
        """
        查询图谱：从关键词匹配实体，扩展关联实体，返回扩展关键词

        Args:
            keywords: 从用户查询提取的关键词
            max_hops: 图遍历跳数

        Returns:
            扩展后的检索关键词
        """
        matched_entities = []
        for kw in keywords:
            # 精确匹配
            if kw in self.graph.entities:
                matched_entities.append(kw)
            # 模糊匹配
            else:
                for entity_name in self.graph.entities:
                    if kw in entity_name or entity_name in kw:
                        matched_entities.append(entity_name)
                        break

        if not matched_entities:
            return keywords

        return self.graph.expand_query_context(
            list(set(matched_entities)), max_hops=max_hops
        )


# ========== 图谱管理器 ==========

GRAPH_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "graph", "knowledge_graph.json")


class KnowledgeGraphManager:
    """
    知识图谱生命周期管理器（单例）

    - 服务启动时从磁盘加载预构建的图谱
    - 文档上传后触发后台重建
    - 查询时直接返回缓存的图谱实例
    """

    _instance: Optional["KnowledgeGraphManager"] = None
    _graph: Optional[KnowledgeGraph] = None
    _building: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    # ── 加载 ──

    def get_graph(self) -> Optional[KnowledgeGraph]:
        """获取当前图谱（优先内存缓存 → 磁盘文件）"""
        if self._graph is not None and self._graph.entity_count > 0:
            return self._graph
        # 尝试从磁盘加载
        loaded = KnowledgeGraph.load(GRAPH_FILE)
        if loaded and loaded.entity_count > 0:
            self._graph = loaded
            logger.info(f"[GraphManager] 从磁盘加载图谱: {loaded.entity_count} 实体, {loaded.relation_count} 关系")
        return self._graph

    # ── 后台构建 ──

    def rebuild_async(self):
        """在后台线程中触发图谱重建（不阻塞主请求）"""
        if self._building:
            logger.debug("[GraphManager] 图谱正在构建中，跳过")
            return
        import threading
        self._building = True
        t = threading.Thread(target=self._do_rebuild, daemon=True, name="graph-rebuild")
        t.start()
        logger.info("[GraphManager] 图谱后台重建已启动")

    def _do_rebuild(self):
        """实际执行重建（在后台线程中运行）。

        重要：先加载已有图谱作为基底，再合入 chunk 提取的新实体，
        避免覆盖通过 build_k12_graph.py 预构建的 K12 知识图谱。
        """
        try:
            logger.info("[GraphManager] 开始构建知识图谱...")
            from database.chunk_store import load_chunks
            from llm.llm_client import LLMClient

            # 1. 加载已有图谱作为基底（保留预构建的 K12 数据）
            base_graph = KnowledgeGraph.load(GRAPH_FILE)
            if base_graph and base_graph.entity_count > 0:
                logger.info(f"[GraphManager] 已有图谱 {base_graph.entity_count} 实体，将在此基础上增量合并")

            chunks_data = load_chunks()
            if not chunks_data:
                logger.info("[GraphManager] 无可用 chunk，跳过图谱构建")
                return

            # 2. 从 chunk 中提取新实体
            from types import SimpleNamespace
            chunks = [SimpleNamespace(content=c["content"], chunk_id=c["chunk_id"])
                      for c in chunks_data]

            llm_client = LLMClient()
            builder = GraphBuilder(llm_client)
            new_graph = builder.build_from_chunks(chunks, sample_every=5)

            # 3. 合并：将新实体/关系合入基底图谱
            if base_graph and base_graph.entity_count > 0:
                merged = base_graph
            else:
                merged = new_graph
                base_graph = None

            if base_graph is not None:
                # 合入新实体
                for name, ent in new_graph.entities.items():
                    merged.add_entity(ent)
                # 合入新关系
                for src, edges in new_graph.adjacency.items():
                    for tgt, rel, w in edges:
                        merged.add_relation(src, tgt, rel, w)
                logger.info(f"[GraphManager] 合并完成: {merged.entity_count} 实体, {merged.relation_count} 关系")

            # 4. 保存并缓存
            merged.save(GRAPH_FILE)
            self._graph = merged
            logger.info(f"[GraphManager] 图谱构建完成: "
                        f"{merged.entity_count} 实体, {merged.relation_count} 关系")
        except Exception as e:
            logger.error(f"[GraphManager] 图谱构建失败: {e}", exc_info=True)
        finally:
            self._building = False

    # ── 失效 ──

    def invalidate(self):
        """标记图谱需要重建（删除缓存，下次查询时重新加载或触发重建）"""
        self._graph = None
        logger.info("[GraphManager] 图谱缓存已失效")

    # ── 统计 ──

    def get_stats(self) -> dict:
        """获取图谱统计"""
        graph = self.get_graph()
        if graph and graph.entity_count > 0:
            stats = graph.get_stats()
            stats["status"] = "ready"
            stats["file"] = GRAPH_FILE
            stats["file_exists"] = os.path.exists(GRAPH_FILE)
            return stats
        return {
            "status": "building" if self._building else "empty",
            "entity_count": 0,
            "relation_count": 0,
            "file_exists": os.path.exists(GRAPH_FILE),
        }