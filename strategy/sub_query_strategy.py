"""
子查询分解策略：分解为子问题 → 分别检索 → 拼接上下文
"""
import json
import re

from strategy.base_strategy import BaseStrategy, StrategyResult
from core.logger import get_logger

logger = get_logger("sub_query_strategy")

DECOMPOSE_PROMPT = """请将以下复杂问题分解为多个子问题，以便分别检索相关信息。

原始问题：{question}

请以JSON数组格式返回子问题列表，例如：
["子问题1", "子问题2", "子问题3"]

子问题列表："""


class SubQueryStrategy(BaseStrategy):
    """子查询分解策略"""

    MAX_SUB_QUERIES = 5

    async def execute(self, query: str, retriever, llm, **kwargs) -> StrategyResult:
        """
        1. LLM 分解为子问题
        2. 逐个子问题检索（每个 top_k=3）
        3. 拼接所有上下文
        """
        try:
            # 1. LLM 分解
            raw = llm.chat(
                messages=[{"role": "user", "content": DECOMPOSE_PROMPT.format(question=query)}],
                max_tokens=300,
            )
            sub_queries = self._parse_sub_queries(raw)
            if not sub_queries:
                logger.info("[SubQuery] 分解失败，降级为原始查询检索")
                results = retriever.search(query, top_k=5)
                context = self._format_context(results)
                return StrategyResult(
                    context=context,
                    metadata={"fallback": True, "sub_queries": []}
                )
            logger.info(f"[SubQuery] 分解出 {len(sub_queries)} 个子问题: {sub_queries}")

            # 2. 逐个子问题检索
            all_contexts = []
            for sq in sub_queries[:self.MAX_SUB_QUERIES]:
                results = retriever.search(sq, top_k=3)
                ctx = self._format_context(results)
                if ctx:
                    all_contexts.append(f"[子问题: {sq}]\n{ctx}")

            if not all_contexts:
                # 降级
                logger.info("[SubQuery] 所有子问题检索为空，降级为原始查询检索")
                results = retriever.search(query, top_k=5)
                context = self._format_context(results)
                return StrategyResult(
                    context=context,
                    metadata={"sub_queries": sub_queries, "fallback": True}
                )

            # 3. 拼接
            context = "\n\n---\n\n".join(all_contexts)
            return StrategyResult(
                context=context,
                metadata={"sub_queries": sub_queries, "result_count": len(all_contexts)}
            )
        except Exception as e:
            logger.warning(f"[SubQuery] 策略执行失败，降级为原始查询检索: {e}")
            try:
                results = retriever.search(query, top_k=5)
                return StrategyResult(
                    context=self._format_context(results),
                    metadata={"fallback": True, "error": str(e)[:100]}
                )
            except Exception:
                return StrategyResult()

    def _parse_sub_queries(self, raw: str) -> list:
        """解析 LLM 返回的 JSON 数组"""
        try:
            result = json.loads(raw.strip())
            if isinstance(result, list) and all(isinstance(q, str) for q in result):
                return result
        except json.JSONDecodeError:
            pass
        # 尝试从文本中提取 JSON 数组
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(0))
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass
        return []