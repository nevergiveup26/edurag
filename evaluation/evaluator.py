"""
模型效果评估模块
评估RAG系统的检索质量和生成质量

指标说明：
- 检索准确率 (Precision): 检索到的相关文档数 / 检索到的总文档数
- 检索召回率 (Recall): 检索到的相关文档数 / 所有相关文档数
- F1分数: 准确率与召回率的调和平均
- MRR (Mean Reciprocal Rank): 第一个相关文档的排名倒数
- NDCG (Normalized Discounted Cumulative Gain): 归一化折损累计增益
- 生成指标: BLEU-1/2, ROUGE-L, 关键词匹配率, LLM评判分数
"""
import json
import time
import math
from typing import List, Dict, Tuple, Optional, Callable
from dataclasses import dataclass, field

from core.models import QueryRequest, QueryResponse, RetrievalResult
from core.logger import get_logger

logger = get_logger("evaluator")

import warnings
warnings.warn(
    "evaluator.py is deprecated. Use evaluation.unified_evaluator.UnifiedEvaluator instead.",
    DeprecationWarning,
    stacklevel=2,
)

# 尝试导入可视化库
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    HAS_MATPLOTLIB = True

    # 初始化时配置中文字体（后续所有图表自动生效）
    _CN_FONTS = ["Noto Sans SC", "SimHei", "Microsoft YaHei", "WenQuanYi Micro Hei"]
    for _fn in _CN_FONTS:
        try:
            fm.findfont(_fn, fallback_to_default=False)
            plt.rcParams["font.sans-serif"] = [_fn]
            plt.rcParams["axes.unicode_minus"] = False
            break
        except Exception:
            continue
    else:
        logger.warning("未找到中文字体，图表中的中文可能显示为乱码（已尝试: %s）", _CN_FONTS)
except ImportError:
    HAS_MATPLOTLIB = False


# ═══════════════════════════════════════════════════════════════
# 数据类
# ═══════════════════════════════════════════════════════════════

@dataclass
class EvalSample:
    """评估样本"""
    query: str
    expected_answer: str             # 期望答案
    expected_keywords: List[str]     # 期望关键词
    relevant_doc_ids: List[str]      # 相关文档ID列表
    category: str = "general"        # 类别


@dataclass
class RetrievalMetrics:
    """检索指标"""
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    mrr: float = 0.0
    ndcg: float = 0.0
    hit_rate: float = 0.0   # 是否至少命中一个相关文档


@dataclass
class GenerationMetrics:
    """生成指标"""
    bleu_1: float = 0.0              # BLEU-1 (unigram)
    bleu_2: float = 0.0              # BLEU-2 (bigram)
    rouge_l: float = 0.0             # ROUGE-L F1
    keyword_match_rate: float = 0.0  # 关键词命中率
    llm_score: float = 0.0           # LLM评判分数 (0-1)，-1 表示未启用
    answer_length: int = 0
    avg_execution_time: float = 0.0


@dataclass
class EvalReport:
    """评估报告"""
    retrieval: RetrievalMetrics = field(default_factory=RetrievalMetrics)
    generation: GenerationMetrics = field(default_factory=GenerationMetrics)
    sample_count: int = 0
    total_time: float = 0.0
    sample_reports: List[Dict] = field(default_factory=list)
    charts: Dict[str, str] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# 文本度量工具
# ═══════════════════════════════════════════════════════════════

def _tokenize_jieba(text: str) -> List[str]:
    """jieba 分词"""
    try:
        import jieba
        return list(jieba.cut(text.strip()))
    except ImportError:
        return list(text.strip())


