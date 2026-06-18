"""retriever.bm25_retriever BM25检索器测试"""
import sys
import pytest
from unittest.mock import MagicMock, patch
import numpy as np
from core.models import DocumentChunk
from retriever.bm25_retriever import BM25Retriever


def make_chunk(content, chunk_id="c1", doc_id="d1", metadata=None):
    return DocumentChunk(
        content=content, chunk_id=chunk_id, doc_id=doc_id,
        metadata=metadata or {},
    )


def _install_mock_rank_bm25(mock_instance=None):
    """注入 mock rank_bm25 模块，让 build_index 能 import 到"""
    if mock_instance is None:
        mock_instance = MagicMock()
    mock_module = MagicMock()
    mock_module.BM25Okapi = MagicMock(return_value=mock_instance)
    sys.modules["rank_bm25"] = mock_module
    return mock_instance, mock_module


def _install_mock_jieba():
    """注入 mock jieba 模块"""
    mock_jieba = MagicMock()
    mock_jieba.cut = lambda text: list(text)
    sys.modules["jieba"] = mock_jieba
    return mock_jieba


def _cleanup_modules():
    for mod in ["rank_bm25", "jieba"]:
        sys.modules.pop(mod, None)


class TestBM25Init:
    def test_initial_state(self):
        retriever = BM25Retriever()
        assert retriever._bm25 is None
        assert retriever._corpus == []
        assert retriever._chunks == []
        assert retriever._dirty is False


class TestBuildIndex:
    def test_build_with_rank_bm25(self):
        try:
            mock_bm25, _ = _install_mock_rank_bm25()
            _install_mock_jieba()

            retriever = BM25Retriever()
            chunks = [make_chunk("测试文档一"), make_chunk("测试文档二")]
            retriever.build_index(chunks)

            assert retriever._bm25 is not None
            assert not retriever._dirty
        finally:
            _cleanup_modules()

    def test_build_index_clears_dirty_flag(self):
        try:
            _install_mock_rank_bm25()
            _install_mock_jieba()

            retriever = BM25Retriever()
            retriever.add_documents([make_chunk("新文档")])
            assert retriever._dirty is True

            retriever.build_index(retriever._chunks)
            assert not retriever._dirty
        finally:
            _cleanup_modules()


class TestSearch:
    def test_no_index_returns_empty(self):
        retriever = BM25Retriever()
        results = retriever.search("测试查询")
        assert results == []

    def test_search_returns_results(self):
        try:
            mock_bm25 = MagicMock()
            mock_bm25.get_scores.return_value = np.array([0.5, 0.8, 0.1])
            _install_mock_rank_bm25(mock_bm25)
            _install_mock_jieba()

            retriever = BM25Retriever()
            chunks = [make_chunk(f"chunk_{i}") for i in range(3)]
            retriever.build_index(chunks)

            results = retriever.search("查询", top_k=2)
            assert len(results) <= 2
            if len(results) >= 1:
                assert results[0].source == "bm25"
        finally:
            _cleanup_modules()

    def test_search_zero_scores_filtered(self):
        try:
            mock_bm25 = MagicMock()
            mock_bm25.get_scores.return_value = np.array([0.0, 0.0])
            _install_mock_rank_bm25(mock_bm25)
            _install_mock_jieba()

            retriever = BM25Retriever()
            retriever.build_index([make_chunk("a"), make_chunk("b")])

            results = retriever.search("query")
            assert results == []
        finally:
            _cleanup_modules()


class TestDirtyFlag:
    def test_add_documents_sets_dirty(self):
        retriever = BM25Retriever()
        retriever.add_documents([make_chunk("新文档")])
        assert retriever._dirty is True
        assert len(retriever._pending_chunks) == 1

    def test_rebuild_if_dirty(self):
        try:
            _install_mock_rank_bm25()
            _install_mock_jieba()

            retriever = BM25Retriever()
            retriever.build_index([make_chunk("初始")])
            assert not retriever._dirty

            retriever.add_documents([make_chunk("新增")])
            assert retriever._dirty is True

            retriever._rebuild_if_dirty()
            assert not retriever._dirty
        finally:
            _cleanup_modules()

    def test_add_multiple_batches(self):
        retriever = BM25Retriever()
        retriever.add_documents([make_chunk("a")])
        retriever.add_documents([make_chunk("b"), make_chunk("c")])
        assert len(retriever._chunks) == 3
        assert len(retriever._pending_chunks) == 3


class TestGetIndexStats:
    def test_empty_stats(self):
        retriever = BM25Retriever()
        stats = retriever.get_index_stats()
        assert stats["num_documents"] == 0
        assert stats["type"] == "BM25"

    def test_after_build(self):
        try:
            _install_mock_rank_bm25()
            _install_mock_jieba()

            retriever = BM25Retriever()
            retriever.build_index([make_chunk("a"), make_chunk("b"), make_chunk("c")])
            stats = retriever.get_index_stats()
            assert stats["num_documents"] == 3
        finally:
            _cleanup_modules()


class TestTokenize:
    def test_with_jieba(self):
        try:
            mock_jieba = MagicMock()
            mock_jieba.cut.return_value = ["测试", "文档"]
            sys.modules["jieba"] = mock_jieba

            retriever = BM25Retriever()
            tokens = retriever._tokenize(["测试文档"])
            assert len(tokens) == 1
            assert "测试" in tokens[0]
        finally:
            _cleanup_modules()

    def test_tokenize_search_query(self):
        try:
            _install_mock_rank_bm25()
            _install_mock_jieba()

            retriever = BM25Retriever()
            retriever.build_index([make_chunk("一元一次方程的解法步骤")])

            # verify tokenizer used in search
            assert retriever._tokenized_corpus == [['一', '元', '一', '次', '方', '程', '的', '解', '法', '步', '骤']]
        finally:
            _cleanup_modules()
