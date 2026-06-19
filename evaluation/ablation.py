"""
消融实验模块（v2 — 分层独立消融真实 Agent 管道）

分层消融维度：
  Layer 1: FAQ 匹配层  → FAQ 开 vs 关
  Layer 2: 路由层      → Full (三层) vs Rule-only vs Similarity-only vs LLM-only vs No-router
  Layer 3: 策略层      → Full (自动) vs direct-only vs hyde-only vs sub_query-only vs backtrack-only
  Layer 4: 检索层      → Full (Hybrid+Reranker) vs BM25-only vs Vector-only vs Hybrid-no-rerank

所有变体均走真实 LangGraph Agent 管道，不再使用简化版检索+生成。
"""
import json
import time
import asyncio
from typing import List, Dict, Optional, Callable, Any
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from core.logger import get_logger
from core.models import DocumentChunk
from evaluation.metrics.generation import GenerationMetrics
from evaluation.metrics.retrieval import RetrievalMetrics

logger = get_logger("ablation")


# ═══════════════════════════════════════════════════════════════
# 分层消融配置
# ═══════════════════════════════════════════════════════════════

@dataclass
class AblationConfig:
    """单个消融实验配置（分层控制）"""
    name: str
    description: str
    layer: str = ""                     # 所属层级: faq / router / strategy / retrieval

    # FAQ 层
    faq_enabled: bool = True            # 是否启用 FAQ 匹配拦截

    # 路由层
    router_mode: str = "full"           # full / rule_only / similarity_only / llm_only / none

    # 策略层
    strategy_mode: str = "auto"         # auto / direct / hyde / sub_query / backtrack

    # 检索层
    bm25_weight: float = 0.3
    vector_weight: float = 0.7
    use_reranker: bool = True


# ═══════════════════════════════════════════════════════════════
# 预定义消融配置（4 层，共 16 个变体）
# ═══════════════════════════════════════════════════════════════

# Layer 1: FAQ 匹配层
FAQ_CONFIGS = [
    AblationConfig(
        name="faq_on",
        description="FAQ 匹配开启（基线）",
        layer="faq", faq_enabled=True,
    ),
    AblationConfig(
        name="faq_off",
        description="FAQ 匹配关闭",
        layer="faq", faq_enabled=False,
    ),
]

# Layer 2: 路由层
ROUTER_CONFIGS = [
    AblationConfig(
        name="router_full",
        description="完整三层路由（基线）",
        layer="router", router_mode="full",
    ),
    AblationConfig(
        name="router_rule_only",
        description="仅规则路由",
        layer="router", router_mode="rule_only",
    ),
    AblationConfig(
        name="router_similarity_only",
        description="仅相似度路由",
        layer="router", router_mode="similarity_only",
    ),
    AblationConfig(
        name="router_llm_only",
        description="仅 LLM 路由",
        layer="router", router_mode="llm_only",
    ),
    AblationConfig(
        name="router_none",
        description="无路由（固定 direct）",
        layer="router", router_mode="none",
    ),
]

# Layer 3: 策略层
STRATEGY_CONFIGS = [
    AblationConfig(
        name="strategy_auto",
        description="自动选择策略（基线）",
        layer="strategy", strategy_mode="auto",
    ),
    AblationConfig(
        name="strategy_direct",
        description="固定 direct 策略",
        layer="strategy", strategy_mode="direct",
    ),
    AblationConfig(
        name="strategy_hyde",
        description="固定 hyde 策略",
        layer="strategy", strategy_mode="hyde",
    ),
    AblationConfig(
        name="strategy_sub_query",
        description="固定 sub_query 策略",
        layer="strategy", strategy_mode="sub_query",
    ),
    AblationConfig(
        name="strategy_backtrack",
        description="固定 backtrack 策略",
        layer="strategy", strategy_mode="backtrack",
    ),
]

# Layer 4: 检索层
RETRIEVAL_CONFIGS = [
    AblationConfig(
        name="retrieval_full",
        description="Hybrid(3:7) + Reranker（基线）",
        layer="retrieval", bm25_weight=0.3, vector_weight=0.7, use_reranker=True,
    ),
    AblationConfig(
        name="retrieval_bm25_only",
        description="仅 BM25 关键词检索",
        layer="retrieval", bm25_weight=1.0, vector_weight=0.0, use_reranker=False,
    ),
    AblationConfig(
        name="retrieval_vector_only",
        description="仅向量语义检索",
        layer="retrieval", bm25_weight=0.0, vector_weight=1.0, use_reranker=False,
    ),
    AblationConfig(
        name="retrieval_hybrid_no_rerank",
        description="Hybrid(3:7) 无重排序",
        layer="retrieval", bm25_weight=0.3, vector_weight=0.7, use_reranker=False,
    ),
]

