"""
从 JSONL 重建 MySQL documents + kb_documents + knowledge_bases
JSONL 是唯一可信数据源
用法: docker exec edurag_app python scripts/rebuild_mysql_from_jsonl.py
"""
import os, sys, json, uuid

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import pymysql
from core.logger import get_logger

logger = get_logger("rebuild_mysql")

JSONL_PATH = os.path.join(BASE_DIR, "data", "chunks_index.jsonl")

SUBJECT_KB = {
    "数学": "数学", "语文": "语文", "英语": "英语",
    "物理": "理科综合", "化学": "理科综合", "生物": "理科综合",
    "历史": "文科综合", "地理": "文科综合", "政治": "文科综合",
}


def collect_docs():
    """从 JSONL 收集所有唯一的 doc_id 及其元数据"""
    doc_info = {}  # doc_id -> {title, subject, grade, source_type, content_preview, ...}

    with open(JSONL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            did = obj.get("doc_id", "")
            if not did or did in doc_info:
                continue

            meta = obj.get("metadata", {})
            content = obj.get("content", "")

            doc_info[did] = {
                "title": (meta.get("title") or did)[:200],
                "subject": meta.get("subject", ""),
                "grade": meta.get("grade", ""),
                "difficulty": meta.get("difficulty", ""),
                "knowledge_tree": meta.get("knowledge_tree", ""),
                "task_type": meta.get("task_type", ""),
                "answer": meta.get("answer", ""),
                "source_type": meta.get("source_type", ""),
                "content_preview": content[:65535],
                "kb_name": None,  # to be filled
            }

    logger.info(f"JSONL 中共 {len(doc_info)} 个唯一 doc_id")
    return doc_info


def assign_kb(doc_info):
    """为每个 doc 分配目标 KB"""
    for did, info in doc_info.items():
        subj = info.get("subject", "")
        src_type = info.get("source_type", "")

        if src_type == "k12_question":
            info["kb_name"] = SUBJECT_KB.get(subj, "文科综合")
        elif did.startswith("cmrc_") or did.startswith("DEV_"):
            info["kb_name"] = "CMRC 2018"
        elif did in ("蔚来教育品牌介绍.md", "教育政策合规知识库.md", "教学方法与教研体系.md"):
            info["kb_name"] = "机构背景,教资实力"
        else:
            # 残留的旧 Markdown doc → 归入 K12题库（待清理）
            info["kb_name"] = "K12题库"


def main():
    logger.info("===== 从 JSONL 重建 MySQL =====")

    # 1. 收集所有 doc
    doc_info = collect_docs()
    assign_kb(doc_info)

    # Show breakdown
    kb_counts = {}
    for info in doc_info.values():
        kb = info["kb_name"]
        kb_counts[kb] = kb_counts.get(kb, 0) + 1
    for kb, cnt in sorted(kb_counts.items(), key=lambda x: -x[1]):
        logger.info(f"  {kb}: {cnt} docs")

    # 2. Connect MySQL
    conn = pymysql.connect(
        host=os.getenv("MYSQL_HOST", "mysql"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "edurag123"),
        database=os.getenv("MYSQL_DATABASE", "edurag_db"),
    )
    cur = conn.cursor()

    # 3. 清空旧的 kb_documents 和 documents
    logger.info("清空旧的 kb_documents 和 documents...")
    cur.execute("DELETE FROM kb_documents")
    cur.execute("DELETE FROM documents")
    conn.commit()
    logger.info("已清空")

    # 4. 批量插入 documents
    logger.info(f"插入 {len(doc_info)} 个文档记录...")
    batch = []
    for did, info in doc_info.items():
        source = f"jsonl_rebuild:{info.get('source_type', '')}"
        metadata_json = json.dumps({
            "subject": info["subject"], "grade": info["grade"],
            "difficulty": info.get("difficulty", ""),
            "knowledge_tree": info.get("knowledge_tree", ""),
            "task_type": info.get("task_type", ""),
        }, ensure_ascii=False)
        batch.append((did, info["title"], source, info["content_preview"], metadata_json))

        if len(batch) >= 500:
            cur.executemany(
                "INSERT INTO documents (id, title, source, content, metadata) VALUES (%s, %s, %s, %s, %s)",
                batch,
            )
            conn.commit()
            batch = []

    if batch:
        cur.executemany(
            "INSERT INTO documents (id, title, source, content, metadata) VALUES (%s, %s, %s, %s, %s)",
            batch,
        )
        conn.commit()
    logger.info("documents 插入完成")

    # 5. 确保所有需要的 KB 存在，删除不需要的旧 KB
    needed_kb_names = set(info["kb_name"] for info in doc_info.values())
    logger.info(f"需要的 KB: {needed_kb_names}")

    # 清理旧 KB (但保留名字相符的)
    cur.execute("SELECT id, name FROM knowledge_bases")
    existing_kb = {r[1]: r[0] for r in cur.fetchall()}
    logger.info(f"现有 KB: {list(existing_kb.keys())}")

    # 确保所需 KB 存在
    kb_map = {}
    for kb_name in needed_kb_names:
        if kb_name in existing_kb:
            kb_map[kb_name] = existing_kb[kb_name]
            logger.info(f"  ✓ {kb_name} (已有)")
        else:
            kb_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO knowledge_bases (id, name, description, category) VALUES (%s, %s, %s, %s)",
                (kb_id, kb_name, f"{kb_name}题库", kb_name),
            )
            kb_map[kb_name] = kb_id
            logger.info(f"  + {kb_name} (新建)")

    conn.commit()

    # 6. 批量插入 kb_documents
    logger.info(f"插入 kb_documents 关联...")
    links = []
    for did, info in doc_info.items():
        kb_id = kb_map[info["kb_name"]]
        links.append((kb_id, did))

        if len(links) >= 1000:
            cur.executemany(
                "INSERT IGNORE INTO kb_documents (kb_id, doc_id) VALUES (%s, %s)",
                links,
            )
            conn.commit()
            links = []

    if links:
        cur.executemany(
            "INSERT IGNORE INTO kb_documents (kb_id, doc_id) VALUES (%s, %s)",
            links,
        )
        conn.commit()
    logger.info("kb_documents 插入完成")

    # 7. 验证
    cur.execute("SELECT COUNT(*) FROM documents")
    doc_cnt = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM kb_documents")
    link_cnt = cur.fetchone()[0]

    logger.info(f"===== 验证 =====")
    logger.info(f"documents: {doc_cnt}")
    logger.info(f"kb_documents: {link_cnt}")

    cur.execute("SELECT k.name, COUNT(kd.doc_id) as c FROM knowledge_bases k LEFT JOIN kb_documents kd ON k.id=kd.kb_id GROUP BY k.id, k.name ORDER BY c DESC")
    for r in cur.fetchall():
        logger.info(f"  {r[0]}: {r[1]} docs")

    conn.close()
    logger.info("===== 重建完成 =====")


if __name__ == "__main__":
    main()
