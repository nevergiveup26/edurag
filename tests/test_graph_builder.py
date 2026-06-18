"""data_processor.graph_builder 知识图谱测试"""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestEntity:
    def test_default_values(self):
        from data_processor.graph_builder import Entity
        e = Entity(name="勾股定理", entity_type="公式", subject="数学", grade="初中",
                   description="直角三角形边长关系")
        assert e.name == "勾股定理"
        assert e.entity_type == "公式"
        assert e.source_chunks == []
        assert e.display_name == ""

    def test_to_dict(self):
        from data_processor.graph_builder import Entity
        e = Entity(name="勾股定理", entity_type="公式", subject="数学",
                   grade="初中", description="desc", display_name="勾股定理")
        d = e.to_dict()
        assert d["name"] == "勾股定理"
        assert d["type"] == "公式"
        assert d["subject"] == "数学"


class TestRelation:
    def test_default_weight(self):
        from data_processor.graph_builder import Relation
        r = Relation(source="A", target="B", relation="相关")
        assert r.weight == 1.0

    def test_to_dict(self):
        from data_processor.graph_builder import Relation
        r = Relation(source="A", target="B", relation="前置知识", weight=0.8)
        d = r.to_dict()
        assert d["relation"] == "前置知识"
        assert d["weight"] == 0.8


class TestKnowledgeGraphAddEntity:
    def test_add_new_entity(self):
        from data_processor.graph_builder import KnowledgeGraph, Entity
        graph = KnowledgeGraph()
        e = Entity(name="一元一次方程", entity_type="概念", source_chunks=["c1"])
        graph.add_entity(e)
        assert graph.entity_count == 1
        assert "一元一次方程" in graph.entities

    def test_add_existing_merges_chunks(self):
        from data_processor.graph_builder import KnowledgeGraph, Entity
        graph = KnowledgeGraph()
        e1 = Entity(name="方程", entity_type="概念", source_chunks=["c1"])
        e2 = Entity(name="方程", entity_type="概念", source_chunks=["c2"])
        graph.add_entity(e1)
        graph.add_entity(e2)
        assert graph.entity_count == 1
        assert set(graph.entities["方程"].source_chunks) == {"c1", "c2"}

    def test_add_existing_fills_description(self):
        from data_processor.graph_builder import KnowledgeGraph, Entity
        graph = KnowledgeGraph()
        e1 = Entity(name="方程", entity_type="概念", description="")
        e2 = Entity(name="方程", entity_type="概念", description="新描述")
        graph.add_entity(e1)
        graph.add_entity(e2)
        assert graph.entities["方程"].description == "新描述"


class TestKnowledgeGraphAddRelation:
    def test_add_relation(self):
        from data_processor.graph_builder import KnowledgeGraph
        graph = KnowledgeGraph()
        graph.add_relation("方程", "一元一次方程", "包含")
        assert graph.entity_count == 2
        assert graph.relation_count == 1

    def test_add_relation_existing_entities(self):
        from data_processor.graph_builder import KnowledgeGraph, Entity
        graph = KnowledgeGraph()
        graph.add_entity(Entity(name="A", entity_type="概念"))
        graph.add_entity(Entity(name="B", entity_type="概念"))
        graph.add_relation("A", "B", "相关")
        assert graph.relation_count == 1

    def test_duplicate_entities_not_re_counted(self):
        from data_processor.graph_builder import KnowledgeGraph, Entity
        graph = KnowledgeGraph()
        graph.add_entity(Entity(name="A", entity_type="概念"))
        graph.add_relation("A", "B", "相关")
        # B 是自动补全的
        assert graph.entity_count == 2


class TestKnowledgeGraphGetEntity:
    def test_get_existing(self):
        from data_processor.graph_builder import KnowledgeGraph, Entity
        graph = KnowledgeGraph()
        graph.add_entity(Entity(name="勾股定理", entity_type="公式"))
        ent = graph.get_entity("勾股定理")
        assert ent is not None
        assert ent.name == "勾股定理"

    def test_get_missing(self):
        from data_processor.graph_builder import KnowledgeGraph
        graph = KnowledgeGraph()
        assert graph.get_entity("不存在") is None


