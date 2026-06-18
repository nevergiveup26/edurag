"""database.milvus_db Milvus向量数据库测试"""
import pytest
import numpy as np
from unittest.mock import MagicMock, patch


class TestMilvusDBInit:
    def test_default_init(self):
        from database.milvus_db import MilvusDB
        db = MilvusDB()
        assert db._client is None
        assert db.embedding_dim > 0


def _install_mock_pymilvus():
    """注入 mock pymilvus 模块"""
    import sys
    mock_pymilvus = MagicMock()
    mock_pymilvus.connections = MagicMock()
    mock_pymilvus.utility = MagicMock()
    mock_pymilvus.Collection = MagicMock()
    mock_pymilvus.CollectionSchema = MagicMock()
    mock_pymilvus.FieldSchema = MagicMock()
    mock_pymilvus.DataType = MagicMock()
    sys.modules["pymilvus"] = mock_pymilvus
    return mock_pymilvus


def _cleanup_pymilvus():
    import sys
    sys.modules.pop("pymilvus", None)


class TestConnect:
    def test_connect_success(self):
        try:
            mock_pymilvus = _install_mock_pymilvus()
            from database.milvus_db import MilvusDB
            db = MilvusDB()
            db.connect()
            assert db._client is not None
        finally:
            _cleanup_pymilvus()

    def test_connect_import_error(self):
        import sys
        from database.milvus_db import MilvusDB
        sys.modules["pymilvus"] = None
        try:
            db = MilvusDB()
            db.connect()
            assert db._client is None
        finally:
            sys.modules.pop("pymilvus", None)

    def test_connect_exception(self):
        try:
            mock_pymilvus = _install_mock_pymilvus()
            mock_pymilvus.connections.connect.side_effect = Exception("host unreachable")
            from database.milvus_db import MilvusDB
            db = MilvusDB()
            db.connect()
            assert db._client is None
        finally:
            _cleanup_pymilvus()


class TestCreateCollection:
    def test_no_client_skips(self):
        from database.milvus_db import MilvusDB
        db = MilvusDB()
        db._client = None
        db.create_collection()  # 不抛异常

    def test_collection_exists(self):
        try:
            mock_pymilvus = _install_mock_pymilvus()
            mock_pymilvus.utility.has_collection.return_value = True
            from database.milvus_db import MilvusDB
            db = MilvusDB()
            db._client = mock_pymilvus.utility
            db.create_collection()
            # 集合已存在，不创建
            mock_pymilvus.Collection.assert_not_called()
        finally:
            _cleanup_pymilvus()

    def test_create_new_collection(self):
        try:
            mock_pymilvus = _install_mock_pymilvus()
            mock_pymilvus.utility.has_collection.return_value = False
            mock_collection = MagicMock()
            mock_pymilvus.Collection.return_value = mock_collection

            from database.milvus_db import MilvusDB
            db = MilvusDB()
            db._client = mock_pymilvus.utility
            db.create_collection()

            mock_pymilvus.Collection.assert_called_once()
            mock_collection.create_index.assert_called_once()
            mock_collection.load.assert_called_once()
        finally:
            _cleanup_pymilvus()


class TestInsertVectors:
    def test_insert_success(self):
        try:
            mock_pymilvus = _install_mock_pymilvus()
            mock_collection = MagicMock()
            mock_pymilvus.Collection.return_value = mock_collection

            from database.milvus_db import MilvusDB
            db = MilvusDB()
            result = db.insert_vectors(
                ids=["c1", "c2"],
                embeddings=[[0.1, 0.2], [0.3, 0.4]],
                contents=["text1", "text2"],
                doc_ids=["d1", "d1"],
            )
            mock_collection.insert.assert_called_once()
        finally:
            _cleanup_pymilvus()


