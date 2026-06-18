"""data_processor.self_rag Self-RAG评估测试"""
import pytest
from unittest.mock import MagicMock


class TestIsSimpleQuery:
    def test_short_who_query(self):
        from data_processor.self_rag import SelfRAGEvaluator
        assert SelfRAGEvaluator.is_simple_query("勾股定理是谁发现的") is True

    def test_short_what_query(self):
        from data_processor.self_rag import SelfRAGEvaluator
        assert SelfRAGEvaluator.is_simple_query("什么是勾股定理") is True

    def test_short_definition(self):
        from data_processor.self_rag import SelfRAGEvaluator
        assert SelfRAGEvaluator.is_simple_query("函数的定义") is True

    def test_short_concept(self):
        from data_processor.self_rag import SelfRAGEvaluator
        assert SelfRAGEvaluator.is_simple_query("一元一次方程概念") is True

    def test_long_query_not_simple(self):
        from data_processor.self_rag import SelfRAGEvaluator
        long_q = "请详细解释牛顿第二定律在生活中的应用场景，并给出具体的例子说明"
        assert SelfRAGEvaluator.is_simple_query(long_q) is False

    def test_short_formula(self):
        from data_processor.self_rag import SelfRAGEvaluator
        assert SelfRAGEvaluator.is_simple_query("勾股定理公式") is True

    def test_which_query(self):
        from data_processor.self_rag import SelfRAGEvaluator
        assert SelfRAGEvaluator.is_simple_query("哪个国家人口最多") is True

    def test_where_query(self):
        from data_processor.self_rag import SelfRAGEvaluator
        assert SelfRAGEvaluator.is_simple_query("珠穆朗玛峰在哪里") is True


class TestParseJson:
    def test_plain_json(self):
        from data_processor.self_rag import SelfRAGEvaluator
        evaluator = SelfRAGEvaluator()
        result = evaluator._parse_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_with_markdown(self):
        from data_processor.self_rag import SelfRAGEvaluator
        evaluator = SelfRAGEvaluator()
        text = '```json\n{"score": 0.8}\n```'
        result = evaluator._parse_json(text)
        assert result == {"score": 0.8}

    def test_json_with_plain_markdown(self):
        from data_processor.self_rag import SelfRAGEvaluator
        evaluator = SelfRAGEvaluator()
        text = '```\n{"x": 1}\n```'
        result = evaluator._parse_json(text)
        assert result == {"x": 1}

    def test_regex_fallback(self):
        from data_processor.self_rag import SelfRAGEvaluator
        evaluator = SelfRAGEvaluator()
        text = '前缀内容 {"a": 1, "b": 2} 后缀内容'
        result = evaluator._parse_json(text)
        assert result == {"a": 1, "b": 2}

    def test_empty_text(self):
        from data_processor.self_rag import SelfRAGEvaluator
        evaluator = SelfRAGEvaluator()
        assert evaluator._parse_json("") is None

    def test_invalid_text(self):
        from data_processor.self_rag import SelfRAGEvaluator
        evaluator = SelfRAGEvaluator()
        assert evaluator._parse_json("not json at all") is None


class TestEvaluate:
    def test_evaluate_success(self):
        from data_processor.self_rag import SelfRAGEvaluator
        evaluator = SelfRAGEvaluator()
        mock_llm = MagicMock()
        mock_llm.generate.return_value = '{"overall": 0.85, "is_acceptable": true, "hallucination": 9, "missing_citations": false, "issues": [], "refined_query": ""}'
        evaluator.llm_client = mock_llm

        result = evaluator.evaluate("query", "answer")
        assert result["overall"] == 0.85
        assert result["is_acceptable"] is True

    def test_evaluate_with_sources(self):
        from data_processor.self_rag import SelfRAGEvaluator
        evaluator = SelfRAGEvaluator()
        mock_llm = MagicMock()
        mock_llm.generate.return_value = '{"overall": 0.7, "is_acceptable": true, "hallucination": 7, "missing_citations": false, "issues": [], "refined_query": ""}'
        evaluator.llm_client = mock_llm

        mock_source = MagicMock()
        mock_source.chunk.content = "source content"

        result = evaluator.evaluate("query", "answer", sources=[mock_source])
        assert result["overall"] == 0.7

    def test_evaluate_llm_failure(self):
        from data_processor.self_rag import SelfRAGEvaluator
        evaluator = SelfRAGEvaluator()
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = Exception("LLM error")
        evaluator.llm_client = mock_llm

        result = evaluator.evaluate("query", "answer")
        assert result["overall"] == 0.8  # 默认
        assert result["is_acceptable"] is True


class TestShouldRetrieve:
    def test_score_below_threshold(self):
        from data_processor.self_rag import SelfRAGEvaluator
        evaluator = SelfRAGEvaluator()
        assert evaluator.should_retrieve({"overall": 0.5}) is True

    def test_score_above_threshold(self):
        from data_processor.self_rag import SelfRAGEvaluator
        evaluator = SelfRAGEvaluator()
        assert evaluator.should_retrieve({"overall": 0.8}) is False

    def test_not_acceptable(self):
        from data_processor.self_rag import SelfRAGEvaluator
        evaluator = SelfRAGEvaluator()
        assert evaluator.should_retrieve({"overall": 0.9, "is_acceptable": False}) is True


class TestGetRefinedQuery:
    def test_has_refined_query(self):
        from data_processor.self_rag import SelfRAGEvaluator
        evaluator = SelfRAGEvaluator()
        result = evaluator.get_refined_query({"refined_query": "优化查询"})
        assert result == "优化查询"

    def test_no_refined_query(self):
        from data_processor.self_rag import SelfRAGEvaluator
        evaluator = SelfRAGEvaluator()
        assert evaluator.get_refined_query({}) == ""


class TestGetGuardResult:
    def test_good_result(self):
        from data_processor.self_rag import SelfRAGEvaluator
        evaluator = SelfRAGEvaluator()
        guard = evaluator.get_guard_result({
            "hallucination": 8, "missing_citations": False,
            "overall": 0.85, "issues": [],
        })
        assert guard["passed"] is True
        assert guard["has_hallucination"] is False
        assert guard["confidence_score"] == 0.85

    def test_bad_result(self):
        from data_processor.self_rag import SelfRAGEvaluator
        evaluator = SelfRAGEvaluator()
        guard = evaluator.get_guard_result({
            "hallucination": 3, "missing_citations": True,
            "overall": 0.3, "issues": ["factual error"],
        })
        assert guard["passed"] is False
        assert guard["has_hallucination"] is True
        assert guard["missing_citations"] is True
