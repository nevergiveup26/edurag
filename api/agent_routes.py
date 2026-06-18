"""
Agentic RAG 路由
——从 routes.py 拆分出的 Agent 查询端点
"""
import uuid
import json
import time

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage

from core.logger import get_logger
from api.shared_models import QueryRequestModel, QueryResponseModel, SourceItem
from api.conversation_helpers import save_conversation_message, load_conversation_history

logger = get_logger("agent_routes")

agent_router = APIRouter()


@agent_router.post("/agent/query")
async def agent_query(request: QueryRequestModel):
    """
    Agentic RAG 查询（非流式）
    """
    from langgraph_agent.chat_agent import create_chat_agent, build_agent_system_prompt
    from langgraph_agent.model import create_chat_model

    start_time = time.time()
    conversation_id = request.conversation_id or str(uuid.uuid4())

    history = load_conversation_history(conversation_id)

    model = create_chat_model()

    save_conversation_message(conversation_id, "user", request.query)

    agent_messages = []
    for h in history[-20:]:
        if h.get("role") == "user":
            agent_messages.append(HumanMessage(content=h.get("content", "")))
        elif h.get("role") == "assistant":
            agent_messages.append(AIMessage(content=h.get("content", "")))
    query_text = request.query
    # 智能路由：确定检索策略
    from router.query_router import get_query_router
    router = get_query_router()
    strategy = router.route(query_text)
    logger.info(f"[AgentQuery] 路由结果: strategy={strategy} query='{query_text[:50]}'")

    # 策略预处理（非 direct 策略）
    strategy_context = None
    if strategy != "direct":
        from strategy import execute_strategy
        from llm.llm_client import get_fast_llm
        from retriever.hybrid_retriever import HybridRetriever
        from langgraph_agent.tools import _provider, tavily_web_search

        async def _web_search_fn(q: str) -> str:
            return tavily_web_search.invoke({"query": q})

        strategy_result = await execute_strategy(
            strategy=strategy,
            query=request.query,
            retriever=HybridRetriever(),
            llm=get_fast_llm(),
            web_search_fn=_web_search_fn,
        )
        if strategy_result and strategy_result.context:
            strategy_context = strategy_result.context
            logger.info(f"[AgentQuery] 策略预处理完成: {strategy} context_len={len(strategy_context)}")

    # 构建 system_prompt（有策略上下文则注入）
    system_prompt = build_agent_system_prompt(request.user_id, "通用")
    if strategy_context:
        from langgraph_agent.chat_agent import CHAT_SYSTEM_PROMPT
        system_prompt = CHAT_SYSTEM_PROMPT + "\n\n【系统已检索到的参考资料】\n" + strategy_context
        system_prompt = system_prompt + "\n\n请直接基于以上参考资料回答用户问题，不要调用 knowledge_search 工具。"

    # 创建 agent（非 direct 策略有上下文时只用 final_answer 工具）
    if strategy != "direct" and strategy_context:
        from langgraph_agent.tools import final_answer
        agent = create_chat_agent(model=model, tools=[final_answer], system_prompt=system_prompt)
    else:
        agent = create_chat_agent(model=model, system_prompt=system_prompt)

    if request.images:
        from llm.ocr_client import get_ocr_client
        ocr = get_ocr_client()
        for idx, img_b64 in enumerate(request.images):
            try:
                result = ocr.extract_text(img_b64, label=f"图片{idx+1}")
                text = result.get("extracted_text", "")
                if text:
                    query_text += f"\n\n[图片{idx+1}的文字内容]\n{text}"
            except Exception as e:
                logger.warning(f"OCR 失败: {e}")
    agent_messages.append(HumanMessage(content=query_text))

    try:
        from monitoring.langfuse_tracer import start_trace
        trace = start_trace(query=request.query, conversation_id=conversation_id,
                            user_id=request.user_id, strategy="langgraph_agent")
    except Exception as e:
        logger.debug(f"Langfuse trace 启动失败: {e}")
        trace = None

    try:
        result = await agent.ainvoke({"messages": agent_messages})

        answer = ""
        tool_calls_info = []
        for msg in reversed(result.get("messages", [])):
            if hasattr(msg, "content") and msg.content and not getattr(msg, "tool_calls", None):
                answer = msg.content
                break

        for msg in result.get("messages", []):
            if getattr(msg, "tool_calls", None):
                for tc in msg.tool_calls:
                    tool_name = tc.get("name", "unknown")
                    tool_calls_info.append(SourceItem(
                        content=str(tc.get("args", ""))[:300],
                        score=1.0,
                        source=tool_name,
                        metadata={"tool_name": tool_name, "arguments": tc.get("args")},
                    ))
                    if trace:
                        trace.log_observation(name=tool_name, input_data=tc.get("args"),
                                             output_data=str(tc.get("args", ""))[:300])

        save_conversation_message(conversation_id, "assistant", answer)

        if trace:
            trace.update(output=answer, status="success")
            trace.flush()

        return QueryResponseModel(
            answer=answer,
            sources=tool_calls_info,
            strategy_used="langgraph_agent",
            router_used="agent",
            execution_time=time.time() - start_time,
            conversation_id=conversation_id,
        )
    except Exception:
        if trace:
            trace.update(status="error")
            trace.flush()
        raise