def _calc_bleu(reference: str, candidate: str, max_n: int = 2) -> Dict[str, float]:
    """
    计算 BLEU-1 和 BLEU-2（使用 jieba 分词）
    返回 {"bleu_1": float, "bleu_2": float}
    """
    if not candidate or not reference:
        return {"bleu_1": 0.0, "bleu_2": 0.0}

    ref_tokens = [_tokenize_jieba(reference)]
    cand_tokens = _tokenize_jieba(candidate)

    if len(cand_tokens) == 0:
        return {"bleu_1": 0.0, "bleu_2": 0.0}

    scores = {}
    for n in (1, 2):
        if len(cand_tokens) < n:
            scores[f"bleu_{n}"] = 0.0
            continue

        # Count n-gram matches
        def _ngrams(tokens, n):
            return [tuple(tokens[i:i+n]) for i in range(len(tokens) - n + 1)]

        cand_ngrams = _ngrams(cand_tokens, n)
        ref_ngrams = _ngrams(ref_tokens[0], n)

        if not cand_ngrams:
            scores[f"bleu_{n}"] = 0.0
            continue

        # Clip counts
        ref_counts = {}
        for ng in ref_ngrams:
            ref_counts[ng] = ref_counts.get(ng, 0) + 1

        matches = 0
        cand_counts = {}
        for ng in cand_ngrams:
            cand_counts[ng] = cand_counts.get(ng, 0) + 1

        for ng, count in cand_counts.items():
            matches += min(count, ref_counts.get(ng, 0))

        precision = matches / len(cand_ngrams)

        # Brevity penalty
        bp = min(1.0, math.exp(1 - len(ref_tokens[0]) / max(len(cand_tokens), 1)))
        scores[f"bleu_{n}"] = round(bp * precision, 4)

    return scores


def _calc_rouge_l(reference: str, candidate: str) -> float:
    """
    计算 ROUGE-L F1（基于最长公共子序列 LCS）
    参考 CMRC 2018 官方评估的分词方式
    """
    if not candidate or not reference:
        return 0.0

    # 字符级分词：中文单字切分，英文按空白切分
    def _tokenize(text: str) -> List[str]:
        tokens = []
        temp = ""
        for ch in text.lower().strip():
            if '一' <= ch <= '鿿' or '㐀' <= ch <= '䶿':
                if temp:
                    tokens.extend(temp.split())
                    temp = ""
                tokens.append(ch)
            else:
                temp += ch
        if temp:
            tokens.extend(temp.split())
        return tokens

    ref_tokens = _tokenize(reference)
    cand_tokens = _tokenize(candidate)

    if not ref_tokens or not cand_tokens:
        return 0.0

    # LCS 动态规划
    m, n = len(ref_tokens), len(cand_tokens)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if ref_tokens[i-1] == cand_tokens[j-1]:
                dp[i][j] = dp[i-1][j-1] + 1
            else:
                dp[i][j] = max(dp[i-1][j], dp[i][j-1])

    lcs_len = dp[m][n]
    if lcs_len == 0:
        return 0.0

    precision = lcs_len / len(cand_tokens)
    recall = lcs_len / len(ref_tokens)
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    return round(f1, 4)


def _llm_judge_correctness(expected: str, generated: str, query: str = "",
                           llm_client=None) -> float:
    """
    使用 LLM 评判答案正确性（0-1 分数）
    与标准答案对比，评估语义一致性
    """
    if not expected or not generated:
        return -1.0

    if llm_client is None:
        try:
            from llm.llm_client import get_fast_llm
            llm_client = get_fast_llm()
        except Exception:
            return -1.0

    prompt = f"""你是一个教育领域的答案评判专家。请对比【学生答案】与【标准答案】，评估学生答案的正确性。

【问题】
{query[:200]}

【标准答案】
{expected[:500]}

【学生答案】
{generated[:500]}

请从以下维度评判（0-10分）：
1. 核心结论是否正确（关键事实、答案选项是否一致）
2. 推理过程是否合理（如有分析说明）
3. 是否包含无关或错误信息

返回JSON格式：
{{"score": <0-10的整数>, "correct": <true/false>, "reason": "<一句话说明>"}}

仅返回JSON。"""

    try:
        response = llm_client.generate(prompt, max_tokens=200, temperature=0.0)
        # 解析 JSON
        text = response.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text)
        raw_score = float(result.get("score", 0))
        return round(raw_score / 10.0, 4)  # 归一化到 0-1
    except Exception as e:
        logger.debug(f"LLM评判失败: {e}")
        return -1.0


