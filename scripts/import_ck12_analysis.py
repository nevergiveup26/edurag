"""
CK12 学而思 K12 题目解析导入知识库（高性能版）

优化策略：
- 循环内只做 API 嵌入（无文件 I/O），每批 ~1 秒
- 全部完成后一次性批量写入 Milvus + chunk_store
- 断点续传：读取 chunk_store 中已有 ck12 数据，跳过已完成片段
- 每 500 批保存一次检查点（内存 → 磁盘），防止崩溃全丢

运行: python scripts/import_ck12_analysis.py --index
"""
import os
import re
import sys
import json
import time
import argparse
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CK12_DIR = os.path.join(BASE_DIR, "data", "external", "k12_question_bank", "original_data")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "knowledge", "ck12")
MERGE_THRESHOLD = 5
CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, ".import_checkpoint.json")


def clean_analysis(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|,，。、；：]', '_', name)
    name = name.strip('_ ')
    return name[:50] if name else "未命名"


def import_analysis():
    """生成 Markdown 文件（与之前相同）"""
    print("=" * 60)
    print("CK12 题目解析 → Markdown 生成")
    print("=" * 60)

    if not os.path.exists(CK12_DIR):
        print(f"❌ 目录不存在: {CK12_DIR}")
        return

    data = defaultdict(lambda: defaultdict(list))
    stats = {"total": 0, "with_analysis": 0, "skipped": 0}

    for grade_dir in sorted(os.listdir(CK12_DIR)):
        grade_path = os.path.join(CK12_DIR, grade_dir)
        if not os.path.isdir(grade_path):
            continue
        for subject_dir in sorted(os.listdir(grade_path)):
            subject_path = os.path.join(grade_path, subject_dir)
            if not os.path.isdir(subject_path):
                continue
            for type_file in sorted(os.listdir(subject_path)):
                if not type_file.endswith(".jsonl"):
                    continue
                fp = os.path.join(subject_path, type_file)
                if os.path.getsize(fp) == 0:
                    continue
                with open(fp, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            d = json.loads(line)
                        except json.JSONDecodeError:
                            stats["skipped"] += 1
                            continue
                        stats["total"] += 1
                        analysis = d.get("analysis", "").strip()
                        if not analysis:
                            stats["skipped"] += 1
                            continue
                        stats["with_analysis"] += 1
                        subject = d.get("task_subject", subject_dir)
                        grade = d.get("task_grade", grade_dir)
                        tree = d.get("knowledge_tree", "").strip()
                        difficulty = d.get("difficulty", "")
                        if not tree:
                            stats["skipped"] += 1
                            continue
                        parts = [p.strip() for p in tree.split("-") if p.strip()]
                        l1 = parts[0] if parts else "其他"
                        l2 = parts[1] if len(parts) > 1 else ""
                        l3 = "-".join(parts[2:]) if len(parts) > 2 else ""
                        cleaned = clean_analysis(analysis)
                        if cleaned:
                            data[subject][l1].append({
                                "grade": grade, "l2": l2, "l3": l3,
                                "analysis": cleaned, "difficulty": difficulty,
                                "full_path": tree,
                            })

    print(f"  总题目: {stats['total']}, 有解析: {stats['with_analysis']}, 跳过: {stats['skipped']}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    file_count = 0
    for subject in sorted(data.keys()):
        subject_dir = os.path.join(OUTPUT_DIR, subject)
        os.makedirs(subject_dir, exist_ok=True)
        topics = data[subject]
        big_topics = {}
        small_topics = []
        for l1, entries in topics.items():
            if len(entries) >= MERGE_THRESHOLD:
                big_topics[l1] = entries
            else:
                small_topics.append((l1, entries))

        for l1, entries in sorted(big_topics.items()):
            filepath = os.path.join(subject_dir, sanitize_filename(l1) + ".md")
            content = _gen_topic_md(subject, l1, entries)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            file_count += 1

        if small_topics:
            filepath = os.path.join(subject_dir, "其他知识点.md")
            content = _gen_merged_md(subject, small_topics)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            file_count += 1

    print(f"  生成文件: {file_count} 个")


def _gen_topic_md(subject, l1_topic, entries):
    lines = [f"# {subject} · {l1_topic}\n",
             f"> 本文档包含「{l1_topic}」相关的 {len(entries)} 道题目解析。\n"]
    by_l2 = defaultdict(list)
    for e in entries:
        by_l2[e["l2"] or "综合"].append(e)
    for l2 in sorted(by_l2.keys()):
        lines.append(f"\n## {l2}\n")
        for e in by_l2[l2]:
            title = e["l3"] if e["l3"] else e["full_path"]
            tags = f"[{e['grade']}]" if e["grade"] else ""
            if e["difficulty"]:
                tags += f"[{e['difficulty']}]"
            lines.append(f"### {title} {tags}\n")
            lines.append(e["analysis"])
            lines.append("")
    return "\n".join(lines)


def _gen_merged_md(subject, small_topics):
    total = sum(len(e) for _, e in small_topics)
    lines = [f"# {subject} · 其他知识点\n",
             f"> 合并 {len(small_topics)} 个小知识点，共 {total} 道题。\n"]
    for l1, entries in sorted(small_topics, key=lambda x: x[0]):
        lines.append(f"\n## {l1}\n")
        for e in entries:
            tags = f"[{e['grade']}]" if e["grade"] else ""
            lines.append(f"### {e['full_path']} {tags}\n")
            lines.append(e["analysis"])
            lines.append("")
    return "\n".join(lines)


def index_knowledge_base(chunk_size: int = 600):
    """高性能批量索引：内存嵌入 → 一次性写入"""
    sys.path.insert(0, BASE_DIR)

    from data_processor.document_loader import DocumentLoader
    from data_processor.document_splitter import DocumentSplitter
    from data_processor.vectorizer import Vectorizer
    from database.chunk_store import save_chunks, load_chunks
    from core.models import DocumentChunk
    import numpy as np

    # ── 1. 读取检查点 ──
    checkpoint = {}
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r") as f:
            checkpoint = json.load(f)
        print(f"  检查点: 已完成 {checkpoint.get('embedded_count', 0)} 个片段")

    # ── 2. 检测 chunk_store 中已有的 CK12 数据 ──
    existing_data = load_chunks()
    existing_ck12_ids = set()
    for d in existing_data:
        if d.get("metadata", {}).get("source_type") == "ck12":
            existing_ck12_ids.add(d["chunk_id"])
    if existing_ck12_ids:
        print(f"  chunk_store 中已有 {len(existing_ck12_ids)} 个 CK12 片段，将跳过")

    # ── 3. 加载 + 切片 ──
    print(f"加载 {OUTPUT_DIR} 下的 Markdown 文档...")
    docs = DocumentLoader.load_directory(OUTPUT_DIR, extensions=[".md"], recursive=True)
    print(f"  加载了 {len(docs)} 个文档")
    if not docs:
        print("❌ 没有文档可索引")
        return

    print(f"切片中（chunk_size={chunk_size}）...")
    splitter = DocumentSplitter(chunk_size=chunk_size, chunk_overlap=80, mode="semantic")
    all_chunks = splitter.split_batch(docs)
    print(f"  生成了 {len(all_chunks)} 个片段")

    for chunk in all_chunks:
        chunk.metadata["source_type"] = "ck12"
        chunk.metadata["knowledge_base"] = "ck12_analysis"

    # ── 4. 合并跳过集合（检查点 + chunk_store 已有） ──
    done_ids = set(checkpoint.get("done_chunk_ids", [])) | existing_ck12_ids
    start_offset = checkpoint.get("start_offset", 0)

    # 过滤出还需要处理的 chunks
    remaining = []
    for i, c in enumerate(all_chunks):
        if c.chunk_id not in done_ids:
            remaining.append((i, c))

    print(f"  待嵌入: {len(remaining)} / {len(all_chunks)} (跳过 {len(done_ids)} 已完成)")

    if not remaining:
        print("✅ 所有片段已嵌入，直接写入存储...")
    else:
        # ── 5. 纯内存嵌入（无文件 I/O） ──
        print("向量化中（纯 API 调用，无磁盘 I/O）...")
        vectorizer = Vectorizer()
        batch_size = 10
        consecutive_errors = 0
        embedded_count = len(done_ids) - len(existing_ck12_ids)  # 本轮新增计数

        t_start = time.time()

        for batch_idx in range(0, len(remaining), batch_size):
            batch_items = remaining[batch_idx:batch_idx + batch_size]
            batch_chunks = [c for _, c in batch_items]

            try:
                batch_chunks = vectorizer.embed_documents(batch_chunks)
                # 写回原始 all_chunks 列表
                for (orig_idx, _), chunk in zip(batch_items, batch_chunks):
                    all_chunks[orig_idx] = chunk
                    done_ids.add(chunk.chunk_id)
                embedded_count += len(batch_chunks)
                consecutive_errors = 0

                # 进度打印（每 500 批）
                if batch_idx % (batch_size * 500) == 0 and batch_idx > 0:
                    elapsed = time.time() - t_start
                    rate = embedded_count / elapsed if elapsed > 0 else 0
                    eta = (len(remaining) - batch_idx) / rate / 60 if rate > 0 else 0
                    print(f"  [{embedded_count}/{len(remaining)}] "
                          f"速度 {rate:.1f}条/秒, 预计剩余 {eta:.0f} 分钟")

                    # 保存检查点
                    with open(CHECKPOINT_FILE, "w") as f:
                        json.dump({
                            "done_chunk_ids": list(done_ids),
                            "start_offset": batch_idx + batch_size,
                            "embedded_count": embedded_count,
                        }, f)

            except Exception as e:
                consecutive_errors += 1
                error_msg = str(e)
                if "Arrearage" in error_msg or "overdue" in error_msg.lower():
                    print(f"\n❌ DashScope 欠费！已嵌入 {embedded_count} 个。")
                    with open(CHECKPOINT_FILE, "w") as f:
                        json.dump({
                            "done_chunk_ids": list(done_ids),
                            "start_offset": batch_idx,
                            "embedded_count": embedded_count,
                        }, f)
                    print(f"  检查点已保存，充值后重跑即可续传")
                    return
                if consecutive_errors >= 5:
                    print(f"\n❌ 连续 {consecutive_errors} 次失败，保存进度退出")
                    with open(CHECKPOINT_FILE, "w") as f:
                        json.dump({
                            "done_chunk_ids": list(done_ids),
                            "start_offset": batch_idx,
                            "embedded_count": embedded_count,
                        }, f)
                    return
                print(f"  ⚠️ 嵌入失败 ({consecutive_errors}): {error_msg[:80]}")
                time.sleep(2 * consecutive_errors)

        elapsed = time.time() - t_start
        print(f"  嵌入完成！{embedded_count} 个片段, 耗时 {elapsed/60:.1f} 分钟")

    # ── 6. 一次性批量写入 chunk_store ──
    print("\n批量写入 chunk_store...")
    ck12_chunks = [c for c in all_chunks if c.chunk_id in done_ids and hasattr(c, 'embedding') and c.embedding is not None]
    print(f"  准备写入 {len(ck12_chunks)} 个 CK12 片段")

    # 分批写入 chunk_store（每 1000 条一批，避免单次 JSON 太大）
    batch_write = 1000
    for i in range(0, len(ck12_chunks), batch_write):
        batch = ck12_chunks[i:i + batch_write]
        save_chunks(batch)
        print(f"  chunk_store: {min(i + batch_write, len(ck12_chunks))}/{len(ck12_chunks)}")

    # ── 7. 一次性批量写入 Milvus ──
    try:
        from database.milvus_db import MilvusDB
        milvus = MilvusDB()
        ids = [c.chunk_id for c in ck12_chunks]
        embeddings = [c.embedding for c in ck12_chunks]
        contents = [c.content for c in ck12_chunks]
        doc_ids = [c.doc_id for c in ck12_chunks]
        metadatas = [c.metadata for c in ck12_chunks]
        # Milvus 分批插入（每 5000 条）
        milvus_batch = 5000
        for i in range(0, len(ids), milvus_batch):
            end = min(i + milvus_batch, len(ids))
            milvus.insert_vectors(
                ids[i:end], embeddings[i:end], contents[i:end],
                doc_ids[i:end], metadatas[i:end]
            )
            print(f"  Milvus: {end}/{len(ids)}")
        print(f"  ✅ Milvus 写入完成 ({len(ids)} 向量)")
    except Exception as e:
        print(f"  ⚠️ Milvus 写入失败（使用内存模式）: {e}")

    # ── 8. 清理 ──
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)

    print(f"\n{'='*60}")
    print(f"✅ 索引完成！共 {len(ck12_chunks)} 个 CK12 片段可被 RAG 检索")
    print(f"   重启后端服务或发送查询时，retriever 会自动重建索引")
    print(f"{'='*60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CK12 题目解析导入工具")
    parser.add_argument("--index", action="store_true", help="生成 Markdown 后自动切片+向量化+入库")
    parser.add_argument("--chunk-size", type=int, default=600, help="切片大小（默认 600）")
    args = parser.parse_args()

    if not os.path.exists(OUTPUT_DIR) or not os.listdir(OUTPUT_DIR):
        import_analysis()

    if args.index:
        print("\n" + "=" * 60)
        print("批量索引 CK12 知识库文档（高性能版）")
        print("=" * 60)
        index_knowledge_base(chunk_size=args.chunk_size)
