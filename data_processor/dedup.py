"""
三层递进式文档去重模块

第一层：文本层硬去重 MD5  — 精确匹配，O(1) 哈希查重
第二层：文本层软去重 SimHash + MinHash LSH  — 近似文档检测
第三层：向量层 Chunk 去重  — 基于嵌入向量的片段级去重（相似度 ≥ 85% → 重复）
"""
import hashlib
import re
import struct
import threading
from typing import List, Dict, Tuple, Optional, Set
from collections import defaultdict

from core.logger import get_logger
from core.models import Document, DocumentChunk

logger = get_logger("dedup")


# ════════════════════════════════════════════════════════════════
# 第一层：MD5 硬去重
# ════════════════════════════════════════════════════════════════

def compute_md5(content: str) -> str:
    """计算文本内容的 MD5 哈希"""
    return hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()


def check_md5_exists_in_db(md5_hash: str, mysql_db) -> Optional[Dict]:
    """查询数据库中是否已有相同 MD5 的文档"""
    try:
        row = mysql_db.query_one(
            "SELECT id, title, source, created_at FROM documents WHERE md5_hash = %s LIMIT 1",
            (md5_hash,)
        )
        return row
    except Exception as e:
        logger.warning(f"MD5 查重查询失败: {e}")
        return None


# ════════════════════════════════════════════════════════════════
# 第二层：SimHash + MinHash LSH 软去重
# ════════════════════════════════════════════════════════════════

class SimHash:
    """
    SimHash 指纹算法

    原理：
    1. 将文档分词/提取 n-gram 特征
    2. 对每个特征计算 hash，映射到固定长度向量
    3. 加权求和后二值化，得到指纹
    4. 两个指纹的汉明距离 ≤ 3 视为相似
    """

    def __init__(self, hash_bits: int = 64):
        self.hash_bits = hash_bits

    def _tokenize(self, text: str, n: int = 3) -> List[str]:
        """提取字符级 n-gram 作为特征"""
        text = re.sub(r'\s+', ' ', text)
        if len(text) < n:
            return [text]
        return [text[i:i + n] for i in range(len(text) - n + 1)]

    def _hash(self, token: str) -> int:
        """将 token 哈希为整数"""
        if self.hash_bits == 64:
            return struct.unpack(">Q", hashlib.sha256(token.encode()).digest()[:8])[0]
        else:
            return struct.unpack(">I", hashlib.sha256(token.encode()).digest()[:4])[0]

    def compute(self, text: str) -> int:
        """计算文本的 SimHash 指纹"""
        tokens = self._tokenize(text)
        # 使用 TF 作为权重
        tf = defaultdict(int)
        for t in tokens:
            tf[t] += 1

        # 初始化向量
        v = [0] * self.hash_bits

        for token, weight in tf.items():
            h = self._hash(token)
            for i in range(self.hash_bits):
                if (h >> i) & 1:
                    v[i] += weight
                else:
                    v[i] -= weight

        # 二值化
        fingerprint = 0
        for i in range(self.hash_bits):
            if v[i] > 0:
                fingerprint |= (1 << i)

        return fingerprint

    @staticmethod
    def hamming_distance(a: int, b: int, bits: int = 64) -> int:
        """计算两个 SimHash 指纹的汉明距离"""
        x = a ^ b
        return x.bit_count()


