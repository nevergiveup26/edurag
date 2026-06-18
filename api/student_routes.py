"""
学生端API路由
"""
import uuid
import json
import re
import os
import asyncio
import threading
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.auth import get_current_user, require_student
from database.mysql_db import MySQLDB
from core.logger import get_logger

logger = get_logger("student_routes")

student_router = APIRouter(prefix="/student", tags=["学生端"])

from api.conversation_helpers import save_conversation_message, load_conversation_history


# ===== 模块级缓存：避免每次请求重建 Retriever 索引 =====
_retriever_cache = {"retriever": None, "built": False}
_llm_client_cache = {"client": None}


def _get_cached_retriever():
    """获取缓存的 HybridRetriever（首次调用时构建索引，后续复用）"""
    if _retriever_cache["built"]:
        return _retriever_cache["retriever"]

    import time as _t
    t0 = _t.time()
    from retriever.hybrid_retriever import HybridRetriever
    from database.chunk_store import load_chunks
    from core.models import DocumentChunk

    retriever = HybridRetriever()
    store_data = load_chunks()
    if store_data:
        chunks = [
            DocumentChunk(
                chunk_id=item["chunk_id"],
                doc_id=item["doc_id"],
                content=item["content"],
                metadata=item.get("metadata", {}),
                embedding=item.get("embedding"),
            )
            for item in store_data
        ]
        retriever.build_index(chunks)
    logger.info(f"[缓存] Retriever索引构建完成, {len(store_data) if store_data else 0} chunks, 耗时{_t.time()-t0:.1f}s")

    _retriever_cache["retriever"] = retriever
    _retriever_cache["built"] = True
    return retriever


def invalidate_retriever_cache():
    """调用方在上传新文档后调用此函数，使下次请求重建索引"""
    _retriever_cache["built"] = False
    _retriever_cache["retriever"] = None
    logger.info("[缓存] Retriever索引已失效")


# ======== 学生端请求模型 ========

class StudentLoginRequest(BaseModel):
    username: str
    password: str


class StudentRegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""


# ======== 认证 ========

@student_router.post("/login")
async def student_login(req: StudentLoginRequest):
    """学生登录"""
    from api.auth import verify_password, create_token, hash_password
    db = MySQLDB()
    user = db.get_user_by_username(req.username)
    if not user:
        raise HTTPException(status_code=401, detail="学号或密码错误")
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="非学生账号")
    pwd_ok, need_upgrade = verify_password(req.password, user["password_hash"])
    if not pwd_ok:
        raise HTTPException(status_code=401, detail="学号或密码错误")
    if need_upgrade:
        db.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                   (hash_password(req.password), user["id"]))
    token = create_token(user["id"], user["username"], user["role"])
    return {"message": "登录成功", "token": token, "user": {"id": user["id"], "username": user["username"], "role": user["role"]}}


@student_router.post("/register")
async def student_register(req: StudentRegisterRequest):
    """学生注册（学号）"""
    from api.auth import hash_password
    db = MySQLDB()
    existing = db.get_user_by_username(req.username)
    if existing:
        raise HTTPException(status_code=400, detail="该学号已注册")
    user_id = f"stu_{uuid.uuid4().hex[:12]}"
    pwd_hash = hash_password(req.password)
    db.create_user(user_id, req.username, pwd_hash, role="student", display_name=req.display_name)
    return {"message": "注册成功", "user_id": user_id}



# ======== 历史 ========

@student_router.get("/history")
async def get_history(user: dict = Depends(require_student), limit: int = 50):
    """获取对话历史（置顶优先）"""
    db = MySQLDB()
    conversations = db.query(
        """SELECT c.id, c.title, c.is_pinned, c.created_at, c.updated_at,
                  (SELECT COUNT(*) FROM conversation_messages WHERE conversation_id = c.id) as message_count
           FROM conversations c
           WHERE c.user_id = %s ORDER BY c.is_pinned DESC, c.updated_at DESC LIMIT %s""",
        (user["user_id"], limit))
    return {"conversations": conversations}


@student_router.post("/conversation")
async def create_conversation(user: dict = Depends(require_student)):
    """创建新对话"""
    conv_id = str(uuid.uuid4())
    try:
        db = MySQLDB()
        sql = "INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, %s)"
        db.execute(sql, (conv_id, user["user_id"], "新对话"))
        return {"conversation_id": conv_id, "message": "对话已创建"}
    except Exception as e:
        logger.error(f"创建对话失败: {e}")
        raise HTTPException(status_code=500, detail=f"创建对话失败: {str(e)}")


@student_router.get("/conversation/{conversation_id}")
async def get_conversation(conversation_id: str, user: dict = Depends(require_student)):
    """获取对话历史"""
    try:
        db = MySQLDB()
        sql = "SELECT * FROM conversation_messages WHERE conversation_id = %s ORDER BY created_at ASC"
        messages = db.query(sql, (conversation_id,))
        return {"conversation_id": conversation_id, "messages": messages}
    except Exception as e:
        logger.error(f"获取对话失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取对话失败: {str(e)}")


@student_router.get("/conversations")
async def list_conversations(user: dict = Depends(require_student),
                              page: int = 1, page_size: int = 10):
    """列出当前学生的对话"""
    try:
        db = MySQLDB()
        offset = (page - 1) * page_size
        total_result = db.query("SELECT COUNT(*) as total FROM conversations WHERE user_id = %s", (user["user_id"],))
        total = total_result[0]["total"] if total_result else 0
        sql = """SELECT c.*,
                        (SELECT COUNT(*) FROM conversation_messages WHERE conversation_id = c.id) as message_count
                 FROM conversations c
                 WHERE c.user_id = %s ORDER BY c.is_pinned DESC, c.updated_at DESC LIMIT %s OFFSET %s"""
        convs = db.query(sql, (user["user_id"], page_size, offset))
        return {"conversations": convs, "total": total, "page": page, "page_size": page_size}
    except Exception as e:
        logger.error(f"列出对话失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取对话列表失败: {str(e)}")


