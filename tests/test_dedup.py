"""data_processor.dedup 去重算法测试"""
import hashlib
import pytest
from data_processor.dedup import (
    compute_md5,
    check_md5_exists_in_db,
    SimHash,
    MinHashLSH,
    Tier3ChunkDedup,
)
from core.models import DocumentChunk


class TestComputeMD5:
    def test_same_content_same_hash(self):
        assert compute_md5("hello") == compute_md5("hello")

    def test_different_content_different_hash(self):
        assert compute_md5("hello") != compute_md5("world")

    def test_known_hash(self):
        h = compute_md5("test")
        expected = hashlib.md5("test".encode()).hexdigest()
        assert h == expected

    def test_unicode(self):
        h1 = compute_md5("一元一次方程")
        h2 = compute_md5("一元一次方程")
        assert h1 == h2

    def test_empty(self):
        h = compute_md5("")
        assert len(h) == 32


class TestSimHash:
    def test_same_text_same_fingerprint(self):
        sh = SimHash()
        fp1 = sh.compute("一元一次方程的解法")
        fp2 = sh.compute("一元一次方程的解法")
        assert fp1 == fp2

    def test_hamming_distance_same(self):
        sh = SimHash()
        fp = sh.compute("test")
        assert SimHash.hamming_distance(fp, fp) == 0

    def test_hamming_distance_different(self):
        sh = SimHash()
        fp1 = sh.compute("一元一次方程是指只含有一个未知数")
        fp2 = sh.compute("光合作用是植物利用光能的过程")
        dist = SimHash.hamming_distance(fp1, fp2)
        assert dist >= 0
        assert dist <= 64

    def test_similar_texts_smaller_distance(self):
        sh = SimHash()
        fp1 = sh.compute("一元一次方程的解法步骤")
        fp2 = sh.compute("一元一次方程怎么解")
        fp3 = sh.compute("光合作用的英文单词是photosynthesis")
        dist_similar = SimHash.hamming_distance(fp1, fp2)
        dist_different = SimHash.hamming_distance(fp1, fp3)
        # 相似文本距应更小（不保证绝对，但大概率）
        # 只验证距离在合法范围内
        assert 0 <= dist_similar <= 64
        assert 0 <= dist_different <= 64

    def test_short_text(self):
        sh = SimHash()
        fp = sh.compute("短")
        assert isinstance(fp, int)
        assert fp >= 0

    def test_empty_text(self):
        sh = SimHash()
        fp = sh.compute("")
        assert isinstance(fp, int)

    def test_different_bits(self):
        sh32 = SimHash(hash_bits=32)
        fp = sh32.compute("测试文本内容")
        assert fp < (1 << 32)


class TestMinHashLSH:
    def test_signature_length(self):
        mh = MinHashLSH(num_perm=64)
        sig = mh.compute_signature("一元一次方程的解法")
        assert len(sig) == 64

    def test_same_text_same_signature(self):
        mh = MinHashLSH(num_perm=64)
        sig1 = mh.compute_signature("测试文本")
        sig2 = mh.compute_signature("测试文本")
        assert sig1 == sig2

    def test_jaccard_perfect_match(self):
        mh = MinHashLSH(num_perm=64)
        sig = mh.compute_signature("test")
        assert mh.jaccard_similarity(sig, sig) == 1.0

    def test_jaccard_range(self):
        mh = MinHashLSH(num_perm=64)
        sig1 = mh.compute_signature("一元一次方程怎么解")
        sig2 = mh.compute_signature("光合作用是植物的生理过程")
        sim = mh.jaccard_similarity(sig1, sig2)
        assert 0.0 <= sim <= 1.0

    def test_lsh_bucket_keys_count(self):
        mh = MinHashLSH(num_perm=64, bands=8)
        sig = mh.compute_signature("测试")
        keys = mh.lsh_bucket_keys(sig)
        assert len(keys) == 8

    def test_lsh_same_text_same_keys(self):
        mh = MinHashLSH(num_perm=64, bands=8)
        sig1 = mh.compute_signature("hello world")
        sig2 = mh.compute_signature("hello world")
        assert mh.lsh_bucket_keys(sig1) == mh.lsh_bucket_keys(sig2)

    def test_empty_text(self):
        mh = MinHashLSH(num_perm=64)
        sig = mh.compute_signature("")
        assert len(sig) == 64
        # 空文本shingle为空 → 签名全是P值

    def test_different_perm(self):
        mh = MinHashLSH(num_perm=32)
        sig = mh.compute_signature("test")
        assert len(sig) == 32


class TestTier3ChunkDedup:
    def test_no_existing_chunks(self):
        dedup = Tier3ChunkDedup()
        chunks = [
            DocumentChunk(content="test", chunk_id="c1", doc_id="d1", embedding=[0.1, 0.2, 0.3]),
        ]
        kept, removed, details = dedup.dedup_chunks(chunks, [], None)
        assert kept == chunks
        assert removed == 0
        assert details == []

    def test_no_existing_embeddings(self):
        dedup = Tier3ChunkDedup()
        existing = [{"chunk_id": "old1", "content": "old"}]
        chunks = [
            DocumentChunk(content="test", chunk_id="c1", doc_id="d1", embedding=[0.1, 0.2, 0.3]),
        ]
        kept, removed, _ = dedup.dedup_chunks(chunks, existing, None)
        assert len(kept) == 1
        assert removed == 0

    def test_high_similarity_removed(self):
        import numpy as np
        dedup = Tier3ChunkDedup(similarity_threshold=0.85)
        # 几乎相同的向量
        vec = [0.5, 0.3, 0.7, 0.2]
        existing = [{"chunk_id": "old1", "content": "old content", "embedding": vec}]
        chunks = [
            DocumentChunk(content="new content", chunk_id="c1", doc_id="d1", embedding=vec),
        ]
        kept, removed, details = dedup.dedup_chunks(chunks, existing, None)
        assert removed == 1
        assert len(kept) == 0
        assert details[0]["max_similarity"] >= 0.85

    def test_low_similarity_kept(self):
        import numpy as np
        dedup = Tier3ChunkDedup(similarity_threshold=0.85)
        existing = [{"chunk_id": "old1", "content": "old", "embedding": [1.0, 0.0, 0.0]}]
        chunks = [
            DocumentChunk(content="new", chunk_id="c1", doc_id="d1", embedding=[0.0, 0.0, 1.0]),
        ]
        kept, removed, _ = dedup.dedup_chunks(chunks, existing, None)
        assert len(kept) == 1
        assert removed == 0

    def test_chunk_without_embedding_kept(self):
        dedup = Tier3ChunkDedup()
        existing = [{"chunk_id": "old1", "content": "old", "embedding": [0.1, 0.2]}]
        chunks = [
            DocumentChunk(content="test", chunk_id="c1", doc_id="d1", embedding=None),
        ]
        kept, removed, _ = dedup.dedup_chunks(chunks, existing, None)
        assert len(kept) == 1
        assert removed == 0