class MinHashLSH:
    """
    MinHash + LSH 近似文档检测

    原理：
    1. 将文档表示为 n-gram 集合
    2. 使用多个哈希函数计算 MinHash 签名
    3. 使用 LSH 分桶，快速筛选候选相似对
    4. 对候选对计算 Jaccard 相似度
    """

    def __init__(self, num_perm: int = 128, threshold: float = 0.5, bands: int = None):
        """
        Args:
            num_perm: MinHash 排列数（签名长度），越大越精确
            threshold: Jaccard 相似度阈值
            bands: LSH 分桶的 band 数
        """
        self.num_perm = num_perm
        self.threshold = threshold
        self.bands = bands or max(1, num_perm // 16)
        self.rows_per_band = num_perm // self.bands

        # 预生成哈希函数参数 (a*x + b) mod p
        import random
        self.P = (1 << 61) - 1  # 大质数 Mersenne prime
        random.seed(42)
        self.hash_params = [(random.randint(1, self.P - 1), random.randint(0, self.P - 1))
                            for _ in range(num_perm)]

    def _shingle(self, text: str, n: int = 3) -> Set[str]:
        """将文本转换为 n-gram 集合"""
        # 对中文使用字符级, 对英文使用 word-level（混合处理）
        text = re.sub(r'\s+', ' ', text)
        tokens = []
        # 简单分词：中文字符作为独立 token，英文单词保持
        for part in re.findall(r'[\u4e00-\u9fff]|[a-zA-Z]+|\d+', text):
            tokens.append(part)
        text_for_ngram = ''.join(tokens)
        if len(text_for_ngram) < n:
            return {text_for_ngram} if text_for_ngram else set()
        return {text_for_ngram[i:i + n] for i in range(len(text_for_ngram) - n + 1)}

    def _hash_shingle(self, shingle: str, a: int, b: int) -> int:
        """对单个 shingle 计算哈希"""
        h = hashlib.sha256(shingle.encode()).digest()
        val = int.from_bytes(h[:8], 'big')
        return (a * val + b) % self.P

    def compute_signature(self, text: str) -> List[int]:
        """计算文本的 MinHash 签名"""
        shingles = self._shingle(text)
        if not shingles:
            return [self.P] * self.num_perm

        signature = []
        for a, b in self.hash_params:
            min_hash = min(self._hash_shingle(s, a, b) for s in shingles)
            signature.append(min_hash)

        return signature

    def jaccard_similarity(self, sig1: List[int], sig2: List[int]) -> float:
        """通过 MinHash 签名估算 Jaccard 相似度"""
        matches = sum(1 for a, b in zip(sig1, sig2) if a == b)
        return matches / len(sig1)

    def lsh_bucket_keys(self, signature: List[int]) -> List[str]:
        """将 MinHash 签名映射到 LSH bucket key"""
        keys = []
        for b in range(self.bands):
            start = b * self.rows_per_band
            band_sig = signature[start:start + self.rows_per_band]
            band_hash = hashlib.md5(
                ','.join(str(x) for x in band_sig).encode()
            ).hexdigest()[:16]
            keys.append(f"band_{b}_{band_hash}")
        return keys


# ── 模块级 Tier2 索引缓存（单例，避免每次请求重建）──
_tier2_simhash_index: Dict[str, int] = {}
_tier2_lsh_index: Dict[str, List[str]] = {}
_tier2_minhash_signatures: Dict[str, List[int]] = {}
_tier2_loaded = False
_tier2_lock = threading.Lock()


class Tier2SoftDedup:
    """
    第二层去重：SimHash + MinHash LSH 联合

    流程：
    1. 用 MinHash LSH 快速筛选候选集（从已有文档中）
    2. 对候选集用 SimHash 精确计算相似度（汉明距离）
    3. 汉明距离 ≤ 3 → 判定为近似重复

    索引为模块级单例，首次加载后缓存复用。
    """

    def __init__(self, minhash_perm: int = 128, simhash_bits: int = 64,
                 lsh_threshold: float = 0.5, simhash_hamming_threshold: int = 10):
        self.minhash = MinHashLSH(num_perm=minhash_perm, threshold=lsh_threshold)
        self.simhash = SimHash(hash_bits=simhash_bits)
        self.hamming_threshold = simhash_hamming_threshold

    @staticmethod
    def _load_existing(mysql_db):
        """从数据库加载已有文档，建立模块级索引（仅首次调用时执行）"""
        global _tier2_loaded
        if _tier2_loaded:
            return
        with _tier2_lock:
            if _tier2_loaded:
                return
            Tier2SoftDedup._do_load(mysql_db)
            _tier2_loaded = True

    @staticmethod
    def _do_load(mysql_db):
        global _tier2_simhash_index, _tier2_lsh_index, _tier2_minhash_signatures
        try:
            rows = mysql_db.query("SELECT id, content, md5_hash FROM documents WHERE content IS NOT NULL")
            logger.info(f"加载已有文档索引: {len(rows)} 篇（仅首次）")
            inst = Tier2SoftDedup()
            for row in rows:
                doc_id = row["id"]
                content = row.get("content", "")
                if not content:
                    continue
                fp = inst.simhash.compute(content)
                sig = inst.minhash.compute_signature(content)
                keys = inst.minhash.lsh_bucket_keys(sig)
                _tier2_simhash_index[doc_id] = fp
                _tier2_minhash_signatures[doc_id] = sig
                for key in keys:
                    if key not in _tier2_lsh_index:
                        _tier2_lsh_index[key] = []
                    _tier2_lsh_index[key].append(doc_id)
        except Exception as e:
            logger.warning(f"加载已有文档索引失败: {e}")

    def add_to_index(self, doc_id: str, content: str):
        """将文档加入索引（同时更新模块级缓存）"""
        global _tier2_simhash_index, _tier2_lsh_index, _tier2_minhash_signatures
        fp = self.simhash.compute(content)
        sig = self.minhash.compute_signature(content)
        keys = self.minhash.lsh_bucket_keys(sig)

        _tier2_simhash_index[doc_id] = fp
        _tier2_minhash_signatures[doc_id] = sig
        for key in keys:
            if key not in _tier2_lsh_index:
                _tier2_lsh_index[key] = []
            if doc_id not in _tier2_lsh_index[key]:
                _tier2_lsh_index[key].append(doc_id)

    def is_duplicate(self, content: str) -> Tuple[bool, Optional[str], float]:
        """
        检测文本是否为重复

        Returns:
            (is_dup, matched_doc_id, confidence)
        """
        if not _tier2_simhash_index:
            return False, None, 0.0

        fp = self.simhash.compute(content)
        sig = self.minhash.compute_signature(content)
        bucket_keys = self.minhash.lsh_bucket_keys(sig)

        # 步骤 1：LSH 快速筛选候选集
        candidates: Set[str] = set()
        for key in bucket_keys:
            doc_ids = _tier2_lsh_index.get(key, [])
            candidates.update(doc_ids)

        if not candidates:
            return False, None, 0.0

        # 步骤 2：SimHash 精确比对
        best_match = None
        best_distance = self.hamming_threshold + 1

        for doc_id in candidates:
            existing_fp = _tier2_simhash_index.get(doc_id)
            if existing_fp is None:
                continue
            distance = SimHash.hamming_distance(fp, existing_fp, self.simhash.hash_bits)
            if distance < best_distance:
                best_distance = distance
                best_match = doc_id

        if best_distance <= self.hamming_threshold:
            confidence = 1.0 - (best_distance / self.simhash.hash_bits)
            return True, best_match, confidence

        return False, None, 0.0


# ════════════════════════════════════════════════════════════════
# 第三层：向量层 Chunk 去重
# ════════════════════════════════════════════════════════════════

class Tier3ChunkDedup:
    """
    第三层去重：基于嵌入向量的 Chunk 级去重

    流程：
    1. 将文档切块后向量化
    2. 对每个 chunk 向量，在已有 chunk 向量库中检索 Top-K 最相似
    3. 若最高相似度 ≥ 85% → 判定为重复片段，仅保留一条
    """

    def __init__(self, similarity_threshold: float = 0.85, top_k: int = 5):
        self.threshold = similarity_threshold
        self.top_k = top_k

    def dedup_chunks(self, new_chunks: List[DocumentChunk],
                     existing_chunks: List[Dict],
                     vectorizer) -> Tuple[List[DocumentChunk], int, List[Dict]]:
        """
        对新 chunk 列表去重

        Args:
            new_chunks: 新文档的 chunk 列表（已向量化）
            existing_chunks: 已有 chunk 列表（from chunk_store）
            vectorizer: Vectorizer 实例

        Returns:
            (kept_chunks, removed_count, duplicate_details)
        """
        if not existing_chunks:
            return new_chunks, 0, []

        # 提取已有 chunk 的嵌入向量（从 chunk_store 中可能有 embedding 字段）
        existing_embeddings = []
        for c in existing_chunks:
            emb = c.get("embedding")
            if emb:
                existing_embeddings.append(emb)

        if not existing_embeddings:
            logger.info("已有 chunk 无嵌入向量，跳过向量层去重")
            return new_chunks, 0, []

        import numpy as np
        existing_matrix = np.array(existing_embeddings, dtype=np.float32)

        kept = []
        removed = 0
        details = []

        for chunk in new_chunks:
            if chunk.embedding is None:
                kept.append(chunk)
                continue

            # 计算当前 chunk 与所有已有 chunk 的余弦相似度
            chunk_vec = np.array(chunk.embedding, dtype=np.float32)
            # 归一化确保余弦相似度计算正确
            chunk_norm = np.linalg.norm(chunk_vec)
            existing_norms = np.linalg.norm(existing_matrix, axis=1)

            if chunk_norm == 0:
                kept.append(chunk)
                continue

            # 批量余弦相似度
            similarities = np.dot(existing_matrix, chunk_vec) / (existing_norms * chunk_norm + 1e-10)
            max_sim = float(np.max(similarities))

            if max_sim >= self.threshold:
                best_idx = int(np.argmax(similarities))
                removed += 1
                details.append({
                    "chunk_id": chunk.chunk_id,
                    "chunk_content_preview": chunk.content[:100],
                    "max_similarity": round(max_sim, 4),
                    "matched_chunk_id": existing_chunks[best_idx].get("chunk_id", ""),
                    "matched_content_preview": existing_chunks[best_idx].get("content", "")[:100],
                })
                logger.debug(f"chunk 去重: {chunk.chunk_id} 相似度 {max_sim:.4f} → 跳过")
            else:
                kept.append(chunk)

        if removed > 0:
            logger.info(f"向量层去重: {removed}/{len(new_chunks)} chunks 被过滤 (阈值={self.threshold})")

        return kept, removed, details


# ════════════════════════════════════════════════════════════════
# 统一去重管理器
# ════════════════════════════════════════════════════════════════

class DedupManager:
    """
    三层递进式去重管理器

    使用方式：
        manager = DedupManager(mysql_db)
        result = manager.dedup(content, filename)
        if result.is_duplicate:
            print(f"文档重复: {result.reason}")
    """

    def __init__(self, mysql_db, enable_tier1: bool = True,
                 enable_tier2: bool = True, enable_tier3: bool = True):
        self.mysql_db = mysql_db
        self.enable_tier1 = enable_tier1
        self.enable_tier2 = enable_tier2
        self.enable_tier3 = enable_tier3

        self._tier2 = Tier2SoftDedup() if enable_tier2 else None
        self._tier3 = Tier3ChunkDedup() if enable_tier3 else None

    def _ensure_tier2_index(self):
        """懒加载 Tier2 索引（模块级缓存，仅首次触发全量加载）"""
        if self._tier2 and not _tier2_loaded:
            Tier2SoftDedup._load_existing(self.mysql_db)

    class DedupResult:
        """去重结果"""
        def __init__(self):
            self.is_duplicate = False
            self.tier = 0              # 在哪一层被拦截
            self.reason = ""
            self.matched_doc_id = None
            self.matched_title = None
            self.confidence = 0.0
            self.md5_hash = ""
            self.filename = ""         # 原始文件名

        def to_dict(self) -> dict:
            return {
                "is_duplicate": self.is_duplicate,
                "tier": self.tier,
                "reason": self.reason,
                "matched_doc_id": self.matched_doc_id,
                "matched_title": self.matched_title,
                "confidence": self.confidence,
                "md5_hash": self.md5_hash,
                "filename": self.filename,
            }

    def check_document_duplicate(self, content: str, filename: str = "",
                                kb_id: str = None) -> DedupResult:
        """
        对整篇文档执行三层去重检测

        Args:
            content: 文档文本内容
            filename: 文件名（用于日志）
            kb_id: 目标知识库ID（提供后仅在KB范围内去重，允许同文件存入不同KB）

        Returns:
            DedupResult
        """
        result = self.DedupResult()
        md5 = compute_md5(content)
        result.md5_hash = md5
        result.filename = filename

        # ── 第一层：MD5 硬去重 ──
        if self.enable_tier1:
            if kb_id:
                existing = self.mysql_db.get_document_by_md5_in_kb(md5, kb_id)
                # 验证匹配文档在 documents 表中是否真实存在（排除孤立关联）
                if existing:
                    real_doc = self.mysql_db.get_document(existing["id"])
                    if not real_doc:
                        logger.info(f"[Tier1 MD5] 匹配文档 {existing['id']} 已不存在（孤立关联），允许重新上传")
                        existing = None
            else:
                existing = check_md5_exists_in_db(md5, self.mysql_db)
            if existing:
                result.is_duplicate = True
                result.tier = 1
                suffix = f"（KB内）" if kb_id else ""
                result.reason = f"MD5 完全匹配{suffix}（哈希: {md5[:12]}...）"
                result.matched_doc_id = existing["id"]
                result.matched_title = existing.get("title", "")
                result.confidence = 1.0
                logger.info(f"[Tier1 MD5] 文档重复: {filename} → 已有文档 {existing['title']}")
                return result

        # ── 第二层：SimHash + MinHash LSH ──
        if self.enable_tier2 and self._tier2:
            self._ensure_tier2_index()
            is_dup, matched_id, confidence = self._tier2.is_duplicate(content)
            if is_dup:
                # 指定 kb_id 时，仅在 KB 范围内判定重复
                if kb_id and matched_id:
                    kb_doc = self.mysql_db.get_document_by_md5_in_kb(
                        compute_md5(content), kb_id
                    )
                    if not kb_doc:
                        # 文档不在当前 KB 中，不算 KB 内重复
                        is_dup = False
                        logger.info(f"[Tier2 SimHash] 近似文档 {matched_id} 不在当前 KB，允许上传")
            if is_dup:
                result.is_duplicate = True
                result.tier = 2
                result.reason = f"SimHash 近似重复（汉明距离 ≤ {self._tier2.hamming_threshold}）"
                result.matched_doc_id = matched_id
                result.confidence = round(confidence, 4)
                try:
                    doc = self.mysql_db.get_document(matched_id)
                    result.matched_title = doc.get("title", "") if doc else ""
                except Exception as e:
                    logger.debug(f"重复文档标题获取失败: {e}")
                logger.info(f"[Tier2 SimHash] 近似重复: {filename} → 已有文档 {matched_id} (置信度: {confidence:.4f})")
                return result

        return result

    def dedup_chunks(self, new_chunks: List[DocumentChunk],
                     vectorizer) -> Tuple[List[DocumentChunk], int, List[Dict]]:
        """
        第三层：对 chunk 列表进行向量去重

        Returns:
            (kept_chunks, removed_count, duplicate_details)
        """
        if not self.enable_tier3 or not self._tier3:
            return new_chunks, 0, []

        try:
            from database.chunk_store import load_chunks
            existing = load_chunks()
            kept, removed, details = self._tier3.dedup_chunks(new_chunks, existing, vectorizer)
            return kept, removed, details
        except Exception as e:
            logger.warning(f"chunk 去重失败（已跳过）: {e}")
            return new_chunks, 0, []

    def add_document_to_index(self, doc_id: str, content: str):
        """文档入库后，将其加入 Tier2 索引"""
        if self._tier2:
            self._ensure_tier2_index()
            self._tier2.add_to_index(doc_id, content)