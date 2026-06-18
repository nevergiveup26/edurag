"""database.mysql_db MySQL数据库操作测试"""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mysql_db():
    """创建带 mock connection 的 MySQLDB"""
    from database.mysql_db import MySQLDB
    db = MySQLDB()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    db.get_connection = MagicMock()
    db.get_connection.return_value = mock_conn
    db._conn = mock_conn
    db._cursor = mock_cursor
    return db


def _get_mock_conn(mysql_db):
    """获取当前 mock connection 的 cursor"""
    ctx = mysql_db.get_connection.return_value
    # context manager returns the connection
    return ctx


class TestCoreOps:
    def test_execute(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.return_value = 3
        result = mysql_db.execute("UPDATE t SET x=1")
        assert result == 3

    def test_query(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [{"id": "1"}, {"id": "2"}]
        rows = mysql_db.query("SELECT * FROM t")
        assert len(rows) == 2

    def test_query_one(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = {"id": "1", "name": "test"}
        row = mysql_db.query_one("SELECT * FROM t WHERE id=%s", ("1",))
        assert row["id"] == "1"


class TestDocumentOps:
    def test_insert_document(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.return_value = 1
        result = mysql_db.insert_document("d1", "测试", "test.txt", "content")
        assert result == 1

    def test_insert_document_without_md5(self, mysql_db):
        """content 提供但 md5_hash 未提供时自动计算"""
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.return_value = 1
        result = mysql_db.insert_document("d1", "测试", "test.txt", "hello")
        assert result == 1

    def test_get_document(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = {
            "id": "d1", "title": "测试", "source": "test.txt",
            "content": "hello", "md5_hash": "abc",
            "metadata": '{}', "created_at": "2024-01-01",
        }
        doc = mysql_db.get_document("d1")
        assert doc["id"] == "d1"

    def test_get_document_not_found(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = None
        assert mysql_db.get_document("nonexistent") is None

    def test_get_document_by_md5(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = {"id": "d1", "title": "测试"}
        doc = mysql_db.get_document_by_md5("abc123")
        assert doc["id"] == "d1"

    def test_get_document_by_md5_in_kb(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = {"id": "d1", "title": "测试"}
        doc = mysql_db.get_document_by_md5_in_kb("abc123", "kb_1")
        assert doc is not None

    def test_get_document_by_md5_global(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = {"id": "d1"}
        doc = mysql_db.get_document_by_md5_global("abc123")
        assert doc["id"] == "d1"

    def test_delete_document(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.return_value = 1
        assert mysql_db.delete_document("d1") == 1

    def test_get_all_documents_content(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [
            {"id": "d1", "content": "hello", "md5_hash": "abc", "title": "T1"},
        ]
        docs = mysql_db.get_all_documents_content()
        assert len(docs) == 1

    def test_cleanup_orphan_documents(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [{"cnt": 5}]
        cursor.execute.return_value = 5
        cnt = mysql_db.cleanup_orphan_documents()
        assert cnt == 5

    def test_cleanup_orphan_documents_none(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        # query returns count=0
        cursor.fetchall.return_value = [{"cnt": 0}]
        cnt = mysql_db.cleanup_orphan_documents()
        assert cnt == 0


class TestUserOps:
    def test_create_user(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.return_value = 1
        result = mysql_db.create_user("u1", "student1", "hash123", "student", "小明")
        assert result == 1

    def test_get_user_by_username(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = {"id": "u1", "username": "student1", "role": "student"}
        user = mysql_db.get_user_by_username("student1")
        assert user["username"] == "student1"

    def test_get_user_by_username_not_found(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = None
        assert mysql_db.get_user_by_username("nobody") is None

    def test_get_user_by_id(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = {"id": "u1", "username": "student1"}
        user = mysql_db.get_user_by_id("u1")
        assert user["id"] == "u1"

    def test_list_users_all(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [
            {"id": "u1", "username": "s1", "role": "student"},
            {"id": "u2", "username": "a1", "role": "admin"},
        ]
        users = mysql_db.list_users()
        assert len(users) == 2

    def test_list_users_by_role(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [{"id": "u1", "role": "admin"}]
        users = mysql_db.list_users(role="admin")
        assert len(users) == 1


class TestFeedbackOps:
    def test_insert_feedback(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.return_value = 1
        result = mysql_db.insert_feedback("f1", "u1", "conv1", "query", "answer", "like")
        assert result == 1

    def test_get_feedback_stats(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.side_effect = [
            {"cnt": 10},  # total
            {"cnt": 7},   # likes
            {"cnt": 3},   # dislikes
        ]
        stats = mysql_db.get_feedback_stats()
        assert stats["total"] == 10
        assert stats["likes"] == 7
        assert stats["dislikes"] == 3

    def test_get_feedback_stats_empty(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = {"cnt": 0}
        stats = mysql_db.get_feedback_stats()
        assert stats["total"] == 0


class TestKnowledgeBaseOps:
    def test_create_knowledge_base(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.return_value = 1
        result = mysql_db.create_knowledge_base("kb1", "数学题库", "描述", "数学", ["标签1"])
        assert result == 1

    def test_list_knowledge_bases(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [
            {"id": "kb1", "name": "数学题库"},
            {"id": "kb2", "name": "英语题库"},
        ]
        kbs = mysql_db.list_knowledge_bases()
        assert len(kbs) == 2

    def test_get_knowledge_base(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = {"id": "kb1", "name": "数学题库"}
        kb = mysql_db.get_knowledge_base("kb1")
        assert kb["name"] == "数学题库"

    def test_update_knowledge_base(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.return_value = 1
        result = mysql_db.update_knowledge_base("kb1", name="新名称")
        assert result == 1

    def test_update_knowledge_base_no_fields(self, mysql_db):
        result = mysql_db.update_knowledge_base("kb1")
        assert result == 0

    def test_delete_knowledge_base(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [{"doc_id": "d1"}, {"doc_id": "d2"}]
        # 第一次 query 返回 still_referenced 为空 → 所有 doc 都是 orphan
        # delete_knowledge_base 会做多次 query
        cursor.fetchall.side_effect = [
            [{"doc_id": "d1"}, {"doc_id": "d2"}],  # 初始查询
            [],  # still_referenced 查询
        ]
        cursor.execute.return_value = 1
        result = mysql_db.delete_knowledge_base("kb1")
        assert result == 1

    def test_add_doc_to_kb(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.return_value = 1
        assert mysql_db.add_doc_to_kb("kb1", "d1") == 1

    def test_get_kb_documents(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [
            {"id": "d1", "title": "文档1"},
            {"id": "d2", "title": "文档2"},
        ]
        docs = mysql_db.get_kb_documents("kb1")
        assert len(docs) == 2


class TestEvalHistoryOps:
    def test_insert_eval_history(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.return_value = 1
        result = mysql_db.insert_eval_history(
            "h1", "retrieval",
            config={"k": 10}, metrics={"ndcg": 0.8},
            sample_count=50, total_time=12.5, mode="builtin",
        )
        assert result == 1

    def test_list_eval_history(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [{"id": "h1", "eval_type": "retrieval"}]
        items = mysql_db.list_eval_history()
        assert len(items) == 1

    def test_list_eval_history_by_type(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [{"id": "h1", "eval_type": "ragas"}]
        items = mysql_db.list_eval_history(eval_type="ragas")
        assert len(items) == 1

    def test_get_eval_history(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = {"id": "h1", "eval_type": "retrieval"}
        hist = mysql_db.get_eval_history("h1")
        assert hist["eval_type"] == "retrieval"

    def test_delete_eval_history(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.return_value = 1
        assert mysql_db.delete_eval_history("h1") == 1


class TestWrongBookOps:
    def test_insert_wrong_book(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.return_value = 1
        result = mysql_db.insert_wrong_book(
            "w1", "u1", subject="数学", question_type="objective",
            question="1+1=?", user_answer="3", correct_answer="2",
            grading={"score": 0}, status="wrong",
        )
        assert result == 1

    def test_list_wrong_book(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [
            {"id": "w1", "subject": "数学", "question": "1+1=?"},
        ]
        items = mysql_db.list_wrong_book("u1")
        assert len(items) == 1

    def test_list_wrong_book_by_subject(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [{"id": "w1", "subject": "数学"}]
        items = mysql_db.list_wrong_book("u1", subject="数学")
        assert len(items) == 1

    def test_get_wrong_book_stats(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [
            {"subject": "数学", "question_type": "objective", "cnt": 3},
            {"subject": "数学", "question_type": "subjective", "cnt": 2},
        ]
        stats = mysql_db.get_wrong_book_stats("u1")
        assert stats["total"] == 5
        assert len(stats["by_subject"]) == 2

    def test_delete_wrong_book(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.return_value = 1
        assert mysql_db.delete_wrong_book("w1") == 1

    def test_delete_wrong_book_with_user(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.return_value = 1
        assert mysql_db.delete_wrong_book("w1", user_id="u1") == 1

    def test_review_wrong_book(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.return_value = 1
        assert mysql_db.review_wrong_book("w1") == 1

    def test_get_wrong_book_by_id(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = {"id": "w1", "subject": "数学"}
        item = mysql_db.get_wrong_book_by_id("w1")
        assert item["subject"] == "数学"


class TestUserProfileOps:
    def test_upsert_insert(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = None  # 不存在 → INSERT
        cursor.execute.return_value = 1
        result = mysql_db.upsert_user_profile(
            "u1", "数学", personality_tags=["细心"],
            ability_level="中级", weak_points=[{"tag": "函数"}],
        )
        assert result == 1

    def test_upsert_update(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = {"id": "p1"}  # 已存在 → UPDATE
        cursor.execute.return_value = 1
        result = mysql_db.upsert_user_profile("u1", "数学", ability_level="高级")
        assert result == 1

    def test_upsert_update_no_fields(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = {"id": "p1"}
        result = mysql_db.upsert_user_profile("u1", "数学")
        assert result == 0

    def test_get_user_profile_single(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchone.return_value = {
            "id": "p1", "user_id": "u1", "subject": "数学",
            "personality_tags": '["细心"]', "weak_points": "[]",
            "ability_level": "中级", "updated_at": "2024-01-01",
        }
        profile = mysql_db.get_user_profile("u1", subject="数学")
        assert profile["subject"] == "数学"
        assert profile["personality_tags"] == ["细心"]

    def test_get_user_profile_all_subjects(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [
            {"id": "p1", "user_id": "u1", "subject": "数学",
             "personality_tags": "[]", "weak_points": "[]",
             "ability_level": "中级", "updated_at": "2024-01-01"},
        ]
        profiles = mysql_db.get_user_profile("u1")
        assert len(profiles) == 1


class TestLogQuery:
    def test_log_query(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.return_value = 1
        mysql_db.log_query("u1", "什么是勾股定理", query_type="chat")
        cursor.execute.assert_called_once()

    def test_log_query_truncates_long_query(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.return_value = 1
        long_query = "测" * 3000
        mysql_db.log_query("u1", long_query)
        # 查询参数被截断到2000字符
        call_args = cursor.execute.call_args[0][1]  # params tuple
        assert len(call_args[2]) <= 2000

    def test_log_query_exception(self, mysql_db):
        cursor = _get_mock_conn(mysql_db).cursor.return_value
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.execute.side_effect = Exception("DB error")
        mysql_db.log_query("u1", "query")  # 不抛异常
