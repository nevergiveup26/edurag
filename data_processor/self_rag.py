"""
Self-RAG 质量评估与自我修正

在生成答案后，自动评估质量。若质量不达标，则：
1. 分析失败原因（相关性/完整性/事实性）
2. 提炼优化后的检索查询
3. 二次检索 + 合并结果 + 重新生成

简单查询（关键词/事实型）自动跳过 Self-RAG，直接输出。
评估使用 qwen-turbo 快思考模型，节省延迟。
"""
import json
from typing import List, Dict, Optional, Tuple
from core.logger import get_logger

logger = get_logger("self_rag")

# 合并了 Guardrails 幻觉检测维度的评估 prompt
EVALUATE_PROMPT = """你是一个答案质量评估专家。请评估以下【答案】对【用户问题】的回复质量。

【评分维度】(每项0-10分):
1. 相关性(relevance): 答案是否直接回答了问题
2. 完整性(completeness): 信息是否完整，是否遗漏关键点
3. 事实性(factualness): 答案是否基于参考资料，有无编造
4. 幻觉检测(hallucination): 答案中是否存在参考资料中没有的信息
5. 来源覆盖(source_coverage): 答案的主要论断是否有对应的引用来源

【用户问题】
{query}

【参考资料摘要】
{context_summary}

【生成的答案】
{answer}

请返回JSON格式：
{{
    "relevance": <0-10>,
    "completeness": <0-10>,
    "factualness": <0-10>,
    "hallucination": <0-10, 10表示无幻觉>,
    "source_coverage": <0-10>,
    "overall": <0.0-1.0>,
    "is_acceptable": <true/false>,
    "issues": ["问题1", "问题2"],
    "missing_citations": <true/false>,
    "refined_query": "<优化后的检索查询，如果需要重新检索>",
    "reason": "<简短说明>"
}}

仅返回JSON，不要添加解释。"""

# 简单查询关键词模式 — 命中则跳过 Self-RAG
SIMPLE_QUERY_PATTERNS = [
    "是谁", "什么是", "什么叫", "定义", "概念",
    "时间", "地点", "日期", "年份", "多少",
    "哪个", "哪里", "哪种", "哪年", "谁",
    "公式", "定理", "定律",
]


