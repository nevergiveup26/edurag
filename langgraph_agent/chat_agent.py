"""
LangGraph ReAct Chat Agent

使用 langgraph.prebuilt.create_react_agent 替代手写的 ReAct 循环（原 agent/rag_agent.py）。
LLM 原生支持 function calling，无需手动解析 Thought/Action/Action Input。

特性：
- 自动工具调用与循环终止
- 流式事件输出（适配现有 SSE 格式）
- 系统提示词规则保留
"""

import threading
import time
from typing import List, Dict, Any, Optional, AsyncGenerator

from langgraph.prebuilt import create_react_agent
from langgraph.graph.state import CompiledStateGraph
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_core.runnables import RunnableConfig

from core.logger import get_logger
from langgraph_agent.model import create_chat_model
from langgraph_agent.tools import create_langchain_tools, CHAT_TOOLS

logger = get_logger("langgraph_chat_agent")

# ======================== 系统提示词（适配 LangGraph） ========================

CHAT_SYSTEM_PROMPT = """你是 EduRAG 智慧问答系统的 AI 学习助手，名字叫"小E"。

【身份与风格】
你是一位耐心、博学的学习伙伴，专门帮助中小学生解答学科问题、梳理知识点、检索资料。
语气亲切自然、循循善诱，像一位课后辅导老师。

【检索规则】
对于任何需要事实信息的问题（学科知识、人物查询、机构信息、政策咨询、最新资讯等）：
1. 先调用 knowledge_search 检索本地知识库（含课程资料、校本教材、训练数据等）
2. 如果 knowledge_search 返回了足够的信息，直接基于本地结果回答，不要再调用 tavily_web_search
3. 只有当 knowledge_search 返回空结果或信息明显不足以回答问题时，才调用 tavily_web_search 补充

只有以下情况允许跳过所有检索：
- 纯问候/闲聊（"你好""谢谢"）
- 学生已经给了你答案让你帮忙看看对不对（批改场景）

【规则】
1. 检索不到时如实告知，建议学生换个问法
2. 回答时使用自然语言，禁止出现 Thought/Action/Observation 等词汇
3. 你的名字是"小E"（最终回答中可以提）
4. 优先采用本地知识库结果，信息不足时补充网络搜索结果

开始吧！学生在等你了。"""


def build_agent_system_prompt(user_id: str = None, subject: str = None) -> str:
    """构建含用户画像的系统提示词"""
    prompt = CHAT_SYSTEM_PROMPT
    if not user_id:
        return prompt
    try:
        from database.mysql_db import MySQLDB
        from data_processor.user_profile import build_profile_section
        db = MySQLDB()
        profile = db.get_user_profile(user_id, subject=subject or "通用")
        if profile:
            section = build_profile_section(profile)
            if section:
                prompt = section + prompt
                # 性格分析放在后台线程执行，不阻塞 Agent 构建路径
                threading.Thread(
                    target=_maybe_trigger_personality,
                    args=(user_id,),
                    daemon=True,
                ).start()
    except Exception as e:
        logger.debug(f"性格分析触发失败: {e}")
    return prompt


def _maybe_trigger_personality(user_id: str):
    """检查是否需要触发性格分析（累计 20 轮对话后触发）"""
    try:
        from database.mysql_db import MySQLDB
        from data_processor.user_profile import update_personality
        import random
        # 10% 概率触发检查，避免每次查询都查 DB
        if random.random() > 0.1:
            return
        db = MySQLDB()
        count_row = db.query_one(
            "SELECT COUNT(DISTINCT conversation_id) as cnt FROM conversation_messages "
            "WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id = %s) AND role = 'user'",
            (user_id,)
        )
        total_queries = count_row["cnt"] if count_row else 0
        if total_queries > 0 and total_queries % 20 == 0:
            tags = update_personality(user_id)
            if tags:
                db.upsert_user_profile(user_id, "通用", personality_tags=tags)
    except Exception as e:
        logger.debug(f"用户画像更新失败: {e}")


