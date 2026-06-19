"""
统一评估器
合并 evaluator.py 和 ragas_evaluator.py 的功能，提供同步+流式双入口

用法:
    evaluator = UnifiedEvaluator()
    report = await evaluator.evaluate(test_cases, query_func)
    # 或
    async for event in evaluator.evaluate_stream(test_cases, query_func):
        yield event
"""
import asyncio
import time
from typing import List, Dict, Optional, Callable, AsyncGenerator, Any
from dataclasses import dataclass, field

from core.logger import get_logger
from evaluation.metrics.retrieval import (
    calc_retrieval_metrics,
    calc_context_precision_embedding,
    RetrievalMetrics,
)
from evaluation.metrics.generation import (
    calc_bleu,
    calc_rouge_l,
    calc_keyword_match_rate,
    GenerationMetrics,
)
from evaluation.metrics.llm_judge import (
    calc_faithfulness,
    calc_answer_relevancy,
    calc_answer_correctness,
    RAGQualityMetrics,
)
from evaluation.report import generate_charts, format_report_html

logger = get_logger("unified_evaluator")


@dataclass
class EvalConfig:
    """评估配置"""
    metrics: List[str] = field(default_factory=lambda: [
        "retrieval", "generation", "faithfulness", "answer_relevancy"
    ])
    top_k: int = 5
    parallel_queries: int = 8
    parallel_scoring: int = 4
    use_llm_judge: bool = True
    max_samples: int = 0


@dataclass
class SampleScore:
    """单样本指标得分"""
    query: str = ""
    answer: str = ""
    contexts: List[str] = field(default_factory=list)
    ground_truth: str = ""
    retrieval: RetrievalMetrics = field(default_factory=RetrievalMetrics)
    generation: GenerationMetrics = field(default_factory=GenerationMetrics)
    rag_quality: RAGQualityMetrics = field(default_factory=RAGQualityMetrics)
    execution_time: float = 0.0


@dataclass
class EvalReport:
    """完整评估报告"""
    config: EvalConfig = field(default_factory=EvalConfig)
    sample_count: int = 0
    total_time: float = 0.0
    avg_metrics: Dict = field(default_factory=dict)
    sample_scores: List[SampleScore] = field(default_factory=list)
    charts: Dict[str, str] = field(default_factory=dict)