class TestSearch:
    def test_search_success(self):
        try:
            mock_pymilvus = _install_mock_pymilvus()
            mock_collection = MagicMock()
            mock_hit = MagicMock()
            mock_hit.entity.get.side_effect = lambda key: {
                "id": "c1", "content": "hello", "doc_id": "d1", "metadata": {}
            }.get(key)
            mock_hit.distance = 0.95
            mock_collection.search.return_value = [[mock_hit]]
            mock_pymilvus.Collection.return_value = mock_collection

            from database.milvus_db import MilvusDB
            db = MilvusDB()
            results = db.search([0.1, 0.2], top_k=3, filter_expr='doc_id == "d1"')
            assert len(results) == 1
            assert results[0]["id"] == "c1"
            assert results[0]["score"] == 0.95
        finally:
            _cleanup_pymilvus()

    def test_search_exception_returns_empty(self):
        try:
            mock_pymilvus = _install_mock_pymilvus()
            mock_collection = MagicMock()
            mock_collection.search.side_effect = Exception("search failed")
            mock_pymilvus.Collection.return_value = mock_collection

            from database.milvus_db import MilvusDB
            db = MilvusDB()
            results = db.search([0.1, 0.2])
            assert results == []
        finally:
            _cleanup_pymilvus()


class TestDeleteByDocId:
    def test_delete_no_connection(self):
        from database.milvus_db import MilvusDB
        db = MilvusDB()
        db.delete_by_doc_id("d1")  # 无连接，跳过

    def test_delete_success(self):
        try:
            mock_pymilvus = _install_mock_pymilvus()
            mock_collection = MagicMock()
            mock_pymilvus.Collection.return_value = mock_collection
            mock_pymilvus.connections.get_connection_addr.return_value = "localhost:19530"

            from database.milvus_db import MilvusDB
            db = MilvusDB()
            db.delete_by_doc_id("d1")
            mock_collection.delete.assert_called_once()
        finally:
            _cleanup_pymilvus()


class TestGetCollectionStats:
    def test_stats_success(self):
        try:
            mock_pymilvus = _install_mock_pymilvus()
            mock_collection = MagicMock()
            mock_collection.num_entities = 100
            mock_pymilvus.Collection.return_value = mock_collection

            from database.milvus_db import MilvusDB
            db = MilvusDB()
            stats = db.get_collection_stats()
            assert stats["num_entities"] == 100
        finally:
            _cleanup_pymilvus()

    def test_stats_exception(self):
        try:
            mock_pymilvus = _install_mock_pymilvus()
            mock_collection = MagicMock()
            mock_collection.num_entities = 0
            del mock_collection.num_entities  # 访问时抛异常
            type(mock_collection).num_entities = MagicMock()
            type(mock_collection).num_entities.__get__ = MagicMock(side_effect=Exception("boom"))
            mock_pymilvus.Collection.return_value = mock_collection

            from database.milvus_db import MilvusDB
            db = MilvusDB()
            stats = db.get_collection_stats()
            assert stats == {}
        finally:
            _cleanup_pymilvus()


class TestFetchAllChunks:
    def test_fetch_success(self):
        try:
            mock_pymilvus = _install_mock_pymilvus()
            mock_collection = MagicMock()
            mock_collection.num_entities = 2
            mock_collection.query.return_value = [
                {"id": "c1", "doc_id": "d1", "content": "hello", "metadata": {}},
                {"id": "c2", "doc_id": "d1", "content": "world", "metadata": {}},
            ]
            mock_pymilvus.Collection.return_value = mock_collection

            from database.milvus_db import MilvusDB
            db = MilvusDB()
            data = db.fetch_all_chunks()
            assert len(data) == 2
            assert data[0]["chunk_id"] == "c1"
        finally:
            _cleanup_pymilvus()

    def test_fetch_empty(self):
        try:
            mock_pymilvus = _install_mock_pymilvus()
            mock_collection = MagicMock()
            mock_collection.num_entities = 0
            mock_pymilvus.Collection.return_value = mock_collection

            from database.milvus_db import MilvusDB
            db = MilvusDB()
            data = db.fetch_all_chunks()
            assert data == []
        finally:
            _cleanup_pymilvus()

    def test_fetch_exception(self):
        try:
            mock_pymilvus = _install_mock_pymilvus()
            mock_collection = MagicMock()
            mock_collection.num_entities = 100
            mock_collection.query.side_effect = Exception("query failed")
            mock_pymilvus.Collection.return_value = mock_collection

            from database.milvus_db import MilvusDB
            db = MilvusDB()
            data = db.fetch_all_chunks()
            assert data == []
        finally:
            _cleanup_pymilvus()


