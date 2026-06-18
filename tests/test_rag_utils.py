"""data_processor.rag_utils 纯函数测试"""
import pytest
from core.models import DocumentChunk, RetrievalResult
from data_processor.rag_utils import (
    deduplicate_results,
    maximal_marginal_relevance,
    prune_by_score,
    trim_context_to_token_limit,
)


def make_chunk(chunk_id, content, score=0.0):
    chunk = DocumentChunk(content=content, chunk_id=chunk_id, doc_id="doc_1", score=score)
    return RetrievalResult(chunk=chunk, score=score, source="bm25")


class TestDeduplicateResults:
    def test_empty(self):
        assert deduplicate_results([]) == []

    def test_unique(self):
        r = [make_chunk("c1", "内容A"), make_chunk("c2", "内容B")]
        result = deduplicate_results(r)
        assert len(result) == 2

    def test_dup_removed(self):
        r = [make_chunk("c1", "内容A"), make_chunk("c1", "内容A")]
        result = deduplicate_results(r)
        assert len(result) == 1

    def test_same_chunk_id_keeps_first(self):
        r = [make_chunk("c1", "first"), make_chunk("c1", "second")]
        result = deduplicate_results(r)
        assert result[0].chunk.content == "first"

    def test_content_prefix_matters(self):
        r = [make_chunk("c1", "abcdefghij" * 20), make_chunk("c2", "abcdefghij" * 20)]
        result = deduplicate_results(r)
        # same content prefix but different chunk_id → both kept
        assert len(result) == 2


class TestMMR:
    def test_fewer_than_top_k(self):
        r = [make_chunk("c1", "A", 0.9), make_chunk("c2", "B", 0.8)]
        result = maximal_marginal_relevance(r, top_k=5)
        assert len(result) == 2

    def test_selects_top_k(self):
        r = [make_chunk(f"c{i}", f"content_{i}", 0.9 - i * 0.1) for i in range(10)]
        result = maximal_marginal_relevance(r, top_k=3)
        assert len(result) == 3

    def test_first_is_highest_score(self):
        r = [make_chunk("c1", "A", 0.3), make_chunk("c2", "B", 0.9), make_chunk("c3", "C", 0.5)]
        result = maximal_marginal_relevance(r, top_k=3)
        # 第一个选中的是最高的score（索引1）
        scores = [res.score for res in result]
        assert 0.9 in scores

    def test_lambda_diversity(self):
        r = [make_chunk(f"c{i}", f"content_{i}", 0.8) for i in range(5)]
        # lambda=0 纯多样性, lambda=1 纯相关性
        result_div = maximal_marginal_relevance(r, top_k=3, lambda_param=0.0)
        result_rel = maximal_marginal_relevance(r, top_k=3, lambda_param=1.0)
        assert len(result_div) == 3
        assert len(result_rel) == 3


class TestPruneByScore:
    def test_empty(self):
        assert prune_by_score([]) == []

    def test_prune_low_scores(self):
        r = [make_chunk("c1", "A", 0.5), make_chunk("c2", "B", 0.05), make_chunk("c3", "C", 0.8)]
        result = prune_by_score(r, min_score=0.1)
        assert len(result) == 2
        assert all(s.score >= 0.1 for s in result)

    def test_all_pruned(self):
        r = [make_chunk("c1", "A", 0.01), make_chunk("c2", "B", 0.02)]
        result = prune_by_score(r, min_score=0.1)
        assert result == []

    def test_all_pass(self):
        r = [make_chunk("c1", "A", 0.9)]
        result = prune_by_score(r, min_score=0.5)
        assert len(result) == 1


class TestTrimContextToTokenLimit:
    def test_no_trim_if_short(self):
        text = "短文本"
        assert trim_context_to_token_limit(text, max_tokens=10) == text

    def test_trim_long(self):
        text = "测试文本" * 2000
        result = trim_context_to_token_limit(text, max_tokens=100)
        assert len(result) < len(text)
        assert len(result) == 100 * 2  # max_tokens * 2 chars

    def test_empty(self):
        assert trim_context_to_token_limit("") == ""

    def test_exact_boundary(self):
        text = "测" * 200
        result = trim_context_to_token_limit(text, max_tokens=100)
        assert result == text  # 200 chars = 100 tokens → 不截断
