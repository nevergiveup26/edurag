"""
LLM客户端
支持多种大语言模型的统一接口（OpenAI 兼容 API）：
- Ollama (DeepSeek / Qwen / Llama 等)
- DeepSeek API
- 通义千问 API (DashScope)
- OpenAI 兼容格式的第三方 API

特性：
- 自动检测模型类型并设置合适的 API 地址
- 统一 OpenAI 兼容 API 接口
- 流式与非流式生成
- 重试与超时机制
- 环境变量 / 配置文件 / 代码参数 三级配置
"""
import re
import hashlib
from typing import Optional, List, Dict, Generator
import os
import time

from core.config_manager import ConfigManager
from core.logger import get_logger

logger = get_logger("llm_client")

# 预置模型配置（OpenAI 兼容 API）
PRESET_MODELS = {
    "ollama": {
        "api_base": "http://localhost:11434/v1",
        "description": "Ollama (支持 DeepSeek/Qwen/Llama 等)",
    },
    "deepseek": {
        "api_base": "https://api.deepseek.com/v1",
        "description": "DeepSeek API",
    },
    "qwen": {
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "description": "通义千问 API (DashScope)",
    },
    "openai": {
        "api_base": "https://api.openai.com/v1",
        "description": "OpenAI API",
    },
    "zhipu": {
        "api_base": "https://open.bigmodel.cn/api/paas/v4",
        "description": "智谱 GLM API",
    },
    "moonshot": {
        "api_base": "https://api.moonshot.cn/v1",
        "description": "Moonshot (Kimi) API",
    },
    "siliconflow": {
        "api_base": "https://api.siliconflow.cn/v1",
        "description": "硅基流动 (DeepSeek/Qwen等)",
    },
}