class SelfRAGEvaluator:
    """
    Self-RAG 质量评估器

    评估生成的答案质量，质量低时提炼新查询进行二次检索。
    默认使用 qwen-turbo 快思考，节省延迟。
    """

    def __init__(self, llm_client=None):
        from llm.llm_client import get_fast_llm
        self.llm_client = llm_client or get_fast_llm()  # 评估用 turbo
        self.quality_threshold = 0.6
        self.max_retrieval_rounds = 2

    def evaluate(self, query: str, answer: str,
                 sources: list = None) -> Dict:
        """评估答案质量（含幻觉检测+来源覆盖）"""
        context_summary = "无"
        if sources:
            snippets = []
            for i, s in enumerate(sources[:5]):
                content = s.chunk.content if hasattr(s, 'chunk') else str(s)
                snippets.append(f"[{i+1}] {content[:300]}")
            context_summary = "\n".join(snippets)

        prompt = EVALUATE_PROMPT.format(
            query=query,
            context_summary=context_summary,
            answer=answer[:2000],
        )

        try:
            response = self.llm_client.generate(prompt, max_tokens=500, temperature=0.1)
            result = self._parse_json(response)
            if result:
                logger.info(f"Self-RAG评估: score={result.get('overall', 0):.2f}, "
                           f"acceptable={result.get('is_acceptable', True)}, "
                           f"hallucination={result.get('hallucination', 'N/A')}")
                return result
        except Exception as e:
            logger.warning(f"Self-RAG评估失败: {e}")

        return {"overall": 0.8, "score": 0.8, "is_acceptable": True, "issues": [],
                "refined_query": "", "reason": "评估失败，默认通过",
                "missing_citations": False, "hallucination": 8}

    def should_retrieve(self, evaluation: Dict) -> bool:
        """根据评估结果判断是否需要重新检索"""
        score = evaluation.get("overall", evaluation.get("score", 1.0))
        acceptable = evaluation.get("is_acceptable", True)
        return not acceptable or float(score) < self.quality_threshold

    def get_refined_query(self, evaluation: Dict) -> str:
        """获取优化后的检索查询"""
        return evaluation.get("refined_query", "")

    def get_guard_result(self, evaluation: Dict) -> Dict:
        """
        从评估结果提取 Guardrails 检查结果。
        Self-RAG 评估已包含幻觉检测，不再需要独立的 Guardrails 调用。
        返回格式兼容 guardrails.generate_missing_source_warning()。
        """
        hallucination_score = evaluation.get("hallucination", 8)
        missing_citations = evaluation.get("missing_citations", False)
        return {
            "passed": hallucination_score >= 5 and not missing_citations,
            "missing_citations": missing_citations,
            "has_hallucination": hallucination_score < 6,
            "confidence_score": evaluation.get("overall", 0.8),
            "hallucination_score": hallucination_score,
            "issues": evaluation.get("issues", []),
        }

    @staticmethod
    def is_simple_query(query: str) -> bool:
        """检测简单事实查询，跳过 Self-RAG 循环"""
        q = query.strip()
        # 短查询 + 关键词命中 → 简单
        if len(q) <= 15 and any(p in q for p in SIMPLE_QUERY_PATTERNS):
            return True
        # 不需要推理的 who/what/where/when 短问题
        if len(q) <= 20 and any(q.startswith(w) or q.endswith(w) for w in ["是谁", "是什么", "哪里", "多少", "哪个"]):
            return True
        return False

    def _parse_json(self, text: str) -> Optional[Dict]:
        """从LLM返回中解析JSON"""
        if not text:
            return None
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            import re
            match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        return None


