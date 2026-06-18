"""
云端重排序模块 (DashScope qwen3-rerank)

使用阿里云 DashScope qwen3-rerank 模型对检索结果进行语义重排序，
无需本地模型、无需 GPU，按 API 调用计费。

API endpoint: POST https://dashscope.aliyuncs.com/compatible-api/v1/reranks
"""
import json
import time
from typing import List, Optional

import requests

from core.models import RetrievalResult
from core.config_manager import ConfigManager
from core.logger import get_logger

logger = get_logger("reranker")


class Reranker:
    """
    DashScope 云端重排序器

    使用阿里云 qwen3-rerank 模型计算 query-document 对的相关性分数，
    按新分数对检索结果重新排序。
    """

    # DashScope qwen3-rerank endpoint (OpenAI-compatible)
    _RERANK_URL = "https://dashscope.aliyuncs.com/compatible-api/v1/reranks"
    _RERANK_MODEL = "qwen3-rerank"
    _DEFAULT_INSTRUCT = "Given a web search query, retrieve relevant passages that answer the query."

    def __init__(self, model_name: str = None):
        config = ConfigManager()
        self.enabled = config.retriever_config.get("rerank_enabled", True)
        self.rerank_top_k = int(config.retriever_config.get("rerank_top_k", 3))
        self.model_name = model_name or self._RERANK_MODEL

        # API 配置：复用 [llm] 中的 api_key
        self._api_key = (
            config.get("embedding", "api_key", "")
            or config.get("llm", "api_key", "")
        )
        self._timeout = 30  # 秒

    def _call_rerank_api(self, query: str, documents: List[str],
                         top_n: int = None) -> List[float]:
        """
        调用 DashScope qwen3-rerank API

        Args:
            query: 查询文本
            documents: 文档文本列表
            top_n: 返回 top_n 个结果

        Returns:
            与 documents 等长的分数列表（未返回的文档分数为 0.0）
        """
        if not documents:
            return []

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        payload = {
            "model": self.model_name,
            "query": query,
            "documents": [doc[:4000] for doc in documents],  # 单条最大 4000 token
            "top_n": top_n or len(documents),
            "instruct": self._DEFAULT_INSTRUCT,
        }

        try:
            start = time.time()
            resp = requests.post(self._RERANK_URL, headers=headers,
                                 json=payload, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
            elapsed = time.time() - start

            # 解析结果: {"results": [{"index": 0, "relevance_score": 0.93}, ...]}
            results = data.get("results", [])

            # 构建与输入 documents 等长的分数数组
            scores = [0.0] * len(documents)
            for item in results:
                idx = item.get("index", -1)
                score = item.get("relevance_score", 0.0)
                if 0 <= idx < len(documents):
                    scores[idx] = float(score)

            logger.info(f"[云端Rerank] {self.model_name} 完成: "
                        f"{len(documents)} 篇文档 → top {len(results)} "
                        f"({elapsed:.2f}s)")
            return scores

        except requests.exceptions.RequestException as e:
            logger.error(f"[云端Rerank] API调用失败: {e}")
            raise
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"[云端Rerank] 响应解析失败: {e}")
            raise

    def rerank(self, query: str, results: List[RetrievalResult],
               top_k: int = None) -> List[RetrievalResult]:
        """
        云端重排序

        1. 提取每个 RetrievalResult 的文本内容
        2. 调用 qwen3-rerank API 获取相关性分数
        3. 按新分数重新排序
        4. 返回 top_k 个结果
        """
        if not self.enabled or not results:
            return results[:top_k] if top_k else results

        top_k = top_k or self.rerank_top_k

        try:
            documents = [r.chunk.content[:500] for r in results]
            scores = self._call_rerank_api(query, documents, top_n=top_k)

            # 更新分数
            for result, score in zip(results, scores):
                result.score = float(score)

            # 按新分数降序排列
            results.sort(key=lambda x: x.score, reverse=True)

            logger.info(f"云端重排序完成: {len(results)} -> {min(top_k, len(results))}")
            return results[:top_k]

        except Exception as e:
            logger.error(f"云端重排序失败: {e}，使用原始分数")
            return self._fallback_rerank(results, top_k)

    def _fallback_rerank(self, results: List[RetrievalResult],
                         top_k: int) -> List[RetrievalResult]:
        """Fallback: 按原始分数排序（不依赖外部 API）"""
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    def cross_encode(self, query: str, documents: List[str]) -> List[float]:
        """
        计算 query 与多个 documents 的相关性分数

        Args:
            query: 查询文本
            documents: 文档列表

        Returns:
            相关性分数列表（越高越相关）
        """
        try:
            return self._call_rerank_api(query, documents)
        except Exception as e:
            logger.error(f"Cross-encode失败: {e}")
            return [0.5] * len(documents)

    def rerank_with_scores(self, query: str,
                           documents: List[str],
                           top_k: int = None) -> List[tuple]:
        """
        重排序纯文本列表，返回 (text, score)

        用于不需要 RetrievalResult 对象的场景
        """
        scores = self.cross_encode(query, documents)
        pairs = list(zip(documents, scores))
        pairs.sort(key=lambda x: x[1], reverse=True)
        return pairs[:top_k] if top_k else pairs

    def get_model_info(self) -> dict:
        """获取当前模型信息"""
        return {
            "model_name": self.model_name,
            "description": f"DashScope 云端重排序 ({self.model_name})",
            "size": "云端",
            "language": "多语言(100+语种)",
            "enabled": self.enabled,
            "loaded": bool(self._api_key),
        }

    @classmethod
    def list_models(cls) -> List[dict]:
        """列出可用的重排序模型"""
        return [
            {
                "name": "qwen3-rerank",
                "description": "通义千问重排序模型(推荐，多语言)",
                "size": "云端",
                "language": "100+语种",
            },
            {
                "name": "gte-rerank-v2",
                "description": "GTE重排序V2(多语言，30000文档)",
                "size": "云端",
                "language": "50+语种",
            },
        ]
