"""kb.knowledge_base 知识库管理测试"""
import pytest
import json
from unittest.mock import MagicMock, patch
from kb.knowledge_base import KnowledgeBase, KnowledgeBaseManager, _inject_chunk_counts


class TestKnowledgeBaseEntity:
    def test_default_values(self):
        kb = KnowledgeBase(name="测试库")
        assert kb.name == "测试库"
        assert kb.kb_id is not None
        assert kb.category == "通用"
        assert kb.tags == []
        assert kb.doc_count == 0
        assert kb.chunk_count == 0
        assert kb.total_size == 0

    def test_full_init(self):
        kb = KnowledgeBase(
            kb_id="kb_001", name="数学题库", description="初中数学",
            category="数学", tags=["数学", "初中"],
            doc_count=10, chunk_count=100, total_size=1024,
            created_at="2024-01-01", updated_at="2024-06-01",
        )
        assert kb.kb_id == "kb_001"
        assert kb.name == "数学题库"
        assert kb.description == "初中数学"
        assert kb.category == "数学"
        assert kb.tags == ["数学", "初中"]
        assert kb.doc_count == 10
        assert kb.chunk_count == 100
        assert kb.total_size == 1024

    def test_to_dict(self):
        kb = KnowledgeBase(kb_id="kb_001", name="测试", category="数学", tags=["标签1"])
        d = kb.to_dict()
        assert d["id"] == "kb_001"
        assert d["kb_id"] == "kb_001"
        assert d["name"] == "测试"
        assert d["category"] == "数学"
        assert d["tags"] == ["标签1"]

    def test_uuid_generated_if_none(self):
        kb = KnowledgeBase(name="测试")
        assert len(kb.kb_id) > 0
        # UUID format
        assert len(kb.kb_id) == 36
        assert kb.kb_id.count('-') == 4


class TestGetFileType:
    def test_pdf(self):
        assert KnowledgeBaseManager._get_file_type("doc.pdf") == "PDF"

    def test_word(self):
        assert KnowledgeBaseManager._get_file_type("doc.docx") == "Word"

    def test_txt(self):
        assert KnowledgeBaseManager._get_file_type("notes.txt") == "文本"

    def test_markdown(self):
        assert KnowledgeBaseManager._get_file_type("readme.md") == "Markdown"

    def test_unknown_ext(self):
        assert KnowledgeBaseManager._get_file_type("file.xyz") == "XYZ"

    def test_no_ext(self):
        assert KnowledgeBaseManager._get_file_type("noextension") == "文档"

    def test_empty_source(self):
        assert KnowledgeBaseManager._get_file_type("") == "文档"


class TestRowToKB:
    def test_basic(self):
        mgr = KnowledgeBaseManager()
        row = {"id": "kb_1", "name": "测试", "category": "数学",
               "tags": '["标签1", "标签2"]', "description": "desc"}
        kb = mgr._row_to_kb(row)
        assert kb.kb_id == "kb_1"
        assert kb.tags == ["标签1", "标签2"]

    def test_tags_already_list(self):
        mgr = KnowledgeBaseManager()
        row = {"id": "kb_1", "name": "测试", "tags": ["标签A", "标签B"]}
        kb = mgr._row_to_kb(row)
        assert kb.tags == ["标签A", "标签B"]

    def test_tags_invalid_json(self):
        mgr = KnowledgeBaseManager()
        row = {"id": "kb_1", "name": "测试", "tags": "{invalid"}
        kb = mgr._row_to_kb(row)
        assert kb.tags == []

    def test_missing_fields(self):
        mgr = KnowledgeBaseManager()
        row = {}
        kb = mgr._row_to_kb(row)
        assert kb.name == ""


class TestKBCreate:
    def test_create_returns_kb(self):
        mgr = KnowledgeBaseManager()
        mock_db = MagicMock()
        mgr._db = mock_db

        kb = mgr.create("新知识库", "描述", "数学", ["标签1"])

        assert kb.name == "新知识库"
        assert kb.category == "数学"
        assert kb.tags == ["标签1"]
        assert mock_db.execute.called

    def test_create_defaults(self):
        mgr = KnowledgeBaseManager()
        mock_db = MagicMock()
        mgr._db = mock_db

        kb = mgr.create("新知识库")
        assert kb.category == "通用"
        assert kb.tags == []
        assert kb.description == ""


class TestKBGet:
    def test_get_exists(self):
        mgr = KnowledgeBaseManager()
        mock_db = MagicMock()
        mock_db.query_one.return_value = {"id": "kb_1", "name": "测试", "tags": "[]"}
        mgr._db = mock_db

        kb = mgr.get("kb_1")
        assert kb is not None
        assert kb.kb_id == "kb_1"
        assert kb.name == "测试"

    def test_get_not_found(self):
        mgr = KnowledgeBaseManager()
        mock_db = MagicMock()
        mock_db.query_one.return_value = None
        mgr._db = mock_db

        kb = mgr.get("nonexistent")
        assert kb is None