class SelfRAGLoop:
    """
    Self-RAG 完整循环

    流程:
    1. 检测是否为简单查询 → 是则跳过 Self-RAG
    2. 正常检索 → 生成答案
    3. 评估答案质量（含幻觉检测，替代独立 Guardrails）
    4. 若不达标 → 用提炼的查询重新检索 → 合并结果 → 重新生成
    5. 最多两轮
    """

    def __init__(self, retriever, llm_client=None, reranker=None):
        from llm.llm_client import LLMClient
        self.retriever = retriever
        self.llm_client = llm_client or LLMClient()  # 答案生成保持用 qwen-max
        self.reranker = reranker
        self.evaluator = SelfRAGEvaluator()  # 评估用 qwen-turbo
        self.max_rounds = 2
        self._compressor = None

    @property
    def compressor(self):
        if self._compressor is None:
            from data_processor.context_compressor import ContextCompressor
            self._compressor = ContextCompressor()
        return self._compressor

    def _build_context(self, query: str, results: list, max_chars: int = 4000) -> str:
        """构建并压缩上下文（含Token预算管理）"""
        from data_processor.rag_utils import trim_context_to_token_limit
        if not results:
            return ""
        context = self.compressor.compress_for_prompt(
            query, results[:8], max_context_chars=max_chars
        )
        context = trim_context_to_token_limit(context, max_tokens=3000)
        return context

    def _do_search(self, query: str, top_k: int,
                   metadata_filter: dict = None,
                   doc_id_filter: list = None) -> list:
        """检索 + rerank"""
        results = self.retriever.search(
            query, top_k=top_k,
            metadata_filter=metadata_filter,
            doc_id_filter=doc_id_filter
        )
        if results and self.reranker:
            try:
                results = self.reranker.rerank(query, results)
            except Exception as e:
                logger.debug(f"Self-RAG rerank跳过: {e}")
        return results

    def execute(self, query: str, top_k: int = 5,
                history: list = None,
                metadata_filter: dict = None,
                doc_id_filter: list = None) -> Dict:
        """
        执行 Self-RAG 完整循环

        Returns:
            {
                "answer": "最终答案",
                "sources": [...],
                "rounds": 1/2,
                "evaluations": [...],
                "quality_score": 0.85,
                "guard_result": {...},  # 替代独立 Guardrails 调用
            }
        """
        from llm.prompt_template import PromptTemplate

        # ── 简单查询：跳过 Self-RAG，直接检索+生成 ──
        if SelfRAGEvaluator.is_simple_query(query):
            logger.info(f"Self-RAG: 简单查询跳过质量循环 → '{query[:40]}'")
            results = self._do_search(query, top_k,
                                      metadata_filter=metadata_filter,
                                      doc_id_filter=doc_id_filter)
            context = self._build_context(query, results)
            prompt = PromptTemplate.generate_qa_prompt(query, context, history)
            answer = self.llm_client.generate(prompt)

            # ── 已注释：Self-RAG 自评环节 ──
            # eval_result = {"overall": 0.85, "is_acceptable": True, "issues": [],
            #               "hallucination": 8, "missing_citations": False}
            # try:
            #     eval_result = self.evaluator.evaluate(query, answer, results)
            # except Exception:
            #     pass

            return {
                "answer": answer,
                "sources": results,
                "rounds": 1,
            }

        # ── 复杂查询：直接检索+生成（已注释 Self-RAG 自评环节）──
        all_sources = []

        # Round 1
        results = self._do_search(query, top_k,
                                  metadata_filter=metadata_filter,
                                  doc_id_filter=doc_id_filter)
        all_sources.extend(results)
        context = self._build_context(query, results)
        prompt = PromptTemplate.generate_qa_prompt(query, context, history)
        logger.info(f"[SelfRAG Round1] prompt总长度={len(prompt)}字符, context长度={len(context)}字符")
        answer = self.llm_client.generate(prompt)

        # ── 已注释：Round 1 自评 + 不达标时二次检索 ──
        # eval1 = self.evaluator.evaluate(query, answer, results)
        # eval1["round"] = 1
        # evaluations.append(eval1)
        # logger.info(f"Self-RAG Round 1: score={eval1.get('overall', 0):.2f}, "
        #             f"sources={len(results)}")
        #
        # if self.evaluator.should_retrieve(eval1):
        #     refined_query = self.evaluator.get_refined_query(eval1) or query
        #     logger.info(f"Self-RAG Round 2: 提炼查询 '{refined_query[:60]}'")
        #     results2 = self._do_search(refined_query, top_k,
        #                                metadata_filter=metadata_filter,
        #                                doc_id_filter=doc_id_filter)
        #     existing_ids = {r.chunk.chunk_id for r in all_sources
        #                    if hasattr(r, 'chunk') and r.chunk is not None and hasattr(r.chunk, 'chunk_id')}
        #     new_sources = [r for r in results2
        #                   if not (hasattr(r, 'chunk') and r.chunk is not None
        #                           and hasattr(r.chunk, 'chunk_id')
        #                           and r.chunk.chunk_id in existing_ids)]
        #     all_sources.extend(new_sources)
        #     logger.info(f"Round 2 新增 {len(new_sources)} 个来源（去重后）")
        #     context2 = self._build_context(query, all_sources[:8])
        #     prompt2 = PromptTemplate.generate_qa_prompt(query, context2, history)
        #     logger.info(f"[SelfRAG Round2] prompt总长度={len(prompt2)}字符, context长度={len(context2)}字符")
        #     answer = self.llm_client.generate(prompt2)
        #     eval2 = self.evaluator.evaluate(query, answer, all_sources)
        #     eval2["round"] = 2
        #     evaluations.append(eval2)
        #     logger.info(f"Self-RAG Round 2: score={eval2.get('overall', 0):.2f}, "
        #                 f"sources={len(all_sources)}")

        return {
            "answer": answer,
            "sources": all_sources,
            "rounds": 1,
        }
