"""
流式思考链事件类型定义

统一的事件类型体系，支持：
- 思考链分级展示（Thought → Action → Observation → Reflection）
- SSE事件流格式
- 前端渲染标识
"""

from enum import Enum
from typing import Any, Dict, Optional


class StreamEventType(str, Enum):
    """流式事件类型"""
    # 思考链事件
    THINKING = "thinking"           # 思考过程（Thought）
    REASONING = "reasoning"          # 推理过程
    PLAN = "plan"                    # 规划/决策
    ACTION = "action"                # 执行动作
    OBSERVATION = "observation"      # 观察结果
    REFLECTION = "reflection"        # 反思评估

    # 进度事件
    STATUS = "status"               # 状态更新
    PROGRESS = "progress"           # 进度百分比

    # 内容事件
    TOKEN = "token"                 # 流式文本token
    SOURCE = "source"               # 检索来源
    IMAGE = "image"                 # 图片内容
    TABLE = "table"                 # 表格内容

    # 生命周期事件
    START = "start"                 # 开始
    DONE = "done"                   # 完成
    ERROR = "error"                 # 错误
    FAQ_HIT = "faq_hit"            # FAQ命中

    # Agent特有
    TOOL_CALL = "tool_call"        # 工具调用
    TOOL_RESULT = "tool_result"     # 工具返回


def make_event(event_type: StreamEventType, **kwargs) -> Dict[str, Any]:
    """
    创建流式事件

    Args:
        event_type: 事件类型
        **kwargs: 事件数据

    Returns:
        标准化的流式事件dict
    """
    return {"type": event_type.value, **kwargs}


def make_thinking(thought: str) -> dict:
    """思考事件"""
    return make_event(StreamEventType.THINKING, content=thought, level="thought")


def make_reasoning(reasoning: str) -> dict:
    """推理事件"""
    return make_event(StreamEventType.REASONING, content=reasoning, level="reasoning")


def make_plan(plan_text: str, steps: list = None) -> dict:
    """规划事件"""
    return make_event(StreamEventType.PLAN, content=plan_text, steps=steps or [])


def make_action(tool_name: str, args: dict = None) -> dict:
    """动作事件"""
    return make_event(StreamEventType.ACTION, tool=tool_name, args=args or {})


def make_observation(result: str) -> dict:
    """观察事件"""
    return make_event(StreamEventType.OBSERVATION, content=result)


def make_reflection(score: float, summary: str) -> dict:
    """反思事件"""
    return make_event(StreamEventType.REFLECTION, score=score, content=summary)


def make_token(text: str) -> dict:
    """Token事件"""
    return make_event(StreamEventType.TOKEN, content=text)


def make_source(sources: list) -> dict:
    """来源事件"""
    return make_event(StreamEventType.SOURCE, sources=sources)


def make_status(message: str) -> dict:
    """状态事件"""
    return make_event(StreamEventType.STATUS, content=message)


def make_progress(percent: float, message: str = "") -> dict:
    """进度事件"""
    return make_event(StreamEventType.PROGRESS, percent=percent, content=message)


def make_start(query: str) -> dict:
    """开始事件"""
    return make_event(StreamEventType.START, query=query)


def make_done(message: str = "完成") -> dict:
    """完成事件"""
    return make_event(StreamEventType.DONE, content=message)


def make_error(message: str) -> dict:
    """错误事件"""
    return make_event(StreamEventType.ERROR, content=message)


def format_sse(event: dict) -> str:
    """格式化SSE事件为SSE协议文本"""
    import json
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def chunk_text_to_tokens(text: str, chunk_size: int = 4) -> list:
    """
    将文本拆分为token块（模拟流式逐字输出）

    Args:
        text: 要拆分的文本
        chunk_size: 每块字符数

    Returns:
        token块列表
    """
    tokens = []
    i = 0
    while i < len(text):
        # 找到自然断点
        end = min(i + chunk_size, len(text))
        chunk = text[i:end]

        # 尝试在标点/空格处断句
        if end < len(text) and not any(p in chunk[-1] for p in "，。！？；：\n 　、\""):
            # 向前找断点
            for j in range(min(i + 8, len(text)) - 1, i + 1, -1):
                if j < len(text) and text[j] in "，。！？；：\n 　、\"":
                    end = j + 1
                    break

        tokens.append(text[i:end])
        i = end
    return tokens