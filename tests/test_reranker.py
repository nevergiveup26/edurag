"""retriever.reranker 云端重排序测试"""
import pytest
from unittest.mock import MagicMock, patch
import numpy as np
from core.models import DocumentChunk, RetrievalResult


def make_result(chunk_id, content="test content", score=0.5, source="hybrid"):
    chunk = DocumentChunk(
        chunk_id=chunk_id, doc_id="d1", content=content,
        metadata={}, embedding=np.array([0.1, 0.2], dtype=np.float32),
    )
    return RetrievalResult(chunk=chunk, score=score, source=source)


class TestRerankerInit:
    def test_default_init(self):
        from retriever.reranker import Reranker
        reranker = Reranker()
        assert reranker.model_name == "qwen3-rerank"
        assert reranker.rerank_top_k == 3
        assert reranker._timeout == 30

    def test_custom_model(self):
        from retriever.reranker import Reranker
        reranker = Reranker(model_name="gte-rerank-v2")
        assert reranker.model_name == "gte-rerank-v2"


class TestCallRerankAPI:
    def test_success(self):
        from retriever.reranker import Reranker
        reranker = Reranker()
        reranker._api_key = "test-key"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"index": 0, "relevance_score": 0.93},
                {"index": 2, "relevance_score": 0.45},
            ]
        }
        with patch("retriever.reranker.requests.post", return_value=mock_response):
            scores = reranker._call_rerank_api("query", ["doc1", "doc2", "doc3"])
            assert len(scores) == 3
            assert scores[0] == 0.93
            assert scores[1] == 0.0  # 未返回
            assert scores[2] == 0.45

    def test_empty_documents(self):
        from retriever.reranker import Reranker
        reranker = Reranker()
        scores = reranker._call_rerank_api("query", [])
        assert scores == []

    def test_truncates_to_4000_chars(self):
        from retriever.reranker import Reranker
        reranker = Reranker()
        reranker._api_key = "test-key"

        mock_response = MagicMock()
        mock_response.json.return_value = {"results": [{"index": 0, "relevance_score": 0.5}]}

        with patch("retriever.reranker.requests.post") as mock_post:
            mock_post.return_value = mock_response
            long_doc = "x" * 5000
            reranker._call_rerank_api("query", [long_doc])
            # 验证截断
            sent_doc = mock_post.call_args[1]["json"]["documents"][0]
            assert len(sent_doc) == 4000

    def test_request_exception(self):
        from retriever.reranker import Reranker
        reranker = Reranker()
        reranker._api_key = "test-key"

        import requests as req_mod
        with patch("retriever.reranker.requests.post", side_effect=req_mod.exceptions.ConnectionError("timeout")):
            with pytest.raises(req_mod.exceptions.RequestException):
                reranker._call_rerank_api("query", ["doc1"])

    def test_empty_results_key(self):
        """响应缺少 results 键时返回全零分数列表"""
        from retriever.reranker import Reranker
        reranker = Reranker()
        reranker._api_key = "test-key"

        mock_response = MagicMock()
        mock_response.json.return_value = {"invalid": "no results key"}
        mock_response.raise_for_status = MagicMock()

        with patch("retriever.reranker.requests.post", return_value=mock_response):
            scores = reranker._call_rerank_api("query", ["doc1"])
            assert scores == [0.0]  # 默认全零


class TestRerank:
    def test_disabled(self):
        from retriever.reranker import Reranker
        reranker = Reranker()
        reranker.enabled = False
        results = [make_result("c1", score=0.5), make_result("c2", score=0.8)]
        reranked = reranker.rerank("query", results, top_k=2)
        # 原样返回（按原始顺序）
        assert len(reranked) == 2

    def test_empty_results(self):
        from retriever.reranker import Reranker
        reranker = Reranker()
        assert reranker.rerank("query", []) == []

    def test_rerank_success(self):
        from retriever.reranker import Reranker
        reranker = Reranker()
        reranker._api_key = "test-key"
        reranker.rerank_top_k = 2

        results = [
            make_result("c1", score=0.5),
            make_result("c2", score=0.8),
            make_result("c3", score=0.3),
        ]

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"index": 0, "relevance_score": 0.2},
                {"index": 1, "relevance_score": 0.9},
                {"index": 2, "relevance_score": 0.6},
            ]
        }

        with patch("retriever.reranker.requests.post", return_value=mock_response):
            reranked = reranker.rerank("query", results)
            assert len(reranked) == 2
            # 第一个应该是 c2 (score=0.9)
            assert reranked[0].chunk.chunk_id == "c2"

    def test_rerank_api_failure_fallback(self):
        from retriever.reranker import Reranker
        reranker = Reranker()
        reranker.rerank_top_k = 2

        results = [
            make_result("c1", score=0.3),
            make_result("c2", score=0.9),
        ]

        with patch("retriever.reranker.requests.post", side_effect=Exception("API down")):
            reranked = reranker.rerank("query", results)
            assert len(reranked) == 2
            assert reranked[0].chunk.chunk_id == "c2"  # 原始高分在前

    def test_rerank_no_results_returns_empty(self):
        from retriever.reranker import Reranker
        reranker = Reranker()
        reranker.enabled = True
        assert reranker.rerank("query", []) == []


