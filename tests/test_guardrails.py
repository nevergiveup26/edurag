"""data_processor.guardrails 安全防护测试"""
import pytest
from unittest.mock import MagicMock, patch
from data_processor.guardrails import RAGGuard


# Mock source object with chunk
class MockSource:
    def __init__(self, content):
        self.chunk = MagicMock(content=content)


class TestCheckCitations:
    def test_bracket_refs(self):
        guard = RAGGuard()
        assert guard._check_citations("详见参考资料[1][2]", []) is True

    def test_ref_keywords(self):
        guard = RAGGuard()
        assert guard._check_citations("以上内容参考了相关资料", []) is True

    def test_source_keyword(self):
        guard = RAGGuard()
        assert guard._check_citations("各来源显示...", []) is True

    def test_no_citations(self):
        guard = RAGGuard()
        assert guard._check_citations("这是一段没有引用的回答，仅包含文本。", []) is False

    def test_empty_answer(self):
        guard = RAGGuard()
        assert guard._check_citations("", []) is False


class TestComputeConfidence:
    def test_no_hallucination(self):
        guard = RAGGuard()
        result = guard._compute_confidence({
            "has_hallucination": False,
            "groundedness": 0.9,
            "confidence_score": 0.9,
        })
        assert result == 0.9

    def test_hallucination_penalty(self):
        guard = RAGGuard()
        result = guard._compute_confidence({
            "has_hallucination": True,
            "groundedness": 0.9,
            "confidence_score": 0.9,
        })
        assert result < 0.9  # 0.9 * 0.7 = 0.63

    def test_bounded_0_1(self):
        guard = RAGGuard()
        assert guard._compute_confidence({"groundedness": 2.0, "has_hallucination": False, "confidence_score": 2.0}) <= 1.0
        assert guard._compute_confidence({"groundedness": -1.0, "has_hallucination": True, "confidence_score": -1.0}) >= 0.0


class TestRuleHallucinationCheck:
    def test_honest_answer_passes(self):
        guard = RAGGuard()
        result = guard._rule_hallucination_check(
            "什么是相对论",
            "据现有资料，无法准确回答该问题。",
            []
        )
        assert result["has_hallucination"] is False

    def test_no_sources_without_honesty(self):
        guard = RAGGuard()
        result = guard._rule_hallucination_check(
            "什么是相对论",
            "相对论是爱因斯坦在1905年提出的理论，包括狭义相对论和广义相对论。",
            []
        )
        assert result["has_hallucination"] is True

    def test_with_sources_keyword_overlap(self):
        sources = [MockSource("爱因斯坦在1905年提出了狭义相对论")]
        guard = RAGGuard()
        result = guard._rule_hallucination_check(
            "什么是相对论",
            "相对论是爱因斯坦在1905年提出的物理理论",
            sources
        )
        assert "groundedness" in result
        assert 0.0 <= result["groundedness"] <= 1.0

    def test_no_overlap(self):
        sources = [MockSource("光合作用是植物进行能量转换的过程")]
        guard = RAGGuard()
        result = guard._rule_hallucination_check(
            "什么是相对论",
            "相对论是爱因斯坦在1905年提出的物理理论",
            sources
        )
        assert "groundedness" in result


class TestGenerateMissingSourceWarning:
    def test_missing_citations(self):
        msg = RAGGuard.generate_missing_source_warning({
            "missing_citations": True, "has_hallucination": False, "confidence_score": 0.8
        })
        assert "未标注参考资料来源" in msg

    def test_hallucination(self):
        msg = RAGGuard.generate_missing_source_warning({
            "has_hallucination": True, "missing_citations": False, "confidence_score": 0.8
        })
        assert "不在参考资料范围内" in msg

    def test_low_confidence(self):
        msg = RAGGuard.generate_missing_source_warning({"confidence_score": 0.3})
        assert "置信度较低" in msg

    def test_all_clean(self):
        msg = RAGGuard.generate_missing_source_warning({
            "missing_citations": False,
            "has_hallucination": False,
            "confidence_score": 0.8,
        })
        assert msg == ""


class TestCheckIntegration:
    def test_full_check_no_sources(self):
        guard = RAGGuard()
        result = guard.check("什么是测试", "这是一个测试回答", sources=[])
        assert "has_hallucination" in result
        assert "confidence_score" in result
        assert "has_sources" in result
        assert result["has_sources"] is False

    def test_full_check_with_sources(self):
        sources = [MockSource("一元一次方程是只含有一个未知数的方程")]
        guard = RAGGuard()
        result = guard.check(
            "一元一次方程",
            "一元一次方程是只含有一个未知数的方程",
            sources=sources
        )
        assert "passed" in result
