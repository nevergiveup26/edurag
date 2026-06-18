"""
消融实验模块

支持分组件评估 RAG 管道各环节的独立贡献：
- 检索方式：BM25-only / Vector-only / Hybrid（默认3:7）
- 重排序：reranker 开/关
- Self-RAG：质量循环 开/关

输出各配置的对比报告，定位性能瓶颈。
"""
import json
import time
import math
from typing import List, Dict, Callable, Optional
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from core.logger import get_logger
from core.models import DocumentChunk, RetrievalResult
from evaluation.evaluator import RAGEvaluator, EvalSample, RetrievalMetrics, GenerationMetrics

logger = get_logger("ablation")


# ═══════════════════════════════════════════════════════════════
# 消融配置
# ═══════════════════════════════════════════════════════════════

@dataclass
class AblationConfig:
    """单个消融实验配置"""
    name: str                          # 配置名称
    description: str                   # 描述
    bm25_weight: float = 0.3           # BM25 权重
    vector_weight: float = 0.7         # 向量权重
    use_reranker: bool = True          # 是否启用重排序
    use_self_rag: bool = False         # 是否启用 Self-RAG 质量循环


# 预定义消融配置
ABLATION_CONFIGS = [
    AblationConfig(
        name="full_pipeline",
        description="完整管道: BM25+向量(3:7) + Reranker",
        bm25_weight=0.3, vector_weight=0.7,
        use_reranker=True, use_self_rag=False,
    ),
    AblationConfig(
        name="bm25_only",
        description="仅 BM25 稀疏检索",
        bm25_weight=1.0, vector_weight=0.0,
        use_reranker=False, use_self_rag=False,
    ),
    AblationConfig(
        name="vector_only",
        description="仅向量密集检索",
        bm25_weight=0.0, vector_weight=1.0,
        use_reranker=False, use_self_rag=False,
    ),
    AblationConfig(
        name="hybrid_no_rerank",
        description="混合检索(无重排序)",
        bm25_weight=0.3, vector_weight=0.7,
        use_reranker=False, use_self_rag=False,
    ),
    AblationConfig(
        name="bm25_with_rerank",
        description="BM25 + Reranker",
        bm25_weight=1.0, vector_weight=0.0,
        use_reranker=True, use_self_rag=False,
    ),
    AblationConfig(
        name="vector_with_rerank",
        description="向量检索 + Reranker",
        bm25_weight=0.0, vector_weight=1.0,
        use_reranker=True, use_self_rag=False,
    ),
]


@dataclass
class AblationResult:
    """单个消融配置的评估结果"""
    config: AblationConfig
    retrieval: RetrievalMetrics = field(default_factory=RetrievalMetrics)
    generation: GenerationMetrics = field(default_factory=GenerationMetrics)
    sample_count: int = 0
    total_time: float = 0.0
    avg_latency_ms: float = 0.0


# ═══════════════════════════════════════════════════════════════
# 消融实验运行器
# ═══════════════════════════════════════════════════════════════

