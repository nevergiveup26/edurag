"""
从原始 JSONL 导入 K12 题目到系统（每道题一个独立文档）
仅嵌入 analysis 字段，保留完整元数据
用法: docker exec edurag_app python scripts/import_questions_from_original.py
"""
import os, sys, json, time, uuid

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from data_processor.vectorizer import Vectorizer
from pymilvus import connections, Collection
import pymysql
from core.logger import get_logger

logger = get_logger("import_questions")

ORIGINAL_DIR = os.path.join(BASE_DIR, "data", "external", "k12_question_bank", "original_data")
JSONL_OUT = os.path.join(BASE_DIR, "data", "chunks_index.jsonl")
MILVUS_HOST = os.getenv("MILVUS_HOST", "milvus")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")
COLLECTION_NAME = "edurag_collection"
BATCH_SIZE = 10  # DashScope batch size

# 学科 → KB 名称
SUBJECT_KB = {
    "数学": "数学", "语文": "语文", "英语": "英语",
    "物理": "理科综合", "化学": "理科综合", "生物": "理科综合",
    "历史": "K12题库", "地理": "K12题库", "政治": "K12题库",
}


def load_questions():
    """加载所有有 analysis 的原始题目"""
    questions = []
    skipped = 0
    for root, dirs, files in os.walk(ORIGINAL_DIR):
        for fname in sorted(files):
            if not fname.endswith(".jsonl"):
                continue
            path = os.path.join(root, fname)
            rel = os.path.relpath(path, ORIGINAL_DIR)
            parts = rel.replace("\\", "/").split("/")
            if len(parts) < 2:
                continue
            grade, subject = parts[0], parts[1]

            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        q = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    analysis = (q.get("analysis") or "").strip()
                    if not analysis:
                        skipped += 1
                        continue
                    questions.append({
                        "id": q["id"],
                        "prompt": q.get("prompt", ""),
                        "analysis": analysis,
                        "answer": q.get("answer", ""),
                        "answer_option": q.get("answer_option", []),
                        "task_type": q.get("task_type", ""),
                        "subject": subject,
                        "grade": grade,
                        "difficulty": q.get("difficulty", ""),
                        "knowledge_tree": q.get("knowledge_tree", ""),
                    })

    logger.info(f"加载完成: {len(questions)} 道有解析, 跳过 {skipped} 道无解析")
    return questions


