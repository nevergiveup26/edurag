"""
管理端API路由
"""
import uuid
import os
import json
import time
import asyncio
from typing import Optional, List
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.auth import require_admin
from database.mysql_db import MySQLDB
from core.logger import get_logger

logger = get_logger("admin_routes")

admin_router = APIRouter(prefix="/admin", tags=["管理端"])


def _make_query_func():
    """创建评估用的 query_func"""
    from types import SimpleNamespace
    from retriever.hybrid_retriever import HybridRetriever
    from database.chunk_store import load_chunks
    from core.models import DocumentChunk
    from llm.llm_client import LLMClient
    from llm.prompt_template import PromptTemplate
    from data_processor.rag_utils import trim_context_to_token_limit

    retriever = HybridRetriever()
    store_data = load_chunks()
    if store_data:
        chunks = [
            DocumentChunk(
                chunk_id=item["chunk_id"], doc_id=item["doc_id"],
                content=item["content"], metadata=item.get("metadata", {}),
                embedding=item.get("embedding"),
            )
            for item in store_data
        ]
        retriever.build_index(chunks)

    llm_client = LLMClient()

    def query_func(query: str):
        results = retriever.search(query, top_k=5)
        if results:
            parts = []
            for i, r in enumerate(results[:8]):
                content = r.chunk.content if hasattr(r.chunk, 'content') else str(r)
                parts.append(f"[{i+1}] {content[:500]}")
            context = "\n\n".join(parts)
            context = trim_context_to_token_limit(context, max_tokens=3000)
        else:
            context = ""

        prompt = PromptTemplate.generate_qa_prompt(query, context)
        answer = llm_client.generate(prompt)

        sources = []
        for s in results:
            if hasattr(s, 'chunk') and s.chunk:
                chunk = s.chunk
                content = chunk.content if hasattr(chunk, 'content') else str(chunk)
                doc_id = chunk.doc_id if hasattr(chunk, 'doc_id') else ""
            else:
                content = str(s)
                doc_id = ""
            sources.append(SimpleNamespace(
                content=content[:500],
                score=getattr(s, 'score', 0),
                chunk=SimpleNamespace(doc_id=doc_id, content=content[:500]),
            ))
        return SimpleNamespace(
            answer=answer,
            sources=sources,
            strategy_used="simple_rag",
            router_used="simple_rag",
            execution_time=0,
            conversation_id="",
        )

    return query_func


# ======== 管理端请求模型 ========

class AdminLoginRequest(BaseModel):
    username: str
    password: str


# ======== 认证 ========

@admin_router.post("/login")
async def admin_login(req: AdminLoginRequest):
    """管理员登录"""
    from api.auth import verify_password, create_token, hash_password
    db = MySQLDB()
    user = db.get_user_by_username(req.username)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="非管理员账号")
    pwd_ok, need_upgrade = verify_password(req.password, user["password_hash"])
    if not pwd_ok:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if need_upgrade:
        db.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                   (hash_password(req.password), user["id"]))
    token = create_token(user["id"], user["username"], user["role"])
    return {"message": "登录成功", "token": token, "user": {"id": user["id"], "username": user["username"], "role": user["role"]}}


# ======== 统计面板 ========

@admin_router.get("/stats")
async def get_admin_stats(admin: dict = Depends(require_admin)):
    """管理员统计面板"""
    db = MySQLDB()
    feedback_stats = db.get_feedback_stats()
    total_docs = db.query_one("SELECT COUNT(*) as cnt FROM documents")
    total_kbs = db.query_one("SELECT COUNT(*) as cnt FROM knowledge_bases")
    total_users = db.query_one("SELECT COUNT(*) as cnt FROM users")
    total_queries_cnt = 0
    query_trend = []
    try:
        total_queries = db.query_one("SELECT COUNT(*) as cnt FROM query_logs")
        total_queries_cnt = total_queries.get("cnt", 0) if total_queries else 0
        # 最近7天每天查询量
        trend_rows = db.query(
            "SELECT DATE(created_at) as day, COUNT(*) as cnt FROM query_logs "
            "GROUP BY DATE(created_at) ORDER BY day DESC LIMIT 7"
        )
        # 转为日期升序 + 补齐空白天
        from datetime import datetime, timedelta
        today = datetime.now().date()
        trend_map = {}
        for row in trend_rows or []:
            d = row.get('day')
            if d:
                d_str = d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d)[:10]
                trend_map[d_str] = row.get('cnt', 0)
        query_trend = []
        for i in range(6, -1, -1):
            day = (today - timedelta(days=i))
            query_trend.append({"date": day.strftime('%m/%d'), "count": trend_map.get(day.strftime('%Y-%m-%d'), 0)})
    except Exception as e:
        logger.debug(f"查询趋势计算失败: {e}")

    total_chunks = 0
    try:
        from database.chunk_store import get_chunk_count
        total_chunks = get_chunk_count()
    except Exception as e:
        logger.debug(f"chunk计数获取失败: {e}")

    return {
        "feedback": feedback_stats,
        "total_documents": total_docs["cnt"] if total_docs else 0,
        "total_chunks": total_chunks,
        "total_knowledge_bases": total_kbs["cnt"] if total_kbs else 0,
        "total_users": total_users["cnt"] if total_users else 0,
        "total_queries": total_queries_cnt,
        "query_trend": query_trend,
    }


# ======== 文档管理 ========

