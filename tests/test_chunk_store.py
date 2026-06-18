"""database.chunk_store JSONL持久化存储测试"""
import json
import os
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from core.models import DocumentChunk


def make_chunk(chunk_id, doc_id="d1", content="test content", embedding=None):
    if embedding is None:
        embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    return DocumentChunk(
        chunk_id=chunk_id, doc_id=doc_id, content=content,
        metadata={"source_type": "text"}, embedding=embedding,
    )


def write_jsonl(path, objects):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for obj in objects:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def write_legacy_json(path, objects):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(objects, f, ensure_ascii=False)


class TestMigrateJSONToJSONL:
    def test_jsonl_exists_returns_0(self, tmp_path, monkeypatch):
        from database import chunk_store as cs
        monkeypatch.setattr(cs, "CHUNK_FILE", str(tmp_path / "chunks.jsonl"))
        monkeypatch.setattr(cs, "CHUNK_FILE_LEGACY", str(tmp_path / "chunks.json"))
        write_jsonl(cs.CHUNK_FILE, [{"chunk_id": "c1"}])
        assert cs.migrate_json_to_jsonl() == 0

    def test_no_files_returns_0(self, tmp_path, monkeypatch):
        from database import chunk_store as cs
        monkeypatch.setattr(cs, "CHUNK_FILE", str(tmp_path / "nonexistent.jsonl"))
        monkeypatch.setattr(cs, "CHUNK_FILE_LEGACY", str(tmp_path / "nonexistent.json"))
        assert cs.migrate_json_to_jsonl() == 0

    def test_migrate_legacy_to_jsonl(self, tmp_path, monkeypatch):
        from database import chunk_store as cs
        jsonl_path = str(tmp_path / "chunks.jsonl")
        legacy_path = str(tmp_path / "chunks.json")
        monkeypatch.setattr(cs, "CHUNK_FILE", jsonl_path)
        monkeypatch.setattr(cs, "CHUNK_FILE_LEGACY", legacy_path)

        legacy_data = [
            {"chunk_id": "c1", "content": "hello"},
            {"chunk_id": "c2", "content": "world"},
        ]
        write_legacy_json(legacy_path, legacy_data)

        count = cs.migrate_json_to_jsonl()
        assert count == 2
        assert os.path.exists(jsonl_path)

        # 验证 JSONL 内容
        with open(jsonl_path, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == 2


class TestSaveChunks:
    def test_save_new_chunks(self, tmp_path, monkeypatch):
        from database import chunk_store as cs
        jsonl_path = str(tmp_path / "chunks.jsonl")
        count_path = str(tmp_path / ".chunk_count")
        doc_count_path = str(tmp_path / "doc_chunk_counts.json")
        monkeypatch.setattr(cs, "CHUNK_FILE", jsonl_path)
        monkeypatch.setattr(cs, "COUNT_FILE", count_path)
        monkeypatch.setattr(cs, "DOC_CHUNK_COUNT_FILE", doc_count_path)

        chunks = [make_chunk("c1"), make_chunk("c2")]
        result = cs.save_chunks(chunks)
        assert result is True
        assert os.path.exists(jsonl_path)

    def test_save_skips_duplicate_ids(self, tmp_path, monkeypatch):
        from database import chunk_store as cs
        jsonl_path = str(tmp_path / "chunks.jsonl")
        monkeypatch.setattr(cs, "CHUNK_FILE", jsonl_path)
        monkeypatch.setattr(cs, "COUNT_FILE", str(tmp_path / ".chunk_count"))
        monkeypatch.setattr(cs, "DOC_CHUNK_COUNT_FILE", str(tmp_path / "doc_chunk_counts.json"))

        # 预存一个 chunk
        write_jsonl(jsonl_path, [{"chunk_id": "c1", "doc_id": "d1", "content": "old",
                                   "metadata": {}, "embedding": [0.1]}])

        chunks = [make_chunk("c1"), make_chunk("c2")]
        cs.save_chunks(chunks)

        with open(jsonl_path, "r", encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == 2  # c1 不重复写入

    def test_save_empty_file(self, tmp_path, monkeypatch):
        from database import chunk_store as cs
        jsonl_path = str(tmp_path / "chunks.jsonl")
        monkeypatch.setattr(cs, "CHUNK_FILE", jsonl_path)
        monkeypatch.setattr(cs, "COUNT_FILE", str(tmp_path / ".chunk_count"))
        monkeypatch.setattr(cs, "DOC_CHUNK_COUNT_FILE", str(tmp_path / "doc_chunk_counts.json"))

        chunks = [make_chunk("c1")]
        result = cs.save_chunks(chunks)
        assert result is True


class TestSaveChunksBatch:
    def test_batch_no_dedup(self, tmp_path, monkeypatch):
        from database import chunk_store as cs
        jsonl_path = str(tmp_path / "chunks.jsonl")
        monkeypatch.setattr(cs, "CHUNK_FILE", jsonl_path)
        monkeypatch.setattr(cs, "COUNT_FILE", str(tmp_path / ".chunk_count"))
        monkeypatch.setattr(cs, "DOC_CHUNK_COUNT_FILE", str(tmp_path / "doc_chunk_counts.json"))

        chunks = [make_chunk("c1"), make_chunk("c1")]  # 重复 ID 不检查
        result = cs.save_chunks_batch(chunks)
        assert result is True


class TestLoadChunks:
    def test_load_from_jsonl(self, tmp_path, monkeypatch):
        import sys
        from database import chunk_store as cs
        jsonl_path = str(tmp_path / "chunks.jsonl")
        monkeypatch.setattr(cs, "CHUNK_FILE", jsonl_path)
        monkeypatch.setattr(cs, "CHUNK_FILE_LEGACY", str(tmp_path / "nonexistent.json"))

        write_jsonl(jsonl_path, [
            {"chunk_id": "c1", "doc_id": "d1", "content": "hello", "metadata": {}, "embedding": [0.1]},
        ])

        # MilvusDB 是 load_chunks 内部的 local import，需要 mock pymilvus
        mock_pymilvus = MagicMock()
        mock_pymilvus.connections.connect.side_effect = Exception("no milvus")
        sys.modules["pymilvus"] = mock_pymilvus
        try:
            data = cs.load_chunks()
            assert len(data) == 1
            assert data[0]["chunk_id"] == "c1"
        finally:
            sys.modules.pop("pymilvus", None)

    def test_load_empty_file(self, tmp_path, monkeypatch):
        import sys
        from database import chunk_store as cs
        jsonl_path = str(tmp_path / "chunks.jsonl")
        monkeypatch.setattr(cs, "CHUNK_FILE", jsonl_path)
        monkeypatch.setattr(cs, "CHUNK_FILE_LEGACY", str(tmp_path / "nonexistent.json"))

        # 阻止 Milvus 连接
        mock_pymilvus = MagicMock()
        mock_pymilvus.connections.connect.side_effect = Exception("no milvus")
        sys.modules["pymilvus"] = mock_pymilvus
        try:
            assert cs.load_chunks() == []
        finally:
            sys.modules.pop("pymilvus", None)

    def test_load_from_milvus(self, tmp_path, monkeypatch):
        import sys
        from database import chunk_store as cs
        jsonl_path = str(tmp_path / "chunks.jsonl")
        monkeypatch.setattr(cs, "CHUNK_FILE", jsonl_path)

        mock_pymilvus = MagicMock()
        mock_collection = MagicMock()
        mock_collection.num_entities = 1
        mock_collection.query.return_value = [
            {"id": "c1", "doc_id": "d1", "content": "hello", "metadata": {}},
        ]
        mock_pymilvus.Collection.return_value = mock_collection
        sys.modules["pymilvus"] = mock_pymilvus
        try:
            data = cs.load_chunks()
            assert len(data) == 1
            assert data[0]["chunk_id"] == "c1"
        finally:
            sys.modules.pop("pymilvus", None)


class TestLoadChunkIds:
    def test_load_ids(self, tmp_path, monkeypatch):
        from database import chunk_store as cs
        jsonl_path = str(tmp_path / "chunks.jsonl")
        monkeypatch.setattr(cs, "CHUNK_FILE", jsonl_path)

        write_jsonl(jsonl_path, [
            {"chunk_id": "c1"}, {"chunk_id": "c2"}, {"chunk_id": "c3"},
        ])
        ids = cs.load_chunk_ids()
        assert ids == {"c1", "c2", "c3"}

    def test_load_ids_empty(self, tmp_path, monkeypatch):
        from database import chunk_store as cs
        monkeypatch.setattr(cs, "CHUNK_FILE", str(tmp_path / "nonexistent.jsonl"))
        ids = cs.load_chunk_ids()
        assert ids == set()


class TestLoadChunkIdsBySource:
    def test_filter_by_source_type(self, tmp_path, monkeypatch):
        from database import chunk_store as cs
        jsonl_path = str(tmp_path / "chunks.jsonl")
        monkeypatch.setattr(cs, "CHUNK_FILE", jsonl_path)

        write_jsonl(jsonl_path, [
            {"chunk_id": "c1", "metadata": {"source_type": "text"}},
            {"chunk_id": "c2", "metadata": {"source_type": "image"}},
            {"chunk_id": "c3", "metadata": {"source_type": "text"}},
        ])
        ids = cs.load_chunk_ids_by_source("text")
        assert ids == {"c1", "c3"}


class TestRemoveChunksByDocId:
    def test_remove_existing(self, tmp_path, monkeypatch):
        from database import chunk_store as cs
        jsonl_path = str(tmp_path / "chunks.jsonl")
        monkeypatch.setattr(cs, "CHUNK_FILE", jsonl_path)
        monkeypatch.setattr(cs, "COUNT_FILE", str(tmp_path / ".chunk_count"))
        monkeypatch.setattr(cs, "DOC_CHUNK_COUNT_FILE", str(tmp_path / "doc_chunk_counts.json"))

        write_jsonl(jsonl_path, [
            {"chunk_id": "c1", "doc_id": "d1"},
            {"chunk_id": "c2", "doc_id": "d2"},
            {"chunk_id": "c3", "doc_id": "d1"},
        ])
        removed = cs.remove_chunks_by_doc_id("d1")
        assert removed == 2

        # 验证只剩 d2
        with open(jsonl_path, "r", encoding="utf-8") as f:
            remaining = [json.loads(line) for line in f if line.strip()]
        assert len(remaining) == 1
        assert remaining[0]["doc_id"] == "d2"

    def test_remove_nonexistent(self, tmp_path, monkeypatch):
        from database import chunk_store as cs
        jsonl_path = str(tmp_path / "chunks.jsonl")
        monkeypatch.setattr(cs, "CHUNK_FILE", jsonl_path)
        monkeypatch.setattr(cs, "COUNT_FILE", str(tmp_path / ".chunk_count"))
        monkeypatch.setattr(cs, "DOC_CHUNK_COUNT_FILE", str(tmp_path / "doc_chunk_counts.json"))

        write_jsonl(jsonl_path, [{"chunk_id": "c1", "doc_id": "d1"}])
        removed = cs.remove_chunks_by_doc_id("d_nonexistent")
        assert removed == 0

    def test_remove_from_nonexistent_file(self, tmp_path, monkeypatch):
        from database import chunk_store as cs
        monkeypatch.setattr(cs, "CHUNK_FILE", str(tmp_path / "nonexistent.jsonl"))
        assert cs.remove_chunks_by_doc_id("d1") == 0


class TestGetChunkCount:
    def test_from_cache(self, tmp_path, monkeypatch):
        from database import chunk_store as cs
        count_path = str(tmp_path / ".chunk_count")
        monkeypatch.setattr(cs, "COUNT_FILE", count_path)
        monkeypatch.setattr(cs, "CHUNK_FILE", str(tmp_path / "chunks.jsonl"))

        with open(count_path, "w") as f:
            f.write("42")
        assert cs.get_chunk_count() == 42

    def test_from_scan(self, tmp_path, monkeypatch):
        from database import chunk_store as cs
        jsonl_path = str(tmp_path / "chunks.jsonl")
        count_path = str(tmp_path / ".chunk_count")
        monkeypatch.setattr(cs, "CHUNK_FILE", jsonl_path)
        monkeypatch.setattr(cs, "COUNT_FILE", count_path)

        write_jsonl(jsonl_path, [{"c": i} for i in range(5)])
        assert cs.get_chunk_count() == 5

    def test_empty_file(self, tmp_path, monkeypatch):
        from database import chunk_store as cs
        monkeypatch.setattr(cs, "CHUNK_FILE", str(tmp_path / "nonexistent.jsonl"))
        monkeypatch.setattr(cs, "COUNT_FILE", str(tmp_path / ".nonexistent"))
        assert cs.get_chunk_count() == 0


class TestDocChunkCounts:
    def test_rebuild(self, tmp_path, monkeypatch):
        from database import chunk_store as cs
        jsonl_path = str(tmp_path / "chunks.jsonl")
        doc_count_path = str(tmp_path / "doc_chunk_counts.json")
        monkeypatch.setattr(cs, "CHUNK_FILE", jsonl_path)
        monkeypatch.setattr(cs, "DOC_CHUNK_COUNT_FILE", doc_count_path)

        write_jsonl(jsonl_path, [
            {"doc_id": "d1"}, {"doc_id": "d1"}, {"doc_id": "d2"},
        ])
        n = cs.rebuild_doc_chunk_counts()
        assert n == 2
        with open(doc_count_path) as f:
            counts = json.load(f)
        assert counts["d1"] == 2
        assert counts["d2"] == 1

    def test_rebuild_empty(self, tmp_path, monkeypatch):
        from database import chunk_store as cs
        monkeypatch.setattr(cs, "CHUNK_FILE", str(tmp_path / "nonexistent.jsonl"))
        monkeypatch.setattr(cs, "DOC_CHUNK_COUNT_FILE", str(tmp_path / "counts.json"))
        assert cs.rebuild_doc_chunk_counts() == 0
