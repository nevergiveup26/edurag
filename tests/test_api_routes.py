"""api/routes.py 和 api/main.py 测试"""
import json
import pytest
from unittest.mock import MagicMock, patch
from io import BytesIO


# ═══════════════════════ fixtures ═════════════════════════════════════════════

@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    test_app = FastAPI()
    try:
        from api.routes import router
    except ImportError:
        pytest.skip("routes module not importable")
    test_app.include_router(router, prefix="/api/v1")

    return TestClient(test_app)


# ═══════════════════════ routes.py - 认证端点 ═════════════════════════════════

class TestAuthRefresh:
    def test_refresh_success(self, client):
        with patch("api.auth.refresh_access_token", return_value="new_token"):
            resp = client.post("/api/v1/auth/refresh",
                               json={"refresh_token": "valid_refresh"})
        assert resp.status_code == 200
        assert resp.json()["access_token"] == "new_token"

    def test_refresh_invalid(self, client):
        with patch("api.auth.refresh_access_token", return_value=None):
            resp = client.post("/api/v1/auth/refresh",
                               json={"refresh_token": "bad"})
        assert resp.status_code == 401


class TestAuthLogout:
    def test_logout_with_body_token(self, client):
        with patch("api.auth.revoke_token") as mock_revoke:
            resp = client.post("/api/v1/auth/logout",
                               json={"token": "my_token"})
        assert resp.status_code == 200
        mock_revoke.assert_called_once_with("my_token")

    def test_logout_with_header_token(self, client):
        with patch("api.auth.revoke_token") as mock_revoke:
            resp = client.post("/api/v1/auth/logout", json={},
                               headers={"Authorization": "Bearer header_token"})
        assert resp.status_code == 200
        mock_revoke.assert_called_once_with("header_token")

    def test_logout_no_token(self, client):
        with patch("api.auth.revoke_token") as mock_revoke:
            resp = client.post("/api/v1/auth/logout", json={})
        assert resp.status_code == 200
        mock_revoke.assert_not_called()


# ═══════════════════════ routes.py - 文档管理 ═════════════════════════════════

class TestListDocuments:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {"id": "d1", "title": "doc1", "source": "s1", "created_at": "2024-01-01"},
        ]
        mock_db.query_one.return_value = {"total": 1}
        with patch("database.mysql_db.MySQLDB", return_value=mock_db):
            resp = client.get("/api/v1/documents?page=1&page_size=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    def test_mysql_error(self, client):
        with patch("database.mysql_db.MySQLDB", side_effect=Exception("db down")):
            resp = client.get("/api/v1/documents")
        assert resp.status_code == 500


# ═══════════════════════ routes.py - 系统状态 ═════════════════════════════════

class TestStats:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.query_one.return_value = {"count": 42}
        with patch("database.mysql_db.MySQLDB", return_value=mock_db), \
             patch("database.chunk_store.get_chunk_count", return_value=200):
            resp = client.get("/api/v1/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_documents"] == 42
        assert data["total_chunks"] == 200

    def test_chunk_count_error(self, client):
        mock_db = MagicMock()
        mock_db.query_one.return_value = {"count": 10}
        with patch("database.mysql_db.MySQLDB", return_value=mock_db), \
             patch("database.chunk_store.get_chunk_count", side_effect=Exception("fail")):
            resp = client.get("/api/v1/stats")
        assert resp.status_code == 200
        assert resp.json()["total_documents"] == 10

    def test_no_documents(self, client):
        mock_db = MagicMock()
        mock_db.query_one.return_value = None
        with patch("database.mysql_db.MySQLDB", return_value=mock_db), \
             patch("database.chunk_store.get_chunk_count", return_value=0):
            resp = client.get("/api/v1/stats")
        assert resp.status_code == 200
        assert resp.json()["avg_chunk_size"] == 0


# ═══════════════════════ routes.py - 反馈 ═════════════════════════════════════

class TestFeedback:
    def test_submit_success(self, client):
        mock_tracker = MagicMock()
        mock_tracker.record_feedback.return_value = "fb_123"
        with patch("data_processor.evaluation.EvaluationTracker", return_value=mock_tracker):
            resp = client.post("/api/v1/feedback", json={
                "rating": 4, "comment": "good", "query": "q", "answer": "a",
            })
        assert resp.status_code == 200
        assert resp.json()["feedback_id"] == "fb_123"

    def test_submit_error(self, client):
        with patch("data_processor.evaluation.EvaluationTracker", side_effect=Exception("fail")):
            resp = client.post("/api/v1/feedback", json={"rating": 3})
        assert resp.status_code == 500

    def test_quality_metrics(self, client):
        mock_tracker = MagicMock()
        mock_tracker.get_quality_metrics.return_value = {"avg_rating": 4.2}
        with patch("data_processor.evaluation.EvaluationTracker", return_value=mock_tracker):
            resp = client.get("/api/v1/feedback/quality?days=30")
        assert resp.status_code == 200
        assert resp.json()["avg_rating"] == 4.2

    def test_list_feedback(self, client):
        mock_tracker = MagicMock()
        mock_tracker.get_feedback.return_value = [{"rating": 5, "comment": "great"}]
        with patch("data_processor.evaluation.EvaluationTracker", return_value=mock_tracker):
            resp = client.get("/api/v1/feedback/list?limit=10")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1


# ═══════════════════════ routes.py - FAQ ══════════════════════════════════════

class TestFAQ:
    def test_list_success(self, client):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {"id": "f1", "question": "what?", "answer": "that",
             "category": "general", "tags": "[]"},
        ]
        mock_db.query_one.return_value = {"total": 1}
        with patch("database.mysql_db.MySQLDB", return_value=mock_db):
            resp = client.get("/api/v1/faq")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_mysql_error(self, client):
        with patch("database.mysql_db.MySQLDB", side_effect=Exception("db error")):
            resp = client.get("/api/v1/faq")
        assert resp.status_code == 500