def create_chat_agent(
    model: BaseChatModel = None,
    tools: List[BaseTool] = None,
    system_prompt: str = None,
    retriever=None,
    llm_client=None,
    kb_manager=None,
) -> CompiledStateGraph:
    """
    创建 LangGraph ReAct Chat Agent

    Args:
        model: LangChain ChatModel（不传则自动创建 ChatOpenAI）
        tools: LangChain 工具列表（不传则使用默认 CHAT_TOOLS）
        system_prompt: 系统提示词（不传则使用默认）
        retriever: 混合检索器（用于工具初始化）
        llm_client: LLMClient（用于工具初始化）
        kb_manager: 知识库管理器（用于工具初始化）

    Returns:
        CompiledStateGraph — 编译好的 LangGraph Agent
    """
    if model is None:
        model = create_chat_model()

    if tools is None:
        _, chat_tools, _ = create_langchain_tools(
            retriever=retriever,
            llm_client=llm_client,
            kb_manager=kb_manager,
        )
        tools = chat_tools

    if system_prompt is None:
        system_prompt = CHAT_SYSTEM_PROMPT

    # 使用 langgraph 预构建的 ReAct Agent
    agent = create_react_agent(
        model=model,
        tools=tools,
        prompt=system_prompt,
    )

    logger.info(f"LangGraph Chat Agent 创建完成，工具数: {len(tools)}")
    return agent


# ======================== 流式事件适配器 ========================