@admin_router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, admin: dict = Depends(require_admin)):
    """删除文档（MySQL 主存储立即删除，Milvus/chunk/图谱等慢操作后台执行）"""
    # 1. 先删除 MySQL 主记录（快）
    mysql_db = MySQLDB()
    affected = mysql_db.delete_document(doc_id)
    if affected == 0:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 2. 慢操作全部丢到后台线程，不阻塞响应
    import threading
    def _background_cleanup():
        try:
            from database.milvus_db import MilvusDB
            MilvusDB().delete_by_doc_id(doc_id)
        except BaseException:
            pass
        try:
            from database.chunk_store import remove_chunks_by_doc_id
            remove_chunks_by_doc_id(doc_id)
        except Exception:
            pass
        try:
            from data_processor.graph_builder import KnowledgeGraphManager
            mgr = KnowledgeGraphManager()
            mgr.invalidate()
            mgr.rebuild_async()
        except Exception:
            pass

    threading.Thread(target=_background_cleanup, daemon=True, name=f"del-{doc_id[:12]}").start()

    return {"message": f"文档 {doc_id} 已删除"}


@admin_router.get("/documents/{doc_id}")
async def get_document_detail(doc_id: str, admin: dict = Depends(require_admin)):
    """获取单个文档完整内容（用于预览）"""
    try:
        mysql_db = MySQLDB()
        doc = mysql_db.get_document(doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="文档不存在")
        return doc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取文档详情失败: {str(e)}")


# ======== 知识图谱管理 ========

