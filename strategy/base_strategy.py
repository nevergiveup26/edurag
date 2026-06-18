"""
检索策略抽象基类
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Any

from core.logger import get_logger

logger = get_logger("strategy")


@dataclass
class StrategyResult:
    """策略执行结果"""
    context: str = ""       # 检索到的上下文，注入 system prompt
    metadata: dict = field(default_factory=dict)  # 策略执行元数据


class BaseStrategy(ABC):
    """检索策略抽象基类"""

    @abstractmethod
    async def execute(self, query: str, retriever, llm, **kwargs) -> StrategyResult:
        """执行策略，返回上下文和元数据"""
        ...

    def _format_context(self, results: List[Any]) -> str:
        """将检索结果列表格式化为上下文字符串"""
        if not results:
            return ""
        parts = []
        for i, r in enumerate(results):
            content = getattr(r, 'content', None) or getattr(r, 'page_content', '')
            if not content and hasattr(r, 'chunk'):
                content = r.chunk.content
            if not content:
                continue
            score = getattr(r, 'score', 0.0)
            source = getattr(r, 'source', '') or getattr(r, 'metadata', {}).get('source', '')
            parts.append(f"[来源 {i+1}] (相关度: {score:.2f})\n{content}")
        return "\n\n".join(parts)