class TestGetDocChunkStats:
    def test_stats_for_all_docs(self, tmp_path):
        try:
            mock_pymilvus = _install_mock_pymilvus()
            mock_collection = MagicMock()
            mock_collection.num_entities = 2
            mock_collection.query.return_value = [
                {"doc_id": "d1", "content": "hello"},  # len=5
                {"doc_id": "d1", "content": "world"},  # len=5
                {"doc_id": "d2", "content": "x"},       # len=1
            ]
            mock_pymilvus.Collection.return_value = mock_collection

            from database.milvus_db import MilvusDB
            db = MilvusDB()
            stats = db.get_doc_chunk_stats()
            assert "d1" in stats
            assert stats["d1"]["chunk_count"] == 2
            assert stats["d2"]["chunk_count"] == 1
        finally:
            _cleanup_pymilvus()

    def test_stats_for_specific_docs(self):
        try:
            mock_pymilvus = _install_mock_pymilvus()
            mock_collection = MagicMock()
            mock_collection.num_entities = 10
            mock_collection.query.return_value = [
                {"doc_id": "d1", "content": "test"},
            ]
            mock_pymilvus.Collection.return_value = mock_collection

            from database.milvus_db import MilvusDB
            db = MilvusDB()
            stats = db.get_doc_chunk_stats(doc_ids=["d1"])
            assert "d1" in stats
            assert stats["d1"]["chunk_count"] == 1
        finally:
            _cleanup_pymilvus()

    def test_stats_exception(self):
        try:
            mock_pymilvus = _install_mock_pymilvus()
            mock_collection = MagicMock()
            mock_collection.num_entities = 10
            mock_collection.query.side_effect = Exception("boom")
            mock_pymilvus.Collection.return_value = mock_collection

            from database.milvus_db import MilvusDB
            db = MilvusDB()
            stats = db.get_doc_chunk_stats()
            assert stats == {}
        finally:
            _cleanup_pymilvus()


class TestSearchByKeyword:
    def test_search_success(self):
        try:
            mock_pymilvus = _install_mock_pymilvus()
            mock_collection = MagicMock()
            mock_collection.query.return_value = [
                {"id": "c1", "doc_id": "d1", "content": "勾股定理", "metadata": {}},
            ]
            mock_pymilvus.Collection.return_value = mock_collection

            from database.milvus_db import MilvusDB
            db = MilvusDB()
            results = db.search_by_keyword(["勾股", "定理"])
            assert len(results) == 1
            assert results[0]["chunk_id"] == "c1"
        finally:
            _cleanup_pymilvus()

    def test_search_empty_keywords(self):
        try:
            mock_pymilvus = _install_mock_pymilvus()
            mock_collection = MagicMock()
            mock_collection.query.return_value = []
            mock_pymilvus.Collection.return_value = mock_collection

            from database.milvus_db import MilvusDB
            db = MilvusDB()
            results = db.search_by_keyword([])
            assert results == []
            # 验证 expr 为 "id != ''"
            call_expr = mock_collection.query.call_args[1]["expr"]
            assert call_expr == "id != ''"
        finally:
            _cleanup_pymilvus()

    def test_search_exception(self):
        try:
            mock_pymilvus = _install_mock_pymilvus()
            mock_collection = MagicMock()
            mock_collection.query.side_effect = Exception("boom")
            mock_pymilvus.Collection.return_value = mock_collection

            from database.milvus_db import MilvusDB
            db = MilvusDB()
            results = db.search_by_keyword(["test"])
            assert results == []
        finally:
            _cleanup_pymilvus()
