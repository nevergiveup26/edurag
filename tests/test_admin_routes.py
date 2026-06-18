"""api/admin_routes.py 测试"""
import json
import pytest
from unittest.mock import MagicMock, patch
from io import BytesIO


FAKE_ADMIN = {"user_id": "adm_abc123", "username": "admin1", "role": "admin"}


@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    test_app = FastAPI()
    try:
        from api.admin_routes import admin_router
    except ImportError:
        pytest.skip("admin_routes module not importable")

    from api.auth import require_admin

    async def fake_require_admin():
        return FAKE_ADMIN

    test_app.dependency_overrides = {require_admin: fake_require_admin}
    test_app.include_router(admin_router)  # router 已有 prefix="/admin"
    return TestClient(test_app)


# ═══════════════════════════ 认证 ═══════════════════════════════════════════════

class TestAdminLogin:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.get_user_by_username.return_value = {
            "id": "adm_1", "username": "admin1", "role": "admin",
            "password_hash": "hashed",
        }
        with patch("api.admin_routes.MySQLDB", return_value=mock_db), \
             patch("api.auth.verify_password", return_value=(True, False)), \
             patch("api.auth.create_token", return_value="token_abc"):
            resp = client.post("/admin/login", json={"username": "admin1", "password": "pwd"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["token"] == "token_abc"
        assert data["user"]["role"] == "admin"

    def test_user_not_found(self, client):
        mock_db = MagicMock()
        mock_db.get_user_by_username.return_value = None
        with patch("api.admin_routes.MySQLDB", return_value=mock_db):
            resp = client.post("/admin/login", json={"username": "bad", "password": "pwd"})
        assert resp.status_code == 401

    def test_not_admin_role(self, client):
        mock_db = MagicMock()
        mock_db.get_user_by_username.return_value = {
            "id": "stu_1", "username": "student1", "role": "student",
            "password_hash": "hashed",
        }
        with patch("api.admin_routes.MySQLDB", return_value=mock_db):
            resp = client.post("/admin/login", json={"username": "student1", "password": "pwd"})
        assert resp.status_code == 403

    def test_wrong_password(self, client):
        mock_db = MagicMock()
        mock_db.get_user_by_username.return_value = {
            "id": "adm_1", "username": "admin1", "role": "admin",
            "password_hash": "hashed",
        }
        with patch("api.admin_routes.MySQLDB", return_value=mock_db), \
             patch("api.auth.verify_password", return_value=(False, False)):
            resp = client.post("/admin/login", json={"username": "admin1", "password": "wrong"})
        assert resp.status_code == 401

    def test_password_upgrade(self, client):
        mock_db = MagicMock()
        mock_db.get_user_by_username.return_value = {
            "id": "adm_1", "username": "admin1", "role": "admin",
            "password_hash": "old_hash",
        }
        with patch("api.admin_routes.MySQLDB", return_value=mock_db), \
             patch("api.auth.verify_password", return_value=(True, True)), \
             patch("api.auth.hash_password", return_value="new_hash"), \
             patch("api.auth.create_token", return_value="token"):
            resp = client.post("/admin/login", json={"username": "admin1", "password": "pwd"})
        assert resp.status_code == 200
        mock_db.execute.assert_called()


# ═══════════════════════════ 统计面板 ══════════════════════════════════════════

class TestAdminStats:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.get_feedback_stats.return_value = {"avg_rating": 4.0}
        mock_db.query_one.side_effect = [
            {"cnt": 50},   # total_docs
            {"cnt": 5},    # total_kbs
            {"cnt": 100},  # total_users
            {"cnt": 200},  # total_queries
        ]
        mock_db.query.return_value = []  # query_trend empty

        with patch("api.admin_routes.MySQLDB", return_value=mock_db), \
             patch("database.chunk_store.get_chunk_count", return_value=500):
            resp = client.get("/admin/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_documents"] == 50
        assert data["total_chunks"] == 500

    def test_chunk_count_error(self, client):
        mock_db = MagicMock()
        mock_db.get_feedback_stats.return_value = {}
        mock_db.query_one.side_effect = [
            {"cnt": 10}, {"cnt": 2}, {"cnt": 20}, {"cnt": 5},
        ]
        mock_db.query.return_value = []
        with patch("api.admin_routes.MySQLDB", return_value=mock_db), \
             patch("database.chunk_store.get_chunk_count", side_effect=Exception("fail")):
            resp = client.get("/admin/stats")
        assert resp.status_code == 200
        assert resp.json()["total_chunks"] == 0


# ═══════════════════════════ 文档管理 ══════════════════════════════════════════

class TestDeleteDocument:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.delete_document.return_value = 1
        with patch("api.admin_routes.MySQLDB", return_value=mock_db), \
             patch("api.admin_routes.threading.Thread") as mock_thread:
            resp = client.delete("/admin/documents/doc_123")
        assert resp.status_code == 200
        mock_thread.assert_called_once()

    def test_not_found(self, client):
        mock_db = MagicMock()
        mock_db.delete_document.return_value = 0
        with patch("api.admin_routes.MySQLDB", return_value=mock_db):
            resp = client.delete("/admin/documents/doc_missing")
        assert resp.status_code == 404


class TestGetDocumentDetail:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.get_document.return_value = {"id": "d1", "title": "doc", "content": "test"}
        with patch("api.admin_routes.MySQLDB", return_value=mock_db):
            resp = client.get("/admin/documents/d1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "d1"

    def test_not_found(self, client):
        mock_db = MagicMock()
        mock_db.get_document.return_value = None
        with patch("api.admin_routes.MySQLDB", return_value=mock_db):
            resp = client.get("/admin/documents/d_missing")
        assert resp.status_code == 404

    def test_db_error(self, client):
        mock_db = MagicMock()
        mock_db.get_document.side_effect = Exception("fail")
        with patch("api.admin_routes.MySQLDB", return_value=mock_db):
            resp = client.get("/admin/documents/d1")
        assert resp.status_code == 500


# ═══════════════════════════ 知识图谱管理 ══════════════════════════════════════

class TestGraphStats:
    def test_success(self, client):
        mock_mgr = MagicMock()
        mock_mgr.get_stats.return_value = {"entity_count": 20, "relation_count": 50}
        with patch("data_processor.graph_builder.KnowledgeGraphManager", return_value=mock_mgr):
            resp = client.get("/admin/graph/stats")
        assert resp.status_code == 200
        assert resp.json()["entity_count"] == 20

    def test_error(self, client):
        with patch("data_processor.graph_builder.KnowledgeGraphManager",
                   side_effect=Exception("fail")):
            resp = client.get("/admin/graph/stats")
        assert resp.status_code == 500


class TestGraphRebuild:
    def test_success(self, client):
        mock_mgr = MagicMock()
        with patch("data_processor.graph_builder.KnowledgeGraphManager", return_value=mock_mgr):
            resp = client.post("/admin/graph/rebuild")
        assert resp.status_code == 200
        assert resp.json()["status"] == "building"

    def test_error(self, client):
        with patch("data_processor.graph_builder.KnowledgeGraphManager",
                   side_effect=Exception("fail")):
            resp = client.post("/admin/graph/rebuild")
        assert resp.status_code == 500


# ═══════════════════════════ FAQ 导入 ══════════════════════════════════════════

class TestImportFAQ:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_vectorizer = MagicMock()
        mock_vectorizer.embed_query.return_value = [0.1, 0.2, 0.3]

        sample_data = [{"question": "Q1", "answer": "A1", "category": "general", "tags": []}]
        mock_open = MagicMock()
        mock_open.return_value.__enter__.return_value.read.return_value = json.dumps(sample_data)

        with patch("api.admin_routes.MySQLDB", return_value=mock_db), \
             patch("data_processor.vectorizer.Vectorizer", return_value=mock_vectorizer), \
             patch("builtins.open", mock_open), \
             patch("os.path.exists", return_value=True):
            resp = client.post("/admin/faq/import")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_error(self, client):
        with patch("builtins.open", side_effect=Exception("file missing")):
            resp = client.post("/admin/faq/import")
        assert resp.status_code == 500


# ═══════════════════════════ 模型评估 ══════════════════════════════════════════

class TestRunEvaluation:
    def test_default(self, client):
        mock_evaluator = MagicMock()
        mock_report = MagicMock()
        mock_report.sample_count = 5
        mock_report.total_time = 10.0
        mock_report.retrieval.precision = 0.8
        mock_report.retrieval.recall = 0.75
        mock_report.retrieval.f1_score = 0.77
        mock_report.retrieval.mrr = 0.85
        mock_report.retrieval.ndcg = 0.82
        mock_report.retrieval.hit_rate = 0.9
        mock_report.generation.bleu_1 = 0.5
        mock_report.generation.bleu_2 = 0.3
        mock_report.generation.rouge_l = 0.6
        mock_report.generation.keyword_match_rate = 0.7
        mock_report.generation.llm_score = -1
        mock_report.generation.answer_length = 200
        mock_report.generation.avg_execution_time = 1.5
        mock_report.charts = {}
        mock_report.sample_reports = []
        mock_evaluator.run_full_evaluation.return_value = mock_report

        with patch("evaluation.evaluator.RAGEvaluator", return_value=mock_evaluator), \
             patch("api.admin_routes._make_query_func", return_value=MagicMock()):
            resp = client.post("/admin/evaluate", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["sample_count"] == 5
        assert data["retrieval"]["precision"] == 0.8

    def test_error(self, client):
        with patch("evaluation.evaluator.RAGEvaluator", side_effect=Exception("fail")):
            resp = client.post("/admin/evaluate", json={})
        assert resp.status_code == 500


class TestGetEvalSamples:
    def test_empty(self, client):
        mock_evaluator = MagicMock()
        mock_evaluator.samples = []
        with patch("evaluation.evaluator.RAGEvaluator", return_value=mock_evaluator):
            resp = client.get("/admin/evaluate/samples")
        assert resp.status_code == 200
        assert resp.json()["samples"] == []


# ═══════════════════════════ RAGAS 评估 ════════════════════════════════════════

class TestRAGASEvaluation:
    def test_default(self, client):
        mock_evaluator = MagicMock()
        mock_metrics = MagicMock()
        mock_metrics.faithfulness = 0.9
        mock_metrics.answer_relevancy = 0.85
        mock_metrics.context_relevancy = 0.8
        mock_metrics.context_precision = 0.75
        mock_metrics.context_recall = 0.7
        mock_metrics.answer_correctness = 0.88
        mock_metrics.avg_score = 0.82
        mock_evaluator.run_full_ragas.return_value = (mock_metrics, [])

        with patch("evaluation.ragas_evaluator.RAGASEvaluator", return_value=mock_evaluator), \
             patch("api.admin_routes._make_query_func", return_value=MagicMock()):
            resp = client.post("/admin/evaluate/ragas", json={"use_builtin": True})
        assert resp.status_code == 200
        data = resp.json()
        assert data["metrics"]["faithfulness"] == 0.9

    def test_error(self, client):
        with patch("evaluation.ragas_evaluator.RAGASEvaluator", side_effect=Exception("fail")):
            resp = client.post("/admin/evaluate/ragas", json={})
        assert resp.status_code == 500


class TestGetRAGASSamples:
    def test_returns_samples(self, client):
        resp = client.get("/admin/evaluate/ragas/samples")
        assert resp.status_code == 200
        assert len(resp.json()["samples"]) == 5


# ═══════════════════════════ 评测流 ════════════════════════════════════════════

class TestEvaluateStream:
    def test_basic(self, client):
        from fastapi.responses import StreamingResponse

        # Mock _make_query_func to avoid heavy imports
        with patch("api.admin_routes._make_query_func", return_value=MagicMock()), \
             patch("os.path.exists", return_value=False), \
             patch("evaluation.evaluator.RAGEvaluator") as mock_eval_cls:
            mock_eval = MagicMock()
            mock_eval.run_full_evaluation_stream.return_value = iter([])
            mock_eval_cls.return_value = mock_eval
            resp = client.get("/admin/evaluate/stream")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")


class TestRAGASEvaluateStream:
    def test_basic(self, client):
        with patch("api.admin_routes._make_query_func", return_value=MagicMock()), \
             patch("os.path.exists", return_value=False), \
             patch("evaluation.ragas_evaluator.RAGASEvaluator") as mock_eval_cls:
            mock_eval = MagicMock()
            mock_eval.run_full_ragas_stream.return_value = iter([])
            mock_eval_cls.return_value = mock_eval
            resp = client.get("/admin/evaluate/ragas/stream")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")


class TestCancelEvaluation:
    def test_found(self, client):
        import threading
        cancel_event = threading.Event()
        from api import admin_routes
        admin_routes._running_evals["session_1"] = cancel_event
        try:
            resp = client.post("/admin/evaluate/cancel/session_1")
            assert resp.status_code == 200
            assert cancel_event.is_set()
        finally:
            admin_routes._running_evals.pop("session_1", None)

    def test_not_found(self, client):
        resp = client.post("/admin/evaluate/cancel/nonexistent")
        assert resp.status_code == 404


# ═══════════════════════════ 评测历史 ══════════════════════════════════════════

class TestListEvalHistory:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.list_eval_history.return_value = [
            {"id": "h1", "eval_type": "retrieval", "config": "{}",
             "metrics": "{}", "created_at": "2024-01-01T00:00:00"},
        ]
        with patch("api.admin_routes.MySQLDB", return_value=mock_db):
            resp = client.get("/admin/evaluate/history")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_empty(self, client):
        mock_db = MagicMock()
        mock_db.list_eval_history.return_value = []
        with patch("api.admin_routes.MySQLDB", return_value=mock_db):
            resp = client.get("/admin/evaluate/history")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


class TestGetEvalHistory:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.get_eval_history.return_value = {
            "id": "h1", "eval_type": "retrieval",
            "config": "{}", "metrics": "{}", "charts": "{}",
            "sample_reports": "[]", "details": "[]",
            "created_at": "2024-01-01T00:00:00",
        }
        with patch("api.admin_routes.MySQLDB", return_value=mock_db):
            resp = client.get("/admin/evaluate/history/h1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "h1"

    def test_not_found(self, client):
        mock_db = MagicMock()
        mock_db.get_eval_history.return_value = None
        with patch("api.admin_routes.MySQLDB", return_value=mock_db):
            resp = client.get("/admin/evaluate/history/missing")
        assert resp.status_code == 404


class TestDeleteEvalHistory:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.delete_eval_history.return_value = 1
        with patch("api.admin_routes.MySQLDB", return_value=mock_db):
            resp = client.delete("/admin/evaluate/history/h1")
        assert resp.status_code == 200

    def test_not_found(self, client):
        mock_db = MagicMock()
        mock_db.delete_eval_history.return_value = 0
        with patch("api.admin_routes.MySQLDB", return_value=mock_db):
            resp = client.delete("/admin/evaluate/history/missing")
        assert resp.status_code == 404


class TestCompareEvalHistory:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.get_eval_history.side_effect = [
            {
                "id": "h1", "eval_type": "retrieval",
                "metrics": json.dumps({"retrieval": {"precision": 0.8}, "generation": {"bleu_1": 0.5}}),
                "created_at": "2024-01-01T00:00:00",
            },
            {
                "id": "h2", "eval_type": "retrieval",
                "metrics": json.dumps({"retrieval": {"precision": 0.9}, "generation": {"bleu_1": 0.6}}),
                "created_at": "2024-02-01T00:00:00",
            },
        ]
        with patch("api.admin_routes.MySQLDB", return_value=mock_db):
            resp = client.post("/admin/evaluate/history/compare",
                               json={"id1": "h1", "id2": "h2"})
        assert resp.status_code == 200
        data = resp.json()
        assert "table" in data
        assert len(data["models"]) == 2

    def test_not_found(self, client):
        mock_db = MagicMock()
        mock_db.get_eval_history.side_effect = [None, {"id": "h2"}]
        with patch("api.admin_routes.MySQLDB", return_value=mock_db):
            resp = client.post("/admin/evaluate/history/compare",
                               json={"id1": "bad", "id2": "h2"})
        assert resp.status_code == 404


# ═══════════════════════════ 知识库管理 ════════════════════════════════════════

class TestCreateKB:
    def test_success(self, client):
        mock_kb = MagicMock()
        mock_kb.to_dict.return_value = {"kb_id": "kb_1", "name": "test_kb"}
        mock_mgr = MagicMock()
        mock_mgr.create.return_value = mock_kb

        with patch("kb.knowledge_base.KnowledgeBaseManager", return_value=mock_mgr):
            resp = client.post("/admin/kb", json={"name": "test_kb", "description": "desc"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "test_kb"

    def test_error(self, client):
        with patch("kb.knowledge_base.KnowledgeBaseManager", side_effect=Exception("fail")):
            resp = client.post("/admin/kb", json={"name": "test_kb"})
        assert resp.status_code == 500


class TestListKBs:
    def test_success(self, client):
        mock_mgr = MagicMock()
        mock_mgr.list.return_value = {"items": [], "total": 0}
        with patch("kb.knowledge_base.KnowledgeBaseManager", return_value=mock_mgr):
            resp = client.get("/admin/kb")
        assert resp.status_code == 200

    def test_error(self, client):
        with patch("kb.knowledge_base.KnowledgeBaseManager", side_effect=Exception("fail")):
            resp = client.get("/admin/kb")
        assert resp.status_code == 500


class TestSearchKBs:
    def test_success(self, client):
        mock_mgr = MagicMock()
        mock_mgr.search_knowledge_bases.return_value = [{"name": "kb1"}]
        with patch("kb.knowledge_base.KnowledgeBaseManager", return_value=mock_mgr):
            resp = client.get("/admin/kb/search?keyword=test")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_error(self, client):
        with patch("kb.knowledge_base.KnowledgeBaseManager", side_effect=Exception("fail")):
            resp = client.get("/admin/kb/search?keyword=test")
        assert resp.status_code == 500


class TestGetKB:
    def test_success(self, client):
        mock_kb = MagicMock()
        mock_kb.to_dict.return_value = {"kb_id": "kb_1", "name": "test"}
        mock_mgr = MagicMock()
        mock_mgr.get.return_value = mock_kb
        with patch("kb.knowledge_base.KnowledgeBaseManager", return_value=mock_mgr):
            resp = client.get("/admin/kb/kb_1")
        assert resp.status_code == 200

    def test_not_found(self, client):
        mock_mgr = MagicMock()
        mock_mgr.get.return_value = None
        with patch("kb.knowledge_base.KnowledgeBaseManager", return_value=mock_mgr):
            resp = client.get("/admin/kb/kb_missing")
        assert resp.status_code == 404

    def test_error(self, client):
        with patch("kb.knowledge_base.KnowledgeBaseManager", side_effect=Exception("fail")):
            resp = client.get("/admin/kb/kb_1")
        assert resp.status_code == 500


class TestUpdateKB:
    def test_success(self, client):
        mock_mgr = MagicMock()
        mock_mgr.update.return_value = True
        with patch("kb.knowledge_base.KnowledgeBaseManager", return_value=mock_mgr):
            resp = client.put("/admin/kb/kb_1", json={"name": "new_name"})
        assert resp.status_code == 200

    def test_no_fields(self, client):
        mock_mgr = MagicMock()
        mock_mgr.update.return_value = False
        with patch("kb.knowledge_base.KnowledgeBaseManager", return_value=mock_mgr):
            resp = client.put("/admin/kb/kb_1", json={})
        assert resp.status_code == 400

    def test_error(self, client):
        with patch("kb.knowledge_base.KnowledgeBaseManager", side_effect=Exception("fail")):
            resp = client.put("/admin/kb/kb_1", json={"name": "x"})
        assert resp.status_code == 500


class TestDeleteKB:
    def test_success(self, client):
        mock_mgr = MagicMock()
        with patch("kb.knowledge_base.KnowledgeBaseManager", return_value=mock_mgr):
            resp = client.delete("/admin/kb/kb_1")
        assert resp.status_code == 200

    def test_error(self, client):
        mock_mgr = MagicMock()
        mock_mgr.delete.side_effect = Exception("fail")
        with patch("kb.knowledge_base.KnowledgeBaseManager", return_value=mock_mgr):
            resp = client.delete("/admin/kb/kb_1")
        assert resp.status_code == 500


class TestKBStats:
    def test_success(self, client):
        mock_mgr = MagicMock()
        mock_mgr.get_stats.return_value = {"doc_count": 10, "chunk_count": 50}
        with patch("kb.knowledge_base.KnowledgeBaseManager", return_value=mock_mgr):
            resp = client.get("/admin/kb/kb_1/stats")
        assert resp.status_code == 200
        assert resp.json()["doc_count"] == 10

    def test_error(self, client):
        with patch("kb.knowledge_base.KnowledgeBaseManager", side_effect=Exception("fail")):
            resp = client.get("/admin/kb/kb_1/stats")
        assert resp.status_code == 500


class TestAddDocumentsToKB:
    def test_success(self, client):
        mock_mgr = MagicMock()
        mock_mgr.add_documents_batch.return_value = 3
        with patch("kb.knowledge_base.KnowledgeBaseManager", return_value=mock_mgr):
            resp = client.post("/admin/kb/kb_1/documents",
                               json={"doc_ids": ["d1", "d2", "d3"]})
        assert resp.status_code == 200
        assert resp.json()["count"] == 3

    def test_error(self, client):
        with patch("kb.knowledge_base.KnowledgeBaseManager", side_effect=Exception("fail")):
            resp = client.post("/admin/kb/kb_1/documents",
                               json={"doc_ids": ["d1"]})
        assert resp.status_code == 500


class TestGetKBDocuments:
    def test_success(self, client):
        mock_mgr = MagicMock()
        mock_mgr.get_documents.return_value = {"items": [], "total": 0}
        with patch("kb.knowledge_base.KnowledgeBaseManager", return_value=mock_mgr):
            resp = client.get("/admin/kb/kb_1/documents")
        assert resp.status_code == 200

    def test_error(self, client):
        with patch("kb.knowledge_base.KnowledgeBaseManager", side_effect=Exception("fail")):
            resp = client.get("/admin/kb/kb_1/documents")
        assert resp.status_code == 500


# ═══════════════════════════ Langfuse 追踪 ═════════════════════════════════════

class TestListTraces:
    def test_success(self, client):
        mock_tracer = MagicMock()
        mock_tracer.list_traces.return_value = [{"id": "t1", "name": "trace1"}]
        with patch("monitoring.langfuse_tracer.get_tracer", return_value=mock_tracer):
            resp = client.get("/admin/traces?limit=10")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_error(self, client):
        with patch("monitoring.langfuse_tracer.get_tracer", side_effect=Exception("fail")):
            resp = client.get("/admin/traces")
        assert resp.status_code == 500


class TestGetTraceDetail:
    def test_success(self, client):
        mock_tracer = MagicMock()
        mock_tracer.get_trace.return_value = {"id": "t1", "name": "trace1"}
        with patch("monitoring.langfuse_tracer.get_tracer", return_value=mock_tracer):
            resp = client.get("/admin/traces/t1")
        assert resp.status_code == 200
        assert resp.json()["id"] == "t1"

    def test_not_found(self, client):
        mock_tracer = MagicMock()
        mock_tracer.get_trace.return_value = None
        with patch("monitoring.langfuse_tracer.get_tracer", return_value=mock_tracer):
            resp = client.get("/admin/traces/missing")
        assert resp.status_code == 404

    def test_error(self, client):
        with patch("monitoring.langfuse_tracer.get_tracer", side_effect=Exception("fail")):
            resp = client.get("/admin/traces/t1")
        assert resp.status_code == 500


# ═══════════════════════════ CMRC 2018 评测 ════════════════════════════════════

class TestCMRCIndex:
    def test_success(self, client):
        mock_evaluator = MagicMock()
        mock_evaluator.load_and_index_all_splits.return_value = (["d1", "d2"], 20)

        mock_kb = MagicMock()
        mock_kb.to_dict.return_value = {"kb_id": "kb_cmrc"}

        mock_mgr = MagicMock()
        mock_mgr.list.return_value = {"items": []}
        mock_mgr.create.return_value = mock_kb

        with patch("evaluation.cmrc_evaluator.CMRCEvaluator", return_value=mock_evaluator), \
             patch("kb.knowledge_base.KnowledgeBaseManager", return_value=mock_mgr):
            resp = client.post("/admin/evaluate/cmrc/index",
                               json={"split": "all", "kb_id": ""})
        assert resp.status_code == 200
        assert resp.json()["doc_count"] == 2

    def test_error(self, client):
        with patch("evaluation.cmrc_evaluator.CMRCEvaluator",
                   side_effect=Exception("fail")):
            resp = client.post("/admin/evaluate/cmrc/index", json={"split": "dev"})
        assert resp.status_code == 500


class TestCMRCRetrieval:
    def test_success(self, client):
        mock_evaluator = MagicMock()
        mock_evaluator.build_samples.return_value = []
        mock_evaluator.run_retrieval_eval.return_value = {"precision": 0.8}

        with patch("evaluation.cmrc_evaluator.CMRCEvaluator", return_value=mock_evaluator), \
             patch("api.admin_routes._make_query_func", return_value=MagicMock()):
            resp = client.post("/admin/evaluate/cmrc/retrieval")
        assert resp.status_code == 200
        assert resp.json()["precision"] == 0.8

    def test_error(self, client):
        with patch("evaluation.cmrc_evaluator.CMRCEvaluator",
                   side_effect=Exception("fail")):
            resp = client.post("/admin/evaluate/cmrc/retrieval")
        assert resp.status_code == 500


class TestCMRCGeneration:
    def test_success(self, client):
        mock_evaluator = MagicMock()
        mock_evaluator.build_samples.return_value = []
        mock_evaluator.run_generation_eval.return_value = {"f1": 0.75, "em": 0.6}

        with patch("evaluation.cmrc_evaluator.CMRCEvaluator", return_value=mock_evaluator), \
             patch("api.admin_routes._make_query_func", return_value=MagicMock()):
            resp = client.post("/admin/evaluate/cmrc/generation")
        assert resp.status_code == 200
        assert resp.json()["f1"] == 0.75

    def test_error(self, client):
        with patch("evaluation.cmrc_evaluator.CMRCEvaluator",
                   side_effect=Exception("fail")):
            resp = client.post("/admin/evaluate/cmrc/generation")
        assert resp.status_code == 500


class TestCMRCCleanup:
    def test_success(self, client):
        mock_evaluator = MagicMock()
        with patch("evaluation.cmrc_evaluator.CMRCEvaluator", return_value=mock_evaluator):
            resp = client.post("/admin/evaluate/cmrc/cleanup")
        assert resp.status_code == 200

    def test_error(self, client):
        with patch("evaluation.cmrc_evaluator.CMRCEvaluator",
                   side_effect=Exception("fail")):
            resp = client.post("/admin/evaluate/cmrc/cleanup")
        assert resp.status_code == 500
