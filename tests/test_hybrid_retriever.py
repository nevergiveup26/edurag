"""retriever.hybrid_retriever 混合检索器测试"""
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from core.models import DocumentChunk, RetrievalResult


def make_result(chunk_id, content="test", doc_id="d1", score=0.5, source="bm25"):
    chunk = DocumentChunk(
        chunk_id=chunk_id, doc_id=doc_id, content=content,
        metadata={}, embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32),
    )
    return RetrievalResult(chunk=chunk, score=score, source=source)


class TestHybridRetrieverInit:
    def test_default_init(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        assert retriever.bm25_retriever is not None
        assert retriever.vector_retriever is not None
        assert 0 <= retriever.bm25_weight <= 1
        assert 0 <= retriever.vector_weight <= 1
        assert retriever.bm25_weight + retriever.vector_weight == pytest.approx(1.0)
        assert retriever._doc_id_filter is None

    def test_weights_from_config(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        assert isinstance(retriever.bm25_weight, float)
        assert isinstance(retriever.vector_weight, float)


class TestBuildIndex:
    def test_build_index_delegates(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        retriever.bm25_retriever.build_index = MagicMock()
        retriever.vector_retriever.build_index = MagicMock()

        chunks = [MagicMock(), MagicMock()]
        retriever.build_index(chunks)

        retriever.bm25_retriever.build_index.assert_called_once_with(chunks)
        retriever.vector_retriever.build_index.assert_called_once_with(chunks)


class TestMergeResults:
    def test_weighted_fusion(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        retriever.bm25_weight = 0.3
        retriever.vector_weight = 0.7

        bm25_results = [make_result("c1", score=0.9, source="bm25")]
        vector_results = [make_result("c1", score=0.5, source="vector")]

        merged = retriever._merge_results(bm25_results, vector_results, top_k=5)
        assert len(merged) == 1
        # 0.3 * 0.9 + 0.7 * 0.5 = 0.27 + 0.35 = 0.62
        assert merged[0].score == pytest.approx(0.62)
        assert merged[0].source == "hybrid"

    def test_union_of_sources(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()

        bm25_results = [make_result("c1", score=0.9, source="bm25")]
        vector_results = [make_result("c2", score=0.8, source="vector")]

        merged = retriever._merge_results(bm25_results, vector_results, top_k=5)
        assert len(merged) == 2
        # c1: 0.3*0.9 + 0.7*0.0 = 0.27
        # c2: 0.3*0.0 + 0.7*0.8 = 0.56
        assert merged[0].chunk.chunk_id == "c2"  # higher score first

    def test_respects_top_k(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()

        bm25_results = [make_result(f"c{i}", score=0.5) for i in range(5)]
        vector_results = [make_result(f"c{i}", score=0.5) for i in range(3, 8)]

        merged = retriever._merge_results(bm25_results, vector_results, top_k=3)
        assert len(merged) == 3

    def test_empty_both(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        assert retriever._merge_results([], [], top_k=5) == []

    def test_only_bm25(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        retriever.bm25_weight = 0.3
        retriever.vector_weight = 0.7

        bm25_results = [make_result("c1", score=0.9, source="bm25")]
        merged = retriever._merge_results(bm25_results, [], top_k=5)
        assert len(merged) == 1
        assert merged[0].score == pytest.approx(0.27)  # 0.3*0.9 + 0.7*0.0

    def test_only_vector(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        retriever.bm25_weight = 0.3
        retriever.vector_weight = 0.7

        vector_results = [make_result("c1", score=0.8, source="vector")]
        merged = retriever._merge_results([], vector_results, top_k=5)
        assert len(merged) == 1
        assert merged[0].score == pytest.approx(0.56)  # 0.3*0.0 + 0.7*0.8


class TestSearch:
    def test_search_both(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        retriever.bm25_retriever.search = MagicMock(return_value=[
            make_result("c1", score=0.9, source="bm25"),
        ])
        retriever.vector_retriever.search = MagicMock(return_value=[
            make_result("c2", score=0.8, source="vector"),
        ])

        results = retriever.search("query", top_k=5)
        assert len(results) == 2

    def test_search_bm25_fails_uses_vector(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        retriever.bm25_retriever.search = MagicMock(side_effect=Exception("BM25 failed"))
        retriever.vector_retriever.search = MagicMock(return_value=[
            make_result("c1", score=0.8, source="vector"),
        ])

        results = retriever.search("query")
        assert len(results) == 1
        assert results[0].source == "hybrid"

    def test_search_vector_fails_uses_bm25(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        retriever.bm25_retriever.search = MagicMock(return_value=[
            make_result("c1", score=0.9, source="bm25"),
        ])
        retriever.vector_retriever.search = MagicMock(side_effect=Exception("Vector failed"))

        results = retriever.search("query")
        assert len(results) == 1

    def test_search_with_doc_id_filter_arg(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        retriever.bm25_retriever.search = MagicMock(return_value=[
            make_result("c1", doc_id="d1", score=0.9),
            make_result("c2", doc_id="d2", score=0.8),
        ])
        retriever.vector_retriever.search = MagicMock(return_value=[])

        results = retriever.search("query", top_k=5, doc_id_filter=["d1"])
        assert len(results) == 1
        assert results[0].chunk.doc_id == "d1"

    def test_search_with_instance_doc_filter(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        retriever.set_doc_filter(["d1"])
        retriever.bm25_retriever.search = MagicMock(return_value=[
            make_result("c1", doc_id="d1", score=0.9),
            make_result("c2", doc_id="d2", score=0.8),
        ])
        retriever.vector_retriever.search = MagicMock(return_value=[])

        results = retriever.search("query")
        assert len(results) == 1
        assert results[0].chunk.doc_id == "d1"

    def test_search_arg_filter_overrides_instance(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        retriever.set_doc_filter(["d_old"])
        retriever.bm25_retriever.search = MagicMock(return_value=[
            make_result("c1", doc_id="d1", score=0.9),
            make_result("c2", doc_id="d2", score=0.8),
        ])
        retriever.vector_retriever.search = MagicMock(return_value=[])
        # 显式参数优先于实例过滤器
        retriever._doc_id_filter = ["d_old"]
        results = retriever.search("query", doc_id_filter=["d1"])
        assert len(results) == 1
        assert results[0].chunk.doc_id == "d1"

    def test_search_with_metadata_filter(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        retriever.bm25_retriever.search = MagicMock(return_value=[])
        retriever.vector_retriever.search = MagicMock(return_value=[])

        results = retriever.search("query", metadata_filter={"subject": "数学"})
        retriever.bm25_retriever.search.assert_called_once()
        call_kwargs = retriever.bm25_retriever.search.call_args[1]
        assert call_kwargs["metadata_filter"] == {"subject": "数学"}


class TestDocFilter:
    def test_set_doc_filter(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        retriever.set_doc_filter(["d1", "d2"])
        assert retriever._doc_id_filter == ["d1", "d2"]

    def test_set_doc_filter_empty(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        retriever._doc_id_filter = ["d1"]
        retriever.set_doc_filter([])
        assert retriever._doc_id_filter is None

    def test_clear_doc_filter(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        retriever._doc_id_filter = ["d1"]
        retriever.clear_doc_filter()
        assert retriever._doc_id_filter is None


class TestAddDocuments:
    def test_add_documents_delegates(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        retriever.bm25_retriever.add_documents = MagicMock()
        retriever.vector_retriever.add_documents = MagicMock()

        chunks = [MagicMock()]
        retriever.add_documents(chunks)

        retriever.bm25_retriever.add_documents.assert_called_once_with(chunks)
        retriever.vector_retriever.add_documents.assert_called_once_with(chunks)


class TestGetIndexStats:
    def test_stats(self):
        from retriever.hybrid_retriever import HybridRetriever
        retriever = HybridRetriever()
        retriever.bm25_retriever.get_index_stats = MagicMock(return_value={"num_documents": 5, "type": "BM25"})
        retriever.vector_retriever.get_index_stats = MagicMock(return_value={"num_documents": 5, "type": "Vector"})

        stats = retriever.get_index_stats()
        assert stats["type"] == "Hybrid"
        assert stats["bm25"]["num_documents"] == 5
        assert stats["vector"]["num_documents"] == 5
        assert "bm25_weight" in stats
        assert "vector_weight" in stats