class AblationRunner:
    """
    消融实验运行器

    用法:
        runner = AblationRunner()
        runner.load_chunks()           # 加载知识库
        runner.load_samples(samples)   # 加载评估样本
        results = runner.run(ABLATION_CONFIGS)  # 运行消融
        runner.print_comparison(results)        # 打印对比报告
    """

    def __init__(self, use_llm_judge: bool = False):
        self.chunks: List[DocumentChunk] = []
        self.samples: List[EvalSample] = []
        self.use_llm_judge = use_llm_judge
        self._llm_client = None
        self._reranker = None

    def load_chunks(self):
        """从 chunk_store 加载全部数据"""
        from database.chunk_store import load_chunks

        data = load_chunks()
        self.chunks = []
        for item in data:
            try:
                embedding = np.array(item["embedding"], dtype=np.float32)
            except (KeyError, TypeError):
                embedding = None
            self.chunks.append(DocumentChunk(
                chunk_id=item["chunk_id"],
                doc_id=item["doc_id"],
                content=item["content"],
                metadata=item.get("metadata", {}),
                embedding=embedding,
            ))
        logger.info(f"加载 {len(self.chunks)} 个 chunk")

    def load_samples(self, samples: List):
        """加载评估样本

        Args:
            samples: EvalSample 列表，或 dict 列表（自动转换）
        """
        if not samples:
            logger.warning("评估样本为空")
            return

        if isinstance(samples[0], EvalSample):
            self.samples = samples
        else:
            self.samples = [
                EvalSample(
                    query=s.get("query", ""),
                    expected_answer=s.get("expected_answer", ""),
                    expected_keywords=s.get("expected_keywords", []),
                    relevant_doc_ids=s.get("relevant_doc_ids", []),
                    category=s.get("category", "general"),
                )
                for s in samples
            ]
        logger.info(f"加载 {len(self.samples)} 个评估样本")

    @staticmethod
    def load_samples_from_file(path: str) -> List[dict]:
        """从 JSON 文件加载评估样本"""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ── 构建各消融配置的 query_func ──

    def _build_query_func(self, config: AblationConfig) -> Callable[[str], any]:
        """根据消融配置构建 query_func"""
        from types import SimpleNamespace
        from retriever.hybrid_retriever import HybridRetriever
        from llm.llm_client import LLMClient
        from llm.prompt_template import PromptTemplate
        from data_processor.rag_utils import trim_context_to_token_limit

        # 创建独立检索器，设置权重
        retriever = HybridRetriever()
        retriever.bm25_weight = config.bm25_weight
        retriever.vector_weight = config.vector_weight

        if self.chunks:
            retriever.build_index(self.chunks)

        llm_client = LLMClient()

        # 延迟加载 reranker
        reranker = None
        if config.use_reranker:
            try:
                from retriever.reranker import Reranker
                reranker = Reranker()
            except Exception as e:
                logger.warning(f"Reranker 初始化失败: {e}")

        def query_func(query: str):
            results = retriever.search(query, top_k=10)

            # 重排序
            if reranker and results:
                try:
                    results = reranker.rerank(query, results)
                except Exception:
                    pass

            results = results[:5]

            if results:
                parts = []
                for i, r in enumerate(results[:8]):
                    content = r.chunk.content if hasattr(r.chunk, 'content') else str(r)
                    parts.append(f"[{i+1}] {content[:500]}")
                context = "\n\n".join(parts)
                context = trim_context_to_token_limit(context, max_tokens=3000)
            else:
                context = ""

            prompt = PromptTemplate.generate_qa_prompt(query, context)
            answer = llm_client.generate(prompt)

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
            return SimpleNamespace(
                answer=answer,
                sources=sources,
                strategy_used=config.name,
                router_used=config.name,
                execution_time=0,
                conversation_id="",
            )

        return query_func

    # ── 运行消融实验 ──

    def run(self, configs: List[AblationConfig] = None) -> List[AblationResult]:
        """
        运行全部消融实验

        Returns:
            各配置的评估结果列表
        """
        if configs is None:
            configs = ABLATION_CONFIGS

        if not self.samples:
            raise RuntimeError("请先调用 load_samples() 加载评估样本")
        if not self.chunks:
            logger.warning("chunks 为空，检索可能无结果")

        results = []
        for i, config in enumerate(configs):
            logger.info(f"[{i+1}/{len(configs)}] 运行: {config.name} — {config.description}")

            evaluator = RAGEvaluator(samples=self.samples, use_llm_judge=self.use_llm_judge)
            query_func = self._build_query_func(config)

            t0 = time.time()
            report = evaluator.run_full_evaluation(query_func)
            elapsed = time.time() - t0

            result = AblationResult(
                config=config,
                retrieval=report.retrieval,
                generation=report.generation,
                sample_count=report.sample_count,
                total_time=elapsed,
                avg_latency_ms=round(elapsed * 1000 / max(report.sample_count, 1), 1),
            )
            results.append(result)

            logger.info(f"  P={result.retrieval.precision:.4f} R={result.retrieval.recall:.4f} "
                        f"F1={result.retrieval.f1_score:.4f} MRR={result.retrieval.mrr:.4f} "
                        f"BLEU-1={result.generation.bleu_1:.4f} ROUGE-L={result.generation.rouge_l:.4f}")

        return results

    # ── 结果输出 ──

    def print_comparison(self, results: List[AblationResult]):
        """打印消融对比报告"""
        print("\n" + "=" * 80)
        print("  EduRAG 消融实验报告 — 分组件效果对比")
        print("=" * 80)
        print(f"  样本数: {results[0].sample_count if results else 0}")
        print()

        # 表头
        header = f"  {'配置':<24} {'P':>6} {'R':>6} {'F1':>6} {'MRR':>7} {'Hit':>6}  {'BLEU-1':>7} {'ROUGE-L':>7} {'延迟':>7}"
        sep = "  " + "-" * (len(header) - 2)
        print(header)
        print(sep)

        # 找最优值（用于高亮）
        best_p = max(r.retrieval.precision for r in results) if results else 0
        best_r = max(r.retrieval.recall for r in results) if results else 0
        best_f1 = max(r.retrieval.f1_score for r in results) if results else 0
        best_mrr = max(r.retrieval.mrr for r in results) if results else 0
        best_hit = max(r.retrieval.hit_rate for r in results) if results else 0
        best_bleu = max(r.generation.bleu_1 for r in results) if results else 0
        best_rouge = max(r.generation.rouge_l for r in results) if results else 0

        for r in results:
            def mark(val, best):
                return f"\033[32m{val:7.4f}\033[0m" if val == best else f"{val:7.4f}"

            p_s = mark(r.retrieval.precision, best_p)
            r_s = mark(r.retrieval.recall, best_r)
            f1_s = mark(r.retrieval.f1_score, best_f1)
            mrr_s = mark(r.retrieval.mrr, best_mrr)
            hit_s = mark(r.retrieval.hit_rate, best_hit)
            bleu_s = mark(r.generation.bleu_1, best_bleu)
            rouge_s = mark(r.generation.rouge_l, best_rouge)

            line = (f"  {r.config.name:<24} {r.retrieval.precision:6.4f} {r.retrieval.recall:6.4f} "
                    f"{r.retrieval.f1_score:6.4f} {r.retrieval.mrr:7.4f} {r.retrieval.hit_rate:6.4f}  "
                    f"{r.generation.bleu_1:7.4f} {r.generation.rouge_l:7.4f} "
                    f"{r.avg_latency_ms:6.0f}ms")
            print(line)

        print(sep)

        # 最佳配置推荐
        print("\n  【最佳配置】")
        best_f1_config = max(results, key=lambda r: r.retrieval.f1_score)
        best_bleu_config = max(results, key=lambda r: r.generation.bleu_1)
        print(f"  检索最佳 (F1):  {best_f1_config.config.name} ({best_f1_config.config.description})")
        print(f"  生成最佳 (BLEU): {best_bleu_config.config.name} ({best_bleu_config.config.description})")

        # 增量分析：每个组件贡献
        print("\n  【组件贡献分析】")
        # 找 full_pipeline 和 hybrid_no_rerank
        full = next((r for r in results if r.config.name == "full_pipeline"), None)
        no_rerank = next((r for r in results if r.config.name == "hybrid_no_rerank"), None)
        if full and no_rerank:
            delta_f1 = full.retrieval.f1_score - no_rerank.retrieval.f1_score
            print(f"  Reranker 对 F1 的贡献: {delta_f1:+.4f} ({(delta_f1 / max(no_rerank.retrieval.f1_score, 0.001)) * 100:+.1f}%)")

        bm25 = next((r for r in results if r.config.name == "bm25_only"), None)
        vector = next((r for r in results if r.config.name == "vector_only"), None)
        if bm25 and vector:
            delta_f1 = vector.retrieval.f1_score - bm25.retrieval.f1_score
            print(f"  向量 vs BM25 的 F1 差: {delta_f1:+.4f}")

        print("=" * 80)

    def to_dict(self, results: List[AblationResult]) -> List[dict]:
        """将消融结果转为可序列化的字典列表"""
        out = []
        for r in results:
            out.append({
                "config": {
                    "name": r.config.name,
                    "description": r.config.description,
                    "bm25_weight": r.config.bm25_weight,
                    "vector_weight": r.config.vector_weight,
                    "use_reranker": r.config.use_reranker,
                    "use_self_rag": r.config.use_self_rag,
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
                    "llm_score": r.generation.llm_score,
                },
                "sample_count": r.sample_count,
                "total_time": r.total_time,
                "avg_latency_ms": r.avg_latency_ms,
            })
        return out

    def save_results(self, results: List[AblationResult], path: str):
        """保存消融结果到 JSON 文件"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(results), f, ensure_ascii=False, indent=2)
        logger.info(f"消融结果已保存到 {path}")


# ═══════════════════════════════════════════════════════════════
# 命令行入口
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="EduRAG 消融实验")
    parser.add_argument("--samples", type=str, default=None,
                        help="评估样本 JSON 路径（默认使用 K-12 测试集）")
    parser.add_argument("--limit", type=int, default=20,
                        help="评估样本数上限")
    parser.add_argument("--configs", type=str, nargs="*",
                        choices=[c.name for c in ABLATION_CONFIGS],
                        help="指定要运行的配置（默认全部）")
    parser.add_argument("--llm-judge", action="store_true",
                        help="启用 LLM 答案评判")
    parser.add_argument("--output", type=str, default=None,
                        help="结果输出 JSON 路径")
    args = parser.parse_args()

    # 加载样本
    if args.samples:
        sample_dicts = AblationRunner.load_samples_from_file(args.samples)
    else:
        default_path = Path(__file__).parent / "k12_test_set.json"
        if default_path.exists():
            sample_dicts = AblationRunner.load_samples_from_file(str(default_path))
        else:
            logger.error(f"找不到默认测试集: {default_path}")
            return

    sample_dicts = sample_dicts[:args.limit]

    # 选择配置
    if args.configs:
        configs = [c for c in ABLATION_CONFIGS if c.name in args.configs]
    else:
        configs = ABLATION_CONFIGS

    # 运行
    runner = AblationRunner(use_llm_judge=args.llm_judge)
    runner.load_chunks()
    runner.load_samples(sample_dicts)
    results = runner.run(configs)
    runner.print_comparison(results)

    if args.output:
        runner.save_results(results, args.output)


if __name__ == "__main__":
    main()
