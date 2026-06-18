"""
LangGraph Grading Agent

使用自定义 StateGraph 替代手写的 GradingAgent（原 agent/grading_agent.py）。

工作流节点：
  OCR → Rubric → Knowledge → Reflect → Grade → Final
  客观题快速通道: OCR → Grade → Final

特性：
- 自定义状态图，精确控制批改流程
- 客观题快速通道（跳过 knowledge + reflect）
- 流式事件输出（适配现有 SSE 格式）
"""

import json
import re
import time
from typing import List, Dict, Any, Optional, TypedDict, AsyncGenerator, Literal

from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langchain_core.runnables import RunnableConfig

from core.logger import get_logger
from langgraph_agent.model import create_chat_model
from langgraph_agent.tools import (
    create_langchain_tools, GRADE_TOOLS, ToolProvider, get_tool_provider, get_tool_monitor,
    ocr_extract,
)

logger = get_logger("langgraph_grade_agent")

# ======================== 状态定义 ========================


class GradeState(TypedDict):
    """批改状态"""

    # 输入
    messages: List[BaseMessage]
    user_message: str
    question_image: Optional[str]
    answer_image: Optional[str]

    # OCR 结果
    question_text: str
    answer_text: str

    # 批改参数（从 user_message 解析或 OCR 后 LLM 分析）
    subject: str
    question_type: str  # 客观题/主观题/选择题/填空题/判断题/计算题
    grade_level: str
    correct_answer: str  # 标准答案（如用户提供）

    # 中间结果
    rubric_data: str          # grading_rubric 返回的 JSON 字符串
    reference_data: str       # knowledge_reference 返回的 JSON 字符串
    reflect_result: str        # reflect 返回的 JSON 字符串
    grading_result: str        # grade_execute 返回的 JSON 字符串

    # 流程控制
    is_objective: bool
    has_images: bool
    step: int
    current_node: str
    error: Optional[str]

    # 输出
    final_answer: str
    tools_used: List[str]
    _pending_llm_prompt: str  # 保留用于兼容，已不再使用 LLM 格式化


# ======================== 系统提示词 ========================

# ======================== 节点函数 ========================


def _ocr_node(state: GradeState) -> dict:
    """OCR 节点：从图片中提取文字，并验证提取质量"""
    provider = get_tool_provider()
    monitor = get_tool_monitor()
    result = {"tools_used": [], "step": state.get("step", 0) + 1}
    question_text = state.get("question_text", "")
    answer_text = state.get("answer_text", "")
    tools_used = list(state.get("tools_used", []))
    ocr_warnings = []

    has_images = bool(state.get("question_image") or state.get("answer_image"))

    def _extract_and_validate(content_type, label):
        """提取OCR文字并验证质量"""
        nonlocal ocr_warnings
        raw_result = ocr_extract.invoke({"content_type": content_type})
        if not raw_result:
            logger.warning(f"[OCR监控] {label} ocr_extract返回空结果")
            return ""

        logger.info(f"[OCR监控] {label} ocr_extract原始返回(前1500字): {str(raw_result)[:1500]}")

        try:
            ocr_data = json.loads(raw_result)
            text = ocr_data.get("extracted_text", "")
            confidence = ocr_data.get("confidence", "未知")
            error = ocr_data.get("error", "")
            engine = ocr_data.get("engine", "未知")
        except Exception:
            text = str(raw_result)[:1000]
            confidence = "未知"
            engine = "解析失败"

        logger.info(f"[OCR监控] {label} 解析后: engine={engine}, confidence={confidence}, "
                    f"text长度={len(text)}, text内容:\n{text[:800]}")

        if error:
            logger.warning(f"[GradeAgent] OCR{label}返回错误: {error}")
            ocr_warnings.append(f"{label}图片OCR错误: {error}")

        if confidence == "低" or (confidence == "未知" and not text):
            logger.warning(f"[GradeAgent] OCR{label}置信度: {confidence}")
            if not error:
                ocr_warnings.append(f"{label}图片识别置信度低，可能存在错误")

        # 验证提取文字质量
        text_stripped = text.strip()
        if not text_stripped:
            logger.warning(f"[GradeAgent] OCR{label}未提取到任何文字")
            ocr_warnings.append(f"{label}图片未提取到文字内容")
        elif len(text_stripped) < 5:
            logger.warning(f"[GradeAgent] OCR{label}提取文字过短({len(text_stripped)}字): {text_stripped[:100]}")
            ocr_warnings.append(f"{label}图片提取文字过短，可能识别失败")

        return text

    if state.get("question_image") and not question_text:
        logger.info(f"[GradeAgent] OCR提取题目图片...")
        monitor.track_start("ocr_extract", {"content_type": "question"})
        try:
            question_text = _extract_and_validate("question", "题目")
            monitor.track_end(question_text)
        except Exception as e:
            monitor.track_error(e)
            monitor.log_state(provider)
            logger.error(f"[GradeAgent] OCR题目提取异常: {e}", exc_info=True)
            ocr_warnings.append(f"题目图片OCR异常: {e}")

        result["question_text"] = question_text
        tools_used.append("ocr_extract")

    if state.get("answer_image") and not answer_text:
        logger.info(f"[GradeAgent] OCR提取作答图片...")
        monitor.track_start("ocr_extract", {"content_type": "answer"})
        try:
            answer_text = _extract_and_validate("answer", "作答")
            monitor.track_end(answer_text)
        except Exception as e:
            monitor.track_error(e)
            monitor.log_state(provider)
            logger.error(f"[GradeAgent] OCR作答提取异常: {e}", exc_info=True)
            ocr_warnings.append(f"作答图片OCR异常: {e}")

        result["answer_text"] = answer_text
        tools_used.append("ocr_extract")

    result["tools_used"] = tools_used
    result["has_images"] = has_images
    if ocr_warnings:
        result["error"] = "; ".join(ocr_warnings)
        logger.warning(f"[GradeAgent] OCR质量警告: {result['error']}")
    return result


