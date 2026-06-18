"""
Layer 1: 规则路由
基于关键词+正则匹配，零延迟、零成本
预期命中率 ~60%
"""
import re
from typing import Optional


class RuleRouter:
    """规则路由：关键词+正则匹配，按优先级依次匹配"""

    # 格式: (正则模式, 最大长度限制(0=不限制), 策略名)
    RULES = [
        # 短事实查询 → direct
        (r"(是谁|什么是|什么叫|定义|公式|多少|哪个|哪里|哪年|谁)", 15, "direct"),
        # 对比分析 → hyde
        (r"(区别|对比|比较|哪个更好|vs|有什么不同)", 0, "hyde"),
        # 多步推理 → sub_query
        (r"(先.*再|然后|步骤|怎么做|怎么解|如何|规划|设计)", 0, "sub_query"),
        # 深度研究 → backtrack
        (r"(为什么|原因|原理|证明|推导|怎么来的)", 0, "backtrack"),
    ]

    def route(self, query: str) -> Optional[str]:
        """
        按优先级依次匹配规则，返回第一个命中的策略名。
        未命中返回 None，交给 Layer 2。

        Args:
            query: 用户查询文本

        Returns:
            策略名（direct/hyde/sub_query/backtrack）或 None
        """
        q = query.strip()
        for pattern, max_len, strategy in self.RULES:
            if max_len > 0 and len(q) > max_len:
                continue
            if re.search(pattern, q):
                return strategy
        return None