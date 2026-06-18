"""
补嵌入 CK12 缺失文件
将 88 个未嵌入的 Markdown 文件切片、向量化并写入 Milvus + MySQL
用法: docker exec edurag_app python scripts/embed_missing_ck12.py
"""
import os, sys, json, time, uuid

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CK12_DIR = os.path.join(BASE_DIR, "data", "knowledge", "ck12")
JSONL_PATH = os.path.join(BASE_DIR, "data", "chunks_index.jsonl")
sys.path.insert(0, BASE_DIR)

from data_processor.document_loader import DocumentLoader
from data_processor.document_splitter import DocumentSplitter
from data_processor.vectorizer import Vectorizer
from pymilvus import connections, Collection
import pymysql
from core.logger import get_logger

logger = get_logger("embed_missing")

CHUNK_SIZE = 600
CHUNK_OVERLAP = 80
BATCH_SIZE = 10
MILVUS_HOST = os.getenv("MILVUS_HOST", "milvus")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")
COLLECTION_NAME = "edurag_collection"


def find_missing_files():
    """找出 JSONL 中没有的 ck12 源文件"""
    # 收集 JSONL 中已有文件
    embedded_files = set()
    with open(JSONL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            title = obj.get("metadata", {}).get("title", "")
            if title:
                embedded_files.add(title)

    # 遍历 ck12 目录
    all_files = {}
    for subj in os.listdir(CK12_DIR):
        subj_dir = os.path.join(CK12_DIR, subj)
        if not os.path.isdir(subj_dir):
            continue
        for fname in os.listdir(subj_dir):
            if fname.endswith(".md") and fname not in embedded_files:
                all_files[fname] = {
                    "path": os.path.join(subj_dir, fname),
                    "subject": subj,
                }

    return all_files


def main():
    logger.info("===== CK12 补嵌入 =====")

    # 1. 找出缺失文件
    missing = find_missing_files()
    logger.info(f"缺失文件: {len(missing)} 个")
    if not missing:
        logger.info("没有缺失文件")
        return

    for fname, info in sorted(missing.items()):
        logger.info(f"  [{info['subject']}] {fname}")

    # 2. 加载缺失文档
    logger.info("加载缺失文档...")
    docs = []
    for fname, info in missing.items():
        try:
            loaded = DocumentLoader.load_file(info["path"])
            for doc in loaded:
                # doc_id 用文件名（与已有数据一致）
                doc.doc_id = fname
                doc.source = info["path"]
                doc.metadata["subject"] = info["subject"]
                docs.append(doc)
        except Exception as e:
            logger.warning(f"加载失败 {fname}: {e}")

    logger.info(f"加载了 {len(docs)} 个文档")

    # 3. 切片
    logger.info(f"切片中 (chunk_size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP})...")
    splitter = DocumentSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, mode="semantic")
    all_chunks = splitter.split_batch(docs)
    logger.info(f"切片完成: {len(all_chunks)} 个 chunk")

    # 4. 嵌入
    logger.info("开始嵌入...")
    vectorizer = Vectorizer()
    embedded_chunks = []
    t_start = time.time()

    for i in range(0, len(all_chunks), BATCH_SIZE):
        batch = all_chunks[i:i + BATCH_SIZE]
        batch_end = min(i + BATCH_SIZE, len(all_chunks))
        try:
            batch = vectorizer.embed_documents(batch)
            embedded_chunks.extend(batch)
        except Exception as e:
            err_msg = str(e)
            if "Arrearage" in err_msg:
                logger.error(f"DashScope 欠费！已嵌入 {i}/{len(all_chunks)}")
            else:
                logger.error(f"嵌入失败 (batch {i}-{batch_end}): {e}")
            break

        if (i // BATCH_SIZE) % 50 == 0 and i > 0:
            elapsed = time.time() - t_start
            rate = i / elapsed if elapsed > 0 else 0
            eta_min = (len(all_chunks) - i) / rate / 60 if rate > 0 else 0
            logger.info(f"  [{i}/{len(all_chunks)}] {rate:.1f}条/秒, 剩余约 {eta_min:.1f} 分钟")

    elapsed = time.time() - t_start
    logger.info(f"嵌入完成: {len(embedded_chunks)}/{len(all_chunks)}, 耗时 {elapsed/60:.1f} 分钟")

    if not embedded_chunks:
        logger.error("没有成功嵌入的 chunk，退出")
        return

    # 5. 写入 JSONL
    logger.info(f"追加 {len(embedded_chunks)} 条到 JSONL...")
    with open(JSONL_PATH, "a", encoding="utf-8") as f:
        for chunk in embedded_chunks:
            emb = chunk.embedding.tolist() if hasattr(chunk.embedding, "tolist") else chunk.embedding
            record = {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "content": chunk.content,
                "metadata": chunk.metadata,
                "embedding": emb,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info("JSONL 写入完成")

    # 6. 写入 Milvus
    logger.info("写入 Milvus...")
    connections.connect(host=MILVUS_HOST, port=str(MILVUS_PORT), timeout=10)
    collection = Collection(COLLECTION_NAME)

    batch_ids, batch_contents, batch_doc_ids = [], [], []
    batch_metadatas, batch_embeddings = [], []
    total_inserted = 0

    for chunk in embedded_chunks:
        emb = chunk.embedding.tolist() if hasattr(chunk.embedding, "tolist") else chunk.embedding
        batch_ids.append(chunk.chunk_id)
        batch_contents.append(chunk.content)
        batch_doc_ids.append(chunk.doc_id)
        batch_metadatas.append(chunk.metadata)
        batch_embeddings.append(emb)

        if len(batch_ids) >= 500:
            collection.insert([batch_ids, batch_contents, batch_doc_ids,
                               batch_metadatas, batch_embeddings])
            total_inserted += len(batch_ids)
            logger.info(f"  Milvus 已插入 {total_inserted} 条...")
            batch_ids, batch_contents, batch_doc_ids = [], [], []
            batch_metadatas, batch_embeddings = [], []

    if batch_ids:
        collection.insert([batch_ids, batch_contents, batch_doc_ids,
                           batch_metadatas, batch_embeddings])
        total_inserted += len(batch_ids)

    collection.flush()
    logger.info(f"Milvus 写入完成: {total_inserted} 条, 总计 {collection.num_entities} 条")

    # 7. 更新 MySQL
    logger.info("更新 MySQL...")
    conn = pymysql.connect(
        host=os.getenv("MYSQL_HOST", "mysql"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "edurag123"),
        database=os.getenv("MYSQL_DATABASE", "edurag_db"),
    )
    cur = conn.cursor()

    # 7a. 确保文档记录存在
    new_doc_ids = set(chunk.doc_id for chunk in embedded_chunks)
    existing = set()
    cur.execute("SELECT id FROM documents")
    for r in cur.fetchall():
        existing.add(r[0])

    new_docs = [d for d in new_doc_ids if d not in existing]
    logger.info(f"  新建 {len(new_docs)} 个文档记录")
    if new_docs:
        with conn.cursor() as c:
            c.executemany(
                "INSERT IGNORE INTO documents (id, title, source) VALUES (%s, %s, %s)",
                [(d, d, f"ck12_import:{d}") for d in new_docs],
            )
        conn.commit()

    # 7b. 关联到知识库（按学科 → KB）
    cur.execute("SELECT id, name FROM knowledge_bases")
    kb_map = {r[1]: r[0] for r in cur.fetchall()}
    logger.info(f"  现有知识库: {list(kb_map.keys())}")

    # 学科 → KB 名
    subject_kb_map = {
        "数学": "数学", "语文": "语文", "英语": "英语",
        "物理": "理科综合", "化学": "理科综合", "生物": "理科综合",
        "历史": "K12题库", "地理": "K12题库", "政治": "K12题库",
    }

    # 确保所需 KB 存在
    for kb_name in set(subject_kb_map.values()):
        if kb_name not in kb_map:
            kb_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO knowledge_bases (id, name, description, category) VALUES (%s, %s, %s, %s)",
                (kb_id, kb_name, f"{kb_name}题库", kb_name),
            )
            kb_map[kb_name] = kb_id
            logger.info(f"  创建知识库: {kb_name} ({kb_id})")

    # 查已有关联
    existing_links = set()
    cur.execute("SELECT kb_id, doc_id FROM kb_documents")
    for r in cur.fetchall():
        existing_links.add((r[0], r[1]))

    # 分组: doc → 目标 KB
    doc_kb_links = []
    for chunk in embedded_chunks:
        did = chunk.doc_id
        subject = chunk.metadata.get("subject", "")
        kb_name = subject_kb_map.get(subject, "K12题库")
        kb_id = kb_map[kb_name]
        if (kb_id, did) not in existing_links:
            doc_kb_links.append((kb_id, did))
            existing_links.add((kb_id, did))

    logger.info(f"  新关联 {len(doc_kb_links)} 条 kb_documents")
    if doc_kb_links:
        with conn.cursor() as c:
            c.executemany(
                "INSERT IGNORE INTO kb_documents (kb_id, doc_id) VALUES (%s, %s)",
                doc_kb_links,
            )
        conn.commit()

    # 7c. 统计输出
    cur.execute("SELECT k.name, COUNT(kd.doc_id) as c FROM knowledge_bases k LEFT JOIN kb_documents kd ON k.id=kd.kb_id GROUP BY k.id, k.name")
    logger.info("知识库统计:")
    for row in cur.fetchall():
        logger.info(f"  {row[0]}: {row[1]} 文档")

    conn.close()

    # 8. 总结
    milvus_total = collection.num_entities
    with open(JSONL_PATH, "r", encoding="utf-8") as f:
        jsonl_total = sum(1 for _ in f)
    logger.info(f"===== 完成 =====")
    logger.info(f"新增 chunk: {len(embedded_chunks)}")
    logger.info(f"JSONL 总计: {jsonl_total}")
    logger.info(f"Milvus 总计: {milvus_total}")


if __name__ == "__main__":
    main()