def _analyze_node(state: GradeState) -> dict:
    """分析节点：从用户消息和OCR结果中提取批改参数（纯 regex，无 LLM 调用）"""
    question_text = state.get("question_text", "")
    answer_text = state.get("answer_text", "")
    user_message = state.get("user_message", "")

    # 从 user_message 中解析 Key=Value 格式参数
    params = _parse_user_message(user_message)
    subject = params.get("subject", params.get("学科", "")) or "通用"
    question_type = params.get("question_type", params.get("题型", "")) or "主观题"
    grade_level = params.get("grade_level", params.get("年级", "")) or "初中"
    correct_answer = params.get("correct_answer", params.get("标准答案", params.get("参考答案", "")))

    # 判断是否客观题
    is_objective = question_type in ("客观题", "选择题", "填空题", "判断题", "计算题")

    logger.info(f"[GradeAgent] 分析结果: subject={subject}, type={question_type}, "
                f"grade={grade_level}, objective={is_objective}")

    return {
        "subject": subject,
        "question_type": question_type,
        "grade_level": grade_level,
        "correct_answer": correct_answer,
        "question_text": question_text or user_message[:3000],
        "answer_text": answer_text or user_message[:3000],
        "is_objective": is_objective,
        "step": state.get("step", 0) + 1,
    }


def _rubric_node(state: GradeState) -> dict:
    """评分标准节点"""
    logger.info("[GradeAgent] 获取评分标准...")
    from langgraph_agent.tools import grading_rubric as grading_rubric_tool

    try:
        rubric_json = grading_rubric_tool.invoke({
            "subject": state["subject"],
            "question_type": state["question_type"],
            "grade_level": state["grade_level"],
        })
        tools_used = list(state.get("tools_used", [])) + ["grading_rubric"]
        return {
            "rubric_data": rubric_json,
            "tools_used": tools_used,
            "step": state.get("step", 0) + 1,
            "current_node": "rubric",
        }
    except Exception as e:
        logger.error(f"获取评分标准失败: {e}")
        return {
            "rubric_data": json.dumps({"error": str(e)}),
            "tools_used": list(state.get("tools_used", [])) + ["grading_rubric"],
            "step": state.get("step", 0) + 1,
            "current_node": "rubric",
        }


def _knowledge_node(state: GradeState) -> dict:
    """知识检索节点"""
    logger.info("[GradeAgent] 检索参考资料...")
    from langgraph_agent.tools import knowledge_reference as knowledge_reference_tool

    question_text = state.get("question_text", "")
    try:
        ref_json = knowledge_reference_tool.invoke({
            "subject": state["subject"],
            "query": question_text[:200],
            "grade_level": state["grade_level"],
        })
        tools_used = list(state.get("tools_used", [])) + ["knowledge_reference"]
        return {
            "reference_data": ref_json,
            "tools_used": tools_used,
            "step": state.get("step", 0) + 1,
            "current_node": "knowledge",
        }
    except Exception as e:
        logger.error(f"检索参考资料失败: {e}")
        return {
            "reference_data": json.dumps({"error": str(e)}),
            "tools_used": list(state.get("tools_used", [])) + ["knowledge_reference"],
            "step": state.get("step", 0) + 1,
            "current_node": "knowledge",
        }


