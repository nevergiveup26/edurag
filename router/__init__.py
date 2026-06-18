"""
智能查询路由模块
提供三层递进路由：规则(rule) → 相似度(similarity) → LLM(llm)
"""
from router.query_router import QueryRouter, get_query_router

__all__ = ["QueryRouter", "get_query_router"]