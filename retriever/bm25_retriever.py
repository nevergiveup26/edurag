"""
BM25稀疏检索
基于词频和逆文档频率的检索算法
"""
from typing import List, Dict, Any, Optional
import numpy as np

from core.models import DocumentChunk, RetrievalResult
from core.logger import get_logger

logger = get_logger("bm25_retriever")


class BM25Retriever:
    """BM25检索器"""

    def __init__(self):
        self._bm25 = None
        self._corpus = []
        self._chunks = []
        self._tokenized_corpus = []
        self._dirty = False
        self._pending_chunks = []

    def _tokenize(self, texts: list) -> list:
        try:
            import jieba
            return [list(jieba.cut(text)) for text in texts]
        except ImportError:
            logger.warning("jieba未安装，使用简单分词")
            return [text.split() for text in texts]

    def build_index(self, chunks: List[DocumentChunk]):
        self._chunks = list(chunks)
        self._corpus = [chunk.content for chunk in self._chunks]
        self._tokenized_corpus = self._tokenize(self._corpus)
        try:
            from rank_bm25 import BM25Okapi
            self._bm25 = BM25Okapi(self._tokenized_corpus)
        except ImportError:
            logger.warning("rank_bm25未安装，BM25检索不可用")
            self._bm25 = None
            return
        self._dirty = False
        self._pending_chunks = []
        logger.info(f"BM25索引构建完成，共 {len(chunks)} 个文档片段")

    def _rebuild_if_dirty(self):
        if self._dirty:
            self.build_index(self._chunks)

    def search(self, query: str, top_k: int = 5,
               metadata_filter: dict = None) -> List[RetrievalResult]:
        self._rebuild_if_dirty()
        if self._bm25 is None:
            logger.warning("BM25索引未构建")
            return []

        try:
            import jieba
            tokenized_query = list(jieba.cut(query))
        except ImportError:
            tokenized_query = query.split()

        scores = self._bm25.get_scores(tokenized_query)
        top_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                chunk = self._chunks[idx]
                if metadata_filter and chunk.metadata:
                    from data_processor.metadata_extractor import MetadataExtractor
                    if not MetadataExtractor.matches_filter(chunk.metadata, metadata_filter):
                        continue
                normalized_score = float(scores[idx]) / (float(scores[idx]) + 1)
                results.append(RetrievalResult(
                    chunk=chunk,
                    score=normalized_score,
                    source="bm25"
                ))

        logger.info(f"BM25检索完成，返回 {len(results)} 个结果")
        return results

    def add_documents(self, chunks: List[DocumentChunk]):
        """增量添加文档（延迟索引重建，在下次检索时自动触发）"""
        self._chunks.extend(chunks)
        self._dirty = True
        self._pending_chunks.extend(chunks)
        logger.info(f"BM25 新增 {len(chunks)} 个文档，将在下次检索时重建索引（当前总数 {len(self._chunks)}）")
    
    def get_index_stats(self) -> Dict[str, Any]:
        """获取索引统计信息"""
        return {
            "num_documents": len(self._chunks),
            "type": "BM25"
        }