class TestKBList:
    def test_list_with_items(self):
        mgr = KnowledgeBaseManager()
        mock_db = MagicMock()
        mock_db.query_one.return_value = {"total": 2}
        mock_db.query.return_value = [
            {"id": "kb_1", "name": "数学题库", "tags": "[]", "updated_at": "2024-01-01"},
            {"id": "kb_2", "name": "英语题库", "tags": "[]", "updated_at": "2024-01-02"},
        ]
        mgr._db = mock_db

        with patch("kb.knowledge_base._inject_chunk_counts"):
            result = mgr.list(page=1, page_size=20)
            assert result["total"] == 2
            assert len(result["items"]) == 2

    def test_list_filter_by_category(self):
        mgr = KnowledgeBaseManager()
        mock_db = MagicMock()
        mock_db.query_one.return_value = {"total": 1}
        mock_db.query.return_value = [
            {"id": "kb_1", "name": "数学题库", "tags": "[]", "updated_at": "2024-01-01"},
        ]
        mgr._db = mock_db

        with patch("kb.knowledge_base._inject_chunk_counts"):
            result = mgr.list(category="数学")
            assert result["total"] == 1


class TestKBUpdate:
    def test_update_name(self):
        mgr = KnowledgeBaseManager()
        mock_db = MagicMock()
        mgr._db = mock_db

        result = mgr.update("kb_1", name="新名称")
        assert result is True
        assert mock_db.execute.called

    def test_update_nothing(self):
        mgr = KnowledgeBaseManager()
        mock_db = MagicMock()
        mgr._db = mock_db

        result = mgr.update("kb_1")
        assert result is False


class TestKBDelete:
    def test_delete_calls_db(self):
        mgr = KnowledgeBaseManager()
        mock_db = MagicMock()
        mgr._db = mock_db

        result = mgr.delete("kb_1")
        assert result is True
        mock_db.delete_knowledge_base.assert_called_once_with("kb_1")


class TestDocumentAssociation:
    def test_add_document(self):
        mgr = KnowledgeBaseManager()
        mock_db = MagicMock()
        mgr._db = mock_db

        result = mgr.add_document("kb_1", "doc_1")
        assert result is True

    def test_add_document_error(self):
        mgr = KnowledgeBaseManager()
        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("DB error")
        mgr._db = mock_db

        result = mgr.add_document("kb_1", "doc_1")
        assert result is False

    def test_add_documents_batch(self):
        mgr = KnowledgeBaseManager()
        mock_db = MagicMock()
        mgr._db = mock_db

        count = mgr.add_documents_batch("kb_1", ["doc_1", "doc_2", "doc_3"])
        assert count == 3
        assert mock_db.execute.call_count == 3

    def test_get_documents(self):
        mgr = KnowledgeBaseManager()
        mock_db = MagicMock()
        mock_db.query_one.return_value = {"total": 1}
        mock_db.query.return_value = [
            {"id": "doc_1", "title": "测试文档", "source": "test.pdf",
             "content": "文档内容", "metadata": '{"key": "val"}',
             "created_at": "2024-01-01", "kb_added_at": "2024-01-01"},
        ]
        mgr._db = mock_db

        result = mgr.get_documents("kb_1")
        assert result["total"] == 1
        assert result["documents"][0]["filename"] == "测试文档"
        assert result["documents"][0]["file_type"] == "PDF"


class TestKBSearch:
    def test_search_knowledge_bases(self):
        mgr = KnowledgeBaseManager()
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {"id": "kb_1", "name": "数学题库", "tags": "[]", "updated_at": "2024-01-01"},
        ]
        mgr._db = mock_db

        results = mgr.search_knowledge_bases("数学")
        assert len(results) == 1

    def test_search_documents_with_kb(self):
        mgr = KnowledgeBaseManager()
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {"id": "doc_1", "title": "测试", "source": "test.pdf", "created_at": "2024-01-01"},
        ]
        mgr._db = mock_db

        results = mgr.search_documents("测试", kb_id="kb_1")
        assert len(results) == 1

    def test_search_documents_without_kb(self):
        mgr = KnowledgeBaseManager()
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {"id": "doc_1", "title": "测试", "source": "test.pdf", "created_at": "2024-01-01"},
        ]
        mgr._db = mock_db

        results = mgr.search_documents("测试")
        assert len(results) == 1


class TestKBStats:
    def test_get_stats_basic(self):
        mgr = KnowledgeBaseManager()
        mock_db = MagicMock()
        mock_db.query_one.side_effect = [
            {"cnt": 5},   # doc count
            None,          # kb_documents query (handled by query)
        ]
        mock_db.query.return_value = [
            {"category": "数学", "cnt": 3},
        ]
        mgr._db = mock_db

        stats = mgr.get_stats("kb_1")
        assert stats["kb_id"] == "kb_1"
        assert stats["doc_count"] == 5
        assert "category_distribution" in stats
