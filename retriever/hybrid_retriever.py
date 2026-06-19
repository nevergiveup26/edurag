"""
混合检索
结合BM25和向量检索的混合检索策略
"""
from typing import List, Dict, Any, Optional
import numpy as np

from core.models import DocumentChunk, RetrievalResult
from core.config_manager import ConfigManager
from core.logger import get_logger
from retriever.bm25_retriever import BM25Retriever
from retriever.vector_retriever import VectorRetriever

logger = get_logger("hybrid_retriever")


class HybridRetriever:
    """混合检索器"""
    
    def __init__(self):
        config = ConfigManager()
        retriever_config = config.retriever_config
        
        self.bm25_retriever = BM25Retriever()
        self.vector_retriever = VectorRetriever()
        
        self.bm25_weight = retriever_config.get("bm25_weight", 0.3)
        self.vector_weight = retriever_config.get("vector_weight", 0.7)
        self.top_k = retriever_config.get("top_k", 5)
        # 实例级文档过滤器（仅限单请求场景，如 agent 路径）
        self._doc_id_filter: Optional[List[str]] = None
        
    def build_index(self, chunks: List[DocumentChunk]):
        """
        构建混合索引
        
        Args:
            chunks: 文档片段列表
        """
        self.bm25_retriever.build_index(chunks)
        self.vector_retriever.build_index(chunks)
        logger.info(f"混合索引构建完成，共 {len(chunks)} 个文档片段")
    
    def search(self, query: str, top_k: int = None, doc_id_filter: List[str] = None,
               metadata_filter: dict = None) -> List[RetrievalResult]:
        """
        混合检索

        Args:
            query: 查询文本
            top_k: 返回结果数量
            doc_id_filter: 可选，只返回匹配这些 doc_id 的结果（用于知识库限定，优先于实例级过滤器）
            metadata_filter: 可选，元数据过滤条件 {"subject": "数学", "grade": "初中"}

        Returns:
            混合检索结果列表
        """
        top_k = top_k or self.top_k
        # 合并显式参数和实例级过滤器
        effective_filter = doc_id_filter if doc_id_filter is not None else self._doc_id_filter

        # BM25检索
        bm25_results = []
        try:
            bm25_results = self.bm25_retriever.search(query, top_k=top_k * 2, metadata_filter=metadata_filter)
        except Exception as e:
            logger.warning(f"BM25检索失败: {e}")

        # 向量检索（允许失败，降级到纯BM25）
        vector_results = []
        try:
            vector_results = self.vector_retriever.search(query, top_k=top_k * 2, metadata_filter=metadata_filter)
        except Exception as e:
            logger.warning(f"[Hybrid] 向量检索完全失败，降级到纯BM25: {type(e).__name__}: {e}")
        
        # 如果指定了 doc_id 过滤，在合并前先过滤
        if effective_filter:
            doc_id_set = set(effective_filter)
            bm25_results = [r for r in bm25_results if r.chunk.doc_id in doc_id_set]
            vector_results = [r for r in vector_results if r.chunk.doc_id in doc_id_set]
        
        # 合并结果
        merged_results = self._merge_results(bm25_results, vector_results, top_k)
        
        logger.info(f"混合检索完成，BM25返回{len(bm25_results)}个，向量返回{len(vector_results)}个，合并后{len(merged_results)}个")
        return merged_results
    
    def set_doc_filter(self, doc_ids: List[str]):
        """设置实例级文档ID过滤器（线程安全：仅用于单请求 retriever 实例）"""
        self._doc_id_filter = list(doc_ids) if doc_ids else None
    
    def clear_doc_filter(self):
        """清除实例级文档ID过滤器"""
        self._doc_id_filter = None
    
    def _merge_results(self, bm25_results: List[RetrievalResult],
                       vector_results: List[RetrievalResult],
                       top_k: int) -> List[RetrievalResult]:
        """
        合并BM25和向量检索结果
        
        使用加权分数融合
        """
        # 建立chunk_id到结果的映射
        result_map = {}
        
        # 添加BM25结果
        for result in bm25_results:
            chunk_id = result.chunk.chunk_id
            result_map[chunk_id] = {
                "chunk": result.chunk,
                "bm25_score": result.score,
                "vector_score": 0.0
            }
        
        # 添加向量结果
        for result in vector_results:
            chunk_id = result.chunk.chunk_id
            if chunk_id in result_map:
                result_map[chunk_id]["vector_score"] = result.score
            else:
                result_map[chunk_id] = {
                    "chunk": result.chunk,
                    "bm25_score": 0.0,
                    "vector_score": result.score
                }
        
        # 计算加权分数
        merged = []
        for chunk_id, data in result_map.items():
            final_score = (self.bm25_weight * data["bm25_score"] + 
                          self.vector_weight * data["vector_score"])
            merged.append(RetrievalResult(
                chunk=data["chunk"],
                score=final_score,
                source="hybrid"
            ))
        
        # 按最终分数排序
        merged.sort(key=lambda x: x.score, reverse=True)
        
        return merged[:top_k]
    
    def add_documents(self, chunks: List[DocumentChunk]):
        """增量添加文档"""
        self.bm25_retriever.add_documents(chunks)
        self.vector_retriever.add_documents(chunks)
    
    def get_index_stats(self) -> Dict[str, Any]:
        """获取索引统计信息"""
        return {
            "bm25": self.bm25_retriever.get_index_stats(),
            "vector": self.vector_retriever.get_index_stats(),
            "type": "Hybrid",
            "bm25_weight": self.bm25_weight,
            "vector_weight": self.vector_weight
        }