def format_langgraph_event(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    将 LangGraph 流式事件转换为现有 SSE 事件格式。

    事件类型映射:
      - on_chat_model_stream → token（逐字输出）
      - on_tool_start       → action（工具调用开始）
      - on_tool_end         → observation（工具调用结果）
      - on_chain_end        → done（完成）

    Args:
        event: LangGraph astream_events 产出的事件

    Returns:
        标准化的 SSE 事件 dict，不需要的返回 None
    """
    event_type = event.get("event", "")

    if event_type == "on_chat_model_stream":
        chunk = event.get("data", {}).get("chunk")
        if chunk and hasattr(chunk, "content") and chunk.content:
            return {
                "type": "token",
                "content": chunk.content,
            }

    elif event_type == "on_tool_start":
        tool_name = event.get("name", "unknown")
        tool_input = event.get("data", {}).get("input", {})
        return {
            "type": "action",
            "action": tool_name,
            "input": tool_input,
        }

    elif event_type == "on_tool_end":
        tool_name = event.get("name", "unknown")
        output = event.get("data", {}).get("output", "")
        return {
            "type": "observation",
            "action": tool_name,
            "output": str(output) if output else "",
        }

    return None


async def stream_agent_response(
    agent: CompiledStateGraph,
    user_message: str,
    config: RunnableConfig = None,
    history: List[dict] = None,
    conversation_id: str = None,
    user_id: str = None,
    images: Optional[List[str]] = None,
    strategy: str = "direct",
) -> AsyncGenerator[str, None]:
    """
    流式输出 Agent 响应（转换为 SSE 格式字符串）

    用法：
        async for sse_str in stream_agent_response(agent, "你好"):
            yield sse_str

    Args:
        agent: 编译好的 LangGraph Agent
        user_message: 用户消息
        config: 可选的 RunnableConfig（含 thread_id 等）
        history: 历史对话记录 [{"role": "user/assistant", "content": "..."}]
        conversation_id: 会话ID（会通过 done 事件返回给前端）
        user_id: 用户ID（用于 LangFuse 追踪）

    Yields:
        SSE 格式字符串
    """
    import json as _json

    logger.info(f"[Agent] 检索策略: {strategy}  query='{user_message[:60]}'")

    # 图片 OCR 处理：将图片文字拼入用户消息
    if images:
        from llm.ocr_client import get_ocr_client
        ocr = get_ocr_client()
        ocr_texts = []
        for idx, img_b64 in enumerate(images):
            try:
                result = ocr.extract_text(img_b64, label=f"图片{idx+1}")
                text = result.get("extracted_text", "")
                if text:
                    ocr_texts.append(f"[图片{idx+1}的文字内容]\n{text}")
            except Exception as e:
                logger.warning(f"OCR 失败 (图片{idx+1}): {e}")
        if ocr_texts:
            user_message = user_message + "\n\n" + "\n\n".join(ocr_texts)

    # 创建 LangFuse 追踪
    try:
        from monitoring.langfuse_tracer import start_trace
        trace = start_trace(
            query=user_message,
            conversation_id=conversation_id,
            user_id=user_id,
            strategy="langgraph_agent",
        )
        logger.info(f"[Langfuse] Trace 创建成功: trace_id={trace.trace_id}, span={'OK' if trace._span else 'None'}")
    except Exception as e:
        logger.error(f"[Langfuse] Trace 创建失败: {e}", exc_info=True)
        trace = None

    # 构建消息列表（含历史）
    messages = []
    if history:
        for h in history[-20:]:  # 最多保留最近20轮
            role = h.get("role", "")
            content = h.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=user_message))

    # 监控日志：打印发给模型的消息摘要
    logger.info(f"[Agent输入] conv_id={conversation_id or 'N/A'} "
                f"history_count={len(history or [])} total_messages={len(messages)}")
    for i, m in enumerate(messages):
        role = type(m).__name__.replace("Message", "").lower()
        preview = (m.content or "")[:80].replace("\n", " ")
        logger.info(f"[Agent输入]   [{i}] {role}: {preview}...")

    full_answer_parts = []
    tool_timers: dict = {}  # tool_name → start_time
    total_input_tokens = 0
    total_output_tokens = 0
    model_name = None
    generation_start = None
    first_token_time = None

    try:
        async for event in agent.astream_events(
            {"messages": messages},
            config=config,
            version="v2",
        ):
            formatted = format_langgraph_event(event)
            event_type = event.get("event", "")
            event_name = event.get("name", "unknown")

            # LangFuse: track LLM generation start
            if trace and event_type == "on_chat_model_start":
                generation_start = time.time()
                first_token_time = None
                # 提取模型名
                meta = event.get("metadata", {})
                model_name = meta.get("ls_model_name") or meta.get("ls_model_id") or "unknown"

            # LangFuse: track first token timing
            if trace and first_token_time is None and event_type == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk", {})
                if hasattr(chunk, "content") and chunk.content:
                    first_token_time = time.time()

            # LangFuse: track LLM generation end — create GENERATION observation
            if trace and event_type == "on_chat_model_end":
                output_data = event.get("data", {}).get("output", {})
                gen_input_tokens = 0
                gen_output_tokens = 0
                if hasattr(output_data, "usage_metadata") and output_data.usage_metadata is not None:
                    usage = output_data.usage_metadata
                    gen_input_tokens = usage.get("input_tokens", 0)
                    gen_output_tokens = usage.get("output_tokens", 0)
                    logger.info(f"[Token] usage_metadata: input={gen_input_tokens}, output={gen_output_tokens}")
                elif hasattr(output_data, "response_metadata"):
                    usage = output_data.response_metadata.get("token_usage", {})
                    gen_input_tokens = usage.get("prompt_tokens", 0)
                    gen_output_tokens = usage.get("completion_tokens", 0)
                    logger.info(f"[Token] response_metadata: input={gen_input_tokens}, output={gen_output_tokens}, raw={output_data.response_metadata}")
                else:
                    logger.info(f"[Token] 无 usage_metadata/response_metadata, output_data type={type(output_data)}")
                    # 打印可用属性帮助调试
                    if hasattr(output_data, 'response_metadata'):
                        logger.info(f"[Token] response_metadata={output_data.response_metadata}")
                total_input_tokens += gen_input_tokens
                total_output_tokens += gen_output_tokens

                trace.log_observation(
                    name="LLM generation",
                    input_data=event.get("data", {}).get("input", {}),
                    output_data=str(output_data)[:500],
                    start_time=generation_start,
                    end_time=time.time(),
                    level="DEFAULT",
                    model=model_name or "unknown",
                    as_type="generation",
                    usage={"input": gen_input_tokens, "output": gen_output_tokens}
                           if gen_input_tokens or gen_output_tokens else None,
                    prompt_name="chat_prompt",
                    completion_start_time=first_token_time,
                )

            # LangFuse: track tool calls as observations
            if trace:
                if event_type == "on_tool_start":
                    tool_timers[event_name] = time.time()
                elif event_type == "on_tool_end":
                    t0 = tool_timers.pop(event_name, None)
                    trace.log_observation(
                        name=event_name,
                        input_data=event.get("data", {}).get("input", {}),
                        output_data=str(event.get("data", {}).get("output", ""))[:500],
                        start_time=t0,
                        end_time=time.time(),
                        level="DEFAULT",
                    )

            if formatted:
                if formatted.get("type") == "token":
                    full_answer_parts.append(formatted.get("content", ""))
                yield f"data: {_json.dumps(formatted, ensure_ascii=False)}\n\n"

        # 发送完成事件（含 conversation_id 供前端多轮对话）
        done_data = {"type": "done"}
        if conversation_id:
            done_data["conversation_id"] = conversation_id
        yield f"data: {_json.dumps(done_data, ensure_ascii=False)}\n\n"

        # LangFuse: 标记成功
        if trace:
            answer = "".join(full_answer_parts)
            logger.info(f"[Langfuse] 准备 flush: trace_id={trace.trace_id}, answer_len={len(answer)}")
            trace.update(
                output=answer,
                status="success",
                metadata={
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens": total_input_tokens + total_output_tokens,
                    "retrieval_strategy": strategy,
                },
            )
            trace.flush()
            logger.info(f"[Langfuse] flush 完成")

    except Exception as e:
        logger.error(f"Agent 流式输出异常: {e}", exc_info=True)
        if trace:
            trace.update(output=str(e), status="error")
            trace.flush()
        yield f"data: {_json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