class LLMClient:
    """大语言模型客户端（OpenAI 兼容 API 统一接口）

    配置优先级: 参数 > 环境变量 > 配置文件
    - LLM_API_KEY     → api_key
    - LLM_API_BASE    → api_base
    - LLM_MODEL_NAME  → model_name

    无降级：任何初始化失败或调用失败直接抛出异常。
    """

    def __init__(self, model_name: str = None, api_base: str = None,
                 api_key: str = None, max_retries: int = 2):
        config = ConfigManager()
        self.config = config.llm_config

        # 三级配置优先级: 参数 > 环境变量 > 配置文件
        self.model_name = (
            model_name
            or os.getenv("LLM_MODEL_NAME")
            or self.config.get("model_name", "gpt-3.5-turbo")
        )
        self.api_base = (
            api_base
            or os.getenv("LLM_API_BASE")
            or self.config.get("api_base", "http://localhost:11434/v1")
        )
        self.api_key = (
            api_key
            or os.getenv("LLM_API_KEY")
            or self.config.get("api_key", "ollama")
        )
        self.temperature = float(self.config.get("temperature", 0.5))
        self.max_tokens = int(self.config.get("max_tokens", 2000))
        self.top_p = float(self.config.get("top_p", 0.9))
        self.timeout = int(self.config.get("timeout", 60))
        self.max_retries = max_retries
        self._client = None

        # 自动检测模型类型
        self._detect_model_type()

    def _detect_model_type(self):
        """自动检测模型类型并设置合适的 API 地址"""
        model_lower = self.model_name.lower()
        env_api_base = os.getenv("LLM_API_BASE")
        if env_api_base:
            self.api_base = env_api_base
            logger.info(f"使用环境变量 API_BASE: {env_api_base}")
            return

        for preset_name, preset_info in PRESET_MODELS.items():
            if preset_name in model_lower:
                if self.api_base == self.config.get("api_base", "http://localhost:11434/v1"):
                    self.api_base = preset_info["api_base"]
                logger.info(f"检测到模型类型: {preset_name} ({preset_info['description']})")
                break

    @classmethod
    def from_preset(cls, preset: str, model_name: str = None) -> "LLMClient":
        """使用预置配置创建客户端"""
        if preset not in PRESET_MODELS:
            raise ValueError(
                f"不支持的预置模型: {preset}。可选: {list(PRESET_MODELS.keys())}"
            )

        preset_info = PRESET_MODELS[preset]
        default_models = {
            "ollama": "qwen2.5:7b",
            "deepseek": "deepseek-chat",
            "qwen": "qwen-turbo",
            "openai": "gpt-3.5-turbo",
            "zhipu": "glm-4",
            "moonshot": "moonshot-v1-8k",
            "siliconflow": "deepseek-ai/DeepSeek-V3",
        }
        return cls(
            model_name=model_name or default_models.get(preset, "gpt-3.5-turbo"),
            api_base=preset_info["api_base"],
            api_key="ollama" if preset == "ollama" else os.getenv("LLM_API_KEY", ""),
        )

    def _get_client(self):
        """获取 OpenAI 兼容客户端（失败抛异常，不降级）"""
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=self.api_key or "not-needed",
                base_url=self.api_base,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
            logger.info(f"已初始化LLM客户端: {self.model_name} @ {self.api_base}")
        return self._client

    # ---- 文本生成 ----

    def generate(self, prompt: str, max_tokens: int = None,
                 temperature: float = None) -> str:
        """生成文本回复（非流式），自动缓存命中"""
        # 查缓存
        cache_key = f"llm:resp:{hashlib.md5(prompt.encode()).hexdigest()}"
        try:
            from database.redis_cache import get_redis_cache
            cache = get_redis_cache()
            if cache:
                cached = cache.get(cache_key)
                if cached:
                    logger.debug(f"LLM缓存命中: {cache_key[:16]}...")
                    return cached
        except Exception as e:
            logger.debug(f"Redis 缓存读取失败: {e}")

        client = self._get_client()

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature or self.temperature,
                    max_tokens=max_tokens or self.max_tokens,
                    top_p=self.top_p,
                    stream=False,
                )
                content = response.choices[0].message.content
                result = content.strip() if content else ""
                # 写入缓存
                try:
                    if cache:
                        cache.set(cache_key, result, ttl=3600)
                except Exception as e:
                    logger.debug(f"Redis 缓存写入失败: {e}")
                return result
            except Exception as e:
                last_error = e
                logger.warning(f"LLM生成失败 (尝试 {attempt+1}/{self.max_retries+1}): {e}")
                if attempt < self.max_retries:
                    time.sleep(1 * (attempt + 1))
        raise RuntimeError(f"LLM生成失败，已重试{self.max_retries+1}次: {last_error}")

    def generate_stream(self, prompt: str, max_tokens: int = None,
                        temperature: float = None) -> Generator[str, None, None]:
        """流式生成文本回复（逐 token 产出）"""
        client = self._get_client()

        stream = client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature or self.temperature,
            max_tokens=max_tokens or self.max_tokens,
            top_p=self.top_p,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    # ---- 多轮对话 ----

    def chat(self, messages: List[Dict[str, str]], max_tokens: int = None) -> str:
        """多轮对话（非流式）"""
        client = self._get_client()

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=max_tokens or self.max_tokens,
                    top_p=self.top_p,
                    stream=False,
                )
                content = response.choices[0].message.content
                return content.strip() if content else ""
            except Exception as e:
                last_error = e
                logger.warning(f"LLM对话失败 (尝试 {attempt+1}): {e}")
                if attempt < self.max_retries:
                    time.sleep(1 * (attempt + 1))
        raise RuntimeError(f"LLM多轮对话失败，已重试{self.max_retries+1}次: {last_error}")

    def chat_stream(self, messages: List[Dict[str, str]],
                    max_tokens: int = None) -> Generator[str, None, None]:
        """多轮对话流式输出"""
        client = self._get_client()

        stream = client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=self.temperature,
            max_tokens=max_tokens or self.max_tokens,
            top_p=self.top_p,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    # ---- Function Calling / Tool Calling ----

    def generate_with_tools(self, messages: List[Dict[str, str]],
                            tools: List[dict]) -> str:
        """带工具调用的生成（用于Agent），失败抛异常"""
        client = self._get_client()

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                msg = response.choices[0].message

                if msg.tool_calls:
                    return {
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                }
                            }
                            for tc in msg.tool_calls
                        ]
                    }

                return msg.content or ""
            except Exception as e:
                last_error = e
                logger.warning(f"Tool calling失败 (尝试 {attempt+1}): {e}")
                if attempt < self.max_retries:
                    time.sleep(1 * (attempt + 1))
        raise RuntimeError(f"Tool calling失败，已重试{self.max_retries+1}次: {last_error}")

    # ---- Vision / 多模态 ----

    def _normalize_image_base64(self, image_base64: str) -> tuple:
        """规范化图片 base64：剥离 Data URI 前缀，检测真实 MIME 类型

        Returns:
            (raw_base64, mime_type) 元组
        """
        mime_type = "image/png"  # 默认
        raw = image_base64

        # 处理 Data URI 格式: data:image/png;base64,xxxx
        data_uri_match = re.match(r'^data:(image/\w+);base64,(.+)$', raw.strip())
        if data_uri_match:
            mime_type = data_uri_match.group(1)
            raw = data_uri_match.group(2).strip()
            logger.debug(f"OCR: 从 Data URI 检测到 MIME 类型: {mime_type}")
        elif ',' in raw[:100]:
            # 可能包含非标准前缀
            for prefix in ['data:image/', 'base64,']:
                if prefix in raw[:200]:
                    raw = raw.split('base64,')[-1].strip()
                    break

        # 移除所有空白字符（base64 不应含空格/换行）
        raw = re.sub(r'\s+', '', raw)

        return raw, mime_type

    def generate_with_image(self, prompt: str, image_path: str = None,
                            image_base64: str = None) -> str:
        """视觉语言理解（多模态生成），失败抛异常"""
        client = self._get_client()

        import base64
        content = [{"type": "text", "text": prompt}]

        if image_path:
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img_b64}"}
            })
        elif image_base64:
            # 安全处理：剥离可能的前缀（前端 readAsDataURL 会带 data:image/...;base64, 前缀）
            raw_b64, mime_type = self._normalize_image_base64(image_base64)
            if not raw_b64 or len(raw_b64) < 50:
                logger.warning(f"图片 base64 数据过短 ({len(raw_b64) if raw_b64 else 0})，可能无效")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{raw_b64}"}
            })
        else:
            logger.warning("generate_with_image 未提供图片")

        response = client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": content}],
            max_tokens=self.max_tokens,
        )
        return response.choices[0].message.content or ""

    # ---- 工具方法 ----

    def get_model_info(self) -> Dict:
        """获取模型信息"""
        return {
            "model_name": self.model_name,
            "api_base": self.api_base,
            "provider": self._detect_provider(),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "timeout": self.timeout,
        }

    def _detect_provider(self) -> str:
        """检测模型提供商"""
        for preset_name, preset_info in PRESET_MODELS.items():
            if (preset_info["api_base"] in self.api_base
                    or preset_name in self.model_name.lower()):
                return preset_name
        return "custom"

    @classmethod
    def list_presets(cls) -> List[Dict]:
        """列出所有预置模型"""
        return [
            {"name": k, "api_base": v["api_base"], "description": v["description"]}
            for k, v in PRESET_MODELS.items()
        ]

    def health_check(self) -> bool:
        """健康检查：测试 API 是否可用"""
        try:
            client = self._get_client()
            client.models.list()
            return True
        except Exception:
            return False


# 全局"快思考"客户端（qwen-turbo），用于路由/评估/压缩等轻量任务
_fast_llm: Optional[LLMClient] = None


def get_fast_llm() -> LLMClient:
    """获取快思考客户端（qwen-turbo），用于非生成任务"""
    global _fast_llm
    if _fast_llm is None:
        _fast_llm = LLMClient(model_name="qwen-turbo")
    return _fast_llm