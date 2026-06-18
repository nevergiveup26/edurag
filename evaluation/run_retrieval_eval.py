"""
纯检索评测脚本 — 不走 Self-RAG / LLM，只测 HybridRetriever 检索质量
"""
import json
import time
import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.models import DocumentChunk
from core.logger import get_logger
from retriever.hybrid_retriever import HybridRetriever
from database.chunk_store import load_chunks
import numpy as np

logger = get_logger("retrieval_eval")


def build_retriever():
    """从 chunk_store 加载全部数据构建 HybridRetriever"""
    chunks_data = load_chunks()
    chunks = []
    for item in chunks_data:
        chunks.append(DocumentChunk(
            chunk_id=item["chunk_id"],
            doc_id=item["doc_id"],
            content=item["content"],
            metadata=item.get("metadata", {}),
            embedding=np.array(item["embedding"], dtype=np.float32),
        ))
    retriever = HybridRetriever()
    retriever.build_index(chunks)
    logger.info(f"检索器就绪: {len(chunks)} 个片段")
    return retriever, chunks


def load_cmrc_samples(data_path: str, limit: int = None):
    """加载 CMRC dev 数据并构建评估样本"""
    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    samples = []
    for doc in data.get("data", []):
        for para in doc.get("paragraphs", []):
            context_id = para["id"]
            expected_doc_id = f"cmrc_{context_id}"
            for qa in para.get("qas", []):
                samples.append({
                    "query": qa["question"],
                    "expected_doc_id": expected_doc_id,
                    "answers": [a["text"] for a in qa.get("answers", [])],
                })
    if limit:
        samples = samples[:limit]
    logger.info(f"加载 {len(samples)} 个评估样本")
    return samples


def calc_metrics(samples, retriever, top_k=5):
    """逐样本检索并计算指标"""
    hits = 0
    reciprocal_ranks = []
    precisions = []
    recalls = []
    ndcgs = []
    per_sample = []
    total_time = 0.0

    for i, s in enumerate(samples):
        t0 = time.time()
        results = retriever.search(s["query"], top_k=top_k)
        elapsed = time.time() - t0
        total_time += elapsed

        retrieved_ids = [r.chunk.doc_id for r in results[:top_k]]
        expected = s["expected_doc_id"]

        # hit@k
        hit = expected in retrieved_ids
        if hit:
            hits += 1

        # MRR
        rank = next((j + 1 for j, rid in enumerate(retrieved_ids) if rid == expected), 0)
        rr = 1.0 / rank if rank > 0 else 0.0
        reciprocal_ranks.append(rr)

        # Precision@k / Recall@k
        relevant_in_top = 1 if hit else 0
        prec = relevant_in_top / top_k
        rec = relevant_in_top / 1  # one relevant doc
        precisions.append(prec)
        recalls.append(rec)

        # NDCG@k
        dcg = 0.0
        for j, rid in enumerate(retrieved_ids):
            if rid == expected:
                dcg = 1.0 / math.log2(j + 2)
                break
        # ideal DCG: relevant at rank 1
        idcg = 1.0 / math.log2(2)
        ndcg = dcg / idcg if idcg > 0 else 0.0
        ndcgs.append(ndcg)

        per_sample.append({
            "index": i,
            "query": s["query"][:60],
            "hit": hit,
            "rank": rank,
            "rr": round(rr, 4),
            "time_ms": round(elapsed * 1000, 1),
        })

        if (i + 1) % 50 == 0:
            n = i + 1
            logger.info(f"进度 [{n}/{len(samples)}] hit_rate={hits/n:.1%} mrr={sum(reciprocal_ranks)/n:.3f}")

    n = len(samples)
    return {
        "sample_count": n,
        "top_k": top_k,
        "hit_rate": round(hits / n, 4),
        "mrr": round(sum(reciprocal_ranks) / n, 4),
        "precision": round(sum(precisions) / n, 4),
        "recall": round(sum(recalls) / n, 4),
        "ndcg": round(sum(ndcgs) / n, 4),
        "f1": round(2 * (sum(precisions)/n) * (sum(recalls)/n) / ((sum(precisions)/n) + (sum(recalls)/n)), 4) if (sum(precisions)/n + sum(recalls)/n) > 0 else 0,
        "total_time_s": round(total_time, 2),
        "avg_time_ms": round(total_time * 1000 / n, 1),
        "per_sample": per_sample,
    }


def print_report(metrics):
    print("\n" + "=" * 60)
    print("  CMRC 2018 纯检索评测报告 (No LLM / No Self-RAG)")
    print("=" * 60)
    print(f"  样本数:     {metrics['sample_count']}")
    print(f"  Top-K:      {metrics['top_k']}")
    print(f"  总耗时:     {metrics['total_time_s']}s")
    print(f"  平均耗时:   {metrics['avg_time_ms']}ms/查询")
    print("-" * 60)
    print("  【检索指标】")
    print(f"  Hit@{metrics['top_k']}:       {metrics['hit_rate']:.2%}")
    print(f"  MRR:          {metrics['mrr']:.4f}")
    print(f"  Precision@{metrics['top_k']}: {metrics['precision']:.2%}")
    print(f"  Recall@{metrics['top_k']}:    {metrics['recall']:.2%}")
    print(f"  NDCG@{metrics['top_k']}:      {metrics['ndcg']:.4f}")
    print(f"  F1@{metrics['top_k']}:        {metrics['f1']:.4f}")
    print("-" * 60)
    # 按 rank 分布
    rank_dist = {}
    for s in metrics["per_sample"]:
        r = s["rank"] if s["rank"] > 0 else "miss"
        rank_dist[r] = rank_dist.get(r, 0) + 1
    print("  【命中排名分布】")
    for rk in sorted([k for k in rank_dist if isinstance(k, int)]):
        print(f"  Rank {rk}: {rank_dist[rk]} ({rank_dist[rk]/metrics['sample_count']:.1%})")
    if "miss" in rank_dist:
        print(f"  Miss:    {rank_dist['miss']} ({rank_dist['miss']/metrics['sample_count']:.1%})")
    print("=" * 60)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200, help="样本数（默认200）")
    parser.add_argument("--top-k", type=int, default=5, help="检索返回数")
    parser.add_argument("--data", type=str, default=None, help="CMRC json 路径")
    args = parser.parse_args()

    data_path = args.data or os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "cmrc2018", "squad-style-data", "cmrc2018_dev.json"
    )

    # 1. 构建检索器（一次性）
    logger.info("构建 HybridRetriever...")
    retriever, chunks = build_retriever()
    chunks_data_raw = load_chunks()
    cmrc_chunks = [c for c in chunks_data_raw if c.get("doc_id", "").startswith("cmrc_")]
    logger.info(f"chunk_store 总量: {len(chunks)} 片段, 其中 CMRC: {len(cmrc_chunks)} 片段")

    # 2. 加载样本
    samples = load_cmrc_samples(data_path, limit=args.limit)

    # 3. 评测
    logger.info(f"开始检索评测 ({args.limit} 条)...")
    metrics = calc_metrics(samples, retriever, top_k=args.top_k)

    # 4. 输出报告
    print_report(metrics)

    # 5. 保存结果
    out_path = os.path.join(os.path.dirname(__file__), "retrieval_eval_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    logger.info(f"结果已保存到 {out_path}")


if __name__ == "__main__":
    main()
