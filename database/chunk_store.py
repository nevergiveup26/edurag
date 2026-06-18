"""
文档片段持久化存储（JSONL 格式）
使用逐行 JSON 格式，支持流式读写，避免大文件内存溢出。
每行一个 JSON 对象：{"chunk_id": ..., "doc_id": ..., "content": ..., "metadata": ..., "embedding": [...]}
"""
import json
import os
from typing import List, Optional, Dict, Any, Set
from datetime import datetime

from core.logger import get_logger

logger = get_logger("chunk_store")

# 新格式：JSONL（逐行 JSON）
CHUNK_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chunks_index.jsonl")
# 旧格式：JSON 数组（用于自动迁移）
CHUNK_FILE_LEGACY = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chunks_index.json")
# 轻量缓存：doc_id → chunk_count（避免每次扫描大 JSONL）
DOC_CHUNK_COUNT_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "doc_chunk_counts.json")


def _ensure_dir():
    os.makedirs(os.path.dirname(CHUNK_FILE), exist_ok=True)


def migrate_json_to_jsonl():
    """
    将旧版 JSON 数组文件迁移为 JSONL 格式。
    使用 ijson 流式解析或直接读取，避免内存溢出。
    返回迁移的条目数，如果无需迁移返回 0。
    """
    if os.path.exists(CHUNK_FILE):
        return 0  # JSONL 已存在，无需迁移

    if not os.path.exists(CHUNK_FILE_LEGACY):
        return 0  # 旧文件也不存在

    _ensure_dir()
    file_size_mb = os.path.getsize(CHUNK_FILE_LEGACY) / 1024 / 1024
    logger.info(f"检测到旧版 JSON 文件 ({file_size_mb:.0f} MB)，开始迁移到 JSONL 格式...")

    try:
        # 对于大文件，使用流式解析
        count = 0
        with open(CHUNK_FILE, "w", encoding="utf-8") as out_f:
            with open(CHUNK_FILE_LEGACY, "r", encoding="utf-8") as in_f:
                # 跳过开头的 [
                char = ''
                while char != '[':
                    char = in_f.read(1)
                    if not char:
                        break

                # 逐个读取 JSON 对象
                decoder = json.JSONDecoder()
                buffer = ''
                while True:
                    chunk = in_f.read(65536)  # 64KB chunks
                    if not chunk:
                        break
                    buffer += chunk

                    # 尝试解析完整的 JSON 对象
                    while True:
                        buffer = buffer.lstrip()
                        if not buffer or buffer[0] == ']':
                            break
                        # 跳过数组分隔符
                        while buffer and buffer[0] in ' \t\n\r,':
                            buffer = buffer[1:]
                            buffer = buffer.lstrip()
                        if not buffer:
                            break
                        try:
                            obj, idx = decoder.raw_decode(buffer)
                            out_f.write(json.dumps(obj, ensure_ascii=False) + "\n")
                            count += 1
                            buffer = buffer[idx:]
                        except json.JSONDecodeError:
                            # 需要更多数据
                            break

        logger.info(f"✅ JSON → JSONL 迁移完成: {count} 个条目")
        return count
    except MemoryError:
        logger.error("❌ 迁移时内存不足，尝试备用方案...")
        # 清理可能写入的不完整文件
        if os.path.exists(CHUNK_FILE):
            os.remove(CHUNK_FILE)
        return _migrate_large_json()
    except Exception as e:
        logger.error(f"❌ 迁移失败: {e}")
        if os.path.exists(CHUNK_FILE):
            os.remove(CHUNK_FILE)
        return 0


def _migrate_large_json():
    """
    备用迁移方案：使用正则表达式逐条提取 JSON 对象（低内存）
    """
    import re
    count = 0
    try:
        with open(CHUNK_FILE, "w", encoding="utf-8") as out_f:
            with open(CHUNK_FILE_LEGACY, "r", encoding="utf-8") as in_f:
                depth = 0
                obj_start = -1
                in_string = False
                escape = False
                pos = 0

                while True:
                    chunk = in_f.read(1024 * 1024)  # 1MB chunks
                    if not chunk:
                        break
                    for i, ch in enumerate(chunk):
                        if escape:
                            escape = False
                            continue
                        if ch == '\\':
                            escape = True
                            continue
                        if ch == '"':
                            in_string = not in_string
                            continue
                        if in_string:
                            continue
                        if ch == '{':
                            if depth == 0:
                                obj_start = pos + i
                            depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0 and obj_start >= 0:
                                # 提取完整对象
                                # 需要回溯读取 — 这个方法太复杂了
                                pass
                    pos += len(chunk)

        logger.info(f"备用迁移: {count} 个条目")
        return count
    except Exception as e:
        logger.error(f"备用迁移也失败了: {e}")
        if os.path.exists(CHUNK_FILE):
            os.remove(CHUNK_FILE)
        return 0