class TestFallbackRerank:
    def test_fallback_sorts_by_score(self):
        from retriever.reranker import Reranker
        reranker = Reranker()
        results = [
            make_result("c1", score=0.3),
            make_result("c2", score=0.9),
            make_result("c3", score=0.5),
        ]
        sorted_results = reranker._fallback_rerank(results, top_k=2)
        assert len(sorted_results) == 2
        assert sorted_results[0].chunk.chunk_id == "c2"
        assert sorted_results[1].chunk.chunk_id == "c3"


class TestCrossEncode:
    def test_cross_encode_success(self):
        from retriever.reranker import Reranker
        reranker = Reranker()
        reranker._api_key = "test-key"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [{"index": 0, "relevance_score": 0.7}, {"index": 1, "relevance_score": 0.3}]
        }

        with patch("retriever.reranker.requests.post", return_value=mock_response):
            scores = reranker.cross_encode("query", ["doc1", "doc2"])
            assert scores == [0.7, 0.3]

    def test_cross_encode_failure(self):
        from retriever.reranker import Reranker
        reranker = Reranker()

        with patch("retriever.reranker.requests.post", side_effect=Exception("API error")):
            scores = reranker.cross_encode("query", ["doc1", "doc2"])
            assert scores == [0.5, 0.5]  # fallback 返回 0.5


class TestRerankWithScores:
    def test_rerank_with_scores(self):
        from retriever.reranker import Reranker
        reranker = Reranker()
        reranker._api_key = "test-key"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [{"index": 0, "relevance_score": 0.3}, {"index": 1, "relevance_score": 0.9}]
        }

        with patch("retriever.reranker.requests.post", return_value=mock_response):
            pairs = reranker.rerank_with_scores("query", ["doc1", "doc2"], top_k=1)
            assert len(pairs) == 1
            assert pairs[0][0] == "doc2"
            assert pairs[0][1] == 0.9

    def test_rerank_with_scores_no_top_k(self):
        from retriever.reranker import Reranker
        reranker = Reranker()
        reranker._api_key = "test-key"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [{"index": 0, "relevance_score": 0.3}, {"index": 1, "relevance_score": 0.9}]
        }

        with patch("retriever.reranker.requests.post", return_value=mock_response):
            pairs = reranker.rerank_with_scores("query", ["doc1", "doc2"])
            assert len(pairs) == 2


class TestGetModelInfo:
    def test_model_info(self):
        from retriever.reranker import Reranker
        reranker = Reranker()
        info = reranker.get_model_info()
        assert info["model_name"] == "qwen3-rerank"
        assert "enabled" in info
        assert "loaded" in info

    def test_loaded_true_with_key(self):
        from retriever.reranker import Reranker
        reranker = Reranker()
        reranker._api_key = "sk-test"
        info = reranker.get_model_info()
        assert info["loaded"] is True

    def test_loaded_false_without_key(self):
        from retriever.reranker import Reranker
        reranker = Reranker()
        reranker._api_key = ""
        info = reranker.get_model_info()
        assert info["loaded"] is False


class TestListModels:
    def test_list_models(self):
        from retriever.reranker import Reranker
        models = Reranker.list_models()
        assert len(models) >= 2
        assert any(m["name"] == "qwen3-rerank" for m in models)
        assert any(m["name"] == "gte-rerank-v2" for m in models)
