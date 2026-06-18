"""
Multi-Query 多查询生成与 RRF 融合

从单个用户查询生成多个语义变体，并行检索，用 Reciprocal Rank Fusion 合并结果。
显著提升召回率（Recall），尤其对模糊查询和多义词查询。
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
from core.logger import get_logger

logger = get_logger("multi_query")

MULTI_QUERY_PROMPT = """你是一个教育领域的查询扩展专家。用户正在使用一个知识库问答系统，请为以下问题生成 {num_variants} 个不同的检索查询变体。

【要求】
1. 每个变体从不同角度表达同一问题（同义词、换说法、更具体/更概括）
2. 使用教育领域的专业术语和常见表述
3. 每个变体必须是可独立检索的完整查询
4. 包含一个直接的关键词式查询（用于BM25）
5. 每个变体一行，不要编号

【用户原始问题】
{query}

【{num_variants}个查询变体】"""


class MultiQueryGenerator:
    """多查询生成器 — 从一个查询生成多个检索变体，并行检索，提升召回"""

    def __init__(self, llm_client=None):
        from llm.llm_client import get_fast_llm
        self.llm_client = llm_client or get_fast_llm()  # 轻量任务用 qwen-turbo
        self.default_variants = 3
        self._max_workers = 8  # 并行检索线程数

    def generate(self, query: str, num_variants: int = None) -> List[str]:
        """
        生成多个查询变体

        Args:
            query: 原始用户查询
            num_variants: 生成的变体数量（默认3，不含原查询）

        Returns:
            [原查询, 变体1, 变体2, ...] 总共 num_variants+1 个查询
        """
        n = num_variants or self.default_variants
        if len(query) < 5:
            return [query]

        try:
            prompt = MULTI_QUERY_PROMPT.format(query=query, num_variants=n)
            response = self.llm_client.generate(prompt, max_tokens=300, temperature=0.3)
            variants = [q.strip() for q in response.strip().split('\n') if q.strip() and len(q.strip()) > 3]
            import re
            variants = [re.sub(r'^[\d]+[.、)\s]+', '', v).strip() for v in variants]
        except Exception as e:
            logger.warning(f"多查询生成失败: {e}")
            return [query]

        if not variants:
            variants = [query]
        else:
            variants = [query] + variants[:n]

        logger.debug(f"多查询扩展: '{query[:30]}' → {len(variants)} 个变体")
        return variants

    @staticmethod
    def rrf_fusion(results_lists: List[list], top_k: int = 5, k: int = 60) -> list:
        """
        Reciprocal Rank Fusion 合并多个检索结果列表

        算法: score = sum(1 / (k + rank_i)) for each list i
        """
        rrf_scores = {}
        chunk_map = {}

        for results in results_lists:
            for rank, r in enumerate(results):
                chunk_id = r.chunk.chunk_id if hasattr(r, 'chunk') else id(r)
                rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + 1.0 / (k + rank + 1)
                if chunk_id not in chunk_map:
                    chunk_map[chunk_id] = r

        sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)[:top_k]

        merged = []
        for chunk_id in sorted_ids:
            r = chunk_map[chunk_id]
            r.score = rrf_scores[chunk_id]
            merged.append(r)

        logger.debug(f"RRF融合: {len(results_lists)} 列表 × {[len(r) for r in results_lists]} → {len(merged)}")
        return merged

    def search_with_expansion(self, retriever, query: str,
                               history: list = None,
                               rewritten_query: str = None,
                               top_k: int = 5,
                               metadata_filter: dict = None,
                               doc_id_filter: list = None) -> list:
        """
        完整流程：生成变体 → 并行检索 → RRF融合

        与旧版的关键区别：多个变体的检索并行执行，而非串行。
        """
        search_query = rewritten_query or query
        variants = self.generate(search_query)
        logger.info(f"多查询扩展检索: {len(variants)} 个变体（并行）")

        # 并行检索所有变体
        all_results = []
        with ThreadPoolExecutor(max_workers=min(self._max_workers, len(variants))) as executor:
            futures = {}
            for v in variants:
                future = executor.submit(
                    retriever.search, v,
                    top_k=top_k,
                    metadata_filter=metadata_filter,
                    doc_id_filter=doc_id_filter,
                )
                futures[future] = v

            for future in as_completed(futures):
                v = futures[future]
                try:
                    results = future.result()
                    all_results.append(results)
                except Exception as e:
                    logger.warning(f"并行检索失败 [{v[:30]}]: {e}")

        # RRF 融合
        return self.rrf_fusion(all_results, top_k=top_k)
