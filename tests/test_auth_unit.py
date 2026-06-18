"""auth 模块纯函数单元测试（无外部依赖）"""
import time
import pytest
from api.auth import (
    create_token,
    decode_token,
    hash_password,
    verify_password,
    get_current_user,
    require_admin,
    require_student,
)


class TestTokenCreate:
    def test_contains_required_fields(self):
        token = create_token("user_1", "testuser", "student")
        payload = decode_token(token)
        assert payload is not None
        assert payload["user_id"] == "user_1"
        assert payload["username"] == "testuser"
        assert payload["role"] == "student"
        assert "jti" in payload
        assert "exp" in payload
        assert "iat" in payload

    def test_admin_role_preserved(self):
        token = create_token("admin_1", "adminuser", "admin")
        payload = decode_token(token)
        assert payload["role"] == "admin"

    def test_student_role_preserved(self):
        token = create_token("stu_1", "stu", "student")
        payload = decode_token(token)
        assert payload["role"] == "student"

    def test_custom_expiry(self):
        token = create_token("u", "n", "student", expire_hours=48)
        payload = decode_token(token)
        # exp should be ~48h from now (allow 5s tolerance)
        expected = int(time.time()) + 48 * 3600
        assert abs(payload["exp"] - expected) < 5


class TestTokenDecode:
    def test_valid_token(self):
        token = create_token("u1", "name", "student")
        payload = decode_token(token)
        assert payload is not None
        assert payload["user_id"] == "u1"

    def test_expired_token(self):
        token = create_token("u1", "name", "student", expire_hours=-1)
        payload = decode_token(token)
        assert payload is None

    def test_tampered_token(self):
        token = create_token("u1", "name", "student")
        # 篡改中间部分（payload）
        parts = token.split(".")
        parts[1] = "dGFtcGVyZWQ="  # base64 of "tampered"
        tampered = ".".join(parts)
        assert decode_token(tampered) is None

    def test_garbage_token(self):
        assert decode_token("not.a.jwt") is None
        assert decode_token("") is None
        assert decode_token("abc.def.ghi") is None


class TestPassword:
    def test_hash_and_verify(self):
        import bcrypt as _bcrypt
        pwd = "mypassword123"
        hashed = _bcrypt.hashpw(pwd.encode(), _bcrypt.gensalt()).decode()
        ok, need_upgrade = verify_password(pwd, hashed)
        assert ok is True
        assert need_upgrade is False

    def test_wrong_password(self):
        import bcrypt as _bcrypt
        pwd = "correct"
        hashed = _bcrypt.hashpw(pwd.encode(), _bcrypt.gensalt()).decode()
        ok, need_upgrade = verify_password("wrong", hashed)
        assert ok is False

    def test_sha256_compat_detected(self):
        import hashlib
        sha_hash = hashlib.sha256("legacy_pass".encode()).hexdigest()
        ok, need_upgrade = verify_password("legacy_pass", sha_hash)
        assert ok is True
        assert need_upgrade is True

    def test_sha256_compat_wrong(self):
        import hashlib
        sha_hash = hashlib.sha256("legacy_pass".encode()).hexdigest()
        ok, need_upgrade = verify_password("wrong_pass", sha_hash)
        assert ok is False


class TestGetCurrentUser:
    def test_no_header_raises_401(self):
        with pytest.raises(Exception) as exc_info:
            get_current_user(None)
        assert exc_info.value.status_code == 401
        assert "缺少认证信息" in exc_info.value.detail

    def test_wrong_prefix_raises_401(self):
        with pytest.raises(Exception) as exc_info:
            get_current_user("Basic YWxhZGRpbjpvcGVuIHNlc2FtZQ==")
        assert exc_info.value.status_code == 401
        assert "无效的认证格式" in exc_info.value.detail

    def test_expired_token_raises_401(self):
        token = create_token("u1", "name", "student", expire_hours=-1)
        with pytest.raises(Exception) as exc_info:
            get_current_user(f"Bearer {token}")
        assert exc_info.value.status_code == 401

    def test_valid_token_returns_payload(self):
        token = create_token("u1", "name", "student")
        payload = get_current_user(f"Bearer {token}")
        assert payload["user_id"] == "u1"
        assert payload["role"] == "student"

    def test_empty_bearer_raises_401(self):
        with pytest.raises(Exception) as exc_info:
            get_current_user("Bearer ")
        assert exc_info.value.status_code == 401


class TestRoleGuards:
    def test_require_admin_allows_admin(self):
        token = create_token("a1", "admin", "admin")
        payload = decode_token(token)
        result = require_admin(payload)
        assert result["role"] == "admin"

    def test_require_admin_blocks_student(self):
        token = create_token("s1", "stu", "student")
        payload = decode_token(token)
        with pytest.raises(Exception) as exc_info:
            require_admin(payload)
        assert exc_info.value.status_code == 403

    def test_require_student_allows_student(self):
        token = create_token("s1", "stu", "student")
        payload = decode_token(token)
        result = require_student(payload)
        assert result["role"] == "student"

    def test_require_student_blocks_admin(self):
        token = create_token("a1", "admin", "admin")
        payload = decode_token(token)
        with pytest.raises(Exception) as exc_info:
            require_student(payload)
        assert exc_info.value.status_code == 403
