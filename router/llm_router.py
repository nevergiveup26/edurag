"""
Layer 3: LLM 路由
使用 qwen-turbo 做意图分类，兜底保障
延迟 ~300-500ms，含 LRU 缓存
"""
import json
import re
from typing import Optional
from collections import OrderedDict

from core.logger import get_logger

logger = get_logger("llm_router")

CLASSIFICATION_PROMPT = """你是一个查询分类器。请将以下用户查询分类到 4 种检索策略之一：

- direct：简单事实查询，直接检索即可回答（如"什么是XX"、"XX的定义"、"XX的公式"）
- hyde：对比分析类问题，需要生成假设文档辅助检索（如"XX和YY的区别"、"XX和YY哪个更好"）
- sub_query：多步推理或复合问题，需要分解为子问题（如"先查XX再分析YY"、"如何做XX"）
- backtrack：深层原理类问题，需要多轮检索和验证（如"为什么XX"、"XX的原理"、"证明XX"）

用户查询：{query}

请仅返回 JSON，不要包含任何其他文字：
{{"strategy": "策略名", "confidence": 0.0~1.0}}"""


class LLMRouter:
    """LLM 路由：qwen-turbo 意图分类，含 LRU 缓存"""

    MAX_CACHE_SIZE = 500

    def __init__(self):
        self._llm = None  # 延迟初始化
        self._cache: OrderedDict[str, str] = OrderedDict()

    def _get_llm(self):
        """延迟获取 fast_llm（避免 import 时初始化）"""
        if self._llm is None:
            from llm.llm_client import get_fast_llm
            self._llm = get_fast_llm()
        return self._llm

    def _cache_get(self, query: str) -> Optional[str]:
        return self._cache.get(query)

    def _cache_set(self, query: str, strategy: str):
        if len(self._cache) >= self.MAX_CACHE_SIZE:
            self._cache.popitem(last=False)  # LRU: 删除最旧的
        self._cache[query] = strategy

    def route(self, query: str) -> str:
        """
        LLM 意图分类，必定返回策略名。
        失败或置信度低时降级为 direct。

        Args:
            query: 用户查询文本

        Returns:
            策略名（direct/hyde/sub_query/backtrack）
        """
        # 1. 查 LRU 缓存
        cached = self._cache_get(query)
        if cached:
            logger.debug(f"[LLMRouter] 缓存命中: {cached}")
            return cached

        try:
            llm = self._get_llm()
            prompt = CLASSIFICATION_PROMPT.format(query=query)
            response = llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
            )

            # 解析 JSON
            result = self._parse_response(response)
            strategy = result.get("strategy", "direct")
            confidence = result.get("confidence", 0.0)

            # 验证策略名有效性
            valid_strategies = {"direct", "hyde", "sub_query", "backtrack"}
            if strategy not in valid_strategies:
                logger.warning(f"[LLMRouter] 无效策略 '{strategy}'，降级为 direct")
                strategy = "direct"

            # 置信度检查
            if confidence < 0.5:
                logger.info(f"[LLMRouter] 置信度过低 {confidence:.2f}，降级为 direct")
                strategy = "direct"

            self._cache_set(query, strategy)
            logger.info(f"[LLMRouter] 分类结果: {strategy} (confidence={confidence:.2f})")
            return strategy

        except Exception as e:
            logger.warning(f"[LLMRouter] 分类失败，降级为 direct: {e}")
            self._cache_set(query, "direct")
            return "direct"

    def _parse_response(self, response: str) -> dict:
        """从 LLM 响应中提取 JSON"""
        # 尝试直接解析
        try:
            return json.loads(response.strip())
        except json.JSONDecodeError:
            pass

        # 尝试从代码块中提取
        match = re.search(r'\{[^{}]*"strategy"[^{}]*\}', response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        logger.warning(f"[LLMRouter] 无法解析响应: {response[:200]}")
        return {}