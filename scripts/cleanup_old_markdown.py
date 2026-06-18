"""
清理旧 Markdown 管道产生的数据
- JSONL: 移除旧 Markdown-based chunks（保留 k12_question + CMRC）
- Milvus: 删除旧 Markdown doc_id 的所有向量
- MySQL: 删除旧 CK12 Markdown 文档及 kb_documents 关联
- 磁盘: 删除 data/knowledge/ck12/ 下 414 个 .md 文件
用法: docker exec edurag_app python scripts/cleanup_old_markdown.py
"""
import os, sys, json, shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from core.logger import get_logger
from pymilvus import connections, Collection
import pymysql

logger = get_logger("cleanup_old_md")

JSONL_PATH = os.path.join(BASE_DIR, "data", "chunks_index.jsonl")
JSONL_BAK = JSONL_PATH + ".bak"
CK12_MD_DIR = os.path.join(BASE_DIR, "data", "knowledge", "ck12")
MILVUS_HOST = os.getenv("MILVUS_HOST", "milvus")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")
COLLECTION_NAME = "edurag_collection"


def identify_old_docs():
    """找出旧 Markdown 的 doc_id 列表"""
    old_docs = set()
    new_count = 0
    cmrc_count = 0
    old_count = 0

    with open(JSONL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            did = obj.get("doc_id", "")
            src_type = obj.get("metadata", {}).get("source_type", "")
            if src_type == "k12_question":
                new_count += 1
            elif did.startswith("cmrc_") or did.startswith("DEV_"):
                cmrc_count += 1
            else:
                old_docs.add(did)
                old_count += 1

    logger.info(f"新题目: {new_count}, CMRC: {cmrc_count}, 旧Markdown: {old_count} ({len(old_docs)} docs)")
    return old_docs


def filter_jsonl(old_docs):
    """从 JSONL 中移除旧 Markdown 条目"""
    logger.info("备份 JSONL...")
    shutil.copy2(JSONL_PATH, JSONL_BAK)

    kept = 0
    removed = 0
    tmp_path = JSONL_PATH + ".tmp"

    with open(JSONL_PATH, "r", encoding="utf-8") as fin, \
         open(tmp_path, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            did = obj.get("doc_id", "")
            src_type = obj.get("metadata", {}).get("source_type", "")
            if src_type != "k12_question" and not did.startswith("cmrc_") and not did.startswith("DEV_"):
                removed += 1
                continue
            fout.write(json.dumps(obj, ensure_ascii=False) + "\n")
            kept += 1

    os.replace(tmp_path, JSONL_PATH)
    logger.info(f"JSONL 清理完成: 保留 {kept}, 移除 {removed}")
    return kept


def cleanup_milvus(old_docs):
    """从 Milvus 删除旧 Markdown 的向量"""
    logger.info(f"删除 Milvus 中 {len(old_docs)} 个旧文档...")
    connections.connect(host=MILVUS_HOST, port=str(MILVUS_PORT), timeout=10)
    collection = Collection(COLLECTION_NAME)

    # 分批按 doc_id 删除
    doc_list = list(old_docs)
    batch_size = 100
    total_deleted = 0
    for i in range(0, len(doc_list), batch_size):
        batch = doc_list[i:i + batch_size]
        expr = "doc_id in " + str(batch).replace("'", '"')
        try:
            result = collection.delete(expr)
            total_deleted += getattr(result, "delete_count", 0)
        except Exception as e:
            logger.error(f"Milvus 删除失败 (batch {i}): {e}")

    collection.flush()
    logger.info(f"Milvus 删除完成: {total_deleted} 条, 剩余 {collection.num_entities}")
    return total_deleted


def cleanup_mysql(old_docs):
    """从 MySQL 删除旧 Markdown 文档及关联"""
    logger.info(f"清理 MySQL 中 {len(old_docs)} 个旧文档...")
    conn = pymysql.connect(
        host=os.getenv("MYSQL_HOST", "mysql"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "edurag123"),
        database=os.getenv("MYSQL_DATABASE", "edurag_db"),
    )
    cur = conn.cursor()

    doc_list = list(old_docs)
    batch_size = 200

    # 先删 kb_documents 关联
    kb_deleted = 0
    for i in range(0, len(doc_list), batch_size):
        batch = doc_list[i:i + batch_size]
        placeholders = ",".join(["%s"] * len(batch))
        cur.execute(f"DELETE FROM kb_documents WHERE doc_id IN ({placeholders})", batch)
        kb_deleted += cur.rowcount
        conn.commit()

    # 再删 documents
    doc_deleted = 0
    for i in range(0, len(doc_list), batch_size):
        batch = doc_list[i:i + batch_size]
        placeholders = ",".join(["%s"] * len(batch))
        cur.execute(f"DELETE FROM documents WHERE id IN ({placeholders})", batch)
        doc_deleted += cur.rowcount
        conn.commit()

    logger.info(f"MySQL 清理: {kb_deleted} 条关联, {doc_deleted} 个文档")

    # 统计剩余
    cur.execute("SELECT COUNT(*) FROM documents")
    remaining_docs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM kb_documents")
    remaining_links = cur.fetchone()[0]
    logger.info(f"MySQL 剩余: {remaining_docs} 文档, {remaining_links} 条关联")

    conn.close()


def delete_md_files():
    """删除 data/knowledge/ck12/ 下所有 .md 文件及空目录"""
    if not os.path.exists(CK12_MD_DIR):
        logger.info(f"目录不存在: {CK12_MD_DIR}")
        return

    md_count = 0
    for root, dirs, files in os.walk(CK12_MD_DIR):
        for fname in files:
            if fname.endswith(".md"):
                os.remove(os.path.join(root, fname))
                md_count += 1

    # 删除空目录
    for root, dirs, files in os.walk(CK12_MD_DIR, topdown=False):
        if root == CK12_MD_DIR:
            continue
        if not os.listdir(root):
            os.rmdir(root)

    logger.info(f"删除 {md_count} 个 .md 文件")


def main():
    logger.info("===== 清理旧 Markdown 数据 =====")

    # 1. 识别旧文档
    old_docs = identify_old_docs()
    if not old_docs:
        logger.info("没有旧 Markdown 数据需要清理")
        return

    # 2. 清理 JSONL
    kept = filter_jsonl(old_docs)

    # 3. 清理 Milvus
    cleanup_milvus(old_docs)

    # 4. 清理 MySQL
    cleanup_mysql(old_docs)

    # 5. 删除源文件
    delete_md_files()

    logger.info("===== 清理完成 =====")
    logger.info(f"JSONL 剩余: {kept} 条")
    logger.info(f"备份文件: {JSONL_BAK} (确认无误后可删除)")


if __name__ == "__main__":
    main()