def _reflect_node(state: GradeState) -> dict:
    """反思节点：评估信息充分性"""
    logger.info("[GradeAgent] 反思信息充分性...")
    from langgraph_agent.tools import reflect as reflect_tool

    try:
        reflect_json = reflect_tool.invoke({
            "rubric_summary": state.get("rubric_data", "")[:500],
            "reference_summary": state.get("reference_data", "")[:500],
            "question_type": state["question_type"],
        })
        tools_used = list(state.get("tools_used", [])) + ["reflect"]
        return {
            "reflect_result": reflect_json,
            "tools_used": tools_used,
            "step": state.get("step", 0) + 1,
            "current_node": "reflect",
        }
    except Exception as e:
        logger.error(f"反思失败: {e}")
        return {
            "reflect_result": json.dumps({"sufficient": True, "gaps": []}),
            "tools_used": list(state.get("tools_used", [])) + ["reflect"],
            "step": state.get("step", 0) + 1,
            "current_node": "reflect",
        }


def _grade_node(state: GradeState) -> dict:
    """执行批改节点"""
    logger.info("[GradeAgent] 执行批改...")
    from langgraph_agent.tools import grade_execute as grade_execute_tool

    question_text = state.get("question_text", "")
    answer_text = state.get("answer_text", "")
    correct_answer = state.get("correct_answer", "")

    # 参考资料（RAG/web search结果）仅作辅助，不作为标准答案
    references = state.get("reference_data", "")

    try:
        grade_json = grade_execute_tool.invoke({
            "question": question_text[:1500],
            "user_answer": answer_text[:3000],
            "subject": state["subject"],
            "question_type": state["question_type"],
            "grade_level": state["grade_level"],
            "references": references[:2000] if references else "",
            "rubric": state.get("rubric_data", "")[:2000],
            "correct_answer": correct_answer,
        })
        tools_used = list(state.get("tools_used", [])) + ["grade_execute"]
        return {
            "grading_result": grade_json,
            "tools_used": tools_used,
            "step": state.get("step", 0) + 1,
            "current_node": "grade",
        }
    except Exception as e:
        logger.error(f"批改执行失败: {e}")
        return {
            "grading_result": json.dumps({"score": 0, "error": str(e)}),
            "tools_used": list(state.get("tools_used", [])) + ["grade_execute"],
            "step": state.get("step", 0) + 1,
            "current_node": "grade",
        }


def _final_node(state: GradeState) -> dict:
    """最终节点：整理结构化批改数据（Markdown 报告由 _build_analysis_report 用 Python 模板生成）"""
    logger.info("[GradeAgent] 整理最终批改数据...")
    grading_result = state.get("grading_result", "{}")

    try:
        grading_data = json.loads(grading_result) if isinstance(grading_result, str) else grading_result
    except Exception:
        grading_data = {"score": "?", "max_score": 100, "feedback": grading_result}

    score = grading_data.get("score", grading_data.get("total_score", "?"))
    max_score = grading_data.get("max_score", 100)
    steps = grading_data.get("steps", [])

    # 一致性修复：如果所有分步都是满分，总分也应该是满分
    if steps and isinstance(score, (int, float)):
        all_full = all(
            (s.get("score", 0) >= s.get("max", s.get("max_score", 1)))
            for s in steps
        )
        if all_full and float(score) < float(max_score):
            logger.info(f"[GradeAgent] 分步均满分但总分{score}，修正为{max_score}")
            score = max_score
            grading_data["score"] = max_score

    logger.info(f"[FinalNode] score={score}/{max_score}, steps={len(steps)}个")

    return {
        "_pending_llm_prompt": "",
        "final_answer": "",
        "grading_result": json.dumps(grading_data, ensure_ascii=False),
        "tools_used": list(state.get("tools_used", [])),
        "step": state.get("step", 0) + 1,
        "current_node": "final",
    }