class UnifiedEvaluator:
    """统一评估器"""

    def __init__(self, config: EvalConfig = None):
        self.config = config or EvalConfig()
        self._llm = None
        self._vectorizer = None

    @property
    def llm(self):
        if self._llm is None and self.config.use_llm_judge:
            from llm.llm_client import get_fast_llm
            self._llm = get_fast_llm()
        return self._llm

    @property
    def vectorizer(self):
        if self._vectorizer is None:
            from data_processor.vectorizer import Vectorizer
            self._vectorizer = Vectorizer()
        return self._vectorizer

    # ═══════════════════════════════════════════════════════════
    # 同步入口
    # ═══════════════════════════════════════════════════════════

    async def evaluate(
        self,
        test_cases: List[Dict],
        query_func: Callable,
    ) -> EvalReport:
        """
        阶段一：并行采集 → 阶段二：批量计算指标 → 返回报告

        Args:
            test_cases: [{"question": "...", "ground_truth": "...", "relevant_doc_ids": [...], "expected_keywords": [...]}]
            query_func: async or sync function(query: str) -> response with .answer and .sources

        Returns:
            EvalReport
        """
        if self.config.max_samples > 0:
            test_cases = test_cases[:self.config.max_samples]

        t0 = time.time()

        # 阶段一：并行采集
        samples = await self._collect_samples(test_cases, query_func)
        if not samples:
            return EvalReport(config=self.config, total_time=round(time.time() - t0, 2))

        # 阶段二：批量计算指标
        sample_scores = await self._score_all(samples)

        # 汇总
        avg_metrics = self._aggregate_metrics(sample_scores)
        total_time = time.time() - t0

        # 图表
        sample_reports = [self._score_to_dict(s) for s in sample_scores]
        charts = generate_charts(sample_reports)

        report = EvalReport(
            config=self.config,
            sample_count=len(sample_scores),
            total_time=round(total_time, 2),
            avg_metrics=avg_metrics,
            sample_scores=sample_scores,
            charts=charts,
        )

        logger.info(
            f"评估完成: {len(sample_scores)} 个样本, {total_time:.1f}s, "
            f"avg_score={avg_metrics.get('avg_score', 0):.4f}"
        )
        return report

    # ═══════════════════════════════════════════════════════════
    # 流式入口
    # ═══════════════════════════════════════════════════════════

    async def evaluate_stream(
        self,
        test_cases: List[Dict],
        query_func: Callable,
        cancel_event=None,
    ) -> AsyncGenerator[Dict, None]:
        """
        逐样本采集+计算 → 实时 yield SSE 事件

        Yields:
            {"event": "progress", ...}
            {"event": "sample_done", ...}
            {"event": "evaluating", ...}
            {"event": "complete", ...}
        """
        if self.config.max_samples > 0:
            test_cases = test_cases[:self.config.max_samples]

        t0 = time.time()
        sample_scores = []
        total = len(test_cases)

        yield {"event": "evaluating", "message": "开始评测...", "total": total}

        for i, tc in enumerate(test_cases):
            if cancel_event and cancel_event.is_set():
                yield {"event": "cancelled", "current": i, "total": total}
                logger.info("评测已被取消")
                return

            yield {"event": "progress", "current": i + 1, "total": total,
                   "question": tc.get("question", "")[:60]}

            t_sample = time.time()
            try:
                if asyncio.iscoroutinefunction(query_func):
                    response = await query_func(tc["question"])
                else:
                    response = await asyncio.to_thread(query_func, tc["question"])

                answer = response.answer if hasattr(response, 'answer') else ""
                sources = response.sources if hasattr(response, 'sources') else []
                contexts = [
                    s.chunk.content if hasattr(s, 'chunk') and hasattr(s.chunk, 'content')
                    else str(s.chunk) if hasattr(s, 'chunk')
                    else str(s)
                    for s in sources[:self.config.top_k]
                ]
                # 提取实际 doc_id，用于与 relevant_doc_ids 精确匹配
                doc_ids = [
                    getattr(s.chunk, 'doc_id', '') if hasattr(s, 'chunk') else ''
                    for s in sources[:self.config.top_k]
                ]
                exec_time = time.time() - t_sample

                score = await self._score_one(
                    question=tc["question"],
                    answer=answer,
                    contexts=contexts,
                    retrieved_doc_ids=doc_ids,
                    ground_truth=tc.get("ground_truth", ""),
                    relevant_doc_ids=tc.get("relevant_doc_ids"),
                    expected_keywords=tc.get("expected_keywords"),
                    expected_answer=tc.get("expected_answer", ""),
                    exec_time=exec_time,
                )
                sample_scores.append(score)

                cumulative = self._aggregate_metrics(sample_scores)

                yield {
                    "event": "sample_done",
                    "index": i,
                    "question": tc["question"][:60],
                    "score": self._score_to_dict(score),
                    "cumulative": cumulative,
                }

            except Exception as e:
                logger.error(f"样本 {i} 评测失败: {e}")
                yield {
                    "event": "sample_done",
                    "index": i,
                    "question": tc.get("question", "")[:60],
                    "error": str(e),
                }

        # 最终汇总
        avg_metrics = self._aggregate_metrics(sample_scores)
        sample_reports = [self._score_to_dict(s) for s in sample_scores]
        charts = generate_charts(sample_reports)

        total_time = time.time() - t0
        yield {
            "event": "complete",
            "sample_count": len(sample_scores),
            "total_time": round(total_time, 2),
            "metrics": avg_metrics,
            "details": sample_reports,
            "charts": charts,
            "mode": "unified",
        }

    # ═══════════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════════

    async def _collect_samples(
        self,
        test_cases: List[Dict],
        query_func: Callable,
        cancel_event=None,
    ) -> List[Dict]:
        """并行查询采集 samples"""
        async def _query_one(tc):
            if cancel_event and cancel_event.is_set():
                return None
            try:
                if asyncio.iscoroutinefunction(query_func):
                    response = await query_func(tc["question"])
                else:
                    response = await asyncio.to_thread(query_func, tc["question"])

                answer = response.answer if hasattr(response, 'answer') else ""
                sources = response.sources if hasattr(response, 'sources') else []
                contexts = [
                    s.chunk.content if hasattr(s, 'chunk') and hasattr(s.chunk, 'content')
                    else str(s.chunk) if hasattr(s, 'chunk')
                    else str(s)
                    for s in sources[:self.config.top_k]
                ]
                doc_ids = [
                    getattr(s.chunk, 'doc_id', '') if hasattr(s, 'chunk') else ''
                    for s in sources[:self.config.top_k]
                ]
                return {
                    "question": tc["question"],
                    "answer": answer,
                    "contexts": contexts,
                    "retrieved_doc_ids": doc_ids,
                    "ground_truth": tc.get("ground_truth", ""),
                    "relevant_doc_ids": tc.get("relevant_doc_ids"),
                    "expected_keywords": tc.get("expected_keywords"),
                    "expected_answer": tc.get("expected_answer", ""),
                }
            except Exception as e:
                logger.error(f"查询失败 [{tc.get('question', '')[:40]}]: {e}")
                return None

        sem = asyncio.Semaphore(self.config.parallel_queries)

        async def _limited_query(tc):
            async with sem:
                return await _query_one(tc)

        tasks = [_limited_query(tc) for tc in test_cases]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]

    async def _score_all(self, samples: List[Dict]) -> List[SampleScore]:
        """并行计算所有样本的指标"""
        sem = asyncio.Semaphore(self.config.parallel_scoring)

        async def _limited_score(sample):
            async with sem:
                return await self._score_one(**sample)

        tasks = [_limited_score(s) for s in samples]
        return await asyncio.gather(*tasks)

    async def _score_one(
        self,
        question: str,
        answer: str,
        contexts: List[str],
        retrieved_doc_ids: List[str] = None,
        ground_truth: str = "",
        relevant_doc_ids: List[str] = None,
        expected_keywords: List[str] = None,
        expected_answer: str = "",
        exec_time: float = 0.0,
    ) -> SampleScore:
        """计算单个样本的全部指标"""
        # 检索指标：使用传入的实际 doc_id，或 fallback 到合成 ID
        if retrieved_doc_ids:
            actual_doc_ids = retrieved_doc_ids
        else:
            actual_doc_ids = [f"ctx_{i}" for i in range(len(contexts))]
        retrieval = calc_retrieval_metrics(
            retrieved_doc_ids=actual_doc_ids,
            retrieved_contents=contexts,
            relevant_doc_ids=relevant_doc_ids,
            expected_keywords=expected_keywords,
            top_k=self.config.top_k,
        )

        # Embedding 相似度指标
        if question and contexts:
            retrieval.context_precision = calc_context_precision_embedding(
                question, contexts, self.vectorizer
            )
            retrieval.context_relevancy = retrieval.context_precision

        # 生成指标
        gen = GenerationMetrics(answer_length=len(answer))
        if expected_answer:
            bleu = calc_bleu(expected_answer, answer)
            gen.bleu_1 = bleu.get("bleu_1", 0.0)
            gen.bleu_2 = bleu.get("bleu_2", 0.0)
            gen.rouge_l = calc_rouge_l(expected_answer, answer)
        if expected_keywords:
            gen.keyword_match_rate = calc_keyword_match_rate(answer, expected_keywords)

        # LLM 评判指标
        rag = RAGQualityMetrics()
        if self.config.use_llm_judge and answer and "faithfulness" in self.config.metrics:
            rag.faithfulness = await calc_faithfulness(question, answer, contexts, self.llm)
        if self.config.use_llm_judge and answer and "answer_relevancy" in self.config.metrics:
            rag.answer_relevancy = await calc_answer_relevancy(question, answer, self.llm)
        if (self.config.use_llm_judge and ground_truth and answer
                and "answer_correctness" in self.config.metrics):
            rag.answer_correctness = await calc_answer_correctness(
                question, answer, ground_truth, self.llm
            )

        return SampleScore(
            query=question,
            answer=answer,
            contexts=contexts,
            ground_truth=ground_truth,
            retrieval=retrieval,
            generation=gen,
            rag_quality=rag,
            execution_time=exec_time,
        )

    def _aggregate_metrics(self, sample_scores: List[SampleScore]) -> Dict:
        """汇总多样本指标为平均值"""
        if not sample_scores:
            return {}

        n = len(sample_scores)
        retrieval = {
            "precision": round(sum(s.retrieval.precision for s in sample_scores) / n, 4),
            "recall": round(sum(s.retrieval.recall for s in sample_scores) / n, 4),
            "f1_score": round(sum(s.retrieval.f1_score for s in sample_scores) / n, 4),
            "mrr": round(sum(s.retrieval.mrr for s in sample_scores) / n, 4),
            "ndcg": round(sum(s.retrieval.ndcg for s in sample_scores) / n, 4),
            "hit_rate": round(sum(s.retrieval.hit_rate for s in sample_scores) / n, 4),
        }
        generation = {
            "bleu_1": round(sum(s.generation.bleu_1 for s in sample_scores) / n, 4),
            "bleu_2": round(sum(s.generation.bleu_2 for s in sample_scores) / n, 4),
            "rouge_l": round(sum(s.generation.rouge_l for s in sample_scores) / n, 4),
            "keyword_match_rate": round(sum(s.generation.keyword_match_rate for s in sample_scores) / n, 4),
            "avg_answer_length": sum(s.generation.answer_length for s in sample_scores) // max(n, 1),
        }
        rag_quality = {
            "faithfulness": round(sum(s.rag_quality.faithfulness for s in sample_scores) / n, 4),
            "answer_relevancy": round(sum(s.rag_quality.answer_relevancy for s in sample_scores) / n, 4),
            "answer_correctness": round(sum(s.rag_quality.answer_correctness for s in sample_scores) / n, 4),
            "context_precision": round(sum(s.retrieval.context_precision for s in sample_scores) / n, 4),
            "context_relevancy": round(sum(s.retrieval.context_relevancy for s in sample_scores) / n, 4),
        }

        # 综合平均分
        all_scores = []
        all_scores.extend(retrieval.values())
        all_scores.extend([generation["bleu_1"], generation["bleu_2"], generation["rouge_l"], generation["keyword_match_rate"]])
        all_scores.extend([v for v in rag_quality.values() if v > 0])
        avg_score = round(sum(all_scores) / max(len(all_scores), 1), 4)

        return {
            "retrieval": retrieval,
            "generation": generation,
            "rag_quality": rag_quality,
            "avg_score": avg_score,
        }

    def _score_to_dict(self, score: SampleScore) -> Dict:
        """将 SampleScore 转为可序列化字典"""
        return {
            "query": score.query[:80],
            "answer": score.answer[:300],
            "context_count": len(score.contexts),
            "ground_truth": score.ground_truth[:100],
            "precision": score.retrieval.precision,
            "recall": score.retrieval.recall,
            "f1": score.retrieval.f1_score,
            "mrr": score.retrieval.mrr,
            "ndcg": score.retrieval.ndcg,
            "hit_rate": score.retrieval.hit_rate,
            "context_precision": score.retrieval.context_precision,
            "bleu_1": score.generation.bleu_1,
            "bleu_2": score.generation.bleu_2,
            "rouge_l": score.generation.rouge_l,
            "keyword_match_rate": score.generation.keyword_match_rate,
            "faithfulness": score.rag_quality.faithfulness,
            "answer_relevancy": score.rag_quality.answer_relevancy,
            "answer_correctness": score.rag_quality.answer_correctness,
            "execution_time": round(score.execution_time, 2),
        }

    def format_report(self, report: EvalReport) -> str:
        """生成 HTML 报告"""
        details = [self._score_to_dict(s) for s in report.sample_scores]
        return format_report_html(
            metrics=report.avg_metrics,
            details=details,
            total_time=report.total_time,
            charts=report.charts,
        )