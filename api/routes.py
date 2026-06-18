"""
API路由定义
上传、FAQ、反馈、系统状态等基础端点
（Agent 端点已拆分至 api/agent_routes.py）
"""
import uuid
import os
import json
import threading
from typing import Optional, List

from fastapi import APIRouter, HTTPException, UploadFile, File, Query, Header
from pydantic import BaseModel, Field

from core.logger import get_logger
from api.shared_models import UploadResponse, FeedbackRequest

logger = get_logger("api_routes")

router = APIRouter()

# ======================== 认证端点（共享） ========================

class TokenRefreshRequest(BaseModel):
    refresh_token: str = Field(..., description="Refresh Token")

class TokenRevokeRequest(BaseModel):
    token: Optional[str] = Field(default=None, description="要吊销的 token（不传则从 Authorization header 提取）")


@router.post("/auth/refresh")
async def refresh_token(req: TokenRefreshRequest):
    """刷新 Access Token"""
    from api.auth import refresh_access_token
    new_token = refresh_access_token(req.refresh_token)
    if new_token is None:
        raise HTTPException(status_code=401, detail="Refresh Token 无效或已过期")
    return {"access_token": new_token}


@router.post("/auth/logout")
async def logout_from_body(req: TokenRevokeRequest, authorization: str = Header(default="")):
    """登出并吊销 Token"""
    from api.auth import revoke_token
    token = req.token
    if not token:
        if authorization.startswith("Bearer "):
            token = authorization[7:]
    if token:
        revoke_token(token)
    return {"message": "已登出"}

# ======================== 文档管理 ========================

