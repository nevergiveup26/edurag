"""冒烟测试：验证完整 app 启动 + 所有路由注册 + 核心链路可达"""
import json
import pytest
from unittest.mock import MagicMock, patch


FAKE_STUDENT = {"user_id": "stu_abc", "username": "student1", "role": "student"}
FAKE_ADMIN = {"user_id": "adm_abc", "username": "admin1", "role": "admin"}


# ═══════════════════════════ fixture：完整 app ══════════════════════════════════

@pytest.fixture(scope="module")
def app():
    """创建完整 EduRAG app（跳过 lifespan，注入假用户依赖）"""
    import core.config_manager as cm
    cm.ConfigManager._instance = None
    cm.ConfigManager._config = None

    mock_parser = MagicMock()
    mock_parser.get.return_value = "test_val"
    mock_parser.has_section.return_value = False

    import importlib
    import api.main

    with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser), \
         patch.object(api.main, "lifespan"):
        importlib.reload(api.main)
        app = api.main.create_app()

    # 注入假用户依赖，避免真实 JWT 校验阻断请求
    from api.auth import require_student, require_admin

    async def fake_student():
        return FAKE_STUDENT

    async def fake_admin():
        return FAKE_ADMIN

    app.dependency_overrides[require_student] = fake_student
    app.dependency_overrides[require_admin] = fake_admin

    yield app

    cm.ConfigManager._instance = None
    cm.ConfigManager._config = None


@pytest.fixture(scope="module")
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)


# ═══════════════════════════ 1. 应用启动 ════════════════════════════════════════

def test_app_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_app_root(client):
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "EduRAG" in data["message"]
    assert data["version"] == "1.0.0"


# ═══════════════════════════ 2. 路由注册完整性 ══════════════════════════════════

ROUTES_EXPECTED = {
    # 公共路由 (routes.py)
    "POST:/api/v1/auth/refresh",
    "POST:/api/v1/auth/logout",
    "GET:/api/v1/documents",
    "GET:/api/v1/stats",
    "POST:/api/v1/feedback",
    "GET:/api/v1/feedback/quality",
    "GET:/api/v1/feedback/list",
    "GET:/api/v1/faq",
    "POST:/api/v1/upload",
    # Agent 路由 (agent_routes.py)
    "POST:/api/v1/agent/query",
    "POST:/api/v1/agent/query/stream",
    # 学生端 (student_routes.py)
    "POST:/api/v1/student/login",
    "POST:/api/v1/student/register",
    "GET:/api/v1/student/history",
    "POST:/api/v1/student/conversation",
    "GET:/api/v1/student/conversations",
    "POST:/api/v1/student/agent/query",
    "POST:/api/v1/student/agent/query/stream",
    "GET:/api/v1/student/agent/tools",
    "POST:/api/v1/student/agent/grade",
    "POST:/api/v1/student/agent/grade/stream",
    "GET:/api/v1/student/wrong-book",
    "GET:/api/v1/student/wrong-book/stats",
    "POST:/api/v1/student/photo-search",
    "GET:/api/v1/student/graph/data",
    "GET:/api/v1/student/graph/stats",
    # 管理端 (admin_routes.py)
    "POST:/api/v1/admin/login",
    "GET:/api/v1/admin/stats",
    "POST:/api/v1/admin/kb",
    "GET:/api/v1/admin/kb",
    "GET:/api/v1/admin/evaluate/history",
    "GET:/api/v1/admin/traces",
}


def test_all_routes_registered(app):
    registered = set()
    for route in app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            for method in route.methods:
                if method not in ("HEAD", "OPTIONS"):
                    registered.add(f"{method}:{route.path}")

    missing = ROUTES_EXPECTED - registered
    assert not missing, f"缺失路由: {missing}"


# ═══════════════════════════ 3. 核心链路冒烟 ═══════════════════════════════════

