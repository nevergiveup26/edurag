"""
RAG 工具函数：
- deduplicate_results: 去重检索结果
- maximal_marginal_relevance: MMR 多样性优化
- prune_by_score: 低分数剪枝
- trim_context_to_token_limit: 上下文压缩到token限制
"""
from typing import List
from core.models import RetrievalResult
import numpy as np


def deduplicate_results(results: List[RetrievalResult]) -> List[RetrievalResult]:
    """对检索结果去重，保留排序中的第一个出现"""
    seen = set()
    unique_results = []
    for r in results:
        # 用 chunk id + content 前 100 字符做指纹
        key = f"{getattr(r.chunk, 'chunk_id', '')}-{r.chunk.content[:100]}"
        if key not in seen:
            seen.add(key)
            unique_results.append(r)
    return unique_results


def maximal_marginal_relevance(
    results: List[RetrievalResult],
    top_k: int = 5,
    lambda_param: float = 0.5,
) -> List[RetrievalResult]:
    """
    最大边缘相关性 (Maximal Marginal Relevance)
    - 优化检索结果多样性，减少重复信息
    - lambda: 0 = 纯多样性，1 = 纯相关性排序
    """
    if len(results) <= top_k:
        return results

    # 提取相似度分数
    scores = np.array([getattr(r, 'score', 0.0) for r in results])
    scores = (scores - scores.min()) / (scores.max() - scores.min() + 1e-8)

    # 选择
    selected = []
    remaining = list(range(len(results)))

    # 第一步：选最高分
    first = int(np.argmax(scores))
    selected.append(remaining.pop(first))

    # 贪心迭代选
    while len(selected) < top_k and remaining:
        mmr_scores = []
        for i in remaining:
            # 计算与已选的最大相似度（用余弦近似，这里简单用分数差代替）
            max_sim = max(
                abs(scores[i] - scores[s]) for s in selected
            )
            mmr = lambda_param * scores[i] - (1 - lambda_param) * max_sim
            mmr_scores.append(mmr)

        best_idx_in_remaining = int(np.argmax(mmr_scores))
        best_global = remaining.pop(best_idx_in_remaining)
        selected.append(best_global)

    return [results[i] for i in selected]


def prune_by_score(
    results: List[RetrievalResult],
    min_score: float = 0.1,
) -> List[RetrievalResult]:
    """只保留分数 >= min_score 的结果"""
    return [r for r in results if getattr(r, 'score', 0.0) >= min_score]


def trim_context_to_token_limit(
    context: str,
    max_tokens: int = 3000,
) -> str:
    """
    简单地按字符估算token（中文 ≈ 0.5 token/字，英文 ≈ 1 token/4 字）
    超过限制时截断尾部保留开头
    """
    # 估算：每个汉字 ≈ 0.5 token，所以约 2 chars = 1 token
    max_chars = max_tokens * 2
    if len(context) <= max_chars:
        return context
    return context[:max_chars]