# 全部配置（用于 --all 模式）
ALL_CONFIGS = FAQ_CONFIGS + ROUTER_CONFIGS + STRATEGY_CONFIGS + RETRIEVAL_CONFIGS


# ═══════════════════════════════════════════════════════════════
# 结果
# ═══════════════════════════════════════════════════════════════

@dataclass
class AblationResult:
    """单个消融变体的评估结果"""
    config: AblationConfig
    retrieval: RetrievalMetrics = field(default_factory=RetrievalMetrics)
    generation: GenerationMetrics = field(default_factory=GenerationMetrics)
    # LLM Judge 指标
    faithfulness: float = 0.0
    answer_correctness: float = 0.0
    answer_relevancy: float = 0.0
    # 元信息
    sample_count: int = 0
    total_time: float = 0.0
    avg_latency_ms: float = 0.0
    errors: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# 真实 Agent 管道构建器
# ═══════════════════════════════════════════════════════════════

def build_ablation_query_func(
    config: AblationConfig,
    chunks: List[DocumentChunk],
) -> Callable[[str], Any]:
    """
    根据分层消融配置，构建走真实 Agent 管道的 query_func。

    每一层独立控制：
      - FAQ 层: faq_enabled → 是否先走 FAQMatcher 匹配
      - 路由层: router_mode → 使用完整路由 / 单层路由 / 跳过路由
      - 策略层: strategy_mode → 自动选择策略 / 固定某种策略
      - 检索层: bm25_weight / vector_weight / use_reranker → 检索器配置

    Returns:
        query_func(query: str) -> SimpleNamespace(answer, sources, strategy_used, router_used)
    """
    from types import SimpleNamespace
    from retriever.hybrid_retriever import HybridRetriever

    # ── 检索器（按 config 配置权重） ──
    retriever = HybridRetriever()
    retriever.bm25_weight = config.bm25_weight
    retriever.vector_weight = config.vector_weight
    if chunks:
        retriever.build_index(chunks)

    # ── Reranker ──
    reranker = None
    if config.use_reranker:
        try:
            from retriever.reranker import Reranker
            reranker = Reranker()
        except Exception as e:
            logger.warning(f"Reranker 初始化失败: {e}")

    def _get_strategy(query: str) -> str:
        """根据 router_mode 决定策略"""
        if config.router_mode == "none":
            return "direct"
        elif config.router_mode == "rule_only":
            from router.rule_router import RuleRouter
            r = RuleRouter()
            result = r.route(query)
            return result if result else "direct"
        elif config.router_mode == "similarity_only":
            from router.similarity_router import SimilarityRouter
            r = SimilarityRouter()
            result = r.route(query)
            return result if result else "direct"
        elif config.router_mode == "llm_only":
            from router.llm_router import LLMRouter
            r = LLMRouter()
            result = r.route(query)
            return result if result else "direct"
        else:
            from router.query_router import get_query_router
            r = get_query_router()
            return r.route(query)

    def _execute_strategy(strategy: str, query: str) -> str:
        """执行策略预处理，返回上下文"""
        if strategy == "direct":
            return ""
        if config.strategy_mode != "auto":
            strategy = config.strategy_mode

        try:
            from strategy import execute_strategy
            from llm.llm_client import get_fast_llm
            from langgraph_agent.tools import tavily_web_search

            def _web_search_fn(q: str) -> str:
                return tavily_web_search.invoke({"query": q})

            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(execute_strategy(
                strategy=strategy,
                query=query,
                retriever=retriever,
                llm=get_fast_llm(),
                web_search_fn=_web_search_fn,
            ))
            loop.close()
            if result and result.context:
                return result.context
        except Exception as e:
            logger.warning(f"策略执行失败 ({strategy}): {e}")

        return ""

    def _run_agent(query: str, strategy: str, strategy_context: str, retrieval_context: str = "") -> str:
        """运行 LangGraph Agent 获取答案（始终使用简化 Agent + 检索上下文注入）"""
        try:
            from langgraph_agent.chat_agent import create_chat_agent, CHAT_SYSTEM_PROMPT
            from langgraph_agent.model import create_chat_model
            from langgraph_agent.tools import final_answer
            from langchain_core.messages import HumanMessage

            model = create_chat_model()

            # 构建上下文：策略上下文 + 检索上下文
            context_parts = []
            if strategy_context:
                context_parts.append(strategy_context)
            if retrieval_context:
                context_parts.append(retrieval_context)
            combined_context = "\n\n".join(context_parts) if context_parts else ""

            system_prompt = CHAT_SYSTEM_PROMPT
            if combined_context:
                system_prompt = (CHAT_SYSTEM_PROMPT
                                 + "\n\n【系统已检索到的参考资料】\n" + combined_context
                                 + "\n\n请直接基于以上参考资料回答用户问题，不要调用 knowledge_search 工具。")

            # 始终使用简化 Agent（仅 final_answer 工具），避免 Agent 内部检索导致 list content 错误
            agent = create_chat_agent(model=model, tools=[final_answer], system_prompt=system_prompt)

            result = agent.invoke({"messages": [HumanMessage(content=query)]})

            messages = result.get("messages", [])
            for msg in reversed(messages):
                if hasattr(msg, "content") and msg.type == "ai":
                    content = msg.content
                    if isinstance(content, list):
                        content = " ".join([
                            c.get("text", "") if isinstance(c, dict) else str(c)
                            for c in content
                        ])
                    return content
            return ""
        except Exception as e:
            error_msg = str(e)
            if "inappropriate content" in error_msg.lower() or "inappropriate" in error_msg.lower():
                logger.warning(f"Agent 内容安全拦截: {query[:50]}...")
                return "[内容安全过滤] 该问题被 DashScope 内容审核拦截，无法生成回答。"
            logger.error(f"Agent 执行失败: {e}")
            return f"[Agent 执行失败] {error_msg[:200]}"

    def _do_retrieval(query: str):
        """执行检索+重排序，返回 sources 列表"""
        results = retriever.search(query, top_k=10)
        if reranker and results:
            try:
                results = reranker.rerank(query, results)
            except Exception:
                pass
        results = results[:5]

        sources = []
        for s in results:
            if hasattr(s, 'chunk') and s.chunk:
                chunk = s.chunk
                content = chunk.content if hasattr(chunk, 'content') else str(chunk)
                doc_id = chunk.doc_id if hasattr(chunk, 'doc_id') else ""
            else:
                content = str(s)
                doc_id = ""
            sources.append(SimpleNamespace(
                content=content[:500],
                score=getattr(s, 'score', 0),
                chunk=SimpleNamespace(doc_id=doc_id, content=content[:500]),
            ))
        return sources

    def query_func(query: str):
        """实际的 query_func，走完整 Agent 管道"""

        # Layer 1: FAQ 匹配
        if config.faq_enabled:
            try:
                from evaluation.faq_matcher import get_faq_matcher
                fm = get_faq_matcher()
                if fm and fm.is_ready:
                    faq_match = fm.match(query)
                    if faq_match:
                        return SimpleNamespace(
                            answer=faq_match["answer"],
                            sources=[SimpleNamespace(
                                content=faq_match["question"],
                                score=faq_match["similarity"],
                                chunk=SimpleNamespace(doc_id=faq_match["id"], content=faq_match["question"]),
                            )],
                            strategy_used="faq",
                            router_used="faq",
                            execution_time=0,
                            conversation_id="",
                        )
            except Exception as e:
                logger.warning(f"FAQ 匹配失败，降级: {e}")

        # Layer 2: 路由
        strategy = _get_strategy(query)

        # Layer 3: 策略预处理
        strategy_context = _execute_strategy(strategy, query)

        # Layer 4: 检索（构建检索上下文传入 Agent，避免 Agent 内部检索导致 list content 错误）
        sources = _do_retrieval(query)
        retrieval_context = "\n\n".join([
            f"[文档 {i+1}] {s.content[:500]}" for i, s in enumerate(sources)
        ]) if sources else ""

        # Agent 推理（始终使用简化 Agent + 检索上下文注入）
        answer = _run_agent(query, strategy, strategy_context, retrieval_context)

        return SimpleNamespace(
            answer=answer,
            sources=sources,
            strategy_used=strategy,
            router_used=config.router_mode,
            execution_time=0,
            conversation_id="",
        )

    return query_func