def _build_analysis_report(score, max_score, feedback, steps, highlights, suggestions) -> str:
    """用 Python 模板从结构化批改数据拼接 Markdown 报告（替代 LLM 格式化）"""
    parts = [f"## 📊 得分概览\n\n**总分 {score}/{max_score}**\n"]

    if feedback:
        parts.append(f"\n{feedback}\n")

    if steps:
        parts.append("\n## 📋 逐项分析\n")
        for i, s in enumerate(steps):
            step_name = s.get("step", s.get("description", f"第{i+1}步"))
            step_score = s.get("score", s.get("student_score", 0))
            step_max = s.get("max", s.get("max_score", 1))
            status = s.get("status", "")
            fb = s.get("feedback", "")
            correct = s.get("correct_solution", "")

            if status == "correct":
                icon = "✅"
            elif status in ("wrong", "missing"):
                icon = "❌"
            else:
                icon = "⚠️"

            parts.append(f"- {icon} **{step_name}**: {step_score}/{step_max}")
            if fb:
                parts.append(f"  - {fb}")
            if correct:
                parts.append(f"  - 正确解法: {correct}")

    if highlights:
        parts.append("\n## 🔍 错误标注\n")
        for h in highlights:
            desc = h.get("description", h.get("step", ""))
            err_type = h.get("error_type", "")
            fb = h.get("feedback", h.get("explanation", h.get("reason", "")))
            correct = h.get("correct_solution", h.get("correction", h.get("improved", "")))
            original = h.get("original", "")

            tag = f" [{err_type}]" if err_type else ""
            parts.append(f"- **{desc}**{tag}")
            if original:
                parts.append(f"  - 原文: {original}")
            if correct:
                parts.append(f"  - 建议修改为: {correct}")
            if fb:
                parts.append(f"  - 说明: {fb}")

    if suggestions:
        parts.append("\n## 💡 改进建议\n")
        for s_item in suggestions:
            if isinstance(s_item, str):
                parts.append(f"- {s_item}")
            elif isinstance(s_item, dict):
                text = s_item.get("reason", s_item.get("point", str(s_item)))
                parts.append(f"- {text}")

    return "\n".join(parts)


# ======================== 条件路由 ========================


def _route_after_ocr(state: GradeState) -> Literal["analyze", "final"]:
    """OCR 后路由：检查是否有可用文字"""
    question_text = state.get("question_text", "")
    answer_text = state.get("answer_text", "")
    has_images = state.get("has_images", False)

    if has_images and not question_text and not answer_text:
        # 有图片但OCR全部失败
        state["error"] = "图片文字提取失败，请直接输入文字内容。"
        return "final"
    return "analyze"


def _route_after_analyze(state: GradeState) -> Literal["rubric", "grade"]:
    """分析后路由：客观题快速通道"""
    if state.get("is_objective", False) and state.get("correct_answer"):
        logger.info("[GradeAgent] 客观题快速通道：跳过 rubric，直接进入 grade")
        return "grade"
    return "rubric"


def _route_after_reflect(state: GradeState) -> Literal["grade", "knowledge"]:
    """反思后路由：检查信息充分性"""
    try:
        ref_result = json.loads(state.get("reflect_result", "{}"))
        if not ref_result.get("sufficient", True):
            gaps = ref_result.get("gaps", [])
            if "参考资料" in gaps:
                return "knowledge"
    except Exception as e:
        logger.debug(f"reflect 路由判断失败: {e}")
    return "grade"


# ======================== Agent 构建 ========================


