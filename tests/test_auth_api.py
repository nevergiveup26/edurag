"""认证 API 端点测试（HTTP 层）"""
from unittest.mock import patch, MagicMock
import pytest
from api.auth import hash_password


# ======================== 健康检查 ========================

class TestHealthCheck:
    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        assert "version" in data

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ======================== 学生登录 ========================

class TestStudentLogin:
    def test_login_success(self, client):
        with patch("api.student_routes.MySQLDB") as mock_db_class, \
             patch("api.auth.verify_password") as mock_verify:
            mock_db = MagicMock()
            mock_db.get_user_by_username.return_value = {
                "id": "stu_001", "username": "test_student",
                "password_hash": "fake_hash", "role": "student",
            }
            mock_db_class.return_value = mock_db
            mock_verify.return_value = (True, False)

            resp = client.post("/api/v1/student/login", json={
                "username": "test_student", "password": "correct123"
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["message"] == "登录成功"
            assert data["token"]
            assert data["user"]["role"] == "student"
            assert data["user"]["username"] == "test_student"

    def test_wrong_password(self, client):
        with patch("api.student_routes.MySQLDB") as mock_db_class, \
             patch("api.auth.verify_password") as mock_verify:
            mock_db = MagicMock()
            mock_db.get_user_by_username.return_value = {
                "id": "stu_001", "username": "test_student",
                "password_hash": "fake_hash", "role": "student",
            }
            mock_db_class.return_value = mock_db
            mock_verify.return_value = (False, False)

            resp = client.post("/api/v1/student/login", json={
                "username": "test_student", "password": "wrong"
            })
            assert resp.status_code == 401

    def test_user_not_found(self, client):
        with patch("api.student_routes.MySQLDB") as mock_db_class:
            mock_db = MagicMock()
            mock_db.get_user_by_username.return_value = None
            mock_db_class.return_value = mock_db

            resp = client.post("/api/v1/student/login", json={
                "username": "no_such_user", "password": "irrelevant"
            })
            assert resp.status_code == 401

    def test_wrong_role_rejected(self, client):
        """学生端点拒绝 admin 角色登录"""
        with patch("api.student_routes.MySQLDB") as mock_db_class, \
             patch("api.auth.verify_password") as mock_verify:
            mock_db = MagicMock()
            mock_db.get_user_by_username.return_value = {
                "id": "admin_001", "username": "admin_user",
                "password_hash": "fake_hash", "role": "admin",
            }
            mock_db_class.return_value = mock_db
            mock_verify.return_value = (True, False)

            resp = client.post("/api/v1/student/login", json={
                "username": "admin_user", "password": "correct123"
            })
            assert resp.status_code == 403


# ======================== 管理登录 ========================

class TestAdminLogin:
    def test_login_success(self, client):
        with patch("api.admin_routes.MySQLDB") as mock_db_class, \
             patch("api.auth.verify_password") as mock_verify:
            mock_db = MagicMock()
            mock_db.get_user_by_username.return_value = {
                "id": "admin_001", "username": "admin_user",
                "password_hash": "fake_hash", "role": "admin",
            }
            mock_db_class.return_value = mock_db
            mock_verify.return_value = (True, False)

            resp = client.post("/api/v1/admin/login", json={
                "username": "admin_user", "password": "correct123"
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["message"] == "登录成功"
            assert data["user"]["role"] == "admin"

    def test_wrong_password(self, client):
        with patch("api.admin_routes.MySQLDB") as mock_db_class, \
             patch("api.auth.verify_password") as mock_verify:
            mock_db = MagicMock()
            mock_db.get_user_by_username.return_value = {
                "id": "admin_001", "username": "admin_user",
                "password_hash": "fake_hash", "role": "admin",
            }
            mock_db_class.return_value = mock_db
            mock_verify.return_value = (False, False)

            resp = client.post("/api/v1/admin/login", json={
                "username": "admin_user", "password": "wrong"
            })
            assert resp.status_code == 401

    def test_student_role_rejected(self, client):
        """管理端点拒绝 student 角色登录"""
        with patch("api.admin_routes.MySQLDB") as mock_db_class, \
             patch("api.auth.verify_password") as mock_verify:
            mock_db = MagicMock()
            mock_db.get_user_by_username.return_value = {
                "id": "stu_001", "username": "student_user",
                "password_hash": "fake_hash", "role": "student",
            }
            mock_db_class.return_value = mock_db
            mock_verify.return_value = (True, False)

            resp = client.post("/api/v1/admin/login", json={
                "username": "student_user", "password": "correct123"
            })
            assert resp.status_code == 403


# ======================== 未授权访问 ========================

class TestUnauthorizedAccess:
    def test_no_token_student_endpoint(self, client):
        resp = client.get("/api/v1/student/history")
        assert resp.status_code == 401

    def test_no_token_admin_endpoint(self, client):
        resp = client.get("/api/v1/admin/stats")
        assert resp.status_code == 401

    def test_expired_token(self, client, expired_token):
        resp = client.get("/api/v1/student/history", headers={
            "Authorization": f"Bearer {expired_token}"
        })
        assert resp.status_code == 401

    def test_invalid_token_format(self, client):
        resp = client.get("/api/v1/student/history", headers={
            "Authorization": "Basic dGVzdDp0ZXN0"
        })
        assert resp.status_code == 401


# ======================== 角色越权 ========================

class TestRoleEscalation:
    def test_student_token_on_admin_endpoint(self, client, student_token):
        resp = client.get("/api/v1/admin/stats", headers={
            "Authorization": f"Bearer {student_token}"
        })
        assert resp.status_code == 403

    def test_admin_token_on_student_endpoint(self, client, admin_token):
        resp = client.get("/api/v1/student/history", headers={
            "Authorization": f"Bearer {admin_token}"
        })
        assert resp.status_code == 403


# ======================== Token 刷新 ========================

class TestTokenRefresh:
    def test_refresh_success(self, client, student_token):
        resp = client.post("/api/v1/auth/refresh", json={
            "refresh_token": student_token
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data

    def test_refresh_invalid_token(self, client):
        resp = client.post("/api/v1/auth/refresh", json={
            "refresh_token": "invalid.token.here"
        })
        assert resp.status_code == 401


# ======================== 登出 ========================

class TestLogout:
    def test_logout_ok(self, client, student_token):
        resp = client.post("/api/v1/auth/logout", json={
            "token": student_token
        })
        assert resp.status_code == 200
        assert resp.json()["message"] == "已登出"

    def test_logout_via_header(self, client, student_token):
        resp = client.post("/api/v1/auth/logout", json={}, headers={
            "Authorization": f"Bearer {student_token}"
        })
        assert resp.status_code == 200
