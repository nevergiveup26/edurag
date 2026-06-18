"""
LangChain Chat Model 包装器

将 LLMClient 的配置映射到 langchain-openai.ChatOpenAI，
复用相同的 DashScope/OpenAI 兼容 API 端点和认证。
"""

import os
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel

from core.config_manager import ConfigManager
from core.logger import get_logger

logger = get_logger("langgraph_model")


def create_chat_model(
    model_name: str = None,
    api_base: str = None,
    api_key: str = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    streaming: bool = True,
) -> BaseChatModel:
    """
    创建 LangChain ChatOpenAI 实例，使用现有的 DashScope/OpenAI 兼容 API 配置。

    配置优先级: 参数 > 环境变量 > config.ini

    Args:
        model_name: 模型名称（如 qwen-max, gpt-4o），覆盖环境变量和配置文件
        api_base: API 地址
        api_key: API Key
        temperature: 温度参数
        max_tokens: 最大输出 token 数
        streaming: 是否启用流式输出

    Returns:
        ChatOpenAI 实例
    """
    config = ConfigManager()
    llm_config = config.llm_config

    # 三级配置优先级（model_name 参数需要显式传入才生效）
    _model_name = (
        model_name
        or os.getenv("LLM_MODEL_NAME")
        or llm_config.get("model_name", "qwen-max")
    )
    _api_base = (
        api_base
        or os.getenv("LLM_API_BASE")
        or llm_config.get("api_base", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    )
    _api_key = (
        api_key
        or os.getenv("LLM_API_KEY")
        or os.getenv("DASHSCOPE_API_KEY")
        or llm_config.get("api_key", "sk-placeholder")
    )

    # DashScope 专有参数：仅 DashScope 端点需要 include_usage
    _is_dashscope = "dashscope" in _api_base.lower()
    _extra = {}
    if _is_dashscope and streaming:
        _extra["stream_options"] = {"include_usage": True}

    logger.info(f"创建 ChatOpenAI: model={_model_name}, base_url={_api_base}")

    return ChatOpenAI(
        model=_model_name,
        base_url=_api_base,
        api_key=_api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=streaming,
        timeout=60,
        max_retries=2,
        **_extra,
    )
