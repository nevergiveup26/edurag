"""
向量化处理
使用 DashScope text-embedding-v4 云端嵌入模型 (1024维)

API 配置复用 [llm] 中的 api_base / api_key，无需 GPU
"""
from typing import List
import time
import numpy as np

from core.models import DocumentChunk
from core.config_manager import ConfigManager
from core.logger import get_logger

logger = get_logger("vectorizer")

# 云端嵌入默认配置
_CLOUD_DEFAULTS = {
    "model": "text-embedding-v4",
    "dimensions": 1024,
    "batch_size": 10,
}


class Vectorizer:
    """文本向量化处理器 — 云端嵌入模式 (DashScope)"""

    def __init__(self, model_name: str = None):
        config = ConfigManager()
        self._init_cloud(config)

    # ======================== 云端初始化 ========================

    def _init_cloud(self, config: ConfigManager):
        """初始化云端嵌入模式（DashScope / OpenAI 兼容 API）"""
        self._provider = "dashscope"
        self._model_name = config.get("embedding", "cloud_model", _CLOUD_DEFAULTS["model"])
        self.embedding_dim = int(config.get("embedding", "dimensions", _CLOUD_DEFAULTS["dimensions"]))
        self._batch_size = int(config.get("embedding", "batch_size", _CLOUD_DEFAULTS["batch_size"]))

        # API 配置：embedding section 优先，fallback 到 llm section
        self._api_base = (
            config.get("embedding", "api_base", "")
            or config.get("llm", "api_base", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        )
        self._api_key = (
            config.get("embedding", "api_key", "")
            or config.get("llm", "api_key", "")
        )
        if not self._api_key:
            raise ValueError("云端嵌入模式需要 API Key，请在 config.ini [llm] 或 [embedding] 中配置 api_key")

        self._client = None
        self._client_ready = False
        logger.info(f"[云端嵌入] 模型: {self._model_name} ({self.embedding_dim}维) | API: {self._api_base}")

    def _init_cloud_client(self):
        """延迟初始化 OpenAI 兼容客户端"""
        if self._client_ready:
            return
        from openai import OpenAI
        self._client = OpenAI(
            api_key=self._api_key,
            base_url=self._api_base,
            timeout=60,
            max_retries=2,
        )
        self._client_ready = True
        logger.info(f"[云端嵌入] 客户端已初始化: {self._model_name}")

    # ======================== 公共接口 ========================

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed(self, texts: List[str]) -> List[List[float]]:
        """将文本列表转换为向量"""
        return self._embed_cloud(texts)

    def embed_query(self, query: str) -> List[float]:
        """将单个查询文本转换为向量"""
        return self.embed([query])[0]

    def embed_documents(self, chunks: List[DocumentChunk]) -> List[DocumentChunk]:
        """批量向量化文档片段"""
        texts = [chunk.content for chunk in chunks]
        embeddings = self.embed(texts)

        for chunk, embedding in zip(chunks, embeddings):
            chunk.embedding = embedding

        logger.info(f"已向量化 {len(chunks)} 个文档片段 (provider={self._provider})")
        return chunks

    # ======================== 云端嵌入实现 ========================

    def _embed_cloud(self, texts: List[str]) -> List[List[float]]:
        """通过云端 API 获取嵌入向量，自动分批"""
        self._init_cloud_client()

        all_embeddings = []
        total = len(texts)

        for batch_start in range(0, total, self._batch_size):
            batch = texts[batch_start:batch_start + self._batch_size]
            batch_end = min(batch_start + self._batch_size, total)

            last_error = None
            for attempt in range(3):
                try:
                    resp = self._client.embeddings.create(
                        model=self._model_name,
                        input=batch,
                        dimensions=self.embedding_dim,
                    )
                    batch_embeddings = [d.embedding for d in resp.data]
                    all_embeddings.extend(batch_embeddings)
                    break
                except Exception as e:
                    last_error = e
                    logger.warning(f"云端嵌入失败 (批次 {batch_start}-{batch_end}, 尝试 {attempt+1}): {e}")
                    if attempt < 2:
                        time.sleep(1.5 * (attempt + 1))
            else:
                raise RuntimeError(
                    f"云端嵌入失败，重试3次后仍失败 (批次 {batch_start}-{batch_end}): {last_error}"
                )

            if batch_end < total:
                logger.debug(f"云端嵌入进度: {batch_end}/{total}")

        return all_embeddings

    # ======================== 工具方法 ========================

    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算两个向量的余弦相似度"""
        v1 = np.array(vec1)
        v2 = np.array(vec2)

        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(np.dot(v1, v2) / (norm1 * norm2))

    @classmethod
    def list_models(cls) -> List[dict]:
        """列出可用的嵌入模型"""
        return [{
            "name": "text-embedding-v4 (DashScope)",
            "dim": 1024,
            "description": "阿里云云端嵌入，中文最佳，无需GPU",
        }]