"""
恢复丢失的 CK12 片段

问题：上一轮导入时 chunk_store 写入部分失败（23,428/30,399）
本脚本：
1. 加载已有 chunk_store 的 CK12 chunk_id
2. 重新切片 Markdown 找出缺失的 chunks
3. 仅嵌入缺失的部分（~7000 条）
4. 一次性写入 chunk_store（只读+写一次文件）
"""
import os, sys, json, time

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "knowledge", "ck12")

sys.path.insert(0, BASE_DIR)


def recover_missing(chunk_size: int = 600):
    from data_processor.document_loader import DocumentLoader
    from data_processor.document_splitter import DocumentSplitter
    from data_processor.vectorizer import Vectorizer
    from database.chunk_store import CHUNK_FILE
    import numpy as np

    # ── 1. 加载已有 CK12 chunk_id ──
    print("加载已有 chunk_store 数据...")
    with open(CHUNK_FILE, "r", encoding="utf-8") as f:
        existing = json.load(f)
    print(f"  总条目: {len(existing)}")

    existing_ck12_ids = set()
    for d in existing:
        if d.get("metadata", {}).get("source_type") == "ck12":
            existing_ck12_ids.add(d["chunk_id"])
    print(f"  已有 CK12 片段: {len(existing_ck12_ids)}")

    # ── 2. 重新切片 Markdown ──
    print(f"\n加载 {OUTPUT_DIR} 下的 Markdown 文档...")
    docs = DocumentLoader.load_directory(OUTPUT_DIR, extensions=[".md"], recursive=True)
    print(f"  加载了 {len(docs)} 个文档")

    splitter = DocumentSplitter(chunk_size=chunk_size, chunk_overlap=80, mode="semantic")
    all_chunks = splitter.split_batch(docs)
    print(f"  总片段数: {len(all_chunks)}")

    for chunk in all_chunks:
        chunk.metadata["source_type"] = "ck12"
        chunk.metadata["knowledge_base"] = "ck12_analysis"

    # ── 3. 找出缺失的 chunks ──
    missing = []
    for chunk in all_chunks:
        if chunk.chunk_id not in existing_ck12_ids:
            missing.append(chunk)

    print(f"\n缺失片段: {len(missing)}")
    if not missing:
        print("✅ 没有缺失的片段！")
        return

    # ── 4. 嵌入缺失的片段 ──
    print(f"嵌入 {len(missing)} 个缺失片段...")
    vectorizer = Vectorizer()
    batch_size = 10
    t_start = time.time()

    for i in range(0, len(missing), batch_size):
        batch = missing[i:i + batch_size]
        try:
            batch = vectorizer.embed_documents(batch)
            for j, chunk in enumerate(batch):
                missing[i + j] = chunk
        except Exception as e:
            if "Arrearage" in str(e):
                print(f"❌ DashScope 欠费！已嵌入 {i}/{len(missing)}")
                return
            print(f"  ⚠️ 嵌入失败: {e}")
            time.sleep(2)

        if (i // batch_size) % 100 == 0 and i > 0:
            elapsed = time.time() - t_start
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(missing) - i) / rate / 60 if rate > 0 else 0
            print(f"  [{i}/{len(missing)}] {rate:.1f}条/秒, 剩余 {eta:.1f} 分钟")

    elapsed = time.time() - t_start
    embedded = [c for c in missing if hasattr(c, 'embedding') and c.embedding is not None]
    print(f"  嵌入完成: {len(embedded)}/{len(missing)}, 耗时 {elapsed/60:.1f} 分钟")

    # ── 5. 一次性写入 chunk_store（读取一次 + 追加 + 写入一次） ──
    print(f"\n写入 chunk_store（一次性追加 {len(embedded)} 条）...")

    # 转换为 dict
    new_stored = []
    for c in embedded:
        emb = c.embedding.tolist() if hasattr(c.embedding, 'tolist') else c.embedding
        new_stored.append({
            "chunk_id": c.chunk_id,
            "doc_id": c.doc_id,
            "content": c.content,
            "metadata": c.metadata,
            "embedding": emb,
        })

    # 单次读取 + 追加 + 写入
    print("  读取现有数据...")
    with open(CHUNK_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    old_count = len(data)

    print(f"  追加 {len(new_stored)} 条...")
    data.extend(new_stored)

    print("  写入文件（可能需要 30-60 秒）...")
    with open(CHUNK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"✅ 恢复完成！")
    print(f"   之前: {old_count} 条 (CK12: {len(existing_ck12_ids)})")
    print(f"   现在: {len(data)} 条 (CK12: {len(existing_ck12_ids) + len(new_stored)})")
    print(f"   新增: {len(new_stored)} 条")
    print(f"{'='*60}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="恢复丢失的 CK12 片段")
    parser.add_argument("--chunk-size", type=int, default=600)
    args = parser.parse_args()
    recover_missing(chunk_size=args.chunk_size)
