"""
测试共享 fixtures
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from contextlib import asynccontextmanager


@asynccontextmanager
async def empty_lifespan(app: FastAPI):
    """空 lifespan，跳过 MySQL/Milvus/Redis 连接"""
    yield


def create_test_app():
    """创建测试用 FastAPI 应用（无基础设施依赖）"""
    app = FastAPI(lifespan=empty_lifespan)

    # 按 main.py 相同顺序注册路由，缺失依赖时不阻塞
    try:
        from api.routes import router
        app.include_router(router, prefix="/api/v1")
    except ImportError:
        pass

    try:
        from api.agent_routes import agent_router
        app.include_router(agent_router, prefix="/api/v1")
    except ImportError:
        pass

    try:
        from api.student_routes import student_router
        app.include_router(student_router, prefix="/api/v1")
    except ImportError:
        pass

    try:
        from api.admin_routes import admin_router
        app.include_router(admin_router, prefix="/api/v1")
    except ImportError:
        pass

    @app.get("/")
    async def root():
        return {"message": "EduRAG Test", "version": "1.0.0", "docs": "/docs"}

    @app.get("/health")
    async def health_check():
        return {"status": "ok"}

    return app


@pytest.fixture
def app():
    return create_test_app()


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def student_token():
    from api.auth import create_token
    return create_token("test_student_1", "testuser", "student")


@pytest.fixture
def admin_token():
    from api.auth import create_token
    return create_token("test_admin_1", "adminuser", "admin")


@pytest.fixture
def expired_token():
    from api.auth import create_token
    return create_token("expired_user", "expired", "student", expire_hours=-1)
