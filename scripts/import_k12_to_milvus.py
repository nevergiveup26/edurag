"""
将 data/chunks_index.json 中的 K12 预嵌入数据写入 Milvus
    用法: docker exec edurag_app python scripts/import_k12_to_milvus.py
    数据: 24955 chunks, 384-dim, 727MB JSON
"""
import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymilvus import connections, Collection, CollectionSchema, FieldSchema, DataType, utility
from core.logger import get_logger

logger = get_logger("import_k12")

COLLECTION_NAME = "edurag_collection"
EMBEDDING_DIM = 1024
BATCH_SIZE = 500
JSON_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chunks_index.json")
MILVUS_HOST = os.getenv("MILVUS_HOST", "localhost")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")

METRIC_TYPE = "IP"  # 内积，与 config.ini 中的 IP 一致；如果模型用 L2 距离则改为 "L2"


def connect_milvus():
    connections.connect(host=MILVUS_HOST, port=str(MILVUS_PORT), timeout=10)
    logger.info(f"已连接到 Milvus: {MILVUS_HOST}:{MILVUS_PORT}")


def recreate_collection():
    """删除旧集合并创建 384 维新集合"""
    if utility.has_collection(COLLECTION_NAME):
        old_col = Collection(COLLECTION_NAME)
        old_count = old_col.num_entities
        utility.drop_collection(COLLECTION_NAME)
        logger.info(f"已删除旧集合 {COLLECTION_NAME}（含 {old_count} 条数据）")

    fields = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=128, is_primary=True),
        FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
        FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="metadata", dtype=DataType.JSON),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM),
    ]

    schema = CollectionSchema(fields, description="EduRAG K12 知识库向量集合")
    collection = Collection(COLLECTION_NAME, schema)

    index_params = {
        "index_type": "IVF_FLAT",
        "metric_type": METRIC_TYPE,
        "params": {"nlist": 2048},
    }
    collection.create_index("embedding", index_params)
    collection.load()
    logger.info(f"新集合 {COLLECTION_NAME} 创建完成 (dim={EMBEDDING_DIM}, metric={METRIC_TYPE})")


def load_chunks_streaming(path: str):
    """流式读取 JSON 数组，逐个 yield chunk（低内存）"""
    with open(path, "r", encoding="utf-8") as f:
        # 跳过开头 [
        char = ''
        while char != '[':
            char = f.read(1)
            if not char:
                return

        decoder = json.JSONDecoder()
        buffer = ''
        count = 0
        while True:
            chunk_data = f.read(1048576)  # 1MB
            if not chunk_data:
                break
            buffer += chunk_data
            buffer = buffer.lstrip()
            while buffer:
                # 跳过数组分隔符 , ] 和空白
                while buffer and buffer[0] in ' \t\n\r,[]':
                    if buffer[0] == ']':
                        logger.info(f"流式读取完成: {count} 个 chunk")
                        return
                    buffer = buffer[1:]
                if not buffer:
                    break
                try:
                    obj, idx = decoder.raw_decode(buffer)
                    yield obj
                    count += 1
                    buffer = buffer[idx:]
                except json.JSONDecodeError:
                    # 需要更多数据
                    break

        logger.info(f"流式读取完成: {count} 个 chunk")


def main():
    logger.info("========== K12 数据导入 Milvus ==========")
    t0 = time.time()

    connect_milvus()
    recreate_collection()

    collection = Collection(COLLECTION_NAME)

    batch_ids, batch_contents, batch_doc_ids = [], [], []
    batch_metadatas, batch_embeddings = [], []
    total = 0
    skipped = 0

    for chunk in load_chunks_streaming(JSON_PATH):
        # 跳过维度不匹配的 chunk
        if len(chunk["embedding"]) != EMBEDDING_DIM:
            skipped += 1
            continue
        batch_ids.append(chunk["chunk_id"])
        batch_contents.append(chunk["content"])
        batch_doc_ids.append(chunk["doc_id"])
        batch_metadatas.append(chunk.get("metadata", {}))
        batch_embeddings.append(chunk["embedding"])

        if len(batch_ids) >= BATCH_SIZE:
            collection.insert([batch_ids, batch_contents, batch_doc_ids,
                               batch_metadatas, batch_embeddings])
            total += len(batch_ids)
            logger.info(f"  已插入 {total} 条...")
            batch_ids, batch_contents, batch_doc_ids = [], [], []
            batch_metadatas, batch_embeddings = [], []

    # 最后一批
    if batch_ids:
        collection.insert([batch_ids, batch_contents, batch_doc_ids,
                           batch_metadatas, batch_embeddings])
        total += len(batch_ids)

    # 刷新索引
    collection.flush()
    logger.info(f"刷新完成，共 {collection.num_entities} 条向量")

    elapsed = time.time() - t0
    logger.info(f"========== 导入完成: {total} 条, 跳过 {skipped} 条 (维度不匹配), 耗时 {elapsed:.1f}s ==========")


if __name__ == "__main__":
    main()
