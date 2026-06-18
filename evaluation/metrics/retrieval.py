"""
检索评估指标
- Precision@K, Recall@K, F1, MRR, NDCG, HitRate (doc_id/keyword matching)
- ContextPrecision, ContextRelevancy (embedding cosine similarity)
"""
import math
from typing import List, Optional
from dataclasses import dataclass, field
import numpy as np

from core.logger import get_logger

logger = get_logger("retrieval_metrics")


@dataclass
class RetrievalMetrics:
    """检索指标"""
    precision: float = 0.0
    recall: float = 0.0
    f1_score: float = 0.0
    mrr: float = 0.0
    ndcg: float = 0.0
    hit_rate: float = 0.0
    context_precision: float = 0.0
    context_relevancy: float = 0.0


def calc_retrieval_metrics(
    retrieved_doc_ids: List[str],
    retrieved_contents: List[str],
    relevant_doc_ids: Optional[List[str]] = None,
    expected_keywords: Optional[List[str]] = None,
    top_k: int = 5,
) -> RetrievalMetrics:
    """
    计算检索指标

    Args:
        retrieved_doc_ids: 检索到的文档 ID 列表
        retrieved_contents: 检索到的文档内容列表
        relevant_doc_ids: 相关文档 ID 列表（精确匹配模式）
        expected_keywords: 期望关键词列表（回退模式）
        top_k: 评估的 Top-K 值

    Returns:
        RetrievalMetrics
    """
    if not retrieved_doc_ids:
        return RetrievalMetrics()

    retrieved_doc_ids = retrieved_doc_ids[:top_k]
    retrieved_contents = retrieved_contents[:top_k]

    has_doc_id_gt = bool(relevant_doc_ids)
    relevant_ids_set = set(relevant_doc_ids or [])

    if has_doc_id_gt:
        relevant_mask = [rid in relevant_ids_set for rid in retrieved_doc_ids]
        total_relevant = len(relevant_ids_set)
        matched_count = sum(1 for rid in retrieved_doc_ids if rid in relevant_ids_set)
    else:
        keywords = expected_keywords or []
        if keywords:
            relevant_mask = [
                any(kw.lower() in retrieved_contents[i].lower() for kw in keywords)
                for i in range(len(retrieved_doc_ids))
            ]
            all_content = " ".join(retrieved_contents).lower()
            matched_count = sum(1 for kw in keywords if kw.lower() in all_content)
            total_relevant = len(keywords)
        else:
            relevant_mask = [False] * len(retrieved_doc_ids)
            total_relevant = 0
            matched_count = 0

    retrieved_relevant = sum(1 for r in relevant_mask if r)

    precision = retrieved_relevant / len(retrieved_doc_ids) if retrieved_doc_ids else 0.0
    recall = matched_count / total_relevant if total_relevant > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    mrr = 0.0
    for i, r in enumerate(relevant_mask):
        if r:
            mrr = 1.0 / (i + 1)
            break

    ndcg = _calc_ndcg(relevant_mask, top_k)
    hit_rate = 1.0 if retrieved_relevant > 0 else 0.0

    return RetrievalMetrics(
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1_score=round(f1, 4),
        mrr=round(mrr, 4),
        ndcg=round(ndcg, 4),
        hit_rate=round(hit_rate, 4),
    )


def _calc_ndcg(relevant_mask: List[bool], k: int) -> float:
    """计算 NDCG@k"""
    relevance_scores = [1.0 if r else 0.0 for r in relevant_mask[:k]]
    ideal_relevance = sorted(relevance_scores, reverse=True)
    ideal_dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(ideal_relevance))
    if ideal_dcg == 0:
        return 0.0
    actual_dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(relevance_scores))
    return round(actual_dcg / ideal_dcg, 4)


def calc_context_precision_embedding(
    query: str,
    contexts: List[str],
    vectorizer=None,
) -> float:
    """
    用 embedding 余弦相似度计算 ContextPrecision
    = mean(query 与每个 context 的余弦相似度)

    Args:
        query: 查询文本
        contexts: 检索到的上下文列表
        vectorizer: Vectorizer 实例（不传则自动创建）

    Returns:
        0-1 之间的相似度均值
    """
    if not contexts:
        return 0.0

    if vectorizer is None:
        from data_processor.vectorizer import Vectorizer
        vectorizer = Vectorizer()

    try:
        query_emb = np.array(vectorizer.embed_query(query), dtype=np.float32)
        similarities = []
        for ctx in contexts:
            if not ctx.strip():
                similarities.append(0.0)
                continue
            ctx_emb = np.array(vectorizer.embed_query(ctx[:500]), dtype=np.float32)
            sim = np.dot(query_emb, ctx_emb) / (
                np.linalg.norm(query_emb) * np.linalg.norm(ctx_emb) + 1e-8
            )
            similarities.append(float(np.clip(sim, 0.0, 1.0)))
        return round(sum(similarities) / len(similarities), 4)
    except Exception as e:
        logger.warning(f"Embedding 相似度计算失败: {e}")
        return 0.0


calc_context_relevancy_embedding = calc_context_precision_embedding