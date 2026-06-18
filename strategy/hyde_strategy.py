"""
HyDE 策略：生成假设文档 → 用假设文档检索 → 返回上下文
"""
from strategy.base_strategy import BaseStrategy, StrategyResult
from core.logger import get_logger

logger = get_logger("hyde_strategy")

HYDE_PROMPT = """请根据以下问题，生成一个假设性的回答文档。
这个文档将用于向量检索，请尽可能详细地包含相关知识点。

问题：{question}

假设性回答："""


class HyDEStrategy(BaseStrategy):
    """HyDE 策略：Hypothetical Document Embeddings"""

    async def execute(self, query: str, retriever, llm, **kwargs) -> StrategyResult:
        """
        1. LLM 生成假设文档
        2. 用假设文档检索（而非原始 query）
        3. 返回检索上下文
        """
        try:
            # 1. 生成假设文档
            hyde_doc = llm.chat(
                messages=[{"role": "user", "content": HYDE_PROMPT.format(question=query)}],
                max_tokens=500,
            )
            logger.info(f"[HyDE] 假设文档生成完成: {hyde_doc[:80]}...")

            # 2. 用假设文档检索
            results = retriever.search(hyde_doc, top_k=5)
            if not results:
                # 降级：用原始 query 检索
                logger.info("[HyDE] 假设文档检索无结果，降级为原始查询检索")
                results = retriever.search(query, top_k=5)

            # 3. 拼接上下文
            context = self._format_context(results)
            return StrategyResult(
                context=context,
                metadata={"hyde_doc": hyde_doc[:200], "result_count": len(results)}
            )
        except Exception as e:
            logger.warning(f"[HyDE] 策略执行失败，降级为原始查询检索: {e}")
            try:
                results = retriever.search(query, top_k=5)
                context = self._format_context(results)
                return StrategyResult(
                    context=context,
                    metadata={"fallback": True, "error": str(e)[:100]}
                )
            except Exception:
                return StrategyResult()