@router.post("/upload", response_model=UploadResponse)
async def upload_documents(
    files: List[UploadFile] = File(...),
    chunk_size: int = Query(default=1000, description="切分大小（字符数，语义模式下为目标大小）"),
    chunk_overlap: int = Query(default=80, description="重叠大小（字符数）"),
    chunk_mode: str = Query(default="semantic", description="切分模式: semantic/langchain/native"),
    kb_id: Optional[str] = Query(default=None, description="目标知识库ID，上传后自动关联"),
    enable_dedup: bool = Query(default=True, description="是否启用三层去重")
):
    """
    上传文档接口

    支持TXT、PDF、Word格式。
    自动完成：去重检测 → 文档加载 → 切分 → 向量化 → 存储MySQL+Milvus
    可选：指定 kb_id 后自动将文档关联到对应知识库

    三层递进式去重：
    1. MD5 硬去重 — 完全相同的文档直接跳过
    2. SimHash + MinHash LSH — 检测近似重复文档
    3. 向量 Chunk 去重 — 片段级相似度 ≥ 85% 过滤
    """
    try:
        from data_processor.document_loader import DocumentLoader
        from data_processor.document_splitter import DocumentSplitter
        from database.mysql_db import MySQLDB

        total_docs = 0
        total_chunks = 0
        uploaded_doc_ids = []
        skipped_duplicates = 0
        all_dedup_details = []

        splitter = DocumentSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap, mode=chunk_mode)
        mysql_db = MySQLDB()

        # 初始化去重管理器
        dedup_mgr = None
        if enable_dedup:
            try:
                from data_processor.dedup import DedupManager
                dedup_mgr = DedupManager(mysql_db, enable_tier1=True, enable_tier2=True, enable_tier3=False)
                logger.info("三层去重管理器已初始化")
            except Exception as e:
                logger.warning(f"去重管理器初始化失败（已禁用）: {e}")

        # 收集所有待后台处理的 chunk 列表
        all_chunks = []
        all_doc_ids_for_index = []

        import tempfile

        for file in files:
            suffix = os.path.splitext(file.filename or "temp.txt")[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                content = await file.read()
                tmp.write(content)
                temp_path = tmp.name

            try:
                docs = DocumentLoader.load_file(temp_path)

                # ── 元数据提取 ──
                try:
                    from data_processor.metadata_extractor import MetadataExtractor
                    meta_extractor = MetadataExtractor()
                    for doc in docs:
                        extracted_meta = meta_extractor.extract_from_document(
                            doc.content, filename=file.filename or ""
                        )
                        if extracted_meta:
                            doc.metadata.update(extracted_meta)
                except Exception as e:
                    logger.debug(f"文档元数据提取失败: {e}")

                # ── 第一/二层：文本去重（在切分前整篇检测）──
                filtered_docs = []
                reused_doc_ids = []
                if dedup_mgr:
                    for doc in docs:
                        result = dedup_mgr.check_document_duplicate(
                            doc.content, file.filename or "", kb_id=kb_id
                        )
                        if result.is_duplicate:
                            skipped_duplicates += 1
                            all_dedup_details.append(result.to_dict())
                            logger.info(f"文档去重跳过: {file.filename} (Tier {result.tier})")
                        elif kb_id and result.md5_hash:
                            global_doc = mysql_db.get_document_by_md5_global(result.md5_hash)
                            if global_doc:
                                reused_doc_ids.append(global_doc["id"])
                                logger.info(f"文档 {file.filename} 全局已存在({global_doc['id']})，直接关联到KB")
                            else:
                                filtered_docs.append(doc)
                        else:
                            filtered_docs.append(doc)
                    if not filtered_docs and not reused_doc_ids:
                        total_docs += len(docs)
                        continue
                else:
                    filtered_docs = docs

                uploaded_doc_ids.extend(reused_doc_ids)
                total_docs += len(filtered_docs) + len(reused_doc_ids)

                # 切分文档
                chunks = splitter.split_batch(filtered_docs)
                total_chunks += len(chunks)

                # 存储到MySQL（快速，在请求线程完成）
                for doc in filtered_docs:
                    doc_id = doc.doc_id or os.path.basename(temp_path)
                    mysql_db.insert_document(
                        doc_id=doc_id,
                        title=doc.title or file.filename or "",
                        source=doc.source or file.filename or "",
                        content=doc.content,
                        metadata=doc.metadata
                    )
                    uploaded_doc_ids.append(doc_id)
                    all_doc_ids_for_index.append((doc_id, doc.content))

                all_chunks.extend(chunks)

            finally:
                os.unlink(temp_path)

        # 关联知识库（快速）
        kb_name = ""
        if kb_id and uploaded_doc_ids:
            try:
                from kb.knowledge_base import KnowledgeBaseManager
                kb_mgr = KnowledgeBaseManager()
                kb = kb_mgr.get(kb_id)
                if kb:
                    kb_mgr.add_documents_batch(kb_id, uploaded_doc_ids)
                    kb_name = kb.name
                    logger.info(f"已将 {len(uploaded_doc_ids)} 个文档关联到知识库「{kb_name}」({kb_id})")
                else:
                    logger.warning(f"知识库 {kb_id} 不存在，跳过关联")
            except Exception as e:
                logger.warning(f"知识库关联失败: {e}")

        # ── 后台线程：向量化 + Milvus + chunk_store + 图谱重建（慢操作）──
        if all_chunks or all_doc_ids_for_index:
            _chunks = all_chunks
            _doc_ids_for_index = all_doc_ids_for_index
            _enable_dedup = enable_dedup
            _chunk_mode = chunk_mode

            def _background_process():
                try:
                    from data_processor.vectorizer import Vectorizer
                    from database.milvus_db import MilvusDB

                    vectorizer = Vectorizer()
                    chunks = vectorizer.embed_documents(_chunks)

                    # 第三层：向量 Chunk 去重
                    if _enable_dedup and chunks:
                        try:
                            from data_processor.dedup import DedupManager
                            _dedup_mgr = DedupManager(MySQLDB(), enable_tier1=False, enable_tier2=False, enable_tier3=True)
                            chunks, _, _ = _dedup_mgr.dedup_chunks(chunks, vectorizer)
                        except Exception as e:
                            logger.warning(f"chunk去重失败: {e}")

                    # Milvus
                    if chunks:
                        try:
                            milvus_db = MilvusDB()
                            milvus_db.insert_vectors(
                                [c.chunk_id for c in chunks],
                                [c.embedding for c in chunks],
                                [c.content for c in chunks],
                                [c.doc_id for c in chunks],
                                [c.metadata for c in chunks],
                            )
                            logger.info(f"后台: 已存储 {len(chunks)} 个向量到Milvus")
                        except Exception as e:
                            logger.warning(f"后台Milvus存储失败: {e}")

                    # chunk_store 持久化
                    try:
                        from database.chunk_store import save_chunks
                        save_chunks(chunks)
                    except Exception as e:
                        logger.warning(f"后台chunk持久化失败: {e}")

                    # 去重索引更新
                    if _enable_dedup:
                        try:
                            from data_processor.dedup import DedupManager
                            _index_mgr = DedupManager(MySQLDB(), enable_tier1=True, enable_tier2=True, enable_tier3=False)
                            for doc_id, content in _doc_ids_for_index:
                                _index_mgr.add_document_to_index(doc_id, content)
                        except Exception as e:
                            logger.warning(f"去重索引更新失败: {e}")

                    # Retriever 缓存失效
                    try:
                        from api.student_routes import invalidate_retriever_cache
                        invalidate_retriever_cache()
                    except Exception:
                        pass

                    # 知识图谱重建
                    try:
                        from data_processor.graph_builder import KnowledgeGraphManager
                        KnowledgeGraphManager().invalidate()
                        KnowledgeGraphManager().rebuild_async()
                    except Exception:
                        pass

                    logger.info(f"后台处理完成: {total_docs} 文档, {len(chunks)} chunks")

                except Exception as e:
                    logger.error(f"后台处理失败: {e}", exc_info=True)

            threading.Thread(target=_background_process, daemon=True, name="upload-bg").start()

        # 构建结果消息
        msg_parts = [f"成功上传 {total_docs} 个文档，切分为 {total_chunks} 个片段（向量化后台处理中）"]
        if skipped_duplicates > 0:
            msg_parts.append(f"跳过 {skipped_duplicates} 个重复文档")
        if kb_name:
            msg_parts.append(f"已归入「{kb_name}」知识库")

        return UploadResponse(
            message="，".join(msg_parts),
            doc_count=total_docs,
            chunk_count=total_chunks,
            skipped_duplicates=skipped_duplicates,
            chunk_duplicates_removed=0,
            dedup_details=all_dedup_details,
        )

    except Exception as e:
        logger.error(f"文档上传失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.get("/documents")
async def list_documents(page: int = 1, page_size: int = 10):
    """查询文档列表"""
    try:
        from database.mysql_db import MySQLDB

        mysql_db = MySQLDB()
        offset = (page - 1) * page_size

        sql = "SELECT id, title, source, created_at FROM documents ORDER BY created_at DESC LIMIT %s OFFSET %s"
        docs = mysql_db.query(sql, (page_size, offset))

        count_result = mysql_db.query_one("SELECT COUNT(*) as total FROM documents")
        total = count_result.get("total", 0) if count_result else 0

        return {"documents": docs, "total": total, "page": page, "page_size": page_size}
    except Exception as e:
        logger.error(f"查询文档列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


# ======================== 系统状态 ========================

@router.get("/stats")
async def get_stats():
    """获取系统统计信息"""
    try:
        total_documents = 0
        total_chunks = 0
        version = "1.0.0"

        # 知识块统计（轻量计数，不加载内容）
        try:
            from database.chunk_store import get_chunk_count
            total_chunks = get_chunk_count()
        except Exception as e:
            logger.debug(f"chunk计数获取失败: {e}")

        # MySQL 文档统计
        try:
            from database.mysql_db import MySQLDB
            db = MySQLDB()
            doc_count = db.query_one("SELECT COUNT(*) as count FROM documents")
            total_documents = doc_count.get("count", 0) if doc_count else 0
        except Exception as e:
            logger.debug(f"文档计数获取失败: {e}")

        return {
            "version": version,
            "total_documents": total_documents,
            "total_chunks": total_chunks,
            "indexed_documents": total_documents,
            "avg_chunk_size": round(total_chunks / total_documents) if total_documents > 0 else 0,
        }
    except Exception as e:
        logger.error(f"获取统计信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


# ======================== 在线评估反馈 ========================

@router.post("/feedback")
async def submit_feedback(request: FeedbackRequest):
    """提交用户反馈（评分+评论）"""
    try:
        from data_processor.evaluation import EvaluationTracker
        tracker = EvaluationTracker()
        tracker.init_tables()
        feedback_id = tracker.record_feedback(
            query_id=request.query_id or str(uuid.uuid4()),
            rating=request.rating,
            comment=request.comment or "",
            query=request.query or "",
            answer=request.answer or "",
            conversation_id=request.conversation_id or "",
            kb_id=request.kb_id or "",
            strategy_used=request.strategy_used or "",
            router_used=request.router_used or "",
            response_time_ms=request.response_time_ms,
            metadata=request.metadata,
        )
        return {"feedback_id": feedback_id, "message": "感谢您的反馈"}
    except Exception as e:
        logger.error(f"提交反馈失败: {e}")
        raise HTTPException(status_code=500, detail=f"提交失败: {str(e)}")


@router.get("/feedback/quality")
async def get_quality_metrics(kb_id: str = None, days: int = 7):
    """获取质量指标（评分分布、趋势、策略对比）"""
    try:
        from data_processor.evaluation import EvaluationTracker
        tracker = EvaluationTracker()
        tracker.init_tables()
        return tracker.get_quality_metrics(kb_id=kb_id, days=days)
    except Exception as e:
        logger.error(f"获取质量指标失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")


@router.get("/feedback/list")
async def list_feedback(query_id: str = None, kb_id: str = None, limit: int = 50):
    """查询历史反馈列表"""
    try:
        from data_processor.evaluation import EvaluationTracker
        tracker = EvaluationTracker()
        tracker.init_tables()
        items = tracker.get_feedback(query_id=query_id, kb_id=kb_id, limit=limit)
        return {"items": items, "total": len(items)}
    except Exception as e:
        logger.error(f"查询反馈列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


# ======================== FAQ ========================


@router.get("/faq")
async def list_faq(page: int = 1, page_size: int = 20):
    """获取FAQ列表"""
    try:
        from database.mysql_db import MySQLDB
        db = MySQLDB()
        offset = (page - 1) * page_size
        sql = "SELECT id, question, answer, category, tags FROM faq LIMIT %s OFFSET %s"
        items = db.query(sql, (page_size, offset))
        count_result = db.query_one("SELECT COUNT(*) as total FROM faq")
        total = count_result.get("total", 0) if count_result else 0
        return {"faq_list": items, "total": total, "page": page, "page_size": page_size}
    except Exception as e:
        logger.error(f"获取FAQ列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取失败: {str(e)}")