"""data_processor.context_compressor 上下文压缩器测试"""
import pytest
from unittest.mock import MagicMock, patch
from core.models import DocumentChunk, RetrievalResult


def make_result(chunk_id, content, score=0.5):
    chunk = DocumentChunk(
        chunk_id=chunk_id, doc_id="d1", content=content, metadata={},
    )
    return RetrievalResult(chunk=chunk, score=score, source="vector")


class TestContextCompressorInit:
    def test_default_init(self):
        from data_processor.context_compressor import ContextCompressor
        compressor = ContextCompressor()
        assert compressor.max_input_chars == 8000
        assert compressor.max_compressed_chars == 3000
        assert compressor.llm_client is not None


class TestCompress:
    def test_below_threshold_no_compress(self):
        from data_processor.context_compressor import ContextCompressor
        compressor = ContextCompressor()
        compressor.llm_client = MagicMock()

        results = [make_result("c1", "短内容")]
        result = compressor.compress("query", results)
        # 内容短，不触发压缩，返回原始格式
        assert "[1]" in result
        assert "短内容" in result
        compressor.llm_client.generate.assert_not_called()

    def test_empty_chunks(self):
        from data_processor.context_compressor import ContextCompressor
        compressor = ContextCompressor()
        result = compressor.compress("query", [])
        assert result == ""

    def test_all_empty_content(self):
        from data_processor.context_compressor import ContextCompressor
        compressor = ContextCompressor()
        r = make_result("c1", "")
        result = compressor.compress("query", [r])
        assert result == ""

    def test_above_threshold_triggers_compress(self):
        from data_processor.context_compressor import ContextCompressor
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "压缩后的内容摘要——这是更长的测试文本以确保超过20字"

        with patch("llm.llm_client.get_fast_llm", return_value=mock_llm):
            compressor = ContextCompressor()

        long_content = "长内容" * 500
        results = [make_result(f"c{i}", long_content) for i in range(10)]
        result = compressor.compress("query", results, max_input=100)
        mock_llm.generate.assert_called_once()
        assert "压缩后的内容摘要" in result

    def test_llm_failure_fallback_to_raw(self):
        from data_processor.context_compressor import ContextCompressor
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = Exception("LLM error")

        with patch("llm.llm_client.get_fast_llm", return_value=mock_llm):
            compressor = ContextCompressor()

        results = [make_result("c1", "内容" * 500)]
        result = compressor.compress("query", results, max_input=50)
        assert "[1]" in result

    def test_short_llm_result_ignored(self):
        from data_processor.context_compressor import ContextCompressor
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "短"  # < 20 chars

        with patch("llm.llm_client.get_fast_llm", return_value=mock_llm):
            compressor = ContextCompressor()

        results = [make_result("c1", "内容" * 300)]
        result = compressor.compress("query", results, max_input=50)
        assert "[1]" in result

    def test_dict_chunks(self):
        """兼容 dict 格式的 chunk"""
        from data_processor.context_compressor import ContextCompressor
        compressor = ContextCompressor()
        compressor.llm_client = MagicMock()

        results = [{"content": "测试内容"}]
        result = compressor.compress("query", results)
        assert "[1] 测试内容" in result


class TestCompressForPrompt:
    def test_below_limit(self):
        from data_processor.context_compressor import ContextCompressor
        compressor = ContextCompressor()
        compressor.llm_client = MagicMock()

        results = [make_result("c1", "短")]
        result = compressor.compress_for_prompt("query", results, max_context_chars=4000)
        assert "短" in result

    def test_above_limit_truncates(self):
        from data_processor.context_compressor import ContextCompressor
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "测" * 5000

        with patch("llm.llm_client.get_fast_llm", return_value=mock_llm):
            compressor = ContextCompressor()

        results = [make_result("c1", "原始" * 300)]
        result = compressor.compress_for_prompt("query", results, max_context_chars=100)
        assert len(result) <= 100 + 50

    def test_truncate_at_sentence_boundary(self):
        from data_processor.context_compressor import ContextCompressor
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "第一句话。" * 100

        with patch("llm.llm_client.get_fast_llm", return_value=mock_llm):
            compressor = ContextCompressor()

        results = [make_result("c1", "原始" * 300)]
        result = compressor.compress_for_prompt("query", results, max_context_chars=200)
        assert result.endswith("...(内容已截断)")