@admin_router.get("/graph/stats")
async def graph_stats(admin: dict = Depends(require_admin)):
    """获取知识图谱统计信息"""
    try:
        from data_processor.graph_builder import KnowledgeGraphManager
        mgr = KnowledgeGraphManager()
        return mgr.get_stats()
    except Exception as e:
        logger.error(f"获取图谱统计失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@admin_router.post("/graph/rebuild")
async def graph_rebuild(admin: dict = Depends(require_admin)):
    """手动触发知识图谱重建"""
    try:
        from data_processor.graph_builder import KnowledgeGraphManager
        mgr = KnowledgeGraphManager()
        mgr.invalidate()
        mgr.rebuild_async()
        return {"message": "图谱后台重建已启动", "status": "building"}
    except Exception as e:
        logger.error(f"触发图谱重建失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ======== FAQ 导入 ========

@admin_router.post("/faq/import")
async def import_faq(admin: dict = Depends(require_admin)):
    """从示例数据导入FAQ到MySQL"""
    try:
        from data_processor.vectorizer import Vectorizer

        sample_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "samples", "faq_sample.json")
        with open(sample_path, "r", encoding="utf-8") as f:
            faq_items = json.load(f)

        db = MySQLDB()
        vectorizer = Vectorizer()

        count = 0
        for item in faq_items:
            faq_id = str(uuid.uuid4())
            question = item.get("question", "")
            answer = item.get("answer", "")
            category = item.get("category", "")
            tags = json.dumps(item.get("tags", []), ensure_ascii=False)

            # 计算FAQ的向量表示
            embedding = vectorizer.embed_query(question)
            embedding_json = json.dumps(embedding)

            sql = """INSERT INTO faq (id, question, answer, category, tags, embedding)
                     VALUES (%s, %s, %s, %s, %s, %s)
                     ON DUPLICATE KEY UPDATE question=VALUES(question), answer=VALUES(answer)"""
            db.execute(sql, (faq_id, question, answer, category, tags, embedding_json))
            count += 1

        return {"message": f"成功导入 {count} 条FAQ数据", "count": count}
    except Exception as e:
        logger.error(f"导入FAQ失败: {e}")
        raise HTTPException(status_code=500, detail=f"导入FAQ失败: {str(e)}")


# ======== 模型评估 ========

class EvalRequestModel(BaseModel):
    """评估请求模型"""
    use_custom_samples: bool = Field(default=False, description="是否使用自定义样本")
    custom_samples: List[dict] = Field(default=[], description="自定义评估样本")


@admin_router.post("/evaluate")
async def run_evaluation(request: EvalRequestModel = None,
                          admin: dict = Depends(require_admin)):
    """
    运行模型效果评估

    评估指标：
    - 检索准确率 (Precision)
    - 检索召回率 (Recall)
    - F1分数
    - MRR (Mean Reciprocal Rank)
    - 关键词匹配率
    - 平均执行时间
    """
    try:
        from evaluation.evaluator import RAGEvaluator, EvalSample

        evaluator = RAGEvaluator()
        query_func = _make_query_func()

        if request and request.use_custom_samples and request.custom_samples:
            custom = []
            for s in request.custom_samples:
                custom.append(EvalSample(
                    query=s.get("query", ""),
                    expected_answer=s.get("expected_answer", ""),
                    expected_keywords=s.get("expected_keywords", []),
                    relevant_doc_ids=s.get("relevant_doc_ids", []),
                    category=s.get("category", "custom"),
                ))
            evaluator.samples = custom

        report = await asyncio.to_thread(evaluator.run_full_evaluation, query_func)

        return {
            "sample_count": report.sample_count,
            "total_time": report.total_time,
            "retrieval": {
                "precision": round(report.retrieval.precision, 4),
                "recall": round(report.retrieval.recall, 4),
                "f1_score": round(report.retrieval.f1_score, 4),
                "mrr": round(report.retrieval.mrr, 4),
                "ndcg": round(report.retrieval.ndcg, 4),
                "hit_rate": round(report.retrieval.hit_rate, 4),
            },
            "generation": {
                "bleu_1": report.generation.bleu_1,
                "bleu_2": report.generation.bleu_2,
                "rouge_l": report.generation.rouge_l,
                "keyword_match_rate": round(report.generation.keyword_match_rate, 4),
                "llm_score": report.generation.llm_score,
                "avg_answer_length": report.generation.answer_length,
                "avg_execution_time": round(report.generation.avg_execution_time, 2),
            },
            "charts": report.charts,
            "sample_reports": report.sample_reports,
        }
    except Exception as e:
        logger.error(f"评估失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"评估失败: {str(e)}")


@admin_router.get("/evaluate/samples")
async def get_eval_samples(admin: dict = Depends(require_admin)):
    """获取当前评估样本（来自外部加载，无内置样本）"""
    from evaluation.evaluator import RAGEvaluator
    evaluator = RAGEvaluator()
    if not evaluator.samples:
        return {"samples": [], "message": "无评估样本。请通过 data/eval_samples/*.json 加载测试集。"}
    return {
        "samples": [
            {
                "query": s.query,
                "expected_answer": s.expected_answer,
                "expected_keywords": s.expected_keywords,
                "category": s.category,
            }
            for s in evaluator.samples
        ]
    }


# ======== 统一评估 ========

class EvalRequest(BaseModel):
    """统一评测请求"""
    test_cases: List[dict] = Field(default_factory=list, description="自定义测试样本")
    metrics: List[str] = Field(default_factory=lambda: ["retrieval", "generation", "faithfulness", "answer_relevancy"],
                               description="要计算的指标")
    max_samples: int = Field(default=0, ge=0, description="最多评测样本数")
    use_llm_judge: bool = Field(default=True, description="是否启用 LLM 评判")
    parallel_queries: int = Field(default=8, ge=1, le=16)
    parallel_scoring: int = Field(default=4, ge=1, le=8)


def _load_builtin_samples() -> List[dict]:
    """加载内置测试样本，优先使用增强版（含 reference_answer 和 relevant_doc_ids）"""
    import json
    base_dir = os.path.dirname(os.path.dirname(__file__))

    # 优先加载增强版测试集
    enriched_path = os.path.join(base_dir, "evaluation", "k12_test_set_enriched.json")
    test_set_path = os.path.join(base_dir, "evaluation", "k12_test_set.json")

    # 选择可用文件
    if os.path.exists(enriched_path):
        load_path = enriched_path
        is_enriched = True
    elif os.path.exists(test_set_path):
        load_path = test_set_path
        is_enriched = False
    else:
        logger.warning("未找到测试集文件，使用内置默认样本")
        return [
            {"question": "什么是素质教育？",
             "ground_truth": "素质教育是注重学生全面发展的教育理念，强调德智体美劳全面发展。",
             "expected_answer": "素质教育是注重学生全面发展的教育理念，强调德智体美劳全面发展。"},
            {"question": "如何提高学生的学习兴趣？",
             "ground_truth": "通过多样化教学方式、创设情境、激发好奇心等方法提高学习兴趣。",
             "expected_answer": "通过多样化教学方式、创设情境、激发好奇心等方法提高学习兴趣。"},
            {"question": "在线教育的优缺点是什么？",
             "ground_truth": "在线教育的优点包括灵活便捷、资源丰富；缺点包括缺乏互动、自律要求高。",
             "expected_answer": "在线教育的优点包括灵活便捷、资源丰富；缺点包括缺乏互动、自律要求高。"},
        ]

    with open(load_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if is_enriched:
        # 增强版：用 reference_answer 作为 ground_truth，有 relevant_doc_ids
        result = [
            {
                "question": item["query"],
                "ground_truth": item.get("reference_answer", item.get("expected_answer", "")),
                "expected_answer": item.get("expected_answer", ""),
                "expected_keywords": item.get("expected_keywords", []),
                "relevant_doc_ids": item.get("relevant_doc_ids", []),
            }
            for item in raw
        ]
        logger.info(f"已加载增强版测试集 ({len(result)} 条样本)")
    else:
        # 原始版：用 expected_answer 作为 ground_truth，无 relevant_doc_ids
        result = [
            {
                "question": item["query"],
                "ground_truth": item.get("expected_answer", ""),
                "expected_answer": item.get("expected_answer", ""),
                "expected_keywords": item.get("expected_keywords", []),
                "relevant_doc_ids": item.get("relevant_doc_ids", []),
            }
            for item in raw
        ]
        logger.info(f"已加载原始测试集 ({len(result)} 条样本，无文档标注)")

    return result


@admin_router.post("/evaluate/run")
async def run_evaluation(request: EvalRequest = None, admin: dict = Depends(require_admin)):
    """运行统一评测"""
    try:
        from evaluation.unified_evaluator import UnifiedEvaluator, EvalConfig

        config = EvalConfig(
            metrics=request.metrics if request else ["retrieval", "generation", "faithfulness", "answer_relevancy"],
            max_samples=request.max_samples if request else 0,
            parallel_queries=request.parallel_queries if request else 8,
            parallel_scoring=request.parallel_scoring if request else 4,
            use_llm_judge=request.use_llm_judge if request else True,
        )
        evaluator = UnifiedEvaluator(config)
        query_func = _make_query_func()

        test_cases = []
        if request and request.test_cases:
            test_cases = request.test_cases
        else:
            test_cases = _load_builtin_samples()

        report = await evaluator.evaluate(test_cases, query_func)

        return {
            "metrics": report.avg_metrics,
            "sample_count": report.sample_count,
            "total_time": report.total_time,
            "details": [evaluator._score_to_dict(s) for s in report.sample_scores],
            "mode": "unified",
        }
    except Exception as e:
        logger.error(f"评测失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"评测失败: {str(e)}")


@admin_router.post("/evaluate/ragas")
async def run_ragas_evaluation_deprecated(admin: dict = Depends(require_admin)):
    """已废弃：请使用 POST /evaluate/run"""
    logger.warning("POST /evaluate/ragas 已废弃，请使用 POST /evaluate/run")
    return await run_evaluation(request=None, admin=admin)


@admin_router.get("/evaluate/samples")
@admin_router.get("/evaluate/ragas/samples")
async def get_eval_samples(admin: dict = Depends(require_admin)):
    """获取评测测试样本"""
    return {"samples": _load_builtin_samples()}


# ======== 评测实时流（SSE）======= 

import threading
import queue as queue_module
import asyncio

# 全局：跟踪运行中的评测取消事件
_running_evals: dict = {}  # {session_id: threading.Event}


@admin_router.get("/evaluate/stream")
async def evaluate_stream(admin: dict = Depends(require_admin)):
    """
    流式运行检索评测（SSE）
    
    事件格式: event: progress|sample_done|complete|cancelled|error
    data: JSON
    """
    import json as _json
    
    session_id = str(uuid.uuid4())
    cancel_event = threading.Event()
    _running_evals[session_id] = cancel_event
    event_queue = queue_module.Queue()
    
    def _run():
        try:
            from evaluation.evaluator import RAGEvaluator, EvalSample

            # 从 evaluation/k12_test_set.json 加载内置评测样本
            builtin_samples = []
            test_set_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "evaluation", "k12_test_set.json"
            )
            if os.path.exists(test_set_path):
                with open(test_set_path, "r", encoding="utf-8") as f:
                    raw_samples = json.load(f)
                for item in raw_samples:
                    builtin_samples.append(EvalSample(
                        query=item["query"],
                        expected_answer=item.get("expected_answer", ""),
                        expected_keywords=item.get("expected_keywords", []),
                        relevant_doc_ids=item.get("relevant_doc_ids", []),
                        category=item.get("category", "general"),
                    ))
                logger.info(f"已加载 {len(builtin_samples)} 条 K12 评测样本")
            else:
                logger.warning(f"评测样本文件不存在: {test_set_path}")

            evaluator = RAGEvaluator(samples=builtin_samples)
            query_func = _make_query_func()
            
            for evt in evaluator.run_full_evaluation_stream(query_func, cancel_event=cancel_event):
                event_queue.put(evt)
        except Exception as e:
            logger.error(f"流式评估异常: {e}", exc_info=True)
            event_queue.put({"event": "error", "message": str(e)})
    
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    
    async def event_generator():
        try:
            # 立即发送 connected 事件，让前端知道后端已就绪
            yield f"event: connected\ndata: {_json.dumps({'event': 'connected', 'session_id': session_id, 'message': '评测引擎已就绪'}, ensure_ascii=False)}\n\n"
            
            while thread.is_alive() or not event_queue.empty():
                try:
                    evt = await asyncio.to_thread(event_queue.get, True, 0.3)
                except queue_module.Empty:
                    yield f": heartbeat {int(time.time())}\n\n"
                    continue
                
                if evt.get("event") == "complete":
                    try:
                        db = MySQLDB()
                        db.insert_eval_history(
                            history_id=session_id,
                            eval_type="retrieval",
                            config={"samples": "builtin"},
                            metrics={"retrieval": evt.get("retrieval", {}),
                                     "generation": evt.get("generation", {})},
                            charts=evt.get("charts", {}),
                            sample_reports=evt.get("sample_reports", []),
                            sample_count=evt.get("sample_count", 0),
                            total_time=evt.get("total_time", 0),
                        )
                    except Exception as e:
                        logger.error(f"保存评测历史失败: {e}")
                
                yield f"event: {evt['event']}\ndata: {_json.dumps(evt, ensure_ascii=False)}\n\n"
            
            _running_evals.pop(session_id, None)
        except asyncio.CancelledError:
            cancel_event.set()
            _running_evals.pop(session_id, None)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Session-Id": session_id,
        }
    )


@admin_router.get("/evaluate/ragas/stream")
async def evaluate_stream_unified(
    admin: dict = Depends(require_admin),
    max_samples: int = Query(0, ge=0, description="最多评测样本数，0=全部"),
    metrics: str = Query("retrieval,generation,faithfulness,answer_relevancy",
                         description="指标列表，逗号分隔"),
):
    """流式统一评测（SSE）"""
    import json as _json

    session_id = str(uuid.uuid4())
    cancel_event = threading.Event()
    _running_evals[session_id] = cancel_event
    event_queue = queue_module.Queue()

    def _run():
        try:
            from evaluation.unified_evaluator import UnifiedEvaluator, EvalConfig

            metric_list = [m.strip() for m in metrics.split(",") if m.strip()]
            config = EvalConfig(
                metrics=metric_list,
                max_samples=max_samples,
                use_llm_judge=True,
            )
            evaluator_obj = UnifiedEvaluator(config)
            query_func = _make_query_func()
            test_cases = _load_builtin_samples()

            async def _run_stream():
                async for evt in evaluator_obj.evaluate_stream(
                    test_cases, query_func, cancel_event=cancel_event
                ):
                    event_queue.put(evt)

            asyncio.run(_run_stream())
        except Exception as e:
            logger.error(f"流式评测异常: {e}", exc_info=True)
            event_queue.put({"event": "error", "message": str(e)})

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    async def event_generator():
        yield f"event: connected\ndata: {_json.dumps({'event': 'connected', 'session_id': session_id, 'message': '统一评测引擎已就绪'}, ensure_ascii=False)}\n\n"

        while thread.is_alive() or not event_queue.empty():
            try:
                evt = await asyncio.to_thread(event_queue.get, True, 0.3)
            except queue_module.Empty:
                yield f": heartbeat {int(time.time())}\n\n"
                continue

            if evt.get("event") == "complete":
                try:
                    db = MySQLDB()
                    db.insert_eval_history(
                        history_id=session_id,
                        eval_type="unified",
                        config={"metrics": metric_list, "max_samples": max_samples},
                        metrics=evt.get("metrics", {}),
                        details=evt.get("details", []),
                        sample_count=evt.get("sample_count", 0),
                        total_time=evt.get("total_time", 0),
                        mode="unified",
                    )
                except Exception as e:
                    logger.error(f"保存评测历史失败: {e}")

            yield f"event: {evt.get('event', 'message')}\ndata: {_json.dumps(evt, ensure_ascii=False)}\n\n"

        if session_id in _running_evals:
            del _running_evals[session_id]

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@admin_router.post("/evaluate/cancel/{session_id}")
async def cancel_evaluation(session_id: str, admin: dict = Depends(require_admin)):
    """取消正在运行的评测"""
    cancel_event = _running_evals.get(session_id)
    if cancel_event:
        cancel_event.set()
        return {"message": "已发送取消信号", "session_id": session_id}
    raise HTTPException(status_code=404, detail="未找到该评测任务或已完成")


# ======== 评测历史管理 ========

class CompareRequest(BaseModel):
    """评测对比请求"""
    id1: str = Field(..., description="第一条历史记录ID")
    id2: str = Field(..., description="第二条历史记录ID")


@admin_router.get("/evaluate/history")
async def list_eval_history(eval_type: str = None, limit: int = 20,
                             admin: dict = Depends(require_admin)):
    """列出评测历史"""
    db = MySQLDB()
    rows = db.list_eval_history(eval_type=eval_type, limit=limit)
    import json as _json
    # 格式化列表数据：解析 JSON 字段、补充 model_name、统一字段名
    for r in rows:
        cfg = r.get("config")
        if isinstance(cfg, str):
            try:
                cfg = _json.loads(cfg)
            except Exception as e:
                logger.debug(f"评测历史 config JSON 解析失败: {e}")
                cfg = {}
        r["config"] = cfg or {}
        m = r.get("metrics")
        if isinstance(m, str):
            try:
                m = _json.loads(m)
            except Exception as e:
                logger.debug(f"评测历史 metrics JSON 解析失败: {e}")
                m = {}
        r["metrics"] = m or {}
        # 补充 model_name（从 config 提取）
        r["model_name"] = cfg.get("model_name", "") if isinstance(cfg, dict) else ""
        # 统一 evaluation_type 字段名
        if "eval_type" in r and "evaluation_type" not in r:
            r["evaluation_type"] = r.get("eval_type", "")
        if r.get("created_at"):
            r["created_at"] = str(r["created_at"])
    return {"history": rows, "total": len(rows)}


@admin_router.get("/evaluate/history/{history_id}")
async def get_eval_history(history_id: str, admin: dict = Depends(require_admin)):
    """获取单条评测历史详情"""
    db = MySQLDB()
    row = db.get_eval_history(history_id)
    if not row:
        raise HTTPException(status_code=404, detail="未找到该评测记录")
    # JSON 字段转回对象
    import json as _json
    for field in ["config", "metrics", "charts", "sample_reports", "details"]:
        if row.get(field) and isinstance(row[field], str):
            try:
                row[field] = _json.loads(row[field])
            except Exception as e:
                logger.debug(f"评测历史 {field} JSON 解析失败: {e}")
    # datetime 转字符串
    if row.get("created_at"):
        row["created_at"] = str(row["created_at"])
    return row


@admin_router.delete("/evaluate/history/{history_id}")
async def delete_eval_history(history_id: str, admin: dict = Depends(require_admin)):
    """删除评测历史"""
    db = MySQLDB()
    affected = db.delete_eval_history(history_id)
    if affected == 0:
        raise HTTPException(status_code=404, detail="未找到该评测记录")
    return {"message": "已删除"}


@admin_router.post("/evaluate/history/compare")
async def compare_eval_history(req: CompareRequest, admin: dict = Depends(require_admin)):
    """对比两次评测历史（返回前端表格格式）"""
    db = MySQLDB()
    r1 = db.get_eval_history(req.id1)
    r2 = db.get_eval_history(req.id2)
    if not r1 or not r2:
        raise HTTPException(status_code=404, detail="未找到评测记录")
    
    import json as _json
    
    def _parse_metrics(row):
        m = row.get("metrics", {})
        if isinstance(m, str):
            try:
                m = _json.loads(m)
            except Exception as e:
                logger.debug(f"指标 JSON 解析失败: {e}")
                m = {}
        return m
    
    m1 = _parse_metrics(r1)
    m2 = _parse_metrics(r2)
    
    # ── 构建模型标签 ──
    def _make_label(row):
        t = row.get("eval_type", "retrieval")
        ts = str(row.get("created_at", ""))[:16] if row.get("created_at") else ""
        return f"{t} ({ts})"
    
    label1 = _make_label(r1)
    label2 = _make_label(r2)
    
    # ── 展平指标 ──
    def _flatten_metrics(m):
        flat = {}
        for k, v in m.items():
            if isinstance(v, dict):
                for sk, sv in v.items():
                    flat[f"{k}.{sk}"] = sv
            else:
                flat[k] = v
        return flat
    
    fm1 = _flatten_metrics(m1)
    fm2 = _flatten_metrics(m2)
    
    # ── 构建对比表格 ──
    table = []
    all_keys = list(dict.fromkeys(list(fm1.keys()) + list(fm2.keys())))  # 保持顺序去重
    for k in all_keys:
        v1 = fm1.get(k)
        v2 = fm2.get(k)
        # 格式化数值（百分比或小数）
        def _fmt(v):
            if v is None:
                return '-'
            if isinstance(v, (int, float)):
                if 0 < abs(v) < 3:
                    return f"{v * 100:.1f}%"
                return f"{v:.4f}"
            return str(v)
        row = {"metric": k, label1: _fmt(v1), label2: _fmt(v2)}
        # 差异高亮
        if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
            diff = v2 - v1
            row["_diff"] = diff
        table.append(row)
    
    # ── 雷达图（matplotlib 可用时生成）──
    radar_chart = None
    try:
        import base64, io, matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from math import pi
        
        # 只取数值型指标
        num_keys = [k for k in all_keys if isinstance(fm1.get(k), (int, float)) and isinstance(fm2.get(k), (int, float))]
        if len(num_keys) >= 3:
            N = len(num_keys)
            angles = [n / float(N) * 2 * pi for n in range(N)]
            angles += angles[:1]  # 闭合
            
            values1 = [fm1.get(k, 0) or 0 for k in num_keys]
            values2 = [fm2.get(k, 0) or 0 for k in num_keys]
            values1 += values1[:1]
            values2 += values2[:1]
            
            fig, ax = plt.subplots(figsize=(5, 5), subplot_kw=dict(polar=True))
            ax.fill(angles, values1, alpha=0.25, color='#4f7cff', label=label1[:20])
            ax.plot(angles, values1, color='#4f7cff', linewidth=2)
            ax.fill(angles, values2, alpha=0.25, color='#ff6b6b', label=label2[:20])
            ax.plot(angles, values2, color='#ff6b6b', linewidth=2)
            ax.set_xticks(angles[:-1])
            ax.set_xticklabels(num_keys, fontsize=7)
            ax.legend(loc='upper right', fontsize=7, bbox_to_anchor=(1.3, 1.0))
            
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
            plt.close()
            buf.seek(0)
            radar_chart = base64.b64encode(buf.read()).decode()
    except Exception as e:
        logger.debug(f"雷达图生成跳过: {e}")
    
    return {
        "table": table,
        "models": [label1, label2],
        "radar_chart": radar_chart,
        # 保留原始数据（调试用）
        "record1": {"id": r1["id"], "eval_type": r1["eval_type"],
                     "metrics": m1, "created_at": str(r1["created_at"])},
        "record2": {"id": r2["id"], "eval_type": r2["eval_type"],
                     "metrics": m2, "created_at": str(r2["created_at"])},
        "differences": {
            k: {"value1": fm1.get(k), "value2": fm2.get(k),
                "diff": round(fm2.get(k, 0) - fm1.get(k, 0), 4) if isinstance(fm1.get(k), (int, float)) and isinstance(fm2.get(k), (int, float)) else None}
            for k in all_keys
        },
    }


@admin_router.get("/evaluate/history/{history_id}/export/pdf")
async def export_eval_pdf(history_id: str, admin: dict = Depends(require_admin)):
    """导出评测报告为 PDF"""
    import json as _json, io as _io, base64 as _b64
    
    db = MySQLDB()
    row = db.get_eval_history(history_id)
    if not row:
        raise HTTPException(status_code=404, detail="未找到该评测记录")
    
    # 解析 JSON 字段
    for field in ["config", "metrics", "charts", "sample_reports", "details"]:
        if row.get(field) and isinstance(row[field], str):
            try:
                row[field] = _json.loads(row[field])
            except Exception as e:
                logger.debug(f"导出PDF JSON解析失败 ({field}): {e}")

    try:
        from fpdf import FPDF
    except ImportError:
        raise HTTPException(status_code=500, detail="fpdf2 未安装，请运行: pip install fpdf2")
    
    pdf = FPDF()
    pdf.add_page()
    
    # 尝试使用中文字体
    chinese_font = None
    for fname, fpath in [
        ("SimHei", "C:/Windows/Fonts/simhei.ttf"),
        ("MSYaHei", "C:/Windows/Fonts/msyh.ttc"),
        ("SimSun", "C:/Windows/Fonts/simsun.ttc"),
    ]:
        if os.path.exists(fpath):
            pdf.add_font("CJK", "", fpath, uni=True)
            pdf.add_font("CJK", "B", fpath, uni=True)
            chinese_font = "CJK"
            break
    
    eval_type = row.get("eval_type", "retrieval")
    metrics = row.get("metrics", {})
    
    # 标题
    pdf.set_font(chinese_font or "Helvetica", "B", 18)
    title = "检索评测报告" if eval_type == "retrieval" else "RAGAS 评测报告"
    pdf.cell(0, 12, title, new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(5)
    
    # 基本信息
    pdf.set_font(chinese_font or "Helvetica", "", 11)
    pdf.cell(0, 8, f"评测时间: {str(row.get('created_at', ''))[:19]}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, f"样本数: {row.get('sample_count', 0)}   总耗时: {row.get('total_time', 0):.1f}s", new_x="LMARGIN", new_y="NEXT")
    if row.get("mode"):
        pdf.cell(0, 8, f"评测模式: {row['mode']}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    
    # 指标
    pdf.set_font(chinese_font or "Helvetica", "B", 13)
    pdf.cell(0, 10, "评测指标", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    
    pdf.set_font(chinese_font or "Helvetica", "", 11)
    
    if eval_type == "retrieval":
        retrieval = metrics.get("retrieval", {})
        generation = metrics.get("generation", {})
        lines = [
            ("检索准确率 (Precision)", f"{retrieval.get('precision', 0):.1%}"),
            ("检索召回率 (Recall)", f"{retrieval.get('recall', 0):.1%}"),
            ("F1 Score", f"{retrieval.get('f1_score', 0):.1%}"),
            ("MRR (平均倒数排名)", f"{retrieval.get('mrr', 0):.1%}"),
            ("NDCG", f"{retrieval.get('ndcg', 0):.1%}"),
            ("命中率 (Hit Rate)", f"{retrieval.get('hit_rate', 0):.1%}"),
            ("BLEU-1", f"{generation.get('bleu_1', 0):.4f}"),
            ("ROUGE-L", f"{generation.get('rouge_l', 0):.4f}"),
            ("关键词匹配率", f"{generation.get('keyword_match_rate', 0):.1%}"),
            ("LLM评判分数", f"{generation.get('llm_score', -1):.2f}" if generation.get('llm_score', -1) >= 0 else "LLM评判分数: 未启用"),
        ]
    else:
        lines = [
            ("忠实度 (Faithfulness)", f"{metrics.get('faithfulness', 0):.1%}"),
            ("答案相关性 (Answer Relevancy)", f"{metrics.get('answer_relevancy', 0):.1%}"),
            ("上下文相关性 (Context Relevancy)", f"{metrics.get('context_relevancy', 0):.1%}"),
            ("上下文精确率 (Context Precision)", f"{metrics.get('context_precision', 0):.1%}"),
            ("上下文召回率 (Context Recall)", f"{metrics.get('context_recall', 0):.1%}"),
            ("平均分 (Avg Score)", f"{metrics.get('avg_score', 0):.1%}"),
        ]
    
    for label, value in lines:
        pdf.cell(100, 7, f"  {label}")
        pdf.cell(0, 7, value, new_x="LMARGIN", new_y="NEXT")
    
    pdf.ln(5)
    
    # 图表（如果有）
    charts = row.get("charts", {})
    if charts:
        for chart_key in ["retrieval_metrics", "keyword_match"] if eval_type == "retrieval" else []:
            img_b64 = charts.get(chart_key)
            if img_b64:
                try:
                    img_data = _b64.b64decode(img_b64)
                    img_path = f"c:/Users/86187/.trae-cn/work/6a25246e71a797d20b4deae8/_tmp_chart_{chart_key}.png"
                    with open(img_path, "wb") as f:
                        f.write(img_data)
                    pdf.set_font(chinese_font or "Helvetica", "B", 12)
                    pdf.cell(0, 8, f"图表: {chart_key}", new_x="LMARGIN", new_y="NEXT")
                    pdf.image(img_path, x=15, w=180)
                    pdf.ln(3)
                    os.remove(img_path)
                except Exception as e:
                    logger.warning(f"嵌入图表失败: {e}")
    
    # 输出
    pdf_buf = _io.BytesIO()
    pdf.output(pdf_buf)
    pdf_buf.seek(0)
    
    return StreamingResponse(
        pdf_buf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="eval_report_{history_id[:8]}.pdf"'
        }
    )


# ======== 知识库管理 ========

class KBCreateRequest(BaseModel):
    """知识库创建请求"""
    name: str = Field(..., min_length=1, max_length=255, description="知识库名称")
    description: str = Field(default="", description="描述")
    category: str = Field(default="通用", description="分类")
    tags: List[str] = Field(default=[], description="标签")


class KBUpdateRequest(BaseModel):
    """知识库更新请求"""
    name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    category: Optional[str] = Field(default=None)
    tags: Optional[List[str]] = Field(default=None)


class KBDocumentRequest(BaseModel):
    """知识库文档操作请求"""
    doc_ids: List[str] = Field(..., description="文档ID列表")


@admin_router.post("/kb")
async def create_knowledge_base(req: KBCreateRequest, admin: dict = Depends(require_admin)):
    """创建知识库"""
    try:
        from kb.knowledge_base import KnowledgeBaseManager
        manager = KnowledgeBaseManager()
        manager.init_tables()
        kb = manager.create(req.name, req.description, req.category, req.tags)
        return kb.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建知识库失败: {str(e)}")


@admin_router.get("/kb")
async def list_knowledge_bases(page: int = 1, page_size: int = 20,
                                category: str = None, keyword: str = None,
                                admin: dict = Depends(require_admin)):
    """列出知识库"""
    try:
        from kb.knowledge_base import KnowledgeBaseManager
        manager = KnowledgeBaseManager()
        return manager.list(page, page_size, category, keyword)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取知识库列表失败: {str(e)}")


@admin_router.get("/kb/search")
async def search_knowledge_bases(keyword: str, top_k: int = 10,
                                  admin: dict = Depends(require_admin)):
    """搜索知识库"""
    try:
        from kb.knowledge_base import KnowledgeBaseManager
        manager = KnowledgeBaseManager()
        results = manager.search_knowledge_bases(keyword, top_k)
        return {"results": results, "total": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


@admin_router.get("/kb/{kb_id}")
async def get_knowledge_base(kb_id: str, admin: dict = Depends(require_admin)):
    """获取知识库详情"""
    try:
        from kb.knowledge_base import KnowledgeBaseManager
        manager = KnowledgeBaseManager()
        kb = manager.get(kb_id)
        if not kb:
            raise HTTPException(status_code=404, detail="知识库不存在")
        return kb.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取知识库失败: {str(e)}")


@admin_router.put("/kb/{kb_id}")
async def update_knowledge_base(kb_id: str, req: KBUpdateRequest,
                                 admin: dict = Depends(require_admin)):
    """更新知识库"""
    try:
        from kb.knowledge_base import KnowledgeBaseManager
        manager = KnowledgeBaseManager()
        ok = manager.update(kb_id, req.name, req.description, req.category, req.tags)
        if not ok:
            raise HTTPException(status_code=400, detail="没有提供更新字段")
        return {"message": "知识库已更新"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新知识库失败: {str(e)}")


@admin_router.delete("/kb/{kb_id}")
async def delete_knowledge_base(kb_id: str, admin: dict = Depends(require_admin)):
    """删除知识库"""
    try:
        from kb.knowledge_base import KnowledgeBaseManager
        manager = KnowledgeBaseManager()
        manager.delete(kb_id)
        return {"message": "知识库已删除"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除知识库失败: {str(e)}")


@admin_router.get("/kb/{kb_id}/stats")
async def get_kb_stats(kb_id: str, admin: dict = Depends(require_admin)):
    """获取知识库统计"""
    try:
        from kb.knowledge_base import KnowledgeBaseManager
        manager = KnowledgeBaseManager()
        return manager.get_stats(kb_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}")


@admin_router.post("/kb/{kb_id}/documents")
async def add_documents_to_kb(kb_id: str, req: KBDocumentRequest,
                               admin: dict = Depends(require_admin)):
    """向知识库添加文档"""
    try:
        from kb.knowledge_base import KnowledgeBaseManager
        manager = KnowledgeBaseManager()
        count = manager.add_documents_batch(kb_id, req.doc_ids)
        return {"message": f"已添加 {count} 个文档到知识库", "count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"添加文档失败: {str(e)}")


@admin_router.get("/kb/{kb_id}/documents")
async def get_kb_documents(kb_id: str, page: int = 1, page_size: int = 20,
                            admin: dict = Depends(require_admin)):
    """获取知识库中的文档列表"""
    try:
        from kb.knowledge_base import KnowledgeBaseManager
        manager = KnowledgeBaseManager()
        return manager.get_documents(kb_id, page, page_size)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取文档列表失败: {str(e)}")


# ======== Langfuse 追踪 ========

@admin_router.get("/traces")
async def list_traces(limit: int = 20, admin: dict = Depends(require_admin)):
    """获取最近的Langfuse追踪记录"""
    try:
        from monitoring.langfuse_tracer import get_tracer
        tracer = get_tracer()
        traces = tracer.list_traces(limit)
        return {"traces": traces, "total": len(traces)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取追踪记录失败: {str(e)}")


@admin_router.get("/traces/{trace_id}")
async def get_trace_detail(trace_id: str, admin: dict = Depends(require_admin)):
    """获取单条Langfuse追踪详情"""
    try:
        from monitoring.langfuse_tracer import get_tracer
        tracer = get_tracer()
        trace = tracer.get_trace(trace_id)
        if not trace:
            raise HTTPException(status_code=404, detail="追踪记录不存在")
        return trace
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取追踪详情失败: {str(e)}")


# ======== CMRC 2018 评测 ========

class CMRCIndexRequest(BaseModel):
    """CMRC 入库请求"""
    split: str = Field(default="dev", description="数据集 split: dev/train/trial/all")
    kb_id: str = Field(default="", description="目标知识库ID，留空则自动创建「CMRC 2018」")


@admin_router.post("/evaluate/cmrc/index")
async def cmrc_index(request: CMRCIndexRequest = None,
                     admin: dict = Depends(require_admin)):
    """
    CMRC 2018 数据入库

    将 CMRC 数据加载并索引到 Milvus/MySQL/chunk_store。
    split=all 时入库全部三个 split（dev + train + trial），约 3500 篇文档。
    """
    try:
        from evaluation.cmrc_evaluator import CMRCEvaluator
        from kb.knowledge_base import KnowledgeBaseManager

        evaluator = CMRCEvaluator()
        split = request.split if request else "dev"

        if split == "all":
            doc_ids, chunks = evaluator.load_and_index_all_splits()
        else:
            evaluator.load_data(split)
            doc_ids, chunks = evaluator.index_data(split)
        docs = len(doc_ids)

        # 关联到知识库
        kb_mgr = KnowledgeBaseManager()
        kb_mgr.init_tables()
        kb_id = request.kb_id if request and request.kb_id else ""
        if not kb_id:
            # 自动查找或创建「CMRC 2018」知识库
            existing = kb_mgr.list(page=1, page_size=100, keyword="CMRC 2018")
            cmrc_kb = None
            for kb in existing.get("items", []):
                if kb["name"] == "CMRC 2018":
                    cmrc_kb = kb
                    break
            if cmrc_kb:
                kb_id = cmrc_kb["id"]
            else:
                kb = kb_mgr.create(name="CMRC 2018", description="CMRC 2018 机器阅读理解数据集",
                                   category="评测数据", tags=["CMRC", "阅读理解", "训练数据"])
                kb_id = kb.kb_id

        kb_mgr.add_documents_batch(kb_id, doc_ids)
        logger.info(f"CMRC 入库已关联知识库: kb_id={kb_id}, docs={docs}")

        return {
            "message": f"CMRC {split} 入库完成",
            "kb_id": kb_id,
            "doc_count": docs,
            "chunk_count": chunks,
        }
    except Exception as e:
        logger.error(f"CMRC 入库失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"入库失败: {str(e)}")


@admin_router.post("/evaluate/cmrc/retrieval")
async def cmrc_retrieval_eval(admin: dict = Depends(require_admin)):
    """
    CMRC 检索评测

    使用已入库的 CMRC 数据运行检索质量评估。
    指标：Precision, Recall, F1, MRR, NDCG, Hit Rate
    """
    try:
        from evaluation.cmrc_evaluator import CMRCEvaluator

        evaluator = CMRCEvaluator()
        evaluator.load_data("dev")
        samples = evaluator.build_samples()
        query_func = _make_query_func()
        result = evaluator.run_retrieval_eval(samples, query_func)
        return result
    except Exception as e:
        logger.error(f"CMRC 检索评测失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"评测失败: {str(e)}")


@admin_router.post("/evaluate/cmrc/generation")
async def cmrc_generation_eval(admin: dict = Depends(require_admin)):
    """
    CMRC 生成评测

    LLM 生成答案 + CMRC 官方 F1/EM 评分。
    注意：会消耗较多 LLM token（~3200 次生成）。
    """
    try:
        from evaluation.cmrc_evaluator import CMRCEvaluator

        evaluator = CMRCEvaluator()
        evaluator.load_data("dev")
        samples = evaluator.build_samples()
        query_func = _make_query_func()

        import asyncio
        result = await asyncio.to_thread(evaluator.run_generation_eval, samples, query_func)
        return result
    except Exception as e:
        logger.error(f"CMRC 生成评测失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"评测失败: {str(e)}")


@admin_router.post("/evaluate/cmrc/cleanup")
async def cmrc_cleanup(admin: dict = Depends(require_admin)):
    """清除所有 CMRC 评测数据（MySQL + Milvus + chunk_store）"""
    try:
        from evaluation.cmrc_evaluator import CMRCEvaluator

        evaluator = CMRCEvaluator()
        evaluator.load_data("dev")
        evaluator.load_data("train")
        evaluator.load_data("trial")
        evaluator.cleanup()
        return {"message": "CMRC 数据已清理"}
    except Exception as e:
        logger.error(f"CMRC 清理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清理失败: {str(e)}")