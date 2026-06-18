"""
回溯检索策略：检索 → 质量评估 → 不满足则换源重检
"""
import json
import re

from strategy.base_strategy import BaseStrategy, StrategyResult
from core.logger import get_logger

logger = get_logger("backtrack_strategy")

QUALITY_EVAL_PROMPT = """请评估以下参考资料对回答问题的充分程度，给出0-1之间的评分。

问题：{question}

参考资料：
{context}

评分标准：
- 0.0-0.3: 资料严重不足，无法回答
- 0.3-0.6: 资料部分相关，但不完整
- 0.6-0.8: 资料较充分，基本可以回答
- 0.8-1.0: 资料非常充分，可以完整回答

仅返回一个0-1之间的数字评分："""

QUERY_REFINE_PROMPT = """基于以下原始问题和当前检索到的信息，生成一个新的查询以便获取更相关的信息。

原始问题：{question}

当前检索结果：
{context}

请生成一个更精确的查询："""


class BacktrackStrategy(BaseStrategy):
    """回溯检索策略：最多 2 轮，第 2 轮切换搜索源"""

    MAX_ROUNDS = 2
    QUALITY_THRESHOLD = 0.6

    async def execute(self, query: str, retriever, llm, web_search_fn=None, **kwargs) -> StrategyResult:
        """
        1. 第 1 轮：本地知识库检索
        2. 质量评估：评分 >= 0.6 则直接返回
        3. 不满足：优化查询 + 第 2 轮联网搜索
        """
        all_contexts = []
        metadata = {"rounds": 1, "score": 0.0}

        try:
            # 第 1 轮：本地检索
            results = retriever.search(query, top_k=5)
            context_1 = self._format_context(results)
            all_contexts.append("[本地知识库检索结果]\n" + context_1)

            # 质量评估
            if context_1.strip():
                score = self._evaluate_quality(query, context_1, llm)
                metadata["score"] = score
                logger.info(f"[Backtrack] 第 1 轮质量评分: {score:.2f}")
            else:
                score = 0.0
                metadata["score"] = 0.0
                logger.info("[Backtrack] 第 1 轮检索为空，直接进入第 2 轮")

            if score >= self.QUALITY_THRESHOLD:
                logger.info("[Backtrack] 质量达标，直接返回")
                return StrategyResult(
                    context=context_1,
                    metadata=metadata
                )

            # 第 2 轮：优化查询 + 联网搜索
            logger.info("[Backtrack] 质量不足，进入第 2 轮联网搜索")
            refined_query = self._refine_query(query, context_1, llm)
            metadata["refined_query"] = refined_query
            metadata["rounds"] = 2

            if web_search_fn:
                web_raw = await web_search_fn(refined_query)
                context_2 = self._format_web_results(web_raw)
                all_contexts.append("[联网搜索结果]\n" + context_2)
            else:
                all_contexts.append("[联网搜索不可用]")

            return StrategyResult(
                context="\n\n---\n\n".join(all_contexts),
                metadata=metadata
            )
        except Exception as e:
            logger.warning(f"[Backtrack] 策略执行失败: {e}")
            return StrategyResult(
                context=all_contexts[0] if all_contexts else "",
                metadata={"fallback": True, "error": str(e)[:100]}
            )

    def _evaluate_quality(self, query: str, context: str, llm) -> float:
        """LLM 评估上下文质量，返回 0-1 评分"""
        try:
            raw = llm.chat(
                messages=[{"role": "user", "content": QUALITY_EVAL_PROMPT.format(
                    question=query, context=context[:3000]
                )}],
                max_tokens=50,
            )
            match = re.search(r'(\d+\.?\d*)', raw)
            if match:
                score = float(match.group(1))
                return max(0.0, min(1.0, score))
            return 0.0
        except Exception as e:
            logger.warning(f"[Backtrack] 质量评估失败: {e}")
            return 0.0

    def _refine_query(self, query: str, context: str, llm) -> str:
        """LLM 优化查询"""
        try:
            refined = llm.chat(
                messages=[{"role": "user", "content": QUERY_REFINE_PROMPT.format(
                    question=query, context=context[:2000]
                )}],
                max_tokens=200,
            )
            return refined.strip() or query
        except Exception:
            return query

    def _format_web_results(self, web_raw: str) -> str:
        """将 tavily 返回的 JSON 字符串格式化为上下文"""
        try:
            data = json.loads(web_raw) if isinstance(web_raw, str) else web_raw
            parts = []
            results = data.get("results", []) or []
            for i, r in enumerate(results):
                parts.append(f"[网页 {i+1}] {r.get('title', '')}\n{r.get('content', '')}")
            if data.get("answer"):
                parts.insert(0, f"[Tavily AI 摘要]\n{data['answer']}")
            return "\n\n".join(parts) if parts else "（无搜索结果）"
        except Exception:
            return str(web_raw)[:3000]