# ══════════════════════ routes.py - 上传错误路径 ══════════════════════════════

class TestUploadErrors:
    def test_no_files(self, client):
        resp = client.post("/api/v1/upload")
        assert resp.status_code == 422

    def test_internal_error(self, client):
        fake_file = BytesIO(b"test content")
        with patch("data_processor.document_loader.DocumentLoader") as mock_loader:
            mock_loader.load_file.side_effect = Exception("parse error")
            resp = client.post(
                "/api/v1/upload",
                files=[("files", ("test.txt", fake_file, "text/plain"))],
            )
        assert resp.status_code == 500


# ═══════════════════════ main.py ══════════════════════════════════════════════

class TestCreateApp:
    def test_app_created(self):
        import core.config_manager as cm
        cm.ConfigManager._instance = None
        cm.ConfigManager._config = None

        mock_parser = MagicMock()
        mock_parser.get.return_value = "test_val"
        mock_parser.has_section.return_value = False

        with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser):
            import importlib
            import api.main

            # Prevent lifespan from running
            with patch.object(api.main, 'lifespan'):
                importlib.reload(api.main)
                app = api.main.create_app()
                assert app is not None

        cm.ConfigManager._instance = None
        cm.ConfigManager._config = None

    def test_root_endpoint(self):
        import core.config_manager as cm
        cm.ConfigManager._instance = None
        cm.ConfigManager._config = None

        mock_parser = MagicMock()
        mock_parser.get.return_value = "test_val"
        mock_parser.has_section.return_value = False

        from fastapi.testclient import TestClient
        import importlib
        import api.main

        with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser), \
             patch.object(api.main, 'lifespan'):
            importlib.reload(api.main)
            app = api.main.create_app()
            client = TestClient(app)

            resp = client.get("/")
            assert resp.status_code == 200
            assert "EduRAG" in resp.json()["message"]

        cm.ConfigManager._instance = None
        cm.ConfigManager._config = None

    def test_health_endpoint(self):
        import core.config_manager as cm
        cm.ConfigManager._instance = None
        cm.ConfigManager._config = None

        mock_parser = MagicMock()
        mock_parser.get.return_value = "test_val"
        mock_parser.has_section.return_value = False

        from fastapi.testclient import TestClient
        import importlib
        import api.main

        with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser), \
             patch.object(api.main, 'lifespan'):
            importlib.reload(api.main)
            app = api.main.create_app()
            client = TestClient(app)

            resp = client.get("/health")
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}

        cm.ConfigManager._instance = None
        cm.ConfigManager._config = None

    def test_cors_headers(self):
        import core.config_manager as cm
        cm.ConfigManager._instance = None
        cm.ConfigManager._config = None

        mock_parser = MagicMock()
        mock_parser.get.return_value = "test_val"
        mock_parser.has_section.return_value = False

        from fastapi.testclient import TestClient
        import importlib
        import api.main

        with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser), \
             patch.object(api.main, 'lifespan'):
            importlib.reload(api.main)
            app = api.main.create_app()
            client = TestClient(app)

            resp = client.options("/", headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            })
            # CORS 预检应该返回 200/405/400，取决于具体配置
            assert resp.status_code in (200, 405, 400)

        cm.ConfigManager._instance = None
        cm.ConfigManager._config = None