def main():
    t0 = time.time()
    logger.info("===== 从原始 JSONL 导入题目 =====")

    # 1. 加载题目
    questions = load_questions()
    if not questions:
        return

    # 2. 嵌入 analysis
    logger.info(f"开始嵌入 {len(questions)} 道题的 analysis...")
    vectorizer = Vectorizer()
    all_analyses = [q["analysis"] for q in questions]
    all_embeddings = []

    for i in range(0, len(all_analyses), BATCH_SIZE):
        batch = all_analyses[i:i + BATCH_SIZE]
        batch_end = min(i + BATCH_SIZE, len(all_analyses))
        try:
            embeddings = vectorizer.embed(batch)
            all_embeddings.extend(embeddings)
        except Exception as e:
            if "Arrearage" in str(e):
                logger.error(f"DashScope 欠费！已嵌入 {i}/{len(all_analyses)}")
            else:
                logger.error(f"嵌入失败 (batch {i}-{batch_end}): {e}")
            break

        if (i // BATCH_SIZE) % 100 == 0 and i > 0:
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta_min = (len(all_analyses) - i) / rate / 60 if rate > 0 else 0
            logger.info(f"  [{i}/{len(all_analyses)}] {rate:.1f}条/秒, 剩余约 {eta_min:.1f} 分钟")

    embedded_count = len(all_embeddings)
    elapsed = time.time() - t0
    logger.info(f"嵌入完成: {embedded_count}/{len(questions)}, 耗时 {elapsed/60:.1f} 分钟")

    if embedded_count == 0:
        return

    # 只用嵌入成功的
    questions = questions[:embedded_count]

    # 3. 构建 chunk 数据
    chunk_ids = []
    doc_ids = []
    contents = []
    metadatas = []
    for q, emb in zip(questions, all_embeddings):
        chunk_id = f"{q['id']}_analysis"
        doc_id = q["id"]
        # content = prompt + analysis 用于预览
        content = f"【题目】{q['prompt']}\n\n【解析】{q['analysis']}"
        chunk_ids.append(chunk_id)
        doc_ids.append(doc_id)
        contents.append(content)
        metadatas.append({
            "title": q["prompt"][:80],
            "subject": q["subject"],
            "grade": q["grade"],
            "difficulty": q["difficulty"],
            "task_type": q["task_type"],
            "knowledge_tree": q["knowledge_tree"],
            "answer": q["answer"],
            "source_type": "k12_question",
            "chunk_index": 0,
            "chunk_count": 1,
        })

    # 4. 追加写入 JSONL
    logger.info(f"写入 JSONL: {embedded_count} 条...")
    with open(JSONL_OUT, "a", encoding="utf-8") as f:
        for i in range(embedded_count):
            record = {
                "chunk_id": chunk_ids[i],
                "doc_id": doc_ids[i],
                "content": contents[i],
                "metadata": metadatas[i],
                "embedding": all_embeddings[i],
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info("JSONL 写入完成")

    # 5. 写入 Milvus
    logger.info("写入 Milvus...")
    connections.connect(host=MILVUS_HOST, port=str(MILVUS_PORT), timeout=10)
    collection = Collection(COLLECTION_NAME)

    batch_ids, batch_docs, batch_contents = [], [], []
    batch_metas, batch_embs = [], []
    total = 0

    for i in range(embedded_count):
        batch_ids.append(chunk_ids[i])
        batch_docs.append(doc_ids[i])
        batch_contents.append(contents[i])
        batch_metas.append(metadatas[i])
        batch_embs.append(all_embeddings[i])

        if len(batch_ids) >= 500:
            collection.insert([batch_ids, batch_contents, batch_docs,
                               batch_metas, batch_embs])
            total += len(batch_ids)
            logger.info(f"  Milvus: {total}/{embedded_count}")
            batch_ids, batch_docs, batch_contents = [], [], []
            batch_metas, batch_embs = [], []

    if batch_ids:
        collection.insert([batch_ids, batch_contents, batch_docs,
                           batch_metas, batch_embs])
        total += len(batch_ids)

    collection.flush()
    logger.info(f"Milvus 完成: {total} 条, 总计 {collection.num_entities}")

    # 6. 更新 MySQL
    logger.info("更新 MySQL...")
    conn = pymysql.connect(
        host=os.getenv("MYSQL_HOST", "mysql"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "edurag123"),
        database=os.getenv("MYSQL_DATABASE", "edurag_db"),
    )
    cur = conn.cursor()

    # 6a. 确保 documents 存在
    existing_docs = set()
    cur.execute("SELECT id FROM documents")
    for r in cur.fetchall():
        existing_docs.add(r[0])

    new_docs = [(q["id"], q["prompt"][:200], f"k12_original:{q['subject']}:{q['grade']}:{q['task_type']}")
                for q in questions if q["id"] not in existing_docs]
    logger.info(f"  新建 {len(new_docs)} 个文档")
    if new_docs:
        # Also store content for preview
        for q in questions:
            if q["id"] not in existing_docs:
                full_content = f"【题目】{q['prompt']}\n\n【解析】{q['analysis']}\n\n【答案】{q['answer']}\n【知识点】{q['knowledge_tree']}"
                cur.execute(
                    "INSERT INTO documents (id, title, source, content, metadata) VALUES (%s, %s, %s, %s, %s)",
                    (q["id"], q["prompt"][:200], f"k12_original:{q['subject']}:{q['grade']}",
                     full_content[:65535],
                     json.dumps({"subject": q["subject"], "grade": q["grade"],
                                 "difficulty": q["difficulty"], "knowledge_tree": q["knowledge_tree"],
                                 "answer": q["answer"], "task_type": q["task_type"]},
                                ensure_ascii=False)),
                )
        conn.commit()

    # 6b. 确保 KB 存在并关联
    cur.execute("SELECT id, name FROM knowledge_bases")
    kb_map = {r[1]: r[0] for r in cur.fetchall()}

    for kb_name in set(SUBJECT_KB.values()):
        if kb_name not in kb_map:
            kb_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO knowledge_bases (id, name, description, category) VALUES (%s, %s, %s, %s)",
                (kb_id, kb_name, f"{kb_name}题库", kb_name),
            )
            kb_map[kb_name] = kb_id
            logger.info(f"  创建 KB: {kb_name}")

    # 6c. 关联文档到 KB
    existing_links = set()
    cur.execute("SELECT kb_id, doc_id FROM kb_documents")
    for r in cur.fetchall():
        existing_links.add((r[0], r[1]))

    new_links = []
    for q in questions:
        kb_name = SUBJECT_KB.get(q["subject"], "K12题库")
        kb_id = kb_map[kb_name]
        if (kb_id, q["id"]) not in existing_links:
            new_links.append((kb_id, q["id"]))
            existing_links.add((kb_id, q["id"]))

    logger.info(f"  新关联 {len(new_links)} 条 kb_documents")
    if new_links:
        with conn.cursor() as c:
            c.executemany(
                "INSERT IGNORE INTO kb_documents (kb_id, doc_id) VALUES (%s, %s)",
                new_links,
            )
        conn.commit()

    # 6d. 统计
    cur.execute("SELECT k.name, COUNT(kd.doc_id) as c FROM knowledge_bases k LEFT JOIN kb_documents kd ON k.id=kd.kb_id GROUP BY k.id, k.name")
    logger.info("KB 统计:")
    for r in cur.fetchall():
        logger.info(f"  {r[0]}: {r[1]} docs")

    conn.close()

    # 7. 总结
    total_elapsed = time.time() - t0
    with open(JSONL_OUT, "r", encoding="utf-8") as f:
        jsonl_total = sum(1 for _ in f)
    logger.info(f"===== 完成 =====")
    logger.info(f"导入题目: {embedded_count}")
    logger.info(f"JSONL 总计: {jsonl_total}")
    logger.info(f"Milvus 总计: {collection.num_entities}")
    logger.info(f"总耗时: {total_elapsed/60:.1f} 分钟")


if __name__ == "__main__":
    main()
