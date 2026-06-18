"""data_processor.query_rewriter 查询重写测试"""
import pytest
from data_processor.query_rewriter import QueryRewriter


class TestShouldRewrite:
    def test_short_query(self):
        rw = QueryRewriter()
        assert rw._should_rewrite("乘法", None) is True

    def test_query_8_chars_or_less(self):
        rw = QueryRewriter()
        assert rw._should_rewrite("12345678", None) is True
        assert rw._should_rewrite("123456789", None) is False  # 9 chars, no pronoun

    def test_pronoun_keywords(self):
        rw = QueryRewriter()
        assert rw._should_rewrite("这个东西怎么解", None) is True
        assert rw._should_rewrite("那个怎么做", None) is True
        assert rw._should_rewrite("它是什么意思", None) is True
        assert rw._should_rewrite("这些怎么算", None) is True
        assert rw._should_rewrite("怎么算这个", None) is True

    def test_short_question(self):
        rw = QueryRewriter()
        assert rw._should_rewrite("为什么地球是圆的", None) is True   # 开头"为什么" + < 15 chars
        assert rw._should_rewrite("怎么解一元一次方程", None) is True  # 开头"怎么" + < 15 chars
        assert rw._should_rewrite("什么是光合作用", None) is True      # 开头"什么是" + < 15 chars

    def test_short_question_not_triggered_when_long(self):
        rw = QueryRewriter()
        # 开头是"为什么"但超过15字符 → 不触发（没有代词）
        long_q = "为什么一元一次方程要移项合并同类项"
        assert rw._should_rewrite(long_q, None) is False  # > 15 chars

    def test_with_history(self):
        rw = QueryRewriter()
        history = [{"role": "user", "content": "什么是勾股定理"}, {"role": "assistant", "content": "勾股定理是..."}]
        assert rw._should_rewrite("那它怎么用", history) is True  # 有历史 + 代词

    def test_no_history_and_clear_query(self):
        rw = QueryRewriter()
        assert rw._should_rewrite("勾股定理的定义和证明方法", None) is False

    def test_no_history_but_short(self):
        rw = QueryRewriter()
        # 没有历史，没有代词，但有为什么开头
        assert rw._should_rewrite("为什么", None) is True

    def test_how_to_calculate_triggered(self):
        rw = QueryRewriter()
        assert rw._should_rewrite("怎么算这道数学题", None) is True  # "怎么算" 是 pronoun_keywords
