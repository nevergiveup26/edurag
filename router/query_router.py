"""
智能查询路由 — 统一入口
三层递进：RuleRouter → SimilarityRouter → LLMRouter
含 LRU 全链路缓存和降级逻辑
"""
from typing import Optional
from collections import OrderedDict

from core.logger import get_logger
from router.rule_router import RuleRouter
from router.similarity_router import SimilarityRouter
from router.llm_router import LLMRouter

logger = get_logger("query_router")

# 全局单例
_query_router: Optional["QueryRouter"] = None


class QueryRouter:
    """三层递进查询路由，含全链路 LRU 缓存"""

    MAX_CACHE_SIZE = 500

    def __init__(self):
        self.rule_router = RuleRouter()
        self.similarity_router = SimilarityRouter(similarity_threshold=0.75)
        self.llm_router = LLMRouter()
        self._cache: OrderedDict[str, str] = OrderedDict()

    def _cache_get(self, query: str) -> Optional[str]:
        return self._cache.get(query)

    def _cache_set(self, query: str, strategy: str):
        if len(self._cache) >= self.MAX_CACHE_SIZE:
            self._cache.popitem(last=False)
        self._cache[query] = strategy

    def route(self, query: str) -> str:
        """
        三层递进路由，返回策略名。

        流程:
        1. 查全链路缓存
        2. Layer 1: 规则匹配（0ms）
        3. Layer 2: 相似度匹配（~50ms）
        4. Layer 3: LLM 分类（~300-500ms，兜底）

        Args:
            query: 用户查询文本

        Returns:
            策略名（direct/hyde/sub_query/backtrack）
        """
        # 1. 全链路缓存
        cached = self._cache_get(query)
        if cached:
            logger.debug(f"[QueryRouter] 缓存命中: {cached}")
            return cached

        # 2. Layer 1: 规则
        result = self.rule_router.route(query)
        if result:
            logger.info(f"[QueryRouter] Layer 1 命中: {result}  query='{query[:50]}'")
            self._cache_set(query, result)
            return result

        # 3. Layer 2: 相似度
        result = self.similarity_router.route(query)
        if result:
            logger.info(f"[QueryRouter] Layer 2 命中: {result}  query='{query[:50]}'")
            self._cache_set(query, result)
            return result

        # 4. Layer 3: LLM 兜底
        result = self.llm_router.route(query)
        logger.info(f"[QueryRouter] Layer 3 兜底: {result}  query='{query[:50]}'")
        self._cache_set(query, result)
        return result


def get_query_router() -> QueryRouter:
    """获取 QueryRouter 全局单例"""
    global _query_router
    if _query_router is None:
        _query_router = QueryRouter()
    return _query_router