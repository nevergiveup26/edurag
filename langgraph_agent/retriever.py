"""
LangChain Retriever 包装器

将自定义 HybridRetriever + Reranker 包装为 LangChain BaseRetriever 和 BaseDocumentCompressor，
支持 LangChain 标准检索链。

用法：
    from langgraph_agent.retriever import create_langchain_retriever
    retriever = create_langchain_retriever()
    docs = retriever.invoke("量子力学是什么")
"""

from typing import List, Optional

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.runnables import RunnableConfig

from core.logger import get_logger

logger = get_logger("langgraph_retriever")


class HybridLangChainRetriever(BaseRetriever):
    """
    将 HybridRetriever 包装为 LangChain BaseRetriever

    支持元数据过滤、top_k 控制。
    """

    top_k: int = 5
    """默认返回结果数"""

    doc_id_filter: Optional[List[str]] = None
    """可选的文档ID过滤列表"""

    def __init__(self, top_k: int = 5, **kwargs):
        super().__init__(top_k=top_k, **kwargs)
        self._hybrid = None

    @property
    def _hybrid_retriever(self):
        """延迟初始化 HybridRetriever"""
        if self._hybrid is None:
            from retriever.hybrid_retriever import HybridRetriever
            self._hybrid = HybridRetriever()
        return self._hybrid

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun = None,
        **kwargs,
    ) -> List[Document]:
        """
        同步检索 — 将 RetrievalResult 转为 LangChain Document

        Args:
            query: 查询文本

        Returns:
            LangChain Document 列表
        """
        from retriever.hybrid_retriever import RetrievalResult

        results: List[RetrievalResult] = self._hybrid_retriever.search(
            query=query,
            top_k=self.top_k,
            doc_id_filter=self.doc_id_filter,
        )

        docs = []
        for r in results:
            # 提取 content
            if hasattr(r, 'chunk') and hasattr(r.chunk, 'content'):
                content = str(r.chunk.content)
            elif hasattr(r, 'content'):
                content = str(r.content)
            else:
                content = str(r)

            # 提取 metadata
            metadata = {}
            if hasattr(r, 'chunk') and hasattr(r.chunk, 'metadata'):
                metadata = dict(r.chunk.metadata) if r.chunk.metadata else {}
            elif hasattr(r, 'metadata'):
                metadata = dict(r.metadata) if r.metadata else {}

            metadata["retrieval_score"] = getattr(r, 'score', 0)
            metadata["retrieval_source"] = "hybrid"

            docs.append(Document(page_content=content, metadata=metadata))

        return docs


def create_langchain_retriever(top_k: int = 5) -> HybridLangChainRetriever:
    """
    创建 LangChain 兼容的混合检索器

    Args:
        top_k: 默认返回结果数

    Returns:
        HybridLangChainRetriever 实例
    """
    return HybridLangChainRetriever(top_k=top_k)
