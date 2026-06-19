"""
Milvus向量数据库操作
提供Milvus向量存储和检索功能
"""
from typing import List, Dict, Any, Optional
import numpy as np

from core.config_manager import ConfigManager
from core.logger import get_logger

logger = get_logger("milvus_db")

# 模块级标志：连接失败只警告一次
_milvus_connect_warned = False


class MilvusDB:
    """Milvus向量数据库操作类"""
    
    def __init__(self):
        config = ConfigManager()
        self.config = config.milvus_config
        self._client = None
        self.collection_name = self.config["collection"]
        self.embedding_dim = self.config["embedding_dim"]
        
    def connect(self):
        """连接Milvus服务器"""
        global _milvus_connect_warned
        try:
            from pymilvus import connections, utility
            connections.connect(
                host=self.config["host"],
                port=str(self.config["port"]),
                timeout=3,
            )
            logger.info(f"已连接到Milvus: {self.config['host']}:{self.config['port']}")
            self._client = utility
        except ImportError:
            if not _milvus_connect_warned:
                _milvus_connect_warned = True
                logger.warning("pymilvus未安装，使用模拟模式")
        except Exception as e:
            if not _milvus_connect_warned:
                _milvus_connect_warned = True
                logger.warning(f"Milvus连接不可用，使用模拟模式: {e}")
    
    def create_collection(self, collection_name: str = None):
        """创建集合"""
        if self._client is None:
            logger.debug("Milvus未连接，跳过集合创建")
            return
        try:
            from pymilvus import Collection, CollectionSchema, FieldSchema, DataType
            
            col_name = collection_name or self.collection_name
            
            # 检查集合是否已存在
            if self._client and self._client.has_collection(col_name):
                logger.info(f"集合 {col_name} 已存在")
                return
            
            # 定义字段
            fields = [
                FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
                FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
                FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=64),
                FieldSchema(name="metadata", dtype=DataType.JSON),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.embedding_dim)
            ]
            
            schema = CollectionSchema(fields, description="EduRAG文档向量集合")
            collection = Collection(col_name, schema)
            
            # 创建索引
            index_params = {
                "index_type": self.config["index_type"],
                "metric_type": self.config["metric_type"],
                "params": {"nlist": 1024}
            }
            collection.create_index("embedding", index_params)
            collection.load()
            
            logger.info(f"集合 {col_name} 创建成功")
            
        except ImportError:
            logger.warning("pymilvus未安装，跳过集合创建")
        except Exception as e:
            logger.error(f"创建集合失败: {e}")
            raise
    
    def insert_vectors(self, ids: List[str], embeddings: List[List[float]], 
                       contents: List[str], doc_ids: List[str], 
                       metadatas: List[Dict] = None):
        """插入向量数据"""
        try:
            from pymilvus import Collection
            collection = Collection(self.collection_name)
            
            entities = [
                ids,
                contents,
                doc_ids,
                metadatas or [{} for _ in ids],
                embeddings
            ]
            
            result = collection.insert(entities)
            logger.info(f"成功插入 {len(ids)} 条向量数据")
            return result
        except Exception as e:
            logger.error(f"插入向量数据失败: {e}")
            raise
    
    def search(self, query_embedding: List[float], top_k: int = 5, 
               filter_expr: str = "") -> List[Dict[str, Any]]:
        """向量检索"""
        try:
            from pymilvus import Collection
            collection = Collection(self.collection_name)
            
            search_params = {
                "metric_type": self.config["metric_type"],
                "params": {"nprobe": 16}
            }
            
            results = collection.search(
                data=[query_embedding],
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                expr=filter_expr,
                output_fields=["id", "content", "doc_id", "metadata"]
            )
            
            # 解析结果
            retrieved = []
            for hits in results:
                for hit in hits:
                    retrieved.append({
                        "id": hit.entity.get("id"),
                        "content": hit.entity.get("content"),
                        "doc_id": hit.entity.get("doc_id"),
                        "metadata": hit.entity.get("metadata"),
                        "score": hit.distance
                    })
            
            return retrieved
            
        except Exception as e:
            logger.error(f"向量检索失败: {e}")
            return []
    
    def delete_by_doc_id(self, doc_id: str):
        """根据文档ID删除向量（非关键操作，失败不抛异常）"""
        try:
            from pymilvus import Collection, connections
            try:
                connections.get_connection_addr("default")
            except Exception:
                # 无活跃连接，跳过删除（模拟模式或未初始化）
                logger.debug(f"Milvus未连接，跳过向量删除: {doc_id}")
                return
            collection = Collection(self.collection_name)
            expr = f'doc_id == "{doc_id}"'
            collection.delete(expr)
            logger.info(f"已删除文档 {doc_id} 的向量数据")
        except Exception as e:
            logger.warning(f"删除向量数据失败（非关键，已忽略）: {e}")
    
    def get_collection_stats(self) -> Dict[str, Any]:
        """获取集合统计信息"""
        try:
            from pymilvus import Collection
            collection = Collection(self.collection_name)
            return {
                "name": self.collection_name,
                "num_entities": collection.num_entities
            }
        except Exception as e:
            logger.error(f"获取集合统计失败: {e}")
            return {}

    def fetch_all_chunks(self, batch_size: int = 1000) -> List[Dict[str, Any]]:
        """分页获取集合中所有数据（替代 chunk_store 的 load_chunks）

        Milvus 限制 offset + limit <= 16384，超过会报错。
        当 batch_size 过大时自动缩减到安全范围。
        """
        try:
            from pymilvus import Collection
            collection = Collection(self.collection_name)
            total = collection.num_entities
            if total == 0:
                return []

            all_data = []
            offset = 0
            output_fields = ["id", "content", "doc_id", "metadata", "embedding"]
            MILVUS_QUERY_WINDOW = 16384  # Milvus 最大查询窗口

            while offset < total:
                # 确保 offset + limit 不超过 Milvus 查询窗口
                safe_limit = min(batch_size, MILVUS_QUERY_WINDOW - offset)
                if safe_limit <= 0:
                    break
                results = collection.query(
                    expr="id != ''",
                    output_fields=output_fields,
                    limit=safe_limit,
                    offset=offset,
                )
                if not results:
                    break
                # 转换为 chunk_store 兼容格式
                for r in results:
                    all_data.append({
                        "chunk_id": r.get("id", ""),
                        "doc_id": r.get("doc_id", ""),
                        "content": r.get("content", ""),
                        "metadata": r.get("metadata", {}),
                        "embedding": r.get("embedding", None),
                    })
                offset += len(results)
                if len(results) < batch_size:
                    break

            logger.info(f"从 Milvus 加载了 {len(all_data)} 个 chunk")
            return all_data
        except Exception as e:
            logger.error(f"从 Milvus 获取全量数据失败: {e}")
            return []

    def get_doc_chunk_stats(self, doc_ids: List[str] = None) -> Dict[str, Dict[str, int]]:
        """
        按 doc_id 统计 chunk 数量和内容总大小。
        返回: {doc_id: {"chunk_count": int, "total_size": int}}
        如果 doc_ids 为 None，统计所有文档。
        """
        try:
            from pymilvus import Collection
            collection = Collection(self.collection_name)
            total = collection.num_entities
            if total == 0:
                return {}

            stats = {}
            batch_size = 2000
            MILVUS_QUERY_WINDOW = 16384
            output_fields = ["id", "doc_id", "content"]

            if doc_ids:
                # 分批查询特定 doc_ids（Milvus IN 表达式长度有限制）
                doc_id_set = set(doc_ids)
                all_results = []
                # 每批最多 200 个 doc_id
                doc_batches = [list(doc_id_set)[i:i+200] for i in range(0, len(doc_id_set), 200)]
                for batch in doc_batches:
                    ids_str = ", ".join(f'"{d}"' for d in batch)
                    expr = f"doc_id in [{ids_str}]"
                    offset = 0
                    while True:
                        safe_limit = min(batch_size, MILVUS_QUERY_WINDOW - offset)
                        if safe_limit <= 0:
                            break
                        results = collection.query(
                            expr=expr,
                            output_fields=output_fields,
                            limit=safe_limit,
                            offset=offset,
                        )
                        if not results:
                            break
                        all_results.extend(results)
                        offset += len(results)
                        if len(results) < safe_limit:
                            break
            else:
                # 获取所有 chunks
                all_results = []
                offset = 0
                while offset < total:
                    safe_limit = min(batch_size, MILVUS_QUERY_WINDOW - offset)
                    if safe_limit <= 0:
                        break
                    results = collection.query(
                        expr="id != ''",
                        output_fields=output_fields,
                        limit=safe_limit,
                        offset=offset,
                    )
                    if not results:
                        break
                    all_results.extend(results)
                    offset += len(results)
                    if len(results) < safe_limit:
                        break

            for r in all_results:
                did = r.get("doc_id", "")
                content_len = len(r.get("content", ""))
                if did not in stats:
                    stats[did] = {"chunk_count": 0, "total_size": 0}
                stats[did]["chunk_count"] += 1
                stats[did]["total_size"] += content_len

            logger.info(f"统计完成: {len(stats)} 个文档, {len(all_results)} 个 chunk")
            return stats
        except Exception as e:
            logger.error(f"统计 doc chunk 失败: {e}")
            return {}

    def search_by_keyword(self, keywords: List[str], top_k: int = 20) -> List[Dict[str, Any]]:
        """关键词搜索（通过 Milvus LIKE 表达式）"""
        try:
            from pymilvus import Collection
            collection = Collection(self.collection_name)

            # 构建 LIKE 表达式: content like "%kw1%" or content like "%kw2%"
            conditions = []
            for kw in keywords:
                kw_escaped = kw.replace("'", "\\'")
                conditions.append(f'content like "%{kw_escaped}%"')
            expr = " or ".join(conditions) if conditions else "id != ''"

            results = collection.query(
                expr=expr,
                output_fields=["id", "content", "doc_id", "metadata"],
                limit=top_k,
            )

            return [
                {
                    "chunk_id": r.get("id", ""),
                    "doc_id": r.get("doc_id", ""),
                    "content": r.get("content", ""),
                    "metadata": r.get("metadata", {}),
                }
                for r in (results or [])
            ]
        except Exception as e:
            logger.error(f"Milvus 关键词搜索失败: {e}")
            return []