# ═══════════════════════════════════════════════════════════════
# RAG 评估器
# ═══════════════════════════════════════════════════════════════

class RAGEvaluator:
    """RAG系统效果评估器"""

    def __init__(self, samples: List[EvalSample] = None,
                 use_llm_judge: bool = False,
                 max_samples: int = None):
        """
        Args:
            samples: 评估样本列表
            use_llm_judge: 是否启用 LLM 答案正确性评判（较慢但更准确）
            max_samples: 最大评估样本数（None 表示全部）
        """
        self.samples = samples or []
        self.use_llm_judge = use_llm_judge
        self.max_samples = max_samples
        self._llm_client = None

    @property
    def llm_client(self):
        if self._llm_client is None:
            try:
                from llm.llm_client import get_fast_llm
                self._llm_client = get_fast_llm()
            except Exception:
                pass
        return self._llm_client

    # ── 检索评估 ──

    def evaluate_retrieval(self, results: List[RetrievalResult],
                           sample: EvalSample, top_k: int = 5) -> RetrievalMetrics:
        """
        评估检索效果

        相关性判定逻辑（统一）：
        1. 优先使用 doc_id 精确匹配
        2. 若 relevant_doc_ids 为空，回退到关键词内容匹配
        """
        retrieved_ids = [r.chunk.doc_id for r in results[:top_k]]
        retrieved_contents = [r.chunk.content for r in results[:top_k]]
        relevant_ids = set(sample.relevant_doc_ids)

        if not retrieved_ids:
            return RetrievalMetrics()

        # ── 相关性判定 ──
        has_doc_id_ground_truth = bool(relevant_ids)

        if has_doc_id_ground_truth:
            # 精确匹配模式：只有 doc_id 在 relevant_ids 中才算相关
            relevant_mask = [rid in relevant_ids for rid in retrieved_ids]
            total_relevant = len(relevant_ids)
            matched_count = sum(1 for rid in retrieved_ids if rid in relevant_ids)
        else:
            # 回退模式：无 doc_id 标注时，用关键词内容匹配
            keywords = sample.expected_keywords
            if keywords:
                relevant_mask = [
                    any(kw.lower() in retrieved_contents[i].lower() for kw in keywords)
                    for i in range(len(retrieved_ids))
                ]
                # 召回率 = 检索结果中覆盖的关键词数 / 总关键词数
                all_content = " ".join(retrieved_contents).lower()
                matched_count = sum(1 for kw in keywords if kw.lower() in all_content)
                total_relevant = len(keywords)
            else:
                relevant_mask = [False] * len(retrieved_ids)
                total_relevant = 0
                matched_count = 0

        retrieved_relevant_count = sum(1 for r in relevant_mask if r)

        # 准确率
        precision = retrieved_relevant_count / len(retrieved_ids)

        # 召回率
        if total_relevant > 0:
            recall = matched_count / total_relevant
        else:
            recall = 0.0

        # F1
        if precision + recall > 0:
            f1 = 2 * precision * recall / (precision + recall)
        else:
            f1 = 0.0

        # MRR
        mrr = 0.0
        for i, r in enumerate(relevant_mask):
            if r:
                mrr = 1.0 / (i + 1)
                break

        # NDCG
        ndcg = self._calc_ndcg(relevant_mask, top_k)

        # 命中率
        hit_rate = 1.0 if retrieved_relevant_count > 0 else 0.0

        return RetrievalMetrics(
            precision=precision,
            recall=recall,
            f1_score=f1,
            mrr=mrr,
            ndcg=ndcg,
            hit_rate=hit_rate,
        )

    def _calc_ndcg(self, relevant_mask: List[bool], k: int) -> float:
        """计算NDCG@k（基于相关性掩码）"""
        relevance_scores = [1.0 if r else 0.0 for r in relevant_mask[:k]]
        ideal_relevance = sorted(relevance_scores, reverse=True)
        ideal_dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(ideal_relevance))

        if ideal_dcg == 0:
            return 0.0

        actual_dcg = sum(
            rel / math.log2(i + 2) for i, rel in enumerate(relevance_scores)
        )
        return actual_dcg / ideal_dcg

    # ── 生成评估 ──

    def evaluate_generation(self, answer: str, sample: EvalSample,
                            exec_time: float = 0.0,
                            query: str = "") -> GenerationMetrics:
        """
        评估生成质量

        计算 BLEU-1, BLEU-2, ROUGE-L, 关键词匹配率, 可选的 LLM 评判
        """
        expected = sample.expected_answer

        # 关键词匹配率（保留作为快速参考）
        if sample.expected_keywords:
            hit_count = sum(
                1 for kw in sample.expected_keywords
                if kw.lower() in answer.lower()
            )
            keyword_match_rate = hit_count / len(sample.expected_keywords)
        else:
            keyword_match_rate = 0.0

        # BLEU & ROUGE-L（当有参考答案时计算）
        bleu_1, bleu_2, rouge_l = 0.0, 0.0, 0.0
        if expected:
            bleu_scores = _calc_bleu(expected, answer)
            bleu_1 = bleu_scores.get("bleu_1", 0.0)
            bleu_2 = bleu_scores.get("bleu_2", 0.0)
            rouge_l = _calc_rouge_l(expected, answer)

        # LLM 评判
        llm_score = -1.0
        if self.use_llm_judge and expected:
            llm_score = _llm_judge_correctness(
                expected, answer, query=query, llm_client=self.llm_client
            )

        return GenerationMetrics(
            bleu_1=bleu_1,
            bleu_2=bleu_2,
            rouge_l=rouge_l,
            keyword_match_rate=keyword_match_rate,
            llm_score=llm_score,
            answer_length=len(answer),
            avg_execution_time=exec_time,
        )

    # ── 完整评估 ──

    def run_full_evaluation(self, query_func):
        """运行完整评估（已委托给 UnifiedEvaluator）"""
        import asyncio
        from evaluation.unified_evaluator import UnifiedEvaluator, EvalConfig

        test_cases = [
            {
                "question": s.query,
                "expected_answer": s.expected_answer,
                "expected_keywords": s.expected_keywords,
                "relevant_doc_ids": s.relevant_doc_ids,
            }
            for s in self.samples
        ]

        evaluator = UnifiedEvaluator(EvalConfig(
            use_llm_judge=self.use_llm_judge,
            max_samples=self.max_samples,
        ))
        unified_report = asyncio.run(evaluator.evaluate(test_cases, query_func))

        # 转换回旧格式 EvalReport
        avg_r = RetrievalMetrics(
            precision=unified_report.avg_metrics["retrieval"]["precision"],
            recall=unified_report.avg_metrics["retrieval"]["recall"],
            f1_score=unified_report.avg_metrics["retrieval"]["f1_score"],
            mrr=unified_report.avg_metrics["retrieval"]["mrr"],
            ndcg=unified_report.avg_metrics["retrieval"]["ndcg"],
            hit_rate=unified_report.avg_metrics["retrieval"]["hit_rate"],
        )
        avg_g = GenerationMetrics(
            bleu_1=unified_report.avg_metrics["generation"]["bleu_1"],
            bleu_2=unified_report.avg_metrics["generation"]["bleu_2"],
            rouge_l=unified_report.avg_metrics["generation"]["rouge_l"],
            keyword_match_rate=unified_report.avg_metrics["generation"]["keyword_match_rate"],
            answer_length=unified_report.avg_metrics["generation"].get("avg_answer_length", 0),
            avg_execution_time=unified_report.total_time / max(unified_report.sample_count, 1),
        )

        return EvalReport(
            retrieval=avg_r,
            generation=avg_g,
            sample_count=unified_report.sample_count,
            total_time=unified_report.total_time,
            sample_reports=[evaluator._score_to_dict(s) for s in unified_report.sample_scores],
            charts=unified_report.charts,
        )

    def run_full_evaluation_stream(self, query_func, cancel_event=None, progress_callback=None):
        """运行流式评估（已委托给 UnifiedEvaluator）"""
        import asyncio
        from evaluation.unified_evaluator import UnifiedEvaluator, EvalConfig

        test_cases = [
            {
                "question": s.query,
                "expected_answer": s.expected_answer,
                "expected_keywords": s.expected_keywords,
                "relevant_doc_ids": s.relevant_doc_ids,
            }
            for s in self.samples
        ]

        evaluator = UnifiedEvaluator(EvalConfig(
            use_llm_judge=self.use_llm_judge,
            max_samples=self.max_samples,
        ))

        async def _run():
            async for evt in evaluator.evaluate_stream(test_cases, query_func):
                yield evt

        return asyncio.run(self._collect_stream_results(_run()))

    # ── 图表 ──

    def generate_charts(self, sample_reports: List[Dict]) -> Dict[str, str]:
        """生成评估图表（返回base64编码的图片）"""
        import base64
        import io

        charts = {}

        try:
            n = max(len(sample_reports), 1)

            # 图1: 检索指标柱状图
            fig, ax = plt.subplots(figsize=(8, 5))
            metrics_names = ["准确率", "召回率", "F1", "MRR", "NDCG", "命中率"]
            values = [
                sum(r.get("precision", 0) for r in sample_reports) / n,
                sum(r.get("recall", 0) for r in sample_reports) / n,
                sum(r.get("f1", 0) for r in sample_reports) / n,
                sum(r.get("mrr", 0) for r in sample_reports) / n,
                sum(r.get("ndcg", 0) if "ndcg" in r else 0 for r in sample_reports) / n,
                sum(r.get("hit_rate", 0) if "hit_rate" in r else 0 for r in sample_reports) / n,
            ]
            colors = ["#4CAF50", "#2196F3", "#FF9800", "#9C27B0", "#E91E63", "#00BCD4"]
            bars = ax.bar(metrics_names, values, color=colors, edgecolor="white")
            for bar, val in zip(bars, values):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                        f"{val:.2%}", ha="center", va="bottom", fontsize=10)
            ax.set_ylim(0, 1.1)
            ax.set_title("检索效果评估指标", fontsize=14, fontweight="bold")
            ax.set_ylabel("分数")
            fig.tight_layout()
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=100)
            buf.seek(0)
            charts["retrieval_metrics"] = base64.b64encode(buf.read()).decode()
            plt.close(fig)

            # 图2: 生成指标（BLEU + ROUGE-L）横向条形图（取前20条）
            top_n = min(20, len(sample_reports))
            display_reports = sample_reports[:top_n]
            queries = [r.get("query", "")[:15] + "..." for r in display_reports]
            y_pos = range(len(queries))

            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

            # BLEU-1 & ROUGE-L
            bleu_vals = [r.get("bleu_1", 0) for r in display_reports]
            rouge_vals = [r.get("rouge_l", 0) for r in display_reports]
            x = range(len(queries))
            width = 0.35
            ax1.barh([i + width/2 for i in x], bleu_vals, width, label="BLEU-1", color="#2196F3", edgecolor="white")
            ax1.barh([i - width/2 for i in x], rouge_vals, width, label="ROUGE-L", color="#4CAF50", edgecolor="white")
            ax1.set_yticks(x)
            ax1.set_yticklabels(queries, fontsize=8)
            ax1.set_xlabel("分数")
            ax1.set_title("生成质量: BLEU-1 & ROUGE-L", fontsize=12, fontweight="bold")
            ax1.set_xlim(0, 1.1)
            ax1.legend(fontsize=8)

            # 关键词匹配率
            kw_rates = [r.get("keyword_match_rate", 0) for r in display_reports]
            ax2.barh(y_pos, kw_rates, color="#FF9800", edgecolor="white")
            ax2.set_yticks(y_pos)
            ax2.set_yticklabels(queries, fontsize=8)
            ax2.set_xlabel("关键词匹配率")
            ax2.set_title("关键词匹配率", fontsize=12, fontweight="bold")
            ax2.set_xlim(0, 1.1)

            fig.tight_layout()
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=100)
            buf.seek(0)
            charts["generation_metrics"] = base64.b64encode(buf.read()).decode()
            plt.close(fig)

            # 图3: 执行时间分布
            exec_times = [r.get("execution_time", 0) for r in sample_reports]
            fig, ax = plt.subplots(figsize=(8, 4))
            ax.barh(range(len(queries)), exec_times[:top_n], color="#FF9800", edgecolor="white")
            ax.set_yticks(range(len(queries)))
            ax.set_yticklabels(queries, fontsize=9)
            ax.set_xlabel("执行时间 (秒)")
            ax.set_title("查询执行时间", fontsize=14, fontweight="bold")
            for i, v in enumerate(exec_times[:top_n]):
                ax.text(v + 0.01, i, f"{v:.2f}s", va="center", fontsize=9)
            fig.tight_layout()
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=100)
            buf.seek(0)
            charts["execution_time"] = base64.b64encode(buf.read()).decode()
            plt.close(fig)

        except Exception as e:
            logger.warning(f"图表生成失败: {e}")

        return charts

    # ── 报告输出 ──

    def print_report(self, report: EvalReport):
        """打印评估报告到控制台"""
        print("\n" + "=" * 60)
        print("  EduRAG 智慧问答系统 - 效果评估报告")
        print("=" * 60)
        print(f"  评估样本数: {report.sample_count}")
        print(f"  总耗时: {report.total_time:.2f}s")
        print(f"  平均耗时: {report.generation.avg_execution_time:.2f}s/样本")
        print("-" * 60)
        print("  【检索效果】")
        print(f"  准确率 (Precision):  {report.retrieval.precision:.2%}")
        print(f"  召回率 (Recall):     {report.retrieval.recall:.2%}")
        print(f"  F1分数:              {report.retrieval.f1_score:.2%}")
        print(f"  MRR:                 {report.retrieval.mrr:.2%}")
        print(f"  命中率 (Hit Rate):    {report.retrieval.hit_rate:.2%}")
        print("-" * 60)
        print("  【生成效果】")
        print(f"  BLEU-1:        {report.generation.bleu_1:.4f}")
        print(f"  BLEU-2:        {report.generation.bleu_2:.4f}")
        print(f"  ROUGE-L:       {report.generation.rouge_l:.4f}")
        print(f"  关键词匹配率:   {report.generation.keyword_match_rate:.2%}")
        if report.generation.llm_score >= 0:
            print(f"  LLM评判分数:    {report.generation.llm_score:.2%}")
        print(f"  平均答案长度:   {report.generation.answer_length} 字")
        print("-" * 60)
        print("  【各样本详情】")
        for i, sr in enumerate(report.sample_reports):
            print(f"  [{i+1}] {sr['query'][:40]}")
            print(f"      BLEU-1={sr.get('bleu_1', 0):.3f}  ROUGE-L={sr.get('rouge_l', 0):.3f}  "
                  f"KW={sr.get('keyword_match_rate', 0):.2%}  "
                  f"P={sr.get('precision', 0):.2%}  R={sr.get('recall', 0):.2%}  "
                  f"耗时={sr.get('execution_time', 0):.2f}s")
        print("=" * 60)


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def run_quick_eval():
    """快速评估（通过API调用）"""
    import requests

    base_url = "http://localhost:8000/api/v1"

    def query_func(query: str):
        resp = requests.post(f"{base_url}/query", json={"query": query}, timeout=60)
        data = resp.json()
        from core.models import QueryResponse, RetrievalResult, DocumentChunk
        sources = []
        for s in data.get("sources", []):
            chunk = DocumentChunk(
                content=s.get("content", ""),
                chunk_id=s.get("metadata", {}).get("doc_id", ""),
                doc_id=s.get("metadata", {}).get("doc_id", ""),
                metadata=s.get("metadata", {}),
            )
            sources.append(RetrievalResult(chunk=chunk, score=s.get("score", 0), source=s.get("source", "")))
        return QueryResponse(
            answer=data.get("answer", ""),
            sources=sources,
            strategy_used=data.get("strategy_used", ""),
            router_used=data.get("router_used", ""),
            execution_time=data.get("execution_time", 0),
        )

    evaluator = RAGEvaluator()
    report = evaluator.run_full_evaluation(query_func)
    evaluator.print_report(report)
    return report


if __name__ == "__main__":
    run_quick_eval()
