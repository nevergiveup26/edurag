"""
JWT 鉴权模块
"""
import hashlib
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional, Tuple

import jwt
from fastapi import Depends, HTTPException, Header
from passlib.hash import bcrypt
from core.logger import get_logger

logger = get_logger("auth")

SECRET_KEY = os.getenv("EDURAG_JWT_SECRET", "edurag-2024-jwt-production-secret-key-change-in-env")
if not os.getenv("EDURAG_JWT_SECRET"):
    import warnings
    warnings.warn(
        "EDURAG_JWT_SECRET 未设置，使用默认密钥。生产环境必须通过环境变量设置！",
        RuntimeWarning,
    )
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24


# ======================== Token 黑名单（Redis） ========================

def _get_redis():
    """获取 Redis 客户端，不可用时返回 None"""
    try:
        from database.redis_cache import get_redis_cache
        cache = get_redis_cache()
        if cache and cache._client:
            return cache._client
    except Exception:
        logger.debug("Redis 不可用，黑名单功能将跳过")
    return None


def _is_token_revoked(jti: str) -> bool:
    """检查 token 是否已被吊销"""
    r = _get_redis()
    if r is None:
        return False
    return r.exists(f"revoked_token:{jti}")


def revoke_token(token: str) -> bool:
    """将 token 加入黑名单（基于 JTI）"""
    payload = decode_token(token)
    if payload is None:
        return False
    jti = payload.get("jti")
    if not jti:
        return False
    r = _get_redis()
    if r is None:
        return False
    now = datetime.utcnow()
    exp = datetime.fromtimestamp(payload["exp"]) if "exp" in payload else now
    ttl = int((exp - now).total_seconds())
    if ttl <= 0:
        return False
    r.setex(f"revoked_token:{jti}", ttl, "1")
    logger.info(f"Token 已吊销: jti={jti[:8]}..., ttl={ttl}s")
    return True


# ======================== 密码处理 ========================

def hash_password(password: str) -> str:
    return bcrypt.hash(password)


def verify_password(password: str, hashed: str) -> Tuple[bool, bool]:
    """验证密码，返回 (是否通过, 是否需要升级hash)

    兼容旧的 SHA256 哈希：如果 bcrypt 不匹配且 hashed 是 64 位 hex，
    用 SHA256 再试一次，匹配则标记为需要升级。
    """
    try:
        if bcrypt.verify(password, hashed):
            return True, False
    except ValueError:
        pass

    if len(hashed) == 64:
        try:
            int(hashed, 16)
            if hashlib.sha256(password.encode()).hexdigest() == hashed:
                return True, True
        except ValueError:
            pass
    return False, False


# ======================== Token 创建/验证 ========================

def create_token(user_id: str, username: str, role: str,
                 expire_hours: int = None) -> str:
    """创建 JWT Token（含 JTI 用于吊销）"""
    payload = {
        "jti": uuid.uuid4().hex,
        "user_id": user_id,
        "username": username,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=expire_hours or TOKEN_EXPIRE_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_tokens(user_id: str, username: str, role: str) -> dict:
    """创建 Access Token + Refresh Token"""
    access_token = create_token(user_id, username, role, expire_hours=1)
    refresh_token = create_token(user_id, username, role, expire_hours=168)  # 7天
    return {"access_token": access_token, "refresh_token": refresh_token}


def refresh_access_token(refresh_token: str) -> Optional[str]:
    """使用 Refresh Token 换取新的 Access Token"""
    payload = decode_token(refresh_token)
    if payload is None:
        return None
    if _is_token_revoked(payload.get("jti", "")):
        return None
    return create_token(
        user_id=payload["user_id"],
        username=payload["username"],
        role=payload["role"],
        expire_hours=1,
    )


def decode_token(token: str) -> Optional[dict]:
    """解析 JWT Token"""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# ======================== 依赖注入 ========================

def get_current_user(authorization: str = Header(None)) -> dict:
    """从请求头获取当前用户（含吊销检查）"""
    if authorization is None:
        raise HTTPException(status_code=401, detail="缺少认证信息，请先登录")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="无效的认证格式")
    token = authorization[7:]
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Token 已过期或无效")
    jti = payload.get("jti")
    if jti and _is_token_revoked(jti):
        raise HTTPException(status_code=401, detail="Token 已被吊销")
    return payload


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """要求管理员角色"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def require_student(user: dict = Depends(get_current_user)) -> dict:
    """要求学生角色"""
    if user.get("role") != "student":
        raise HTTPException(status_code=403, detail="需要学生权限")
    return user