def create_grade_agent(
    model: BaseChatModel = None,
    retriever=None,
    llm_client=None,
    kb_manager=None,
    question_image: str = None,
    answer_image: str = None,
) -> CompiledStateGraph:
    """
    创建 LangGraph 批改 Agent

    Args:
        model: LangChain ChatModel
        retriever: 混合检索器
        llm_client: LLMClient（用于OCR工具）
        kb_manager: 知识库管理器
        question_image: 题目图片 base64
        answer_image: 作答图片 base64

    Returns:
        CompiledStateGraph
    """
    if model is None:
        model = create_chat_model()

    # 初始化工具提供器
    create_langchain_tools(
        retriever=retriever,
        llm_client=llm_client,
        kb_manager=kb_manager,
        question_image=question_image,
        answer_image=answer_image,
    )

    # 构建状态图
    workflow = StateGraph(GradeState)

    # 添加节点（analyze 和 final 不再依赖 model，直接注册函数引用）
    workflow.add_node("ocr", _ocr_node)
    workflow.add_node("analyze", _analyze_node)
    workflow.add_node("rubric", _rubric_node)
    workflow.add_node("knowledge", _knowledge_node)
    workflow.add_node("reflect", _reflect_node)
    workflow.add_node("grade", _grade_node)
    workflow.add_node("final", _final_node)

    # 入口路由：无图片时跳过 OCR
    def _entry_router(state: GradeState) -> Literal["ocr", "analyze"]:
        if state.get("has_images"):
            return "ocr"
        return "analyze"

    workflow.set_conditional_entry_point(
        _entry_router,
        {"ocr": "ocr", "analyze": "analyze"},
    )

    # 添加边
    workflow.add_conditional_edges("ocr", _route_after_ocr, {
        "analyze": "analyze",
        "final": "final",
    })

    workflow.add_conditional_edges("analyze", _route_after_analyze, {
        "rubric": "rubric",
        "grade": "grade",
    })

    workflow.add_edge("rubric", "knowledge")

    # 客观题跳过 knowledge 和 reflect
    workflow.add_conditional_edges("knowledge", _skip_knowledge_for_objective, {
        "reflect": "reflect",
        "grade": "grade",
    })

    workflow.add_conditional_edges("reflect", _route_after_reflect, {
        "grade": "grade",
        "knowledge": "knowledge",
    })

    workflow.add_edge("grade", "final")
    workflow.add_edge("final", END)

    agent = workflow.compile()
    logger.info("LangGraph Grading Agent 创建完成")
    return agent


def _skip_knowledge_for_objective(state: GradeState) -> Literal["reflect", "grade"]:
    """客观题跳过 knowledge + reflect"""
    if state.get("is_objective", False):
        return "grade"
    return "reflect"


# ======================== 辅助函数 ========================


def _parse_user_message(message: str) -> Dict[str, str]:
    """解析用户消息中的 Key=Value 参数"""
    params = {}
    # 匹配 学科=xxx 格式（中英文分隔符）
    for match in re.finditer(r'(学科|题型|年级|标准答案|参考答案|题目|作答)\s*[=：:]\s*([^|\n]+)', message):
        key = match.group(1)
        value = match.group(2).strip()
        params[key] = value
    # 英文 key=value
    for match in re.finditer(r'(subject|question_type|grade_level|correct_answer)\s*[=：:]\s*([^|\n]+)', message, re.IGNORECASE):
        key = match.group(1).lower()
        value = match.group(2).strip()
        if key not in params:
            params[key] = value
    return params


# ======================== 流式适配器 ========================