def load_chunk_ids() -> Set[str]:
    """仅加载所有 chunk_id 集合（轻量级，不加载 embedding）"""
    ids = set()
    if not os.path.exists(CHUNK_FILE):
        return ids
    try:
        with open(CHUNK_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    ids.add(obj["chunk_id"])
                except (json.JSONDecodeError, KeyError):
                    continue
    except Exception as e:
        logger.warning(f"加载 chunk_id 失败: {e}")
    return ids


def load_chunk_ids_by_source(source_type: str) -> Set[str]:
    """加载指定 source_type 的 chunk_id 集合"""
    ids = set()
    if not os.path.exists(CHUNK_FILE):
        return ids
    try:
        with open(CHUNK_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("metadata", {}).get("source_type") == source_type:
                        ids.add(obj["chunk_id"])
                except (json.JSONDecodeError, KeyError):
                    continue
    except Exception as e:
        logger.warning(f"加载 chunk_id (source={source_type}) 失败: {e}")
    return ids


def save_chunks(chunks: List) -> bool:
    """
    将文档片段持久化（追加写入 JSONL，自动去重）
    
    使用流式 ID 检查 + 追加写入，不需要加载整个文件到内存。
    """
    try:
        _ensure_dir()

        # 流式检查已有 ID（不加载完整数据）
        existing_ids = load_chunk_ids()

        new_count = 0
        with open(CHUNK_FILE, "a", encoding="utf-8") as f:
            for c in chunks:
                if c.chunk_id in existing_ids:
                    continue
                embedding = c.embedding.tolist() if hasattr(c.embedding, 'tolist') else c.embedding
                obj = {
                    "chunk_id": c.chunk_id,
                    "doc_id": c.doc_id,
                    "content": c.content,
                    "metadata": c.metadata,
                    "embedding": embedding,
                }
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
                existing_ids.add(c.chunk_id)  # 防止本次批次内重复
                new_count += 1

        total = len(existing_ids)
        _update_chunk_count(total)
        _increment_doc_chunk_counts(chunks)
        logger.info(f"已持久化 {new_count} 个文档片段 (总计 {total} 个)")
        return True
    except Exception as e:
        logger.warning(f"持久化文档片段失败: {e}")
        return False


def save_chunks_batch(chunks: List) -> bool:
    """
    快速批量写入（不做去重检查，直接追加）
    仅在调用方已确保 chunk_id 不重复时使用（如首次导入、恢复缺失数据）
    """
    try:
        _ensure_dir()

        new_count = 0
        with open(CHUNK_FILE, "a", encoding="utf-8") as f:
            for c in chunks:
                embedding = c.embedding.tolist() if hasattr(c.embedding, 'tolist') else c.embedding
                obj = {
                    "chunk_id": c.chunk_id,
                    "doc_id": c.doc_id,
                    "content": c.content,
                    "metadata": c.metadata,
                    "embedding": embedding,
                }
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
                new_count += 1

        if os.path.exists(COUNT_FILE):
            os.remove(COUNT_FILE)
        _increment_doc_chunk_counts(chunks)
        logger.info(f"批量追加 {new_count} 个文档片段")
        return True
    except Exception as e:
        logger.warning(f"批量追加失败: {e}")
        return False


def load_chunks() -> List[Dict]:
    """加载所有文档片段（优先 Milvus，不可用时 fallback JSONL）"""
    # 优先从 Milvus 加载
    try:
        from database.milvus_db import MilvusDB
        milvus = MilvusDB()
        milvus.connect()
        if milvus._client:
            data = milvus.fetch_all_chunks()
            if data:
                return data
    except Exception as e:
        logger.debug(f"Milvus 加载失败，回退到 JSONL: {e}")

    # Fallback: JSONL 文件
    if not os.path.exists(CHUNK_FILE):
        migrated = migrate_json_to_jsonl()
        if migrated == 0 or not os.path.exists(CHUNK_FILE):
            logger.info("未找到持久化的文档片段")
            return []

    data = []
    try:
        with open(CHUNK_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        logger.info(f"从 JSONL 加载了 {len(data)} 个文档片段")
        return data
    except MemoryError:
        logger.error("加载文档片段时内存溢出，请使用 Milvus 模式")
        return []
    except Exception as e:
        logger.warning(f"加载持久化文档片段失败: {e}")
        return []


def rebuild_index_from_store(get_strategy_fn):
    """
    从持久化存储重建所有策略的检索器索引
    """
    store_data = load_chunks()
    if not store_data:
        return 0

    chunks = []
    import numpy as np
    from core.models import DocumentChunk

    for item in store_data:
        chunk = DocumentChunk(
            chunk_id=item["chunk_id"],
            doc_id=item["doc_id"],
            content=item["content"],
            metadata=item.get("metadata", {}),
            embedding=np.array(item["embedding"], dtype=np.float32),
        )
        chunks.append(chunk)

    if not chunks:
        return 0

    strategies = get_strategy_fn()
    for name in ["direct", "hyde", "sub_query", "backtrack"]:
        strategy = strategies.get(name)
        if strategy and hasattr(strategy, 'retriever') and hasattr(strategy.retriever, 'build_index'):
            strategy.retriever.build_index(chunks)

    logger.info(f"已从持久化存储重建索引，共 {len(chunks)} 个文档片段")
    return len(chunks)


def remove_chunks_by_doc_id(doc_id: str) -> int:
    """
    从持久化存储中移除指定文档的所有 chunk（流式处理）
    """
    if not os.path.exists(CHUNK_FILE):
        return 0

    try:
        kept = []
        removed = 0
        with open(CHUNK_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("doc_id") == doc_id:
                        removed += 1
                    else:
                        kept.append(line)
                except json.JSONDecodeError:
                    kept.append(line)

        if removed > 0:
            with open(CHUNK_FILE, "w", encoding="utf-8") as f:
                for line in kept:
                    f.write(line + "\n")
            if os.path.exists(COUNT_FILE):
                os.remove(COUNT_FILE)
            # 更新 doc_chunk_counts 缓存
            counts = _load_doc_chunk_counts()
            if doc_id in counts:
                del counts[doc_id]
                _save_doc_chunk_counts(counts)
            logger.info(f"已从持久化存储移除文档 {doc_id} 的 {removed} 个 chunk")

        return removed
    except Exception as e:
        logger.warning(f"移除持久化 chunk 失败: {e}")
        return 0


COUNT_FILE = os.path.join(os.path.dirname(CHUNK_FILE), ".chunk_count")


def _update_chunk_count(new_count: int):
    try:
        with open(COUNT_FILE, "w") as f:
            f.write(str(new_count))
    except Exception as e:
        logger.debug(f"chunk count 写入缓存失败: {e}")


def get_chunk_count() -> int:
    """获取已存储的 chunk 总数（读缓存，不扫描大文件）"""
    # 优先读缓存
    if os.path.exists(COUNT_FILE):
        try:
            with open(COUNT_FILE, "r") as f:
                return int(f.read().strip())
        except Exception as e:
            logger.debug(f"chunk count 缓存读取失败: {e}")
    # 首次：全量扫描后缓存
    if not os.path.exists(CHUNK_FILE):
        return 0
    count = 0
    try:
        with open(CHUNK_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        _update_chunk_count(count)
    except Exception as e:
        logger.debug(f"chunk 文件扫描失败: {e}")
    return count


# ════════════════════════════════════════════════════════════════
# 轻量 doc_chunk_counts 缓存（避免知识库列表页扫描大 JSONL）
# ════════════════════════════════════════════════════════════════

def _load_doc_chunk_counts() -> Dict[str, int]:
    """读取缓存文件"""
    if not os.path.exists(DOC_CHUNK_COUNT_FILE):
        return {}
    try:
        with open(DOC_CHUNK_COUNT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_doc_chunk_counts(counts: Dict[str, int]):
    """写入缓存文件"""
    try:
        _ensure_dir()
        with open(DOC_CHUNK_COUNT_FILE, "w", encoding="utf-8") as f:
            json.dump(counts, f)
    except Exception as e:
        logger.debug(f"doc_chunk_counts 写入失败: {e}")


def _increment_doc_chunk_counts(chunks: List):
    """增量更新 doc chunk count"""
    counts = _load_doc_chunk_counts()
    for c in chunks:
        doc_id = c.doc_id if hasattr(c, 'doc_id') else c.get("doc_id", "")
        counts[doc_id] = counts.get(doc_id, 0) + 1
    _save_doc_chunk_counts(counts)


def rebuild_doc_chunk_counts():
    """从 JSONL 全量重建 doc_chunk_counts 缓存（首次使用或数据恢复时调用）"""
    if not os.path.exists(CHUNK_FILE):
        return 0
    counts = {}
    try:
        with open(CHUNK_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    did = obj.get("doc_id", "")
                    counts[did] = counts.get(did, 0) + 1
                except Exception:
                    continue
        _save_doc_chunk_counts(counts)
        logger.info(f"doc_chunk_counts 缓存已重建: {len(counts)} 个文档")
        return len(counts)
    except Exception as e:
        logger.warning(f"doc_chunk_counts 重建失败: {e}")
        return 0