@student_router.delete("/conversation/{conversation_id}")
async def delete_conversation(conversation_id: str,
                               user: dict = Depends(require_student)):
    """删除对话（级联删除消息）"""
    try:
        db = MySQLDB()
        # 验证对话属于当前用户
        conv = db.query_one("SELECT id FROM conversations WHERE id = %s AND user_id = %s", (conversation_id, user["user_id"]))
        if not conv:
            raise HTTPException(status_code=404, detail="对话不存在")
        # 先删消息再删对话（满足外键约束）
        db.execute("DELETE FROM conversation_messages WHERE conversation_id = %s", (conversation_id,))
        db.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
        return {"message": "对话已删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除对话失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除对话失败: {str(e)}")


@student_router.patch("/conversation/{conversation_id}/pin")
async def pin_conversation(conversation_id: str,
                            user: dict = Depends(require_student)):
    """置顶/取消置顶对话"""
    try:
        db = MySQLDB()
        conv = db.query_one("SELECT id, is_pinned FROM conversations WHERE id = %s AND user_id = %s",
                            (conversation_id, user["user_id"]))
        if not conv:
            raise HTTPException(status_code=404, detail="对话不存在")
        new_pinned = 0 if conv.get("is_pinned") else 1
        db.execute("UPDATE conversations SET is_pinned = %s WHERE id = %s", (new_pinned, conversation_id))
        return {"is_pinned": bool(new_pinned), "message": "已置顶" if new_pinned else "已取消置顶"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"置顶对话失败: {e}")
        raise HTTPException(status_code=500, detail=f"操作失败: {str(e)}")


# ======== 学生端多模态 ========


@student_router.post("/multimodal/upload")
async def student_multimodal_upload(file: UploadFile = File(...),
                                     user: dict = Depends(require_student)):
    """
    学生端上传多模态文件（PDF/DOCX/图片）

    支持格式：PDF, DOCX, TXT, MD, HTML, JPG, PNG, GIF, WEBP, BMP
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供文件")

    ext = Path(file.filename).suffix.lower()
    IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    DOC_EXTS = {".pdf", ".docx", ".txt", ".md", ".html"}

    if ext not in DOC_EXTS | IMAGE_EXTS:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式: {ext}")

    try:
        from data_processor.multimodal_loader import MultiModalLoader

        temp_path = os.path.join(os.path.dirname(__file__), "..", "data", "uploads", file.filename)
        os.makedirs(os.path.dirname(temp_path), exist_ok=True)
        content = await file.read()
        with open(temp_path, "wb") as f:
            f.write(content)

        loader = MultiModalLoader()

        if ext in IMAGE_EXTS:
            chunk = loader.load_image(temp_path, caption=file.filename)
            chunks = [chunk]
        else:
            chunks = loader.load_document(temp_path)

        text_blocks = sum(1 for c in chunks if c.content_type == "text")
        image_blocks = sum(1 for c in chunks if c.content_type == "image")
        table_blocks = sum(1 for c in chunks if c.content_type == "table")

        return {
            "file_name": file.filename,
            "text_blocks": text_blocks,
            "image_blocks": image_blocks,
            "table_blocks": table_blocks,
            "total_blocks": len(chunks),
            "message": f"上传成功，{len(chunks)} 个片段",
        }
    except Exception as e:
        logger.error(f"多模态上传失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@student_router.get("/multimodal/models")
async def student_list_multimodal_models(user: dict = Depends(require_student)):
    """列出可用的多模态/视觉模型"""
    try:
        from data_processor.vision_encoder import VisionEncoder
        models = VisionEncoder.list_models()
        return {"models": models, "total": len(models)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取模型列表失败: {str(e)}")


# ======== 拍照搜题（OCR + 联网搜索 + LLM 解析）========

@student_router.post("/photo-search")
async def student_photo_search(
    file: Optional[UploadFile] = File(None),
    query: str = Form(""),
    user: dict = Depends(require_student),
):
    """
    拍照搜题接口

    流程：图片 → DashScope OCR → 联网搜索（优先）→ LLM 生成题目解析
    支持两种调用方式：
    - 图片上传：file=图片文件，自动 OCR 后搜索
    - 文字输入：query=题目文字，直接搜索

    返回：
    - extracted_text: OCR 提取的文字（图片模式）
    - analysis: LLM 生成的题目解析
    - web_sources: 联网搜索结果列表
    """
    import base64
    import time as _time
    _t_start = _time.time()

    extracted_text = ""
    logger.info(f"[photo-search] 收到请求: file={file.filename if file else None}, query长度={len(query)}")

    # ===== 1. 图片 OCR 提取文字 =====
    if file and file.filename:
        ext = Path(file.filename).suffix.lower()
        IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
        if ext not in IMAGE_EXTS:
            raise HTTPException(status_code=400, detail=f"不支持的图片格式: {ext}")

        try:
            content = await file.read()
            image_base64 = base64.b64encode(content).decode("utf-8")

            # 使用 DashScope OCR
            from llm.ocr_client import get_ocr_client
            ocr_client = get_ocr_client()
            ocr_result = ocr_client.extract_text(image_base64, label="题目图片")

            extracted_text = ocr_result.get("extracted_text", "")
            ocr_error = ocr_result.get("error", "")
            if ocr_error:
                logger.warning(f"[photo-search] OCR 错误: {ocr_error}")

            if not extracted_text:
                return {
                    "extracted_text": "",
                    "analysis": "图片中未识别到文字，请重新拍照或直接输入题目文字。",
                    "web_sources": [],
                    "error": ocr_error or "OCR 未提取到文字",
                }
        except Exception as e:
            logger.error(f"[photo-search] 图片处理失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"图片处理失败: {str(e)}")

    logger.info(f"[photo-search] OCR阶段完成, 耗时{_time.time()-_t_start:.1f}s")

    # ===== 2. 确定搜索文本 =====
    search_text = extracted_text or query.strip()
    logger.info(f"[photo-search] 搜索文本: extracted_text长度={len(extracted_text)}, query长度={len(query.strip())}, 最终search_text长度={len(search_text)}")
    if not search_text:
        raise HTTPException(status_code=400, detail="请提供图片或题目文字")

    # ===== 3. 联网搜索（优先，basic模式快~1.5s）=====
    import asyncio

    def _run_tavily(query_text: str):
        """同步执行Tavily搜索（在to_thread中运行，不阻塞事件循环）"""
        from langgraph_agent.tools import tavily_web_search
        web_result = tavily_web_search.invoke({
            "query": query_text[:500],
            "search_depth": "basic",
            "max_results": 5,
            "include_domains": "",
        })
        web_data = json.loads(web_result) if isinstance(web_result, str) else web_result
        sources = web_data.get("results", []) if isinstance(web_data, dict) else []
        answer = web_data.get("answer", "") if isinstance(web_data, dict) else ""
        return sources, answer

    web_sources = []
    web_answer = ""
    t_tavily = _time.time()
    try:
        web_sources, web_answer = await asyncio.to_thread(_run_tavily, search_text)
        logger.info(f"[photo-search] 联网搜索成功: {len(web_sources)} 条结果, 耗时{_time.time()-t_tavily:.1f}s")
    except Exception as e:
        logger.warning(f"[photo-search] 联网搜索失败: {e}")

    # ===== 4. LLM 生成题目解析（asyncio.to_thread不阻塞事件循环）=====
    analysis = ""
    t_llm = _time.time()
    try:
        from llm.llm_client import LLMClient
        llm = LLMClient()

        # 构造联网搜索上下文
        web_context_parts = []
        if web_answer:
            web_context_parts.append(f"[联网摘要] {web_answer[:600]}")
        for r in web_sources[:5]:
            title = r.get("title", "")
            content = r.get("content", "")
            if title or content:
                web_context_parts.append(f"[{title}] {content[:300]}")
        web_context = "\n".join(web_context_parts) if web_context_parts else "（联网无结果）"

        prompt = f"""请对以下题目进行解析。

