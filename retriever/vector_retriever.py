"""
向量密集检索
基于向量相似度的检索
"""
from typing import List, Dict, Any, Optional

from core.models import DocumentChunk, RetrievalResult
from core.logger import get_logger
from data_processor.vectorizer import Vectorizer

logger = get_logger("vector_retriever")


class VectorRetriever:
    """向量检索器"""
    
    def __init__(self):
        self.vectorizer = Vectorizer()
        self._chunks = []
        
    def build_index(self, chunks: List[DocumentChunk]):
        """
        构建向量索引
        
        Args:
            chunks: 文档片段列表
        """
        self._chunks = chunks
        # 向量化已在数据处理阶段完成
        vector_count = sum(1 for c in chunks if c.embedding is not None)
        logger.info(f"向量索引构建完成，共 {len(chunks)} 个文档片段，{vector_count} 个已向量化")
    
    def search(self, query: str, top_k: int = 5, 
               similarity_threshold: float = 0.0,
               metadata_filter: dict = None) -> List[RetrievalResult]:
        """
        向量检索
        
        Args:
            query: 查询文本
            top_k: 返回结果数量
            similarity_threshold: 相似度阈值
            
        Returns:
            检索结果列表
        """
        if not self._chunks:
            logger.warning("向量索引为空")
            return []
        
        # 获取查询向量
        try:
            query_embedding = self.vectorizer.embed_query(query)
        except Exception as e:
            logger.error(f"查询向量化失败: {e}")
            return []
        
        # 计算与所有文档片段的相似度
        results = []
        for chunk in self._chunks:
            if chunk.embedding is None:
                continue
            
            # 维度不匹配时跳过该chunk
            try:
                similarity = self.vectorizer.cosine_similarity(query_embedding, chunk.embedding)
            except ValueError as e:
                logger.debug(f"chunk {chunk.chunk_id} 向量维度不匹配，跳过: {e}")
                continue
            
            # 元数据过滤
            if metadata_filter and chunk.metadata:
                from data_processor.metadata_extractor import MetadataExtractor
                if not MetadataExtractor.matches_filter(chunk.metadata, metadata_filter):
                    continue

            if similarity >= similarity_threshold:
                results.append(RetrievalResult(
                    chunk=chunk,
                    score=similarity,
                    source="vector"
                ))
        
        # 按相似度排序
        results.sort(key=lambda x: x.score, reverse=True)
        
        # 返回top_k
        results = results[:top_k]
        
        logger.info(f"向量检索完成，返回 {len(results)} 个结果")
        return results
    
    def add_documents(self, chunks: List[DocumentChunk]):
        """增量添加文档"""
        # 向量化新文档
        chunks_with_embeddings = self.vectorizer.embed_documents(chunks)
        self._chunks.extend(chunks_with_embeddings)
    
    def get_index_stats(self) -> Dict[str, Any]:
        """获取索引统计信息"""
        return {
            "num_documents": len(self._chunks),
            "type": "Vector"
        }
