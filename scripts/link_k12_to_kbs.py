"""
将 K12 题库 chunk 关联到知识库

- 读取 chunks_index.jsonl，收集所有 doc_id 及其 subject/grade 元数据
- 为缺失的 doc_id 在 MySQL documents 表中创建记录
- 按学科将 doc_id 关联到对应知识库
- 无法判断学科的归入「K12题库」知识库
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import get_logger
from database.mysql_db import MySQLDB
from kb.knowledge_base import KnowledgeBaseManager

logger = get_logger("link_k12")

CHUNKS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chunks_index.jsonl")

# 学科 → KB 名称映射
SUBJECT_KB_MAP = {
    "数学": "数学",
    "英语": "英语",
    "语文": "语文",
    "理科综合": "理科综合",
}


def main():
    # 1. 收集 K12 doc_id 及元数据
    logger.info("读取 K12 chunks...")
    doc_meta = {}  # doc_id -> {"subject": set, "grade": set}
    if not os.path.exists(CHUNKS_FILE):
        logger.error(f"文件不存在: {CHUNKS_FILE}")
        return

    with open(CHUNKS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            doc_id = obj.get("doc_id", "")
            if not doc_id:
                continue
            meta = obj.get("metadata", {})
            subj = meta.get("subject", "")
            grade = meta.get("grade", "")
            if doc_id not in doc_meta:
                doc_meta[doc_id] = {"subjects": set(), "grades": set()}
            if subj and subj != "unknown":
                doc_meta[doc_id]["subjects"].add(subj)
            if grade and grade != "unknown":
                doc_meta[doc_id]["grades"].add(grade)

    logger.info(f"K12 共 {len(doc_meta)} 个不同 doc_id")

    # 2. 连接 MySQL，检查已存在的 doc_id
    db = MySQLDB()
    kb_mgr = KnowledgeBaseManager()
    kb_mgr.init_tables()

    existing = set()
    rows = db.query("SELECT id FROM documents")
    for r in rows:
        existing.add(r["id"])
    logger.info(f"MySQL 中已有 {len(existing)} 个文档")

    # 3. 插入缺失的文档记录
    missing = {k: v for k, v in doc_meta.items() if k not in existing}
    logger.info(f"需要新建 {len(missing)} 个文档记录...")

    inserted = 0
    for doc_id, meta in missing.items():
        # 用 doc_id 作为标题（清理临时文件名前缀）
        title = doc_id
        if title.startswith("tmp") and (".md" in title or ".txt" in title):
            # 临时文件名，尝试用其他信息
            title = doc_id
        try:
            db.execute(
                "INSERT IGNORE INTO documents (id, title, source) VALUES (%s, %s, %s)",
                (doc_id, title, f"k12_import:{title}"),
            )
            inserted += 1
        except Exception as e:
            logger.warning(f"插入文档 {doc_id} 失败: {e}")

    logger.info(f"新建了 {inserted} 个文档记录")

    # 4. 确保目标 KB 存在
    kb_map = {}  # subject -> kb_id
    for subject, kb_name in SUBJECT_KB_MAP.items():
        rows = db.query("SELECT id FROM knowledge_bases WHERE name = %s", (kb_name,))
        if rows:
            kb_map[subject] = rows[0]["id"]
        else:
            kb = kb_mgr.create(name=kb_name, description=f"{kb_name}题库", category=kb_name)
            kb_map[subject] = kb.kb_id
            logger.info(f"创建知识库: {kb_name} ({kb.kb_id})")

    # 确保「K12题库」存在
    rows = db.query("SELECT id FROM knowledge_bases WHERE name = %s", ("K12题库",))
    if rows:
        k12_kb_id = rows[0]["id"]
    else:
        kb = kb_mgr.create(name="K12题库", description="K12全科错题解析题库", category="题库")
        k12_kb_id = kb.kb_id
        logger.info(f"创建知识库: K12题库 ({k12_kb_id})")

    # 5. 插入 kb_documents 关联
    # 先查已有关联
    existing_links = set()
    link_rows = db.query("SELECT kb_id, doc_id FROM kb_documents")
    for r in link_rows:
        existing_links.add((r["kb_id"], r["doc_id"]))

    linked_count = 0
    for doc_id, meta in doc_meta.items():
        # 判断学科 → KB
        subjects = meta.get("subjects", set())
        linked_to_kb = False

        for subj in subjects:
            if subj in kb_map:
                kb_id = kb_map[subj]
                if (kb_id, doc_id) not in existing_links:
                    try:
                        kb_mgr.add_document(kb_id, doc_id)
                        existing_links.add((kb_id, doc_id))
                        linked_count += 1
                        linked_to_kb = True
                    except Exception as e:
                        logger.warning(f"关联 {doc_id} → {subj} 失败: {e}")

        # 没有明确学科的归入 K12题库
        if not linked_to_kb:
            if (k12_kb_id, doc_id) not in existing_links:
                try:
                    kb_mgr.add_document(k12_kb_id, doc_id)
                    existing_links.add((k12_kb_id, doc_id))
                    linked_count += 1
                except Exception as e:
                    logger.warning(f"关联 {doc_id} → K12题库 失败: {e}")

    logger.info(f"新增 {linked_count} 条文档-知识库关联")

    # 6. 统计输出
    for kb_name, kb_id in list(kb_map.items()) + [("K12题库", k12_kb_id)]:
        cnt = db.query_one(
            "SELECT COUNT(*) as cnt FROM kb_documents WHERE kb_id = %s", (kb_id,)
        )
        count = cnt.get("cnt", 0) if cnt else 0
        logger.info(f"  {kb_name}: {count} 个文档")

    logger.info("K12 数据关联完成！")


if __name__ == "__main__":
    main()