【题目内容】
{search_text}

【联网参考资料】
{web_context}

【输出要求】
1. 只输出题目解析，不输出任何废话、寒暄、引导语
2. 格式：
   - **题目类型**：（如选择题/填空题/计算题/阅读理解等）
   - **考查知识点**：（列出核心知识点）
   - **解题思路**：（分步骤说明解题方法）
   - **参考答案**：（给出答案）
   - **关键提醒**：（易错点或注意事项，如无可不写）
3. 优先使用联网参考资料中的信息
4. 如联网无结果，使用你的专业知识解析
5. 不要输出“好的”“以下是”“希望对你有帮助”等废话，直接开始解析"""

        analysis = await asyncio.to_thread(llm.generate, prompt, 1500)
        # 清理可能的废话前缀
        analysis = re.sub(r'^(好的[，,]?\s*|以下是[^"]*?[：:]\s*|让我[^"]*?[：:]\s*)', '', analysis.strip())
        logger.info(f"[photo-search] LLM解析完成, 耗时{_time.time()-t_llm:.1f}s")

    except Exception as e:
        logger.error(f"[photo-search] LLM 解析失败: {e}", exc_info=True)
        analysis = f"解析生成失败，请查看联网搜索结果。\n\n联网摘要：{web_answer[:300] if web_answer else '无'}"

    # ===== 5. 记录查询日志 =====
    try:
        MySQLDB().log_query(user_id=user["user_id"], query=search_text[:200], query_type="photo_search")
    except Exception as e:
        logger.debug(f"查询日志记录失败: {e}")

    logger.info(f"[photo-search] 总耗时: {_time.time()-_t_start:.1f}s (OCR+Tavily+LLM)")
    return {
        "extracted_text": extracted_text,
        "analysis": analysis,
        "web_sources": [
            {"title": s.get("title", ""), "url": s.get("url", ""), "content": s.get("content", "")[:300]}
            for s in web_sources[:5]
        ],
    }


# ======== 学生Agent ========

class StudentAgentRequest(BaseModel):
    """学生Agent查询请求"""
    query: str = Field(..., min_length=1, max_length=5000)
    top_k: int = Field(default=5, ge=1, le=20)
    conversation_id: Optional[str] = Field(default=None, description="会话ID（不传则自动创建）")


@student_router.post("/agent/query")
async def student_agent_query(request: StudentAgentRequest,
                               user: dict = Depends(require_student)):
    """学生端Agent查询 — 自动调用工具、多轮思考"""
    import time
    try:
        from core.models import QueryRequest as CoreQueryRequest
        from langgraph_agent.chat_agent import create_chat_agent, build_agent_system_prompt
        from langgraph_agent.model import create_chat_model
        from llm.llm_client import LLMClient

        # 复用缓存的检索器
        retriever = _get_cached_retriever()

        llm_client = LLMClient()

        model = create_chat_model()
        system_prompt = build_agent_system_prompt(user["user_id"], "通用")
        agent = create_chat_agent(
            model=model, retriever=retriever, llm_client=llm_client,
            system_prompt=system_prompt,
        )

        # 会话管理
        conversation_id = request.conversation_id or str(uuid.uuid4())
        if not request.conversation_id:
            try:
                db = MySQLDB()
                db.execute(
                    "INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, %s)",
                    (conversation_id, user["user_id"], "新对话"))
            except Exception as e:
                logger.debug(f"创建会话失败（非关键）: {e}")

        save_conversation_message(conversation_id, "user", request.query)

        start = time.time()
        from langchain_core.messages import HumanMessage

        # LangFuse trace
        try:
            from monitoring.langfuse_tracer import start_trace
            trace = start_trace(query=request.query, conversation_id=conversation_id,
                                user_id=user["user_id"], strategy="langgraph_agent")
        except Exception as e:
            logger.debug(f"Langfuse trace 启动失败: {e}")
            trace = None

        try:
            result = await agent.ainvoke({"messages": [HumanMessage(content=request.query)]})

            # 提取最终回答
            answer = ""
            for msg in reversed(result.get("messages", [])):
                if hasattr(msg, "content") and msg.content and not hasattr(msg, "tool_calls"):
                    answer = msg.content
                    break

            save_conversation_message(conversation_id, "assistant", answer)

            if trace:
                trace.update(output=answer, status="success")
                trace.flush()

            return {
                "answer": answer,
                "conversation_id": conversation_id,
                "execution_time": time.time() - start,
            }
        except Exception:
            if trace:
                trace.update(status="error")
                trace.flush()
            raise
    except Exception as e:
        logger.error(f"学生Agent查询失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@student_router.post("/agent/query/stream")
async def student_agent_query_stream(request: StudentAgentRequest,
                                      user: dict = Depends(require_student)):
    """
    学生端 Agent 流式查询 (SSE)
    —— LangGraph ReAct Agent + token 逐字流式输出
    """
    from core.stream_events import format_sse

    # 会话管理
    conversation_id = request.conversation_id or str(uuid.uuid4())
    if not request.conversation_id:
        try:
            db = MySQLDB()
            db.execute(
                "INSERT INTO conversations (id, user_id, title) VALUES (%s, %s, %s)",
                (conversation_id, user["user_id"], "新对话"))
        except Exception as e:
            logger.debug(f"创建会话失败（非关键）: {e}")

    # 保存用户消息
    save_conversation_message(conversation_id, "user", request.query)

    return await _langgraph_chat_stream(request, user, conversation_id)


# ======================== LangGraph 引擎适配器 ========================


async def _langgraph_chat_stream(request, user: dict, conversation_id: str):
    """
    LangGraph 引擎的流式查询
    
    使用 langgraph.prebuilt.create_react_agent 替代手写 ReActAgent
    """
    import time as _time
    t0 = _time.time()

    from core.stream_events import format_sse
    from llm.llm_client import LLMClient

    # 复用缓存的检索器（首次请求才构建索引，后续直接复用）
    retriever = _get_cached_retriever()
    logger.info(f"[Agent] Retriever准备完成, 耗时{_time.time()-t0:.2f}s")

    llm_client = LLMClient()

    # 创建 LangGraph Agent
    from langgraph_agent.chat_agent import create_chat_agent, stream_agent_response, build_agent_system_prompt
    from langgraph_agent.model import create_chat_model

    model = create_chat_model()
    system_prompt = build_agent_system_prompt(user.get("user_id", ""), "通用")
    agent = create_chat_agent(
        model=model,
        retriever=retriever,
        llm_client=llm_client,
        system_prompt=system_prompt,
    )

    # 加载历史
    history = load_conversation_history(conversation_id)
    logger.info(f"[Agent流式] conv_id={conversation_id} "
                f"前端传入conv_id={request.conversation_id or '无'} "
                f"历史消息数={len(history)} "
                f"query={request.query[:60]}")
    for i, h in enumerate(history):
        logger.info(f"[Agent流式]   历史[{i}] {h['role']}: {h['content'][:60]}...")

    full_answer = []

    async def event_stream():
        try:
            from langchain_core.runnables import RunnableConfig
            config = RunnableConfig(configurable={"thread_id": conversation_id})

            async for sse_str in stream_agent_response(
                agent, request.query, config=config,
                history=history, conversation_id=conversation_id,
                user_id=user.get("user_id", ""),
            ):
                # 收集 token 内容用于保存
                if sse_str.startswith("data: "):
                    try:
                        data = json.loads(sse_str[6:].strip())
                        if data.get("type") == "token":
                            full_answer.append(data.get("content", ""))
                    except Exception as e:
                        logger.debug(f"SSE token 解析失败: {e}")
                yield sse_str

        except Exception as e:
            logger.error(f"LangGraph流式查询失败: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

        # 保存助手回答
        answer_text = "".join(full_answer)
        if answer_text.strip():
            save_conversation_message(conversation_id, "assistant", answer_text)

        yield f"data: {json.dumps({'type': 'done', 'conversation_id': conversation_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@student_router.get("/agent/tools")
async def student_list_agent_tools(user: dict = Depends(require_student)):
    """列出Agent可用工具"""
    try:
        from langgraph_agent.tools import ALL_TOOLS
        return {
            "tools": [
                {"name": t.name, "description": t.description,
                 "parameters": list(t.args.keys())}
                for t in ALL_TOOLS
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取工具列表失败: {str(e)}")


async def _langgraph_grade_stream(user_message: str, request, user: dict, format_sse):
    """
    LangGraph 引擎的流式批改

    使用 langgraph.StateGraph 替代手写 GradingAgent
    """
    from retriever.hybrid_retriever import HybridRetriever
    from llm.llm_client import LLMClient

    retriever = HybridRetriever()
    llm_client = LLMClient()

    from langgraph_agent.grade_agent import create_grade_agent, stream_grade_response
    from langgraph_agent.model import create_chat_model

    model = create_chat_model()
    agent = create_grade_agent(
        model=model,
        retriever=retriever,
        llm_client=llm_client,
        question_image=request.question_image or None,
        answer_image=request.answer_image or None,
    )

    grading_data = {}

    async def event_stream():
        nonlocal grading_data
        try:
            async for sse_str in stream_grade_response(
                agent,
                user_message,
                question_image=request.question_image or None,
                answer_image=request.answer_image or None,
                question_text=request.question or "",
                answer_text=request.user_answer or "",
            ):
                # 从 stream_grade_response 中拦截 grading_result 事件，获取原始结构化数据
                if sse_str.startswith("data: "):
                    try:
                        data = json.loads(sse_str[6:].strip())
                        if data.get("type") == "grading_result" and data.get("grading"):
                            grading_data = data["grading"]
                    except Exception as e:
                        logger.debug(f"SSE grading_result 解析失败: {e}")
                yield sse_str

        except Exception as e:
            logger.error(f"LangGraph流式批改失败: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

        # 使用 grade_execute 原始结构化数据进行自动保存
        score = grading_data.get("score", 0) if grading_data else 0
        wb_id = None
        if request.auto_save and score < 60 and grading_data:
            try:
                db = MySQLDB()
                wb_id = str(uuid.uuid4())
                db.insert_wrong_book(
                    wb_id=wb_id,
                    user_id=user.get("user_id", ""),
                    subject=grading_data.get("subject", request.subject),
                    question_type=grading_data.get("question_type", request.question_type),
                    question=(request.question or "[图片题目]")[:2000],
                    user_answer=(request.user_answer or "[图片作答]")[:2000],
                    correct_answer=request.correct_answer[:2000],
                    grading=grading_data,
                    status="wrong",
                )
            except Exception as e:
                logger.warning(f"自动保存错题失败: {e}")

            # 刷新用户画像（能力层级 + 易错点）
            if wb_id:
                try:
                    from data_processor.user_profile import refresh_user_profile
                    refresh_user_profile(user.get("user_id", ""), grading_data.get("subject", request.subject))
                except Exception as e:
                    logger.warning(f"刷新用户画像失败: {e}")

        # 最终事件：补上 auto_save 信息
        yield f"data: {json.dumps({'type': 'grading_result', 'grading': grading_data, 'wrong_book_id': wb_id, 'auto_saved': wb_id is not None}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# ======== 智能批改 ========

class GradingRequest(BaseModel):
    """批改请求"""
    question: str = Field(default="", max_length=5000, description="题目内容（文本或留空用图片）")
    user_answer: str = Field(default="", max_length=10000, description="学生作答（文本或留空用图片）")
    correct_answer: str = Field(default="", max_length=5000, description="标准答案")
    subject: str = Field(default="通用", description="学科：语文/数学/英语")
    question_type: str = Field(default="auto", description="客观题/主观题")
    user_steps: str = Field(default="", description="计算过程（已废弃，Agent自动处理）")
    reference_steps: str = Field(default="", description="标准步骤（已废弃，Agent自动处理）")
    grade_level: str = Field(default="初中", description="年级：小学/初中/高中")
    auto_save: bool = Field(default=True, description="是否自动保存错题")
    question_image: str = Field(default="", description="题目图片 base64")
    answer_image: str = Field(default="", description="作答图片 base64")


@student_router.post("/agent/grade")
async def student_grade(request: GradingRequest,
                         user: dict = Depends(require_student)):
    """
    智能批改 — Agent驱动的全流程批改

    Agent工作流：
    1. 有图片 → OCR 提取文字
    2. grading_rubric → 获取年级评分标准
    3. knowledge_reference → 检索参考答案/知识点
    4. reflect → 评估信息充分性
    5. grade_execute → 调用 UnifiedGrader 执行批改
    6. final_answer → 格式化输出结果

    回退策略：Agent 失败时降级为直接调用 UnifiedGrader
    """
    try:
        # ===== 方式一：LangGraph Agent 驱动批改 =====
        try:
            from langgraph_agent.grade_agent import create_grade_agent
            from langgraph_agent.model import create_chat_model
            from retriever.hybrid_retriever import HybridRetriever
            from llm.llm_client import LLMClient

            retriever = HybridRetriever()
            llm_client = LLMClient()
            model = create_chat_model()

            # 构建 Agent 输入消息
            parts = []
            if request.question_image:
                parts.append(f"[题目图片已上传，调用 ocr_extract(content_type='question') 提取文字]")
            if request.answer_image:
                parts.append(f"[作答图片已上传，调用 ocr_extract(content_type='answer') 提取文字]")

            parts.append(f"学科: {request.subject}")
            parts.append(f"题型: {request.question_type}")
            parts.append(f"年级: {request.grade_level}")

            if request.question:
                parts.append(f"题目内容: {request.question[:1500]}")
            if request.user_answer:
                parts.append(f"学生作答: {request.user_answer[:2000]}")
            if request.correct_answer:
                parts.append(f"标准答案: {request.correct_answer[:500]}")
            if request.auto_save:
                parts.append("注意：批改后需自动保存到错题集。")


            user_message = "\n".join(parts)

            if (request.question_image or request.answer_image) and \
               (not request.question and not request.user_answer):
                user_message += "\n\n【重要】题目和作答都是图片形式。请先用 ocr_extract 提取文字，再用提取到的文字进行批改。"

            # 创建并运行 LangGraph Agent
            agent = create_grade_agent(
                model=model,
                retriever=retriever,
                llm_client=llm_client,
                question_image=request.question_image or None,
                answer_image=request.answer_image or None,
            )

            from langgraph_agent.grade_agent import GradeState
            from langchain_core.messages import HumanMessage
            initial_state = GradeState(
                messages=[HumanMessage(content=user_message)],
                user_message=user_message,
                question_image=request.question_image or None,
                answer_image=request.answer_image or None,
                question_text=request.question or "",
                answer_text=request.user_answer or "",
                subject="", question_type="", grade_level="", correct_answer="",
                rubric_data="", reference_data="", reflect_result="", grading_result="",
                is_objective=False, has_images=bool(request.question_image or request.answer_image),
                step=0, current_node="", error=None, final_answer="", tools_used=[], _pending_llm_prompt="",
            )

            result = await agent.ainvoke(initial_state)

            # 非流式路径：直接用 Python 模板生成报告
            from langgraph_agent.grade_agent import _build_analysis_report
            grading_json = result.get("grading_result", "{}")
            try:
                gd = json.loads(grading_json) if isinstance(grading_json, str) else grading_json
            except Exception:
                gd = {}
            result["final_answer"] = _build_analysis_report(
                gd.get("score", "?"), gd.get("max_score", 100), gd.get("feedback", ""),
                gd.get("steps", []), gd.get("highlights", []), gd.get("suggestions", []),
            )

            # 提取批改结果
            grading_json = result.get("grading_result", "{}")
            try:
                grading_data = json.loads(grading_json) if isinstance(grading_json, str) else grading_json
            except Exception as e:
                logger.debug(f"grading_result JSON 解析失败: {e}")
                grading_data = {}

            logger.info(f"[LangGraph批改] 完成: tools={result.get('tools_used')}, "
                       f"steps={result.get('step')}")

        except Exception as agent_err:
            logger.warning(f"Agent批改失败，回退到直接批改: {agent_err}")
            # ===== 方式二：降级为直接批改 =====
            grading_data = _direct_grade(request)
            result = {"tools_used": [], "step": 0}

        # ===== 自动保存错题 =====
        wb_id = None
        score = grading_data.get("score", 0)
        is_correct = grading_data.get("is_correct", False)
        if request.auto_save and (score < 60 or not is_correct):
            try:
                db = MySQLDB()
                wb_id = str(uuid.uuid4())
                db.insert_wrong_book(
                    wb_id=wb_id,
                    user_id=user.get("user_id", ""),
                    subject=request.subject,
                    question_type=grading_data.get("question_type", request.question_type),
                    question=(request.question or "[图片题目]")[:2000],
                    user_answer=(request.user_answer or "[图片作答]")[:2000],
                    correct_answer=request.correct_answer[:2000],
                    grading=grading_data,
                    status="wrong",
                )
            except Exception as e:
                logger.warning(f"自动保存错题失败: {e}")

            # 刷新用户画像（能力层级 + 易错点）
            if wb_id:
                try:
                    from data_processor.user_profile import refresh_user_profile
                    refresh_user_profile(user.get("user_id", ""), request.subject)
                except Exception as e:
                    logger.warning(f"刷新用户画像失败: {e}")

        return {
            "grading": grading_data,
            "wrong_book_id": wb_id,
            "auto_saved": wb_id is not None,
            "graded_by": "langgraph" if result.get("tools_used") else "direct",
            "agent_tools_used": result.get("tools_used", []),
            "agent_steps": result.get("step", 0),
        }
    except Exception as e:
        logger.error(f"批改失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"批改失败: {str(e)}")


@student_router.post("/agent/grade/stream")
async def student_grade_stream(request: GradingRequest,
                               user: dict = Depends(require_student)):
    """
    智能批改 — LangGraph Agent 驱动的流式批改 (SSE)

    逐步输出思考链 + 进度 + 批改结果
    """
    from core.stream_events import format_sse

    # 构建 Agent 输入消息
    parts = []
    if request.question_image:
        parts.append(f"[题目图片已上传，调用 ocr_extract(content_type='question') 提取文字]")
    if request.answer_image:
        parts.append(f"[作答图片已上传，调用 ocr_extract(content_type='answer') 提取文字]")

    parts.append(f"学科: {request.subject}")
    parts.append(f"题型: {request.question_type}")
    parts.append(f"年级: {request.grade_level}")

    if request.question:
        parts.append(f"题目内容: {request.question[:1500]}")
    if request.user_answer:
        parts.append(f"学生作答: {request.user_answer[:2000]}")
    if request.correct_answer:
        parts.append(f"标准答案: {request.correct_answer[:500]}")
    if request.auto_save:
        parts.append("注意：批改后需自动保存到错题集。")

    user_message = "\n".join(parts)

    if (request.question_image or request.answer_image) and \
       (not request.question and not request.user_answer):
        user_message += "\n\n【重要】题目和作答都是图片形式。请先用 ocr_extract 提取文字，再用提取到的文字进行批改。"

    return await _langgraph_grade_stream(
        user_message, request, user, format_sse
    )


def _extract_grading_from_text(text: str) -> dict:
    """
    从纯文本回答中提取批改评分数据

    Agent 的 final_answer 是一段自然语言批改结果，
    需要从中提取 JSON 评分块或解析评论文本中的分数。
    """
    if not text:
        return {}

    # 方法1：从文本中提取 JSON 块
    try:
        json_match = re.search(r'\{[\s\S]*"score"[\s\S]*\}', text[:3000])
        if json_match:
            data = json.loads(json_match.group())
            if "score" in data:
                return data
    except Exception as e:
        logger.debug(f"从文本提取 JSON 评分失败: {e}")

    # 方法2：从 Markdown/自然语言格式中提取评分
    score_patterns = [
        r'评分[：:]\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)',
        r'得分[：:]\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)',
        r'Score[：:]\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)',
        r'总分[：:]\s*(\d+(?:\.\d+)?)',
        r'\*\*评分\*\*[：:]\s*(\d+(?:\.\d+)?)',
        r'\*\*得分\*\*[：:]\s*(\d+(?:\.\d+)?)',
    ]
    for pat in score_patterns:
        m = re.search(pat, text)
        if m:
            score = float(m.group(1))
            max_score = float(m.group(2)) if m.lastindex >= 2 else 100.0
            return {"score": score, "max_score": max_score}

    return {}


def _extract_grading_from_agent_result(agent_result: dict) -> dict:
    """
    从 Agent 结果中提取批改 JSON

    Agent 的 final_answer 可能包含 JSON 块或自然语言描述
    优先查找 grade_execute 返回的 JSON
    """
    answer = agent_result.get("answer", "")
    steps = agent_result.get("steps", [])

    # 方法1：查找 grade_execute 步骤的 JSON 结果
    for step in reversed(steps):
        if step.get("action", "") == "grade_execute":
            result_str = step.get("result", "")
            if "score" in result_str and "max_score" in result_str:
                try:
                    json_match = re.search(r'\{[\s\S]*"score"[\s\S]*\}', result_str)
                    if json_match:
                        return json.loads(json_match.group())
                except Exception as e:
                    logger.debug(f"从 grade_execute 步骤提取 JSON 失败: {e}")

    # 方法2：从 final_answer 中提取 JSON
    try:
        json_match = re.search(r'\{[\s\S]*"score"[\s\S]*\}', answer)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        logger.debug(f"从 final_answer 提取 JSON 失败: {e}")

    # 方法3：从 Markdown/自然语言格式中提取评分
    # 例：📊 评分：100/100  或  得分：80/100  或  Score: 95/100
    score_patterns = [
        r'评分[：:]\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)',
        r'得分[：:]\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)',
        r'Score[：:]\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)',
        r'总分[：:]\s*(\d+(?:\.\d+)?)',
    ]
    for pat in score_patterns:
        m = re.search(pat, answer)
        if m:
            score = float(m.group(1))
            max_score = float(m.group(2)) if m.lastindex >= 2 else 100.0
            # 判断对错
            is_correct_str = None
            if '✅ 正确' in answer or '完全正确' in answer:
                is_correct_str = True
            elif '❌ 错误' in answer:
                is_correct_str = False
            
            return {
                "score": score,
                "max_score": max_score,
                "is_correct": is_correct_str if is_correct_str is not None else (score >= 60),
                "question_type": "auto",
                "feedback": answer[:500] if answer else "批改完成",
                "agent_raw": answer[:1000] if answer else "",
            }

    # 方法4：构建简化结果兜底
    return {
        "score": 0,
        "max_score": 100,
        "question_type": "auto",
        "feedback": answer[:500] if answer else "批改完成，请查看详细结果",
        "agent_raw": answer[:1000] if answer else "",
    }


def _direct_grade(request: GradingRequest) -> dict:
    """直接调用 UnifiedGrader（Agent 降级方案）"""
    from agent.grading import UnifiedGrader
    grader = UnifiedGrader()

    result = grader.auto_detect_and_grade(
        question=request.question,
        user_answer=request.user_answer,
        correct_answer=request.correct_answer,
        subject=request.subject,
        question_type=request.question_type,
        user_steps=request.user_steps,
        reference_steps=request.reference_steps,
        grade_level=request.grade_level,
    )
    return result.to_dict()


# ======== 错题集 ========

class WrongBookQueryParams:
    """错题集查询参数"""


@student_router.get("/wrong-book")
async def list_wrong_book(subject: str = None, limit: int = 50,
                           user: dict = Depends(require_student)):
    """获取错题列表"""
    db = MySQLDB()
    uid = user.get("user_id", "")
    rows = db.list_wrong_book(user_id=uid, subject=subject, limit=limit)
    # 解析JSON字段
    for r in rows:
        for f in ["grading"]:
            if r.get(f) and isinstance(r[f], str):
                try:
                    r[f] = json.loads(r[f])
                except Exception as e:
                    logger.debug(f"错题 grading JSON 解析失败: {e}")
        if r.get("created_at"):
            r["created_at"] = str(r["created_at"])
    return {"wrong_book": rows, "total": len(rows)}


@student_router.get("/wrong-book/stats")
async def wrong_book_stats(user: dict = Depends(require_student)):
    """错题集统计"""
    db = MySQLDB()
    uid = user.get("user_id", "")
    return db.get_wrong_book_stats(user_id=uid)


@student_router.delete("/wrong-book/{wb_id}")
async def delete_wrong_book(wb_id: str, user: dict = Depends(require_student)):
    """删除错题"""
    db = MySQLDB()
    uid = user.get("user_id", "")
    affected = db.delete_wrong_book(wb_id, uid)
    if affected == 0:
        raise HTTPException(status_code=404, detail="未找到该错题")
    return {"message": "已删除"}


# ======== 举一反三 ========

@student_router.post("/wrong-book/{wb_id}/analogy")
async def generate_analogy(wb_id: str, user: dict = Depends(require_student)):
    """
    举一反三：根据错题生成 3 道变式题（Agent 驱动）

    工作流：
    1. 从 DB 读取错题信息
    2. 调用 GradingAgent 的 analogy_question 工具
    3. 返回变式题列表
    """
    try:
        db = MySQLDB()
        uid = user.get("user_id", "")
        row = db.get_wrong_book_by_id(wb_id)
        if not row or row.get("user_id") != uid:
            raise HTTPException(status_code=404, detail="未找到该错题")

        # 解析 JSON 字段
        grading = row.get("grading")
        if isinstance(grading, str):
            try:
                grading = json.loads(grading)
            except Exception as e:
                logger.debug(f"举一反三 grading JSON 解析失败: {e}")
                grading = {}

        from langgraph_agent.tools import analogy_question, get_tool_provider
        from llm.llm_client import LLMClient

        # 确保工具提供器已初始化
        provider = get_tool_provider()
        provider.set_dependencies(llm_client=LLMClient())

        # 构造 gradin 摘要
        grading_summary = json.dumps({
            "score": grading.get("score", 0),
            "feedback": (grading.get("feedback", "") or "")[:100],
            "error_types": [h.get("error_type", "") for h in grading.get("highlights", [])[:3]],
        }, ensure_ascii=False)

        result_str = analogy_question.invoke({
            "question": (row.get("question") or "")[:1000],
            "user_answer": (row.get("user_answer") or "")[:500],
            "subject": row.get("subject", "数学"),
            "question_type": row.get("question_type", "客观题"),
            "grade_level": "初中",
            "grading_result": grading_summary,
        })

        result = json.loads(result_str) if isinstance(result_str, str) else result_str
        return {"wb_id": wb_id, **result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"举一反三生成失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成失败: {str(e)}")


# ======== 艾宾浩斯遗忘曲线 ========

EBBINGHAUS_CURVE = [
    {"label": "20分钟", "hours": 0.33, "retention": 58},
    {"label": "1小时", "hours": 1, "retention": 44},
    {"label": "9小时", "hours": 9, "retention": 36},
    {"label": "1天", "hours": 24, "retention": 34},
    {"label": "2天", "hours": 48, "retention": 28},
    {"label": "6天", "hours": 144, "retention": 25},
    {"label": "1个月", "hours": 720, "retention": 21},
]

REVIEW_SCHEDULE = [
    {"label": "第1次复习", "days": 1, "description": "学习后1天复习"},
    {"label": "第2次复习", "days": 2, "description": "学习后2天复习"},
    {"label": "第3次复习", "days": 4, "description": "学习后4天复习"},
    {"label": "第4次复习", "days": 7, "description": "学习后7天复习"},
    {"label": "第5次复习", "days": 15, "description": "学习后15天复习"},
    {"label": "第6次复习", "days": 30, "description": "学习后30天复习"},
]


@student_router.get("/wrong-book/ebbinghaus")
async def get_ebbinghaus_curve(user: dict = Depends(require_student)):
    """
    获取艾宾浩斯遗忘曲线数据

    返回：
    - curve: 理论曲线数据点
    - items: 每道错题的遗忘曲线位置
    - review_schedule: 建议的复习时间表
    """
    from datetime import datetime, timezone

    db = MySQLDB()
    uid = user.get("user_id", "")
    rows = db.list_wrong_book(user_id=uid, limit=200)

    now = datetime.now()

    items_on_curve = []
    for r in rows:
        created_str = str(r.get("created_at", ""))
        if not created_str:
            continue

        try:
            created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            if created.tzinfo:
                created = created.replace(tzinfo=None)
            hours_since = max(0, (now - created).total_seconds() / 3600)
        except Exception:
            hours_since = 0

        # 找到最近的曲线点
        closest_point = EBBINGHAUS_CURVE[0]
        for pt in EBBINGHAUS_CURVE:
            if hours_since >= pt["hours"]:
                closest_point = pt

        review_count = r.get("review_count", 0) or 0

        # 计算下次复习时间（基于复习次数推荐下一次复习天数）
        next_review_days = REVIEW_SCHEDULE[min(review_count, len(REVIEW_SCHEDULE) - 1)]["days"]
        last_reviewed = r.get("last_reviewed_at")
        # review_count == 0 表示从未真正复习过，按创建时间计算
        if review_count == 0:
            days_since_review = int(hours_since / 24)
        elif last_reviewed:
            try:
                lr = datetime.fromisoformat(str(last_reviewed).replace("Z", "+00:00"))
                if lr.tzinfo:
                    lr = lr.replace(tzinfo=None)
                days_since_review = max(0, (now - lr).days)
            except Exception:
                days_since_review = int(hours_since / 24)
        else:
            days_since_review = int(hours_since / 24)

        items_on_curve.append({
            "id": r.get("id", ""),
            "question": (r.get("question") or "图片题目")[:60],
            "subject": r.get("subject", ""),
            "hours_since": round(hours_since, 1),
            "estimated_retention": closest_point["retention"],
            "curve_label": closest_point["label"],
            "review_count": review_count,
            "next_review_in_days": next_review_days,
            "days_since_review": days_since_review,
            "needs_review": True if review_count == 0 else days_since_review >= next_review_days,
        })

    # 统计
    needs_review = sum(1 for i in items_on_curve if i["needs_review"])

    return {
        "curve": EBBINGHAUS_CURVE,
        "items": items_on_curve,
        "review_schedule": REVIEW_SCHEDULE,
        "total_items": len(items_on_curve),
        "needs_review_count": needs_review,
    }


@student_router.post("/wrong-book/{wb_id}/review")
async def review_wrong_question(wb_id: str, user: dict = Depends(require_student)):
    """标记已复习（艾宾浩斯遗忘曲线计数+1）"""
    db = MySQLDB()
    uid = user.get("user_id", "")
    row = db.get_wrong_book_by_id(wb_id)
    if not row or row.get("user_id") != uid:
        raise HTTPException(status_code=404, detail="未找到该错题")
    db.review_wrong_book(wb_id)
    return {"message": "已复习", "review_count": (row.get("review_count") or 0) + 1}


# ======== 知识图谱探索 ========

@student_router.get("/graph/data")
async def get_graph_data(subject: str = None, grade: str = None, user: dict = Depends(require_student)):
    """获取知识图谱数据（实体 + 关系），供 ECharts 渲染。
    可选参数: subject=数学/物理/..., grade=初中/高中/小学
    返回精简字段（无 source_chunks/description），保证前端轻量渲染。
    """
    try:
        from data_processor.graph_builder import KnowledgeGraphManager
        mgr = KnowledgeGraphManager()
        graph = mgr.get_graph()
        if not graph or graph.entity_count == 0:
            return {"entities": [], "relations": [], "stats": {"entity_count": 0, "relation_count": 0}}

        # 按 subject / grade 过滤实体
        # 注意：空 grade/subject 视为"通用"（匹配所有筛选条件）
        filtered_names = set()
        for ent in graph.entities.values():
            match = True
            if subject and ent.subject and ent.subject != subject:
                match = False
            if grade and ent.grade and ent.grade != grade:
                match = False
            if match:
                filtered_names.add(ent.name)

        # 精简序列化（仅保留 ECharts 渲染所需字段）
        entities_data = []
        for name in filtered_names:
            ent = graph.entities[name]
            entities_data.append({
                "name": ent.name,
                "entity_type": ent.entity_type,
                "subject": ent.subject,
                "grade": ent.grade,
                "display_name": ent.display_name or ent.name,
            })

        relations_data = []
        for source, edges in graph.adjacency.items():
            if source not in filtered_names:
                continue
            for target, relation, weight in edges:
                if target in filtered_names:
                    relations_data.append({
                        "source": source, "target": target,
                        "relation": relation, "weight": weight,
                    })

        from collections import defaultdict
        type_dist = defaultdict(int)
        subj_dist = defaultdict(int)
        for e in entities_data:
            type_dist[e["entity_type"]] += 1
            if e.get("subject"):
                subj_dist[e["subject"]] += 1

        return {
            "entities": entities_data,
            "relations": relations_data,
            "stats": {
                "entity_count": len(entities_data),
                "relation_count": len(relations_data),
                "entity_types": dict(type_dist),
                "subject_distribution": dict(subj_dist),
            },
        }
    except Exception as e:
        logger.error(f"获取知识图谱数据失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取知识图谱数据失败: {str(e)}")


@student_router.get("/graph/stats")
async def get_graph_stats(grade: str = None, user: dict = Depends(require_student)):
    """获取知识图谱统计信息。可选 grade 参数筛选特定学段的学科分布。"""
    try:
        from data_processor.graph_builder import KnowledgeGraphManager
        mgr = KnowledgeGraphManager()
        graph = mgr.get_graph()
        if not graph or graph.entity_count == 0:
            return {"status": "empty", "entity_count": 0, "relation_count": 0, "subject_distribution": {}}

        stats = graph.get_stats()
        if grade:
            # 只统计该学段实体的学科分布（过滤少于5个实体的噪音学科）
            from collections import defaultdict
            subj_dist = defaultdict(int)
            for ent in graph.entities.values():
                if ent.grade and grade in ent.grade.split("、"):
                    for s in (ent.subject or "").split("、"):
                        s = s.strip()
                        if s:
                            subj_dist[s] += 1
                    if not ent.subject:
                        subj_dist["通用"] += 1
            stats["subject_distribution"] = {
                k: v for k, v in subj_dist.items() if v >= 5
            }

        stats["status"] = "ready"
        return stats
    except Exception as e:
        logger.error(f"获取知识图谱统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取知识图谱统计失败: {str(e)}")


@student_router.get("/graph/entity/{name}")
async def get_entity_detail(name: str, user: dict = Depends(require_student)):
    """获取单个实体详情及其 1 跳邻居"""
    try:
        from data_processor.graph_builder import KnowledgeGraphManager
        mgr = KnowledgeGraphManager()
        graph = mgr.get_graph()
        if not graph:
            raise HTTPException(status_code=404, detail="知识图谱未加载")

        entity = graph.get_entity(name)
        if not entity:
            raise HTTPException(status_code=404, detail="实体不存在")

        neighbors = graph.get_neighbors(name, max_hops=1)
        neighbor_list = []
        for ent, rel, weight, hop in neighbors:
            neighbor_list.append({
                "name": ent.name,
                "type": ent.entity_type,
                "relation": rel,
                "weight": weight,
                "hop": hop,
                "description": ent.description,
                "subject": ent.subject,
                "display_name": ent.display_name or ent.name,
            })

        return {
            "entity": entity.to_dict(),
            "neighbors": neighbor_list,
            "neighbor_count": len(neighbor_list),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取实体详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取实体详情失败: {str(e)}")