async def stream_grade_response(
    agent: CompiledStateGraph,
    user_message: str,
    question_image: str = None,
    answer_image: str = None,
    question_text: str = "",
    answer_text: str = "",
    config: RunnableConfig = None,
) -> AsyncGenerator[str, None]:
    """
    流式输出批改 Agent 响应

    使用 astream 获取每个节点的输出，转换为 SSE 事件格式。
    final 节点不再调用 LLM，直接使用 Python 模板生成 Markdown 报告。

    事件类型：
      - status: 状态信息
      - progress: 进度更新（0.0 ~ 1.0）
      - token: 报告分块输出
      - grading_result: 最终批改结果 JSON
      - done: 完成
      - error: 错误

    Args:
        agent: 编译好的 LangGraph Grading Agent
        user_message: 用户消息
        question_image: 题目图片 base64
        answer_image: 作答图片 base64
        question_text: 题目文字
        answer_text: 作答文字
        config: RunnableConfig

    Yields:
        SSE 格式字符串
    """
    import json as _json

    PROGRESS_MAP = {
        "ocr": 0.1,
        "analyze": 0.15,
        "rubric": 0.25,
        "knowledge": 0.40,
        "reflect": 0.55,
        "grade": 0.85,
        "final": 0.95,
    }

    NODE_NAMES = {
        "ocr": "👁️ OCR文字提取",
        "analyze": "📋 分析批改参数",
        "rubric": "📐 获取评分标准",
        "knowledge": "🔍 检索参考资料",
        "reflect": "🤔 评估信息充分性",
        "grade": "✏️ 执行智能批改",
        "final": "📝 生成批改评语",
    }

    initial_state = GradeState(
        messages=[HumanMessage(content=user_message)],
        user_message=user_message,
        question_image=question_image,
        answer_image=answer_image,
        question_text=question_text,
        answer_text=answer_text,
        subject="",
        question_type="",
        grade_level="",
        correct_answer="",
        rubric_data="",
        reference_data="",
        reflect_result="",
        grading_result="",
        is_objective=False,
        has_images=bool(question_image or answer_image),
        step=0,
        current_node="",
        error=None,
        final_answer="",
        tools_used=[],
        _pending_llm_prompt="",
    )

    def emit(event_dict: dict) -> str:
        return f"data: {_json.dumps(event_dict, ensure_ascii=False)}\n\n"

    try:
        yield emit({"type": "status", "content": "🤖 批改Agent启动中...", "step": 0})

        pending_prompt = None
        grading_parsed = {}

        async for chunk in agent.astream(initial_state, config=config, stream_mode="updates"):
            for node_name, node_output in chunk.items():
                if node_name in NODE_NAMES:
                    display_name = NODE_NAMES[node_name]
                    progress = PROGRESS_MAP.get(node_name, 0.5)

                    yield emit({
                        "type": "status",
                        "content": display_name,
                        "step": node_output.get("step", 0),
                    })
                    yield emit({
                        "type": "progress",
                        "progress": progress,
                        "current": display_name,
                    })

                    if node_name == "grade" and node_output.get("grading_result"):
                        yield emit({
                            "type": "observation",
                            "action": "grade_execute",
                            "output": node_output["grading_result"][:500],
                        })

                    if node_name == "final":
                        grading_raw = node_output.get("grading_result", "{}")
                        if isinstance(grading_raw, str):
                            try:
                                grading_parsed = json.loads(grading_raw)
                            except Exception:
                                grading_parsed = {}
                        else:
                            grading_parsed = grading_raw

                        if grading_parsed:
                            yield emit({"type": "status", "content": "📝 正在整理评语...", "step": node_output.get("step", 0)})
                            full_text = _build_analysis_report(
                                grading_parsed.get("score", "?"),
                                grading_parsed.get("max_score", 100),
                                grading_parsed.get("feedback", ""),
                                grading_parsed.get("steps", []),
                                grading_parsed.get("highlights", []),
                                grading_parsed.get("suggestions", []),
                            )
                            for token_chunk in _chunk_text(full_text, chunk_size=5):
                                yield emit({"type": "token", "content": token_chunk})
                            yield emit({
                                "type": "grading_result",
                                "grading": grading_parsed,
                            })

        yield emit({"type": "done"})

    except Exception as e:
        logger.error(f"批改流式输出异常: {e}", exc_info=True)
        yield emit({"type": "error", "content": str(e)})


def _chunk_text(text: str, chunk_size: int = 5):
    """将文本切分为小块，模拟流式输出"""
    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]


def _extract_grading_from_text(text: str) -> dict:
    """从 LLM 输出中提取评分信息

    注意：此函数已不再被 stream_grade_response 调用（改用原始结构化数据），
    仅作为 fallback 保留。匹配优先级：总分 > 得分 > 评分。
    """
    result = {"score": 0, "max_score": 100}
    if not text:
        return result

    # 按优先级匹配分数模式
    score_patterns = [
        (r'总分[：:]?\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)', True),   # 总分: 75/100
        (r'总分[：:]?\s*(\d+(?:\.\d+)?)\s*(?:分)?', False),                 # 总分: 75
        (r'总得分[：:]?\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)', True), # 总得分: 75/100
        (r'总得分[：:]?\s*(\d+(?:\.\d+)?)\s*(?:分)?', False),              # 总得分: 75
        (r'(?:得了|得到|得到了)\s*(\d+(?:\.\d+)?)\s*(?:分)?', False),  # 得了/得到了 75 分
        (r'得分[：:]?\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)', True), # 得分: 75/100
        (r'得分[：:]?\s*(\d+(?:\.\d+)?)\s*(?:分)?', False),                # 得分: 75 分
        (r'评分[：:]?\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)', True), # 评分: 75/100
        (r'评分[：:]?\s*(\d+(?:\.\d+)?)\s*(?:分)?', False),                # 评分: 75 分
    ]
    for pattern, has_max in score_patterns:
        m = re.search(pattern, text)
        if m:
            try:
                result["score"] = float(m.group(1))
                if has_max:
                    result["max_score"] = float(m.group(2))
                return result
            except Exception as e:
                logger.debug(f"分数解析失败: {e}")

    return result