class TestKnowledgeGraphGetNeighbors:
    def test_no_neighbors(self):
        from data_processor.graph_builder import KnowledgeGraph, Entity
        graph = KnowledgeGraph()
        graph.add_entity(Entity(name="孤立", entity_type="概念"))
        neighbors = graph.get_neighbors("孤立")
        assert neighbors == []

    def test_entity_not_found(self):
        from data_processor.graph_builder import KnowledgeGraph
        graph = KnowledgeGraph()
        assert graph.get_neighbors("不存在") == []

    def test_one_hop_neighbors(self):
        from data_processor.graph_builder import KnowledgeGraph
        graph = KnowledgeGraph()
        graph.add_relation("A", "B", "相关")
        neighbors = graph.get_neighbors("A", max_hops=1)
        assert len(neighbors) == 1
        assert neighbors[0][0].name == "B"
        assert neighbors[0][1] == "相关"
        assert neighbors[0][3] == 1  # hop distance

    def test_reverse_neighbors(self):
        from data_processor.graph_builder import KnowledgeGraph
        graph = KnowledgeGraph()
        graph.add_relation("A", "B", "相关")
        # 从 B 出发，反向找到 A
        neighbors = graph.get_neighbors("B", max_hops=1)
        assert len(neighbors) == 1
        assert neighbors[0][0].name == "A"

    def test_multi_hop(self):
        from data_processor.graph_builder import KnowledgeGraph
        graph = KnowledgeGraph()
        graph.add_relation("A", "B", "相关")
        graph.add_relation("B", "C", "前置知识")
        neighbors = graph.get_neighbors("A", max_hops=2)
        # B (hop1) + C (hop2 via B)
        names = {n[0].name for n in neighbors}
        assert "B" in names
        assert "C" in names

    def test_max_hops_respected(self):
        from data_processor.graph_builder import KnowledgeGraph
        graph = KnowledgeGraph()
        graph.add_relation("A", "B", "相关")
        graph.add_relation("B", "C", "相关")
        graph.add_relation("C", "D", "相关")
        neighbors = graph.get_neighbors("A", max_hops=1)
        assert len(neighbors) == 1  # only B


class TestKnowledgeGraphSearchEntity:
    def test_exact_match(self):
        from data_processor.graph_builder import KnowledgeGraph, Entity
        graph = KnowledgeGraph()
        graph.add_entity(Entity(name="勾股定理", entity_type="公式"))
        results = graph.search_entity("勾股定理")
        assert len(results) >= 1
        assert results[0].name == "勾股定理"

    def test_display_name_match(self):
        from data_processor.graph_builder import KnowledgeGraph, Entity
        graph = KnowledgeGraph()
        e = Entity(name="math-01-001", entity_type="概念", display_name="勾股定理")
        graph.add_entity(e)
        results = graph.search_entity("勾股定理")
        assert len(results) == 1

    def test_path_segment_match(self):
        from data_processor.graph_builder import KnowledgeGraph, Entity
        graph = KnowledgeGraph()
        e = Entity(name="数学-初中-函数-一次函数", entity_type="概念")
        graph.add_entity(e)
        results = graph.search_entity("一次函数")
        assert len(results) == 1

    def test_partial_match_in_display_name(self):
        from data_processor.graph_builder import KnowledgeGraph, Entity
        graph = KnowledgeGraph()
        e = Entity(name="e1", entity_type="概念", display_name="一元二次方程")
        graph.add_entity(e)
        results = graph.search_entity("二次")
        assert len(results) == 1

    def test_max_results(self):
        from data_processor.graph_builder import KnowledgeGraph, Entity
        graph = KnowledgeGraph()
        for i in range(10):
            graph.add_entity(Entity(name=f"概念_{i}", entity_type="概念", display_name=f"概念_{i}"))
        results = graph.search_entity("概念", max_results=3)
        assert len(results) <= 3


class TestKnowledgeGraphExpandQueryContext:
    def test_expand_with_neighbors(self):
        from data_processor.graph_builder import KnowledgeGraph
        graph = KnowledgeGraph()
        graph.add_relation("勾股定理", "直角三角形", "相关")
        graph.add_relation("勾股定理", "毕达哥拉斯", "相关")

        expanded = graph.expand_query_context(["勾股定理"], max_hops=1, max_expansions=8)
        assert "勾股定理" in expanded
        assert "直角三角形" in expanded
        assert "毕达哥拉斯" in expanded

    def test_expand_fuzzy_match(self):
        from data_processor.graph_builder import KnowledgeGraph, Entity
        graph = KnowledgeGraph()
        graph.add_entity(Entity(name="勾股定理", entity_type="公式",
                                source_chunks=["c1"], display_name="勾股定理"))
        graph.add_relation("勾股定理", "直角三角形", "相关")

        expanded = graph.expand_query_context(["勾股"], max_hops=1)
        assert "勾股定理" in expanded


class TestKnowledgeGraphGetChunks:
    def test_get_chunks_for_entities(self):
        from data_processor.graph_builder import KnowledgeGraph, Entity
        graph = KnowledgeGraph()
        graph.add_entity(Entity(name="A", entity_type="概念", source_chunks=["c1", "c2"]))
        graph.add_entity(Entity(name="B", entity_type="概念", source_chunks=["c2", "c3"]))

        chunks = graph.get_chunks_for_entities(["A", "B"])
        assert chunks == {"c1", "c2", "c3"}

    def test_empty(self):
        from data_processor.graph_builder import KnowledgeGraph
        graph = KnowledgeGraph()
        assert graph.get_chunks_for_entities(["不存在"]) == set()