class TestCoreSmoke:
    # ── 学生端：登录 → 提问 → 拿到回答 ──

    def test_student_chat_flow(self, client):
        mock_db = MagicMock()
        mock_db.get_user_by_username.return_value = {
            "id": "stu_1", "username": "u1", "role": "student",
            "password_hash": "hashed",
        }

        mock_agent = MagicMock()
        async def mock_ainvoke(input_data):
            msg = MagicMock()
            msg.content = "三角形面积 = 底 × 高 ÷ 2"
            del msg.tool_calls
            return {"messages": [msg]}
        mock_agent.ainvoke = mock_ainvoke

        with patch("api.student_routes.MySQLDB", return_value=mock_db), \
             patch("api.auth.verify_password", return_value=(True, False)), \
             patch("api.auth.create_token", return_value="smoke_token"), \
             patch("api.student_routes._get_cached_retriever", return_value=MagicMock()), \
             patch("langgraph_agent.chat_agent.create_chat_agent", return_value=mock_agent), \
             patch("langgraph_agent.chat_agent.build_agent_system_prompt", return_value=""), \
             patch("langgraph_agent.model.create_chat_model"), \
             patch("llm.llm_client.LLMClient"), \
             patch("api.student_routes.save_conversation_message"), \
             patch("monitoring.langfuse_tracer.start_trace", return_value=None):

            # Step 1: 登录
            login_resp = client.post("/api/v1/student/login",
                                     json={"username": "u1", "password": "pwd"})
            assert login_resp.status_code == 200, login_resp.text
            assert login_resp.json()["token"] == "smoke_token"

            # Step 2: 提问
            query_resp = client.post("/api/v1/student/agent/query",
                                     json={"query": "三角形面积公式"})
            assert query_resp.status_code == 200, query_resp.text
            assert "三角形" in query_resp.json()["answer"]

    # ── 管理端：登录 → 查看统计 ──

    def test_admin_stats_flow(self, client):
        mock_db = MagicMock()
        mock_db.get_user_by_username.return_value = {
            "id": "adm_1", "username": "admin1", "role": "admin",
            "password_hash": "hashed",
        }
        mock_db.get_feedback_stats.return_value = {"avg_rating": 4.2}
        mock_db.query_one.side_effect = [
            {"cnt": 50}, {"cnt": 5}, {"cnt": 100}, {"cnt": 200},
        ]
        mock_db.query.return_value = []

        with patch("api.admin_routes.MySQLDB", return_value=mock_db), \
             patch("api.auth.verify_password", return_value=(True, False)), \
             patch("api.auth.create_token", return_value="admin_token"), \
             patch("database.chunk_store.get_chunk_count", return_value=500):

            # Step 1: 登录
            login_resp = client.post("/api/v1/admin/login",
                                     json={"username": "admin1", "password": "pwd"})
            assert login_resp.status_code == 200, login_resp.text
            assert login_resp.json()["token"] == "admin_token"

            # Step 2: 查看统计
            stats_resp = client.get("/api/v1/admin/stats")
            assert stats_resp.status_code == 200, stats_resp.text
            assert stats_resp.json()["total_documents"] == 50

    # ── 公共路由：无需认证的端点 ──

    def test_public_documents(self, client):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {"id": "d1", "title": "小学数学", "source": "人教版",
             "created_at": "2024-01-01"},
        ]
        mock_db.query_one.return_value = {"total": 1}

        with patch("database.mysql_db.MySQLDB", return_value=mock_db):
            resp = client.get("/api/v1/documents?page=1&page_size=10")
        assert resp.status_code == 200, resp.text
        assert resp.json()["total"] == 1

    def test_public_stats(self, client):
        mock_db = MagicMock()
        mock_db.query_one.return_value = {"count": 42}

        with patch("database.mysql_db.MySQLDB", return_value=mock_db), \
             patch("database.chunk_store.get_chunk_count", return_value=200):
            resp = client.get("/api/v1/stats")
        assert resp.status_code == 200, resp.text
        assert resp.json()["total_documents"] == 42

    # ── 边界行为 ──

    def test_empty_query_rejected(self, client):
        resp = client.post("/api/v1/student/agent/query", json={"query": ""})
        assert resp.status_code == 422

    def test_unknown_route_404(self, client):
        resp = client.get("/api/v1/nonexistent")
        assert resp.status_code == 404
