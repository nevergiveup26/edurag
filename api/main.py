"""
FastAPI主入口
应用初始化和配置
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from core.config_manager import ConfigManager
from core.logger import get_logger

logger = get_logger("api_main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("=" * 50)
    logger.info("EduRAG智慧问答系统启动中...")
    
    # 初始化MySQL
    try:
        from database.mysql_db import MySQLDB
        db = MySQLDB()
        db.init_tables()
        logger.info("✓ MySQL初始化完成")
    except Exception as e:
        logger.warning(f"⚠ MySQL初始化失败 (系统仍可运行): {e}")
    
    # 初始化Milvus
    try:
        from database.milvus_db import MilvusDB
        milvus = MilvusDB()
        milvus.connect()
        milvus.create_collection()
        logger.info("✓ Milvus初始化完成")
    except Exception as e:
        logger.warning(f"⚠ Milvus初始化失败 (系统仍可运行): {e}")
    
    # 初始化Redis
    try:
        from database.redis_cache import get_redis_cache
        get_redis_cache()
        logger.info("✓ Redis初始化完成")
    except Exception as e:
        logger.warning(f"⚠ Redis初始化失败 (系统仍可运行): {e}")
    
    # 预热 LangGraph Agent
    from langgraph_agent.chat_agent import create_chat_agent
    from langgraph_agent.model import create_chat_model
    _ = create_chat_agent(model=create_chat_model())
    logger.info("✓ LangGraph Agent 已预热")
    
    # 初始化默认知识库（数学/语文/英语）
    try:
        from kb.knowledge_base import KnowledgeBaseManager
        kb_mgr = KnowledgeBaseManager()
        default_kbs = [
            ("数学", "k12数学知识库，包含k12全部知识点、例题和练习题"),
            ("语文", "k12语文知识库，包含k12重点课文解析、古诗文汇总和作文指导"),
            ("英语", "k12英语知识库，包含k12词汇表和核心语法总结"),
        ]
        for name, desc in default_kbs:
            # 检查是否已存在，不存在则创建
            existing = kb_mgr.search_knowledge_bases(name)
            if not any(kb.get("name") == name for kb in existing):
                kb = kb_mgr.create(name, desc, category=name, tags=["六年级", "上册"])
                logger.info(f"✓ 创建默认知识库「{name}」({kb.kb_id})")
            else:
                logger.info(f"✓ 默认知识库「{name}」已存在")
    except Exception as e:
        logger.warning(f"⚠ 默认知识库初始化失败: {e}")
    
    logger.info("EduRAG智慧问答系统启动完成 ✓")
    logger.info("=" * 50)
    
    yield

    # ======== 资源清理 ========
    logger.info("EduRAG智慧问答系统关闭中...")

    # 关闭 MySQL 连接池
    try:
        from database.mysql_db import _pool
        if _pool:
            _pool.close()
            logger.info("✓ MySQL 连接池已关闭")
    except Exception as e:
        logger.warning(f"MySQL 连接池关闭失败: {e}")

    # 断开 Milvus
    try:
        from pymilvus import connections
        connections.disconnect("default")
        logger.info("✓ Milvus 连接已断开")
    except Exception as e:
        logger.warning(f"Milvus 连接断开失败: {e}")
        pass

    # 关闭 Redis
    try:
        from database.redis_cache import get_redis_cache
        cache = get_redis_cache()
        if cache and cache._client:
            cache._client.close()
            logger.info("✓ Redis 连接已关闭")
    except Exception as e:
        logger.warning(f"Redis 连接关闭失败: {e}")

    logger.info("系统已安全关闭 ✓")


def create_app() -> FastAPI:
    """创建FastAPI应用"""
    config = ConfigManager()
    system_config = config.system_config
    
    app = FastAPI(
        title=system_config.get("app_name", "EduRAG智慧问答系统"),
        description="基于RAG技术的智能问答系统",
        version="1.0.0",
        debug=system_config.get("debug", False),
        lifespan=lifespan
    )
    
    # CORS配置
    origins_env = os.getenv("EDURAG_CORS_ORIGINS", "http://localhost:5173")
    allow_origins = [o.strip() for o in origins_env.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 注册路由 — 缺失依赖时不阻塞启动
    # tier 1：公共路由
    try:
        from api.routes import router
        app.include_router(router, prefix="/api/v1")
    except ImportError as e:
        logger.warning(f"公共路由模块未加载: {e}")

    # tier 2：Agent 路由
    try:
        from api.agent_routes import agent_router
        app.include_router(agent_router, prefix="/api/v1")
    except ImportError as e:
        logger.warning(f"Agent路由模块未加载: {e}")

    # tier 3：学生端路由
    try:
        from api.student_routes import student_router
        app.include_router(student_router, prefix="/api/v1")
    except ImportError as e:
        logger.warning(f"学生端模块未加载: {e}")

    # tier 4：管理端路由
    try:
        from api.admin_routes import admin_router
        app.include_router(admin_router, prefix="/api/v1")
    except ImportError as e:
        logger.warning(f"管理端模块未加载: {e}")
    
    @app.get("/")
    async def root():
        return {
            "message": "欢迎使用EduRAG智慧问答系统",
            "version": "1.0.0",
            "docs": "/docs"
        }
    
    @app.get("/health")
    async def health_check():
        return {"status": "ok"}
    
    return app


# 创建应用实例
app = create_app()