class TestKnowledgeGraphStats:
    def test_empty_stats(self):
        from data_processor.graph_builder import KnowledgeGraph
        graph = KnowledgeGraph()
        stats = graph.get_stats()
        assert stats["entity_count"] == 0
        assert stats["relation_count"] == 0

    def test_stats_with_data(self):
        from data_processor.graph_builder import KnowledgeGraph, Entity
        graph = KnowledgeGraph()
        graph.add_entity(Entity(name="A", entity_type="概念", subject="数学"))
        graph.add_entity(Entity(name="B", entity_type="公式", subject="数学"))
        graph.add_relation("A", "B", "相关")

        stats = graph.get_stats()
        assert stats["entity_count"] == 2
        assert stats["relation_count"] == 1
        assert "概念" in stats["entity_types"]
        assert stats["entity_types"]["概念"] == 1
        assert "数学" in stats["subject_distribution"]


class TestKnowledgeGraphSaveLoad:
    def test_save_and_load(self, tmp_path):
        from data_processor.graph_builder import KnowledgeGraph, Entity
        graph = KnowledgeGraph()
        graph.add_entity(Entity(name="勾股定理", entity_type="公式", subject="数学",
                                grade="初中", description="a²+b²=c²",
                                source_chunks=["c1"], display_name="勾股定理"))
        graph.add_relation("勾股定理", "直角三角形", "相关", weight=1.0)

        filepath = tmp_path / "graph.json"
        graph.save(str(filepath))
        assert filepath.exists()

        loaded = KnowledgeGraph.load(str(filepath))
        assert loaded is not None
        assert loaded.entity_count == 2
        assert loaded.relation_count == 1
        assert loaded.get_entity("勾股定理").subject == "数学"

    def test_load_nonexistent(self, tmp_path):
        from data_processor.graph_builder import KnowledgeGraph
        assert KnowledgeGraph.load(str(tmp_path / "nonexistent.json")) is None


class TestKnowledgeGraphToDict:
    def test_to_dict(self):
        from data_processor.graph_builder import KnowledgeGraph, Entity
        graph = KnowledgeGraph()
        graph.add_entity(Entity(name="A", entity_type="概念", display_name="概念A"))
        graph.add_relation("A", "B", "相关")

        d = graph.to_dict()
        assert "entities" in d
        assert "relations" in d
        assert len(d["entities"]) == 2
        assert len(d["relations"]) == 1


class TestRuleExtract:
    def test_extract_formulas(self):
        from data_processor.graph_builder import GraphBuilder
        builder = GraphBuilder()
        mock_llm = MagicMock()
        builder.llm_client = mock_llm

        entities = builder._rule_extract("勾股定理是直角三角形边长关系定理。")
        assert len(entities) >= 1
        names = [e.name for e in entities]
        assert any("勾股定理" in n for n in names)

    def test_extract_concept_markers(self):
        from data_processor.graph_builder import GraphBuilder
        builder = GraphBuilder()
        mock_llm = MagicMock()
        builder.llm_client = mock_llm

        entities = builder._rule_extract("一元一次方程的定义和相关概念")
        concepts = [e for e in entities if e.entity_type == "概念"]
        assert len(concepts) >= 1

    def test_extract_empty_content(self):
        from data_processor.graph_builder import GraphBuilder
        builder = GraphBuilder()
        mock_llm = MagicMock()
        builder.llm_client = mock_llm
        assert builder._rule_extract("") == []


class TestKnowledgeGraphManager:
    def test_get_stats_empty(self, tmp_path, monkeypatch):
        from data_processor.graph_builder import KnowledgeGraphManager
        monkeypatch.setattr("data_processor.graph_builder.GRAPH_FILE", str(tmp_path / "nonexistent.json"))
        # 重置单例状态
        KnowledgeGraphManager._graph = None
        KnowledgeGraphManager._building = False
        mgr = KnowledgeGraphManager()
        mgr._graph = None
        mgr._building = False
        stats = mgr.get_stats()
        assert stats["status"] == "empty"

    def test_get_stats_ready(self, tmp_path, monkeypatch):
        from data_processor.graph_builder import KnowledgeGraphManager, KnowledgeGraph, Entity

        mgr = KnowledgeGraphManager()
        graph = KnowledgeGraph()
        graph.add_entity(Entity(name="A", entity_type="概念"))
        mgr._graph = graph

        filepath = tmp_path / "graph.json"
        monkeypatch.setattr("data_processor.graph_builder.GRAPH_FILE", str(filepath))
        graph.save(str(filepath))

        stats = mgr.get_stats()
        assert stats["entity_count"] == 1
        assert stats["file_exists"] is True
        assert stats["status"] == "ready"

    def test_invalidate(self):
        from data_processor.graph_builder import KnowledgeGraphManager
        mgr = KnowledgeGraphManager()
        mgr._graph = MagicMock()
        mgr.invalidate()
        assert mgr._graph is None