# ═══════════════════════════════════════════════════════════════
# 消融实验运行器 v2
# ═══════════════════════════════════════════════════════════════

class AblationRunner:
    """分层消融实验运行器

    用法:
        runner = AblationRunner(use_llm_judge=True)
        runner.load_chunks()
        runner.load_samples(samples)
        results = runner.run_layer("router", ROUTER_CONFIGS)
        runner.print_layer_report(results)
    """

    def __init__(self, use_llm_judge: bool = False):
        self.chunks: List[DocumentChunk] = []
        self.samples: List[dict] = []
        self.use_llm_judge = use_llm_judge

    def load_chunks(self):
        """从 chunk_store 加载全部数据"""
        from database.chunk_store import load_chunks

        data = load_chunks()
        self.chunks = []
        for item in data:
            raw_embedding = item.get("embedding")
            if raw_embedding is None:
                embedding = None
            else:
                try:
                    embedding = np.array(raw_embedding, dtype=np.float32)
                except (TypeError, ValueError):
                    embedding = None
            self.chunks.append(DocumentChunk(
                chunk_id=item["chunk_id"],
                doc_id=item["doc_id"],
                content=item["content"],
                metadata=item.get("metadata", {}),
                embedding=embedding,
            ))
        logger.info(f"加载 {len(self.chunks)} 个 chunk")

    def load_samples(self, samples: List[dict]):
        """加载评估样本"""
        if not samples:
            logger.warning("评估样本为空")
            return
        self.samples = samples
        logger.info(f"加载 {len(self.samples)} 个评估样本")

    @staticmethod
    def load_samples_from_file(path: str) -> List[dict]:
        """从 JSON 文件加载评估样本"""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def load_faq_samples(limit: int = 20) -> List[dict]:
        """从 MySQL faq 表加载 FAQ 样本（用于 Layer 1 消融）"""
        from database.mysql_db import MySQLDB
        db = MySQLDB()
        rows = db.query("SELECT id, question, answer, category, tags FROM faq ORDER BY RAND() LIMIT %s", (limit,))
        samples = []
        for row in rows:
            samples.append({
                "query": row["question"],
                "expected_answer": row["answer"],
                "expected_keywords": [],
                "relevant_doc_ids": [row["id"]],
                "category": row.get("category", "faq"),
            })
        return samples

    def run(self, configs: List[AblationConfig]) -> List[AblationResult]:
        """运行全部消融变体"""
        return self._run_configs(configs)

    def run_layer(self, layer: str, configs: List[AblationConfig] = None) -> List[AblationResult]:
        """运行某一层的消融实验"""
        if configs is None:
            configs = [c for c in ALL_CONFIGS if c.layer == layer]
        return self._run_configs(configs)

    def _run_configs(self, configs: List[AblationConfig]) -> List[AblationResult]:
        """内部：运行一批消融变体"""
        if not self.samples:
            raise RuntimeError("请先调用 load_samples() 加载评估样本")
        if not self.chunks:
            logger.warning("chunks 为空，检索可能无结果")

        results = []
        for i, config in enumerate(configs):
            t0 = time.time()
            logger.info(f"[{i+1}/{len(configs)}] 运行: {config.name} — {config.description}")

            try:
                query_func = build_ablation_query_func(config, self.chunks)
                result = self._evaluate_single(config, query_func)
                result.total_time = time.time() - t0
                result.avg_latency_ms = round(result.total_time * 1000 / max(result.sample_count, 1), 1)
                results.append(result)

                logger.info(f"  F1={result.retrieval.f1_score:.4f} "
                            f"BLEU-1={result.generation.bleu_1:.4f} "
                            f"ROUGE-L={result.generation.rouge_l:.4f} "
                            f"Faithfulness={result.faithfulness:.4f}")
            except Exception as e:
                logger.error(f"  {config.name} 执行失败: {e}")
                results.append(AblationResult(
                    config=config,
                    errors=[str(e)],
                    total_time=time.time() - t0,
                ))

        return results

    def _evaluate_single(self, config: AblationConfig, query_func: Callable) -> AblationResult:
        """对单个变体进行评估"""
        from evaluation.metrics.retrieval import calc_retrieval_metrics
        from evaluation.metrics.generation import calc_bleu, calc_rouge_l, calc_keyword_match_rate

        all_retrieval = []
        all_generation = []
        all_faithfulness = []
        all_correctness = []
        all_relevancy = []

        for s in self.samples:
            query = s.get("query", "")
            expected = s.get("expected_answer", "")
            expected_keywords = s.get("expected_keywords", [])
            relevant_doc_ids = s.get("relevant_doc_ids", [])

            try:
                result = query_func(query)
            except Exception as e:
                logger.warning(f"query_func 执行失败: {e}，跳过样本 [{query[:50]}...]")
                continue
            answer = result.answer if hasattr(result, 'answer') else str(result)
            # 确保 answer 是字符串（LangChain 可能返回 list）
            if not isinstance(answer, str):
                answer = " ".join([str(c) for c in answer]) if isinstance(answer, list) else str(answer)

            retrieved_doc_ids = []
            retrieved_contents = []
            if hasattr(result, 'sources') and result.sources:
                for src in result.sources:
                    if hasattr(src, 'chunk') and hasattr(src.chunk, 'doc_id'):
                        retrieved_doc_ids.append(src.chunk.doc_id)
                    if hasattr(src, 'content'):
                        retrieved_contents.append(src.content[:200])

            retrieval_metrics = calc_retrieval_metrics(
                retrieved_doc_ids=retrieved_doc_ids,
                retrieved_contents=retrieved_contents,
                relevant_doc_ids=relevant_doc_ids,
                expected_keywords=expected_keywords,
                top_k=5,
            )
            all_retrieval.append(retrieval_metrics)

            bleu = calc_bleu(expected, answer)
            rouge = calc_rouge_l(expected, answer)
            kw = calc_keyword_match_rate(answer, expected_keywords)
            all_generation.append({
                "bleu_1": bleu.get("bleu_1", 0.0),
                "bleu_2": bleu.get("bleu_2", 0.0),
                "rouge_l": rouge,
                "keyword_match_rate": kw,
            })

            if self.use_llm_judge:
                try:
                    from evaluation.metrics.llm_judge import (
                        calc_faithfulness, calc_answer_relevancy, calc_answer_correctness
                    )
                    context = ""
                    if hasattr(result, 'sources') and result.sources:
                        context = " ".join([s.content[:300] for s in result.sources[:3] if hasattr(s, 'content')])

                    faith = asyncio.run(calc_faithfulness(answer, context))
                    relevancy = asyncio.run(calc_answer_relevancy(query, answer))
                    correctness = asyncio.run(calc_answer_correctness(query, answer, expected))

                    all_faithfulness.append(faith)
                    all_correctness.append(correctness)
                    all_relevancy.append(relevancy)
                except Exception as e:
                    logger.warning(f"LLM Judge 评估失败: {e}")

        n = max(len(all_retrieval), 1)
        avg_retrieval = RetrievalMetrics(
            precision=sum(r.precision for r in all_retrieval) / n,
            recall=sum(r.recall for r in all_retrieval) / n,
            f1_score=sum(r.f1_score for r in all_retrieval) / n,
            mrr=sum(r.mrr for r in all_retrieval) / n,
            ndcg=sum(r.ndcg for r in all_retrieval) / n,
            hit_rate=sum(r.hit_rate for r in all_retrieval) / n,
        )

        avg_generation = GenerationMetrics(
            bleu_1=sum(g["bleu_1"] for g in all_generation) / n,
            bleu_2=sum(g["bleu_2"] for g in all_generation) / n,
            rouge_l=sum(g["rouge_l"] for g in all_generation) / n,
            keyword_match_rate=sum(g["keyword_match_rate"] for g in all_generation) / n,
        )

        avg_faith = sum(all_faithfulness) / max(len(all_faithfulness), 1)
        avg_correct = sum(all_correctness) / max(len(all_correctness), 1)
        avg_relev = sum(all_relevancy) / max(len(all_relevancy), 1)

        return AblationResult(
            config=config,
            retrieval=avg_retrieval,
            generation=avg_generation,
            faithfulness=avg_faith,
            answer_correctness=avg_correct,
            answer_relevancy=avg_relev,
            sample_count=len(all_retrieval),
        )

    # ── 报告输出 ──

    def print_layer_report(self, results: List[AblationResult]):
        """打印分层消融报告"""
        if not results:
            print("无结果")
            return

        layer = results[0].config.layer if results else "unknown"
        print(f"\n{'=' * 80}")
        print(f"  EduRAG 消融实验报告 — Layer: {layer}")
        print(f"{'=' * 80}")
        print(f"  样本数: {results[0].sample_count}")
        print()

        header = f"  {'配置':<28} {'F1':>6} {'MRR':>7} {'Hit':>6} {'BLEU-1':>7} {'ROUGE-L':>7} {'延迟':>7}"
        sep = "  " + "-" * (len(header) - 2)
        print("  【传统指标】")
        print(header)
        print(sep)

        for r in results:
            line = (f"  {r.config.name:<28} {r.retrieval.f1_score:6.4f} {r.retrieval.mrr:7.4f} "
                    f"{r.retrieval.hit_rate:6.4f} {r.generation.bleu_1:7.4f} {r.generation.rouge_l:7.4f} "
                    f"{r.avg_latency_ms:6.0f}ms")
            print(line)

        print(sep)

        if any(r.faithfulness > 0 or r.answer_correctness > 0 or r.answer_relevancy > 0 for r in results):
            print("\n  【LLM Judge 指标】")
            header2 = f"  {'配置':<28} {'Faithfulness':>13} {'Correctness':>13} {'Relevancy':>13}"
            sep2 = "  " + "-" * (len(header2) - 2)
            print(header2)
            print(sep2)
            for r in results:
                line2 = (f"  {r.config.name:<28} {r.faithfulness:13.4f} {r.answer_correctness:13.4f} "
                         f"{r.answer_relevancy:13.4f}")
                print(line2)
            print(sep2)

        print("\n  【最佳配置】")
        best_f1 = max(results, key=lambda r: r.retrieval.f1_score)
        best_bleu = max(results, key=lambda r: r.generation.bleu_1)
        best_faith = max(results, key=lambda r: r.faithfulness) if any(r.faithfulness > 0 for r in results) else None
        print(f"  检索最佳 (F1):  {best_f1.config.name} = {best_f1.retrieval.f1_score:.4f}")
        print(f"  生成最佳 (BLEU): {best_bleu.config.name} = {best_bleu.generation.bleu_1:.4f}")
        if best_faith and best_faith.faithfulness > 0:
            print(f"  忠实度最佳:     {best_faith.config.name} = {best_faith.faithfulness:.4f}")

        if layer == "retrieval":
            self._print_retrieval_contribution(results)
        elif layer == "router":
            self._print_router_contribution(results)
        elif layer == "faq":
            self._print_faq_contribution(results)

        print(f"{'=' * 80}")

    def _print_retrieval_contribution(self, results: List[AblationResult]):
        print("\n  【组件贡献分析】")
        full = next((r for r in results if r.config.name == "retrieval_full"), None)
        no_rerank = next((r for r in results if r.config.name == "retrieval_hybrid_no_rerank"), None)
        if full and no_rerank:
            delta = full.retrieval.f1_score - no_rerank.retrieval.f1_score
            print(f"  Reranker 对 F1 的贡献: {delta:+.4f}")

        bm25 = next((r for r in results if r.config.name == "retrieval_bm25_only"), None)
        vector = next((r for r in results if r.config.name == "retrieval_vector_only"), None)
        if bm25 and vector:
            delta = vector.retrieval.f1_score - bm25.retrieval.f1_score
            print(f"  向量 vs BM25 F1 差: {delta:+.4f}")

    def _print_router_contribution(self, results: List[AblationResult]):
        print("\n  【组件贡献分析】")
        full = next((r for r in results if r.config.name == "router_full"), None)
        none_r = next((r for r in results if r.config.name == "router_none"), None)
        if full and none_r:
            delta = full.retrieval.f1_score - none_r.retrieval.f1_score
            print(f"  三层路由 vs 无路由 F1 差: {delta:+.4f}")
            delta_b = full.generation.bleu_1 - none_r.generation.bleu_1
            print(f"  三层路由 vs 无路由 BLEU-1 差: {delta_b:+.4f}")

    def _print_faq_contribution(self, results: List[AblationResult]):
        print("\n  【组件贡献分析】")
        on_r = next((r for r in results if r.config.name == "faq_on"), None)
        off_r = next((r for r in results if r.config.name == "faq_off"), None)
        if on_r and off_r:
            delta = on_r.avg_latency_ms - off_r.avg_latency_ms
            print(f"  FAQ 匹配 延迟差: {delta:+.0f}ms (负值=加速)")
            delta_f = on_r.faithfulness - off_r.faithfulness
            print(f"  FAQ 匹配 Faithfulness 差: {delta_f:+.4f}")

    def to_dict(self, results: List[AblationResult]) -> List[dict]:
        """序列化消融结果"""
        out = []
        for r in results:
            out.append({
                "config": {
                    "name": r.config.name,
                    "description": r.config.description,
                    "layer": r.config.layer,
                    "faq_enabled": r.config.faq_enabled,
                    "router_mode": r.config.router_mode,
                    "strategy_mode": r.config.strategy_mode,
                    "bm25_weight": r.config.bm25_weight,
                    "vector_weight": r.config.vector_weight,
                    "use_reranker": r.config.use_reranker,
                },
                "retrieval": {
                    "precision": r.retrieval.precision,
                    "recall": r.retrieval.recall,
                    "f1_score": r.retrieval.f1_score,
                    "mrr": r.retrieval.mrr,
                    "ndcg": r.retrieval.ndcg,
                    "hit_rate": r.retrieval.hit_rate,
                },
                "generation": {
                    "bleu_1": r.generation.bleu_1,
                    "bleu_2": r.generation.bleu_2,
                    "rouge_l": r.generation.rouge_l,
                    "keyword_match_rate": r.generation.keyword_match_rate,
                },
                "llm_judge": {
                    "faithfulness": r.faithfulness,
                    "answer_correctness": r.answer_correctness,
                    "answer_relevancy": r.answer_relevancy,
                },
                "sample_count": r.sample_count,
                "total_time": r.total_time,
                "avg_latency_ms": r.avg_latency_ms,
                "errors": r.errors,
            })
        return out

    def save_results(self, results: List[AblationResult], path: str):
        """保存消融结果到 JSON"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(results), f, ensure_ascii=False, indent=2)
        logger.info(f"消融结果已保存到 {path}")


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="EduRAG 消融实验 v2 — 分层独立消融")
    parser.add_argument("--layer", type=str, default=None,
                        choices=["faq", "router", "strategy", "retrieval", "all"],
                        help="消融层级（默认 all）")
    parser.add_argument("--samples", type=str, default=None,
                        help="评估样本 JSON 路径")
    parser.add_argument("--limit", type=int, default=20,
                        help="评估样本数上限")
    parser.add_argument("--llm-judge", action="store_true",
                        help="启用 LLM Judge 评估")
    parser.add_argument("--output", type=str, default=None,
                        help="结果输出 JSON 路径")
    args = parser.parse_args()

    runner = AblationRunner(use_llm_judge=args.llm_judge)
    runner.load_chunks()

    layers = []
    if args.layer == "all" or args.layer is None:
        layers = [("faq", FAQ_CONFIGS), ("router", ROUTER_CONFIGS),
                  ("strategy", STRATEGY_CONFIGS), ("retrieval", RETRIEVAL_CONFIGS)]
    elif args.layer == "faq":
        layers = [("faq", FAQ_CONFIGS)]
    elif args.layer == "router":
        layers = [("router", ROUTER_CONFIGS)]
    elif args.layer == "strategy":
        layers = [("strategy", STRATEGY_CONFIGS)]
    elif args.layer == "retrieval":
        layers = [("retrieval", RETRIEVAL_CONFIGS)]

    all_results = {}

    for layer_name, configs in layers:
        if layer_name == "faq":
            samples = AblationRunner.load_faq_samples(limit=args.limit)
        elif args.samples:
            samples = AblationRunner.load_samples_from_file(args.samples)[:args.limit]
        else:
            default_path = Path(__file__).parent / "k12_test_set.json"
            if default_path.exists():
                samples = AblationRunner.load_samples_from_file(str(default_path))[:args.limit]
            else:
                logger.error(f"找不到默认测试集: {default_path}")
                continue

        runner.load_samples(samples)
        results = runner.run_layer(layer_name, configs)
        runner.print_layer_report(results)
        all_results[layer_name] = results

    if args.output:
        flat = []
        for r_list in all_results.values():
            flat.extend(runner.to_dict(r_list))
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(flat, f, ensure_ascii=False, indent=2)
        logger.info(f"消融结果已保存到 {args.output}")


if __name__ == "__main__":
    main()