@agent_router.post("/agent/query/stream")
async def agent_query_stream(request: QueryRequestModel):
    """
    Agentic RAG 流式查询

    SSE 事件流：thinking → action → observation → reflection → token → done
    """
    from langgraph_agent.chat_agent import create_chat_agent, stream_agent_response, build_agent_system_prompt
    from langgraph_agent.model import create_chat_model

    conversation_id = request.conversation_id or str(uuid.uuid4())
    history = load_conversation_history(conversation_id)

    logger.info(f"[Agent流式] conv_id={conversation_id} "
                f"query={request.query[:60]} history={len(history)}")

    model = create_chat_model()

    save_conversation_message(conversation_id, "user", request.query)

    # 智能路由
    from router.query_router import get_query_router
    router = get_query_router()
    strategy = router.route(request.query)
    logger.info(f"[AgentStream] 路由结果: strategy={strategy} query='{request.query[:50]}'")

    # 策略预处理（非 direct 策略）
    strategy_context = None
    if strategy != "direct":
        from strategy import execute_strategy
        from llm.llm_client import get_fast_llm
        from langgraph_agent.tools import _provider, tavily_web_search

        async def _web_search_fn(q: str) -> str:
            return tavily_web_search.invoke({"query": q})

        from retriever.hybrid_retriever import HybridRetriever
        strategy_result = await execute_strategy(
            strategy=strategy,
            query=request.query,
            retriever=HybridRetriever(),
            llm=get_fast_llm(),
            web_search_fn=_web_search_fn,
        )
        if strategy_result and strategy_result.context:
            strategy_context = strategy_result.context
            logger.info(f"[AgentStream] 策略预处理完成: {strategy} context_len={len(strategy_context)}")

    # 构建 system_prompt（有策略上下文则注入）
    system_prompt = build_agent_system_prompt(request.user_id, "通用")
    if strategy_context:
        from langgraph_agent.chat_agent import CHAT_SYSTEM_PROMPT
        system_prompt = CHAT_SYSTEM_PROMPT + "\n\n【系统已检索到的参考资料】\n" + strategy_context
        system_prompt = system_prompt + "\n\n请直接基于以上参考资料回答用户问题，不要调用 knowledge_search 工具。"

    # 创建 agent（非 direct 策略有上下文时只用 final_answer 工具）
    if strategy != "direct" and strategy_context:
        from langgraph_agent.tools import final_answer
        agent = create_chat_agent(model=model, tools=[final_answer], system_prompt=system_prompt)
    else:
        agent = create_chat_agent(model=model, system_prompt=system_prompt)

    full_answer = []

    async def event_stream():
        from langchain_core.runnables import RunnableConfig
        config = RunnableConfig(configurable={"thread_id": conversation_id})

        try:
            async for sse_str in stream_agent_response(
                agent, request.query, config=config, history=history,
                conversation_id=conversation_id, user_id=request.user_id,
                images=request.images,
                strategy=strategy,
            ):
                if sse_str.startswith("data: "):
                    try:
                        data = json.loads(sse_str[6:].strip())
                        if data.get("type") == "token":
                            full_answer.append(data.get("content", ""))
                    except Exception as e:
                        logger.debug(f"SSE token 解析失败: {e}")
                yield sse_str
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

        answer_text = "".join(full_answer)
        if answer_text.strip():
            save_conversation_message(conversation_id, "assistant", answer_text)

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@agent_router.post("/agent/voice-to-text")
async def voice_to_text(audio: UploadFile = File(...)):
    """
    语音转文字：接收音频文件，调用 DashScope Paraformer 识别，返回文字。
    """
    import base64
    import os

    audio_bytes = await audio.read()
    if len(audio_bytes) < 500:
        raise HTTPException(status_code=400, detail="录音太短，请重试")

    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("LLM_API_KEY") or ""
    if not api_key:
        from core.config_manager import ConfigManager
        api_key = ConfigManager().dashscope_config.get("api_key", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="语音识别服务未配置")

    try:
        import dashscope
        from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

        class _Callback(RecognitionCallback):
            def __init__(self):
                self.text = ""
            def on_open(self):
                logger.debug("[VoiceToText] 连接已建立")
            def on_event(self, result: RecognitionResult):
                sentence = result.get_sentence()
                if sentence and sentence.get("text"):
                    self.text = sentence["text"]
            def on_close(self):
                pass
            def on_error(self, msg):
                logger.error(f"[VoiceToText] 错误: {msg}")

        callback = _Callback()
        recognition = Recognition(
            model="paraformer-realtime-v2",
            format="wav",
            sample_rate=16000,
            callback=callback,
        )
        # 将音频数据编码为 base64 后调用
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        recognition.call(audio_b64)
        text = callback.text.strip()

        if not text:
            raise HTTPException(status_code=422, detail="未识别到语音内容")

        logger.info(f"[VoiceToText] 识别成功: {text[:60]}...")
        return {"text": text}
    except HTTPException:
        raise
    except ImportError:
        raise HTTPException(status_code=500, detail="dashscope 未安装")
    except Exception as e:
        logger.error(f"[VoiceToText] 异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"语音识别失败: {str(e)}")
