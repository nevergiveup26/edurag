"""快速批量关联 K12 数据到知识库（批量 SQL）"""
import json, os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import get_logger
from database.mysql_db import MySQLDB

logger = get_logger("link_k12_fast")

CHUNKS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chunks_index.jsonl")

# 1. 收集所有 K12 doc_id
doc_ids = set()
with open(CHUNKS_FILE, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        did = obj.get("doc_id", "")
        if did:
            doc_ids.add(did)

logger.info(f"K12 共 {len(doc_ids)} 个不同 doc_id")

db = MySQLDB()

# 2. 查已存在的 doc_id
existing = set()
for r in db.query("SELECT id FROM documents"):
    existing.add(r["id"])
logger.info(f"MySQL 中已有 {len(existing)} 个文档")

# 3. 批量插入缺失的文档
missing = [d for d in doc_ids if d not in existing]
logger.info(f"需新建 {len(missing)} 个文档")

if missing:
    with db.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT IGNORE INTO documents (id, title, source) VALUES (%s, %s, %s)",
                [(d, d, "k12_import") for d in missing]
            )
        conn.commit()
    logger.info(f"批量创建 {len(missing)} 个文档完成")

# 4. 确保 K12题库 KB 存在
rows = db.query("SELECT id FROM knowledge_bases WHERE name = 'K12题库'")
if rows:
    k12_kb_id = rows[0]["id"]
    logger.info(f"K12题库 已存在: {k12_kb_id}")
else:
    k12_kb_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO knowledge_bases (id, name, description, category) VALUES (%s, %s, %s, %s)",
        (k12_kb_id, "K12题库", "K12全科错题解析题库", "题库")
    )
    logger.info(f"创建 K12题库: {k12_kb_id}")

# 5. 查已有 kb_documents 关联
existing_links = set()
for r in db.query("SELECT doc_id FROM kb_documents WHERE kb_id = %s", (k12_kb_id,)):
    existing_links.add(r["doc_id"])

new_links = [d for d in doc_ids if d not in existing_links]
logger.info(f"需新增 {len(new_links)} 条关联到 K12题库")

if new_links:
    with db.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(
                "INSERT IGNORE INTO kb_documents (kb_id, doc_id) VALUES (%s, %s)",
                [(k12_kb_id, d) for d in new_links]
            )
        conn.commit()
    logger.info(f"批量关联 {len(new_links)} 条完成")

# 6. 输出统计
for r in db.query("SELECT k.id, k.name, COUNT(kd.doc_id) as cnt FROM knowledge_bases k LEFT JOIN kb_documents kd ON k.id=kd.kb_id GROUP BY k.id ORDER BY cnt DESC"):
    logger.info(f"  {r['name']}: {r['cnt']} 文档")

logger.info("完成！")
