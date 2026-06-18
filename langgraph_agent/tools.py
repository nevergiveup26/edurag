"""
LangChain 工具系统 — 替代手写 Tool/ToolRegistry

将原有的 10+ 个工具改写为 LangChain @tool 装饰器函数，
支持 LangGraph Agent 直接调用。

保留原 ToolRegistry 的核心逻辑（图片上下文、多策略路由）作为 ToolProvider。
"""

import json
import re
import time
from typing import List, Dict, Any, Optional

from langchain_core.tools import tool, StructuredTool
from langchain_core.runnables import RunnableConfig

from core.logger import get_logger

logger = get_logger("langgraph_tools")

# ========================== Tool 上下文提供器 ==========================


class ToolProvider:
    """
    工具上下文提供器

    持有所有工具需要的共享状态（检索器、LLM、图片上下文、知识库管理器）。
    被 LangChain tools 通过闭包或 partial 绑定使用。
    """

    def __init__(self):
        self._retriever = None
        self._llm_client = None
        self._kb_manager = None
        self._question_image: Optional[str] = None
        self._answer_image: Optional[str] = None

    def set_dependencies(self, retriever=None, llm_client=None, kb_manager=None):
        """注入外部依赖"""
        if retriever is not None:
            self._retriever = retriever
        if llm_client is not None:
            self._llm_client = llm_client
        if kb_manager is not None:
            self._kb_manager = kb_manager

    def set_image_context(self, question_image: str = None, answer_image: str = None):
        """预存图片 base64 上下文，OCR 工具直接读取"""
        if question_image:
            self._question_image = question_image
        if answer_image:
            self._answer_image = answer_image

    # ==================== 工具辅助方法 ====================

    def _knowledge_search_inner(self, query: str, top_k: int = 5) -> str:
        """知识库检索（直接使用检索器）"""
        if not self._retriever:
            result = json.dumps({"error": "检索器未初始化"}, ensure_ascii=False)
        else:
            try:
                results = self._retriever.search(query, top_k=top_k)
            except Exception as e:
                logger.warning(f"retriever 异常，降级关键词匹配: {e}")
                result = self._keyword_fallback(query, top_k)
                self._log_kb_query(query)
                return result

            if not results:
                result = self._keyword_fallback(query, top_k)
            else:
                sources = []
                for r in results[:top_k]:
                    score = getattr(r, 'score', 0)
                    if hasattr(r, 'chunk') and hasattr(r.chunk, 'content'):
                        text = r.chunk.content
                    elif hasattr(r, 'content'):
                        text = str(r.content)
                    else:
                        text = str(r)
                    source = ""
                    if hasattr(r, 'chunk') and hasattr(r.chunk, 'metadata'):
                        source = r.chunk.metadata.get('source', '')
                    sources.append({
                        "content": (str(text))[:300] if text else "",
                        "score": round(score, 4),
                        "source": source,
                    })
                result = json.dumps({"sources": sources}, ensure_ascii=False)

        self._log_kb_query(query)
        return result

    def _log_kb_query(self, query: str):
        """知识库响应计数（后台线程写入，不阻塞主流程）"""
        import threading
        def _write():
            try:
                from database.mysql_db import MySQLDB
                MySQLDB().log_query(user_id="", query=query, query_type="kb")
            except Exception as e:
                logger.debug(f"KB查询计数失败（不影响主流程）: {e}")
        threading.Thread(target=_write, daemon=True).start()

    def _keyword_fallback(self, query: str, top_k: int = 5) -> str:
        """关键词匹配（chunk_store 文件扫描兜底，retriever 已查过 Milvus 无需重复）"""
        try:
            keywords = [w.strip() for w in re.split(r'[\s,，。？！、：:；;]+', query) if len(w.strip()) >= 1]
            if not keywords:
                keywords = [query]
            if len(keywords) == 1 and len(keywords[0]) > 2:
                expanded = self._split_chinese_query(keywords[0])
                if expanded and len(expanded) > 1:
                    keywords = expanded

            # chunk_store 文件关键词匹配（retriever 已查过 Milvus，此处仅作最后兜底）
            from database.chunk_store import load_chunks
            store_data = load_chunks()
            if not store_data:
                return json.dumps({"sources": [], "note": "知识库为空"}, ensure_ascii=False)

            scored = []
            for item in store_data:
                content = item.get('content', '')
                if not content:
                    continue
                hits = sum(1 for kw in keywords if kw in content)
                if hits > 0:
                    scored.append((hits, content, item.get('metadata', {}).get('source', '')))

            if not scored and any('\u4e00' <= kw <= '\u9fff' for kw in keywords):
                char_keywords = [c for c in query if '\u4e00' <= c <= '\u9fff' and c not in '的是了在有个我你他她它吗呢吧啊之与和或']
                if char_keywords:
                    for item in store_data:
                        content = item.get('content', '')
                        if not content:
                            continue
                        hits = sum(1 for c in char_keywords if c in content)
                        if hits > 0:
                            scored.append((hits, content, item.get('metadata', {}).get('source', '')))

            scored.sort(key=lambda x: x[0], reverse=True)
            sources = []
            for hits, content, src in scored[:top_k]:
                sources.append({
                    "content": content[:300],
                    "score": round(hits / max(len(keywords), 1), 4),
                    "source": src,
                })
            return json.dumps({"sources": sources, "note": "使用关键词匹配"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"sources": [], "error": str(e)}, ensure_ascii=False)

    @staticmethod
    def _split_chinese_query(text: str) -> list:
        try:
            import jieba
            words = [w for w in jieba.cut(text) if len(w.strip()) >= 1]
            if len(words) > 1:
                return words
        except ImportError:
            pass
        result = []
        for size in [3, 2]:
            for i in range(len(text) - size + 1):
                result.append(text[i:i + size])
        return result or [text]


# ========================== 全局 ToolProvider 实例 ==========================

_provider = ToolProvider()


def get_tool_provider() -> ToolProvider:
    """获取全局工具提供器"""
    return _provider


# ========================== LangChain @tool 定义 ==========================


@tool(response_format="content")
def knowledge_search(query: str, top_k: int = 5) -> str:
    """
    RAG搜索工具，在本地知识库中检索信息。
    覆盖范围：教育政策、教学方法、学科知识、机构背景、讲师信息、FAQ、培训资料等。

    Args:
        query: 搜索查询词，使用原文关键词（不要改写为问句）
        top_k: 返回结果数量，默认5
    """
    return _provider._knowledge_search_inner(query=query, top_k=top_k)


@tool(response_format="content")
def final_answer(answer: str, references: list = None) -> str:
    """
    当已收集到足够信息时，给出最终答案。需要综合所有检索到的信息，给出准确、完整的回答。

    Args:
        answer: 最终答案
        references: 引用的来源摘要列表（可选）
    """
    return json.dumps({
        "status": "final",
        "answer": answer,
        "references": references or [],
    }, ensure_ascii=False)


@tool(response_format="content")
def ocr_extract(content_type: str = "question") -> str:
    """
    从已上传的图片中提取文字内容。题目图片和作答图片已预先上传，只需指定要提取哪一张。
    如果图片尚未上传或OCR多次失败，请告知用户提供文字。

    Args:
        content_type: 指定提取哪张图：question(题目图片) 或 answer(作答图片)
    """
    label = "题目" if content_type == "question" else "学生作答"

    # 从预存储的图片上下文获取
    if content_type == "question" and _provider._question_image:
        image_base64 = _provider._question_image
        logger.info(f"OCR: 使用预存储的题目图片 (base64长度: {len(image_base64)})")
    elif content_type == "answer" and _provider._answer_image:
        image_base64 = _provider._answer_image
        logger.info(f"OCR: 使用预存储的作答图片 (base64长度: {len(image_base64)})")
    else:
        image_base64 = None

    if not image_base64 or len(image_base64) < 100:
        return json.dumps({
            "extracted_text": "",
            "content_type": content_type,
            "error": "未找到有效的图片数据，请上传图片或直接输入文字内容。",
        }, ensure_ascii=False)

    # 1) 优先使用阿里云 DashScope OCR
    try:
        from llm.ocr_client import get_ocr_client
        ocr_client = get_ocr_client()
        dashscope_result = ocr_client.extract_text(image_base64, label)
        if dashscope_result.get("extracted_text") and not dashscope_result.get("error"):
            logger.info(f"[ocr_extract] DashScope OCR {label}成功: {len(dashscope_result['extracted_text'])}字")
            dashscope_result["content_type"] = content_type
            return json.dumps(dashscope_result, ensure_ascii=False)
        else:
            logger.info(f"[ocr_extract] DashScope OCR不可用，fallback: {dashscope_result.get('error', '')}")
    except Exception as e:
        logger.warning(f"[ocr_extract] DashScope OCR异常，fallback: {e}")

    # 2) Fallback: 本地 LLM vision
    if not _provider._llm_client:
        return json.dumps({
            "extracted_text": "",
            "content_type": content_type,
            "warning": "LLM未初始化，OCR不可用。请直接输入文字内容。",
        }, ensure_ascii=False)

    try:
        prompt = f"""请从这张{label}图片中逐字逐行提取所有可见的文字内容。

⚠️ 重要规则：
1. 只提取图片中实际存在的文字，不要猜测、不要编造、不要补充
2. 保持原文的格式和排版（换行、段落等）
3. 如果图片模糊、有遮挡或无法辨认某些文字，在对应位置标注 [无法辨认]
4. 如果图片中没有任何文字，返回空字符串
5. 如果是手写文字，尽力辨认但标注 confidence 为"低"
6. 不要添加任何解释、评价或额外内容

请以 JSON 格式返回：
{{"extracted_text": "提取的文字内容（必须逐字还原）", "confidence": "高/中/低"}}"""

        resp = _provider._llm_client.generate_with_image(
            prompt=prompt,
            image_base64=image_base64,
        )

        json_match = re.search(r'\{[\s\S]*\}', resp)
        if json_match:
            data = json.loads(json_match.group())
            data["content_type"] = content_type
            return json.dumps(data, ensure_ascii=False)

        return json.dumps({
            "extracted_text": resp[:500] if resp else "",
            "content_type": content_type,
            "confidence": "低",
            "note": "OCR结果可能不完整，建议人工校对",
        }, ensure_ascii=False)

    except Exception as e:
        logger.error(f"OCR提取失败: {e}", exc_info=True)
        return json.dumps({
            "extracted_text": "",
            "content_type": content_type,
            "error": f"OCR提取失败: {str(e)}",
            "suggestion": "请直接输入文字内容",
        }, ensure_ascii=False)


@tool(response_format="content")
def knowledge_reference(subject: str, query: str, grade_level: str = "初中") -> str:
    """
    检索批改参考材料。
    优先联网搜索获取最新、最广泛的题目资料；
    联网失败或结果不足时才回退到本地知识库。
    用于为批改提供辅助参照系（非权威标准答案）。

    Args:
        subject: 学科：语文/数学/英语
        query: 检索关键词，如题目核心内容或知识点
        grade_level: 年级：小学/初中/高中
    """
    web_has_results = False

    # 1) 优先联网搜索（覆盖面广，不受本地知识库限制）
    logger.info(f"[knowledge_reference] 优先联网搜索: {query[:80]}")
    try:
        from langgraph_agent.tools import tavily_web_search
        web_result = tavily_web_search.invoke({
            "query": f"{subject} {grade_level} {query} 题目 答案 解析",
            "search_depth": "basic",
            "max_results": 5,
            "include_domains": "",
        })
        web_data = json.loads(web_result) if isinstance(web_result, str) else web_result
        web_results = web_data.get("results", []) if isinstance(web_data, dict) else []
        web_answer = web_data.get("answer", "") if isinstance(web_data, dict) else ""

        if web_results or web_answer:
            web_has_results = True
            logger.info(f"[knowledge_reference] 联网搜索成功，获得 {len(web_results)} 条结果")
    except Exception as e:
        logger.warning(f"[knowledge_reference] 联网搜索失败: {e}")
        web_results = []
        web_answer = ""

    # 2) 组装结果（仅使用联网搜索结果，不依赖本地知识库）
    all_sources = list(web_results) if web_results else []

    if all_sources or web_answer:
        return json.dumps({
            "sources": all_sources,
            "answer": web_answer,
            "source_type": "web",
            "note": "以下为网络参考资料，仅供参考——批改时请优先使用你的专业知识判断，不要盲信参考资料。如果参考资料与题目不相关，请忽略。",
        }, ensure_ascii=False)

    # 3) 联网无结果：告知上游，让LLM依靠预训练知识批改
    return json.dumps({
        "sources": [],
        "answer": "",
        "source_type": "none",
        "note": "未找到匹配的网络参考资料。请完全依靠你的学科知识和教学经验来批改——分析题目要求、评估学生作答质量、给出专业评分和建议。",
    }, ensure_ascii=False)


@tool(response_format="content")
def reflect(rubric_summary: str, reference_summary: str, question_type: str) -> str:
    """
    汇总所有已收集的信息（评分标准 + 参考资料），评估是否足以完成批改。
    如果信息不足（缺少评分标准/参考资料），指出需要补充的内容。

    Args:
        rubric_summary: 已获取的评分标准摘要
        reference_summary: 已获取的参考资料摘要
        question_type: 客观题/主观题
    """
    missing = []
    if not rubric_summary or rubric_summary.strip() in ("", "null"):
        missing.append("评分标准")
    if not reference_summary or reference_summary.strip() in ("", "null"):
        missing.append("参考资料")
    if missing:
        return json.dumps({
            "sufficient": False,
            "gaps": missing,
            "suggestion": f"需要补充: {', '.join(missing)}"
        }, ensure_ascii=False)
    return json.dumps({"sufficient": True, "gaps": []}, ensure_ascii=False)


# ==================== 评分标准库 ====================

RUBRIC_DB = {
    ("语文", "客观题", "小学"): {
        "dimensions": {"字词正确": 40, "语句通顺": 30, "理解准确": 30},
        "description": "小学语文客观题评分标准：重点考察基础字词和简单理解",
    },
    ("语文", "客观题", "初中"): {
        "dimensions": {"字词正确": 35, "语法规范": 25, "理解准确": 40},
        "description": "初中语文客观题评分标准：增加语法和深度理解的考察",
    },
    ("语文", "客观题", "高中"): {
        "dimensions": {"字词正确": 25, "语法规范": 25, "逻辑推理": 25, "综合分析": 25},
        "description": "高中语文客观题评分标准：强调逻辑推理和综合分析能力",
    },
    ("语文", "主观题", "小学"): {
        "dimensions": {"内容完整": 30, "语句通顺": 30, "表达清晰": 20, "书写规范": 20},
        "description": "小学语文主观题（作文/阅读）评分标准：侧重基础表达能力",
    },
    ("语文", "主观题", "初中"): {
        "dimensions": {"立意": 25, "结构": 25, "语言": 25, "素材": 25},
        "description": "初中语文作文评分标准：四维平衡，强调立意和语言表达",
    },
    ("语文", "主观题", "高中"): {
        "dimensions": {"立意深度": 30, "结构严谨": 20, "语言文采": 25, "素材运用": 15, "思想高度": 10},
        "description": "高中语文作文评分标准：强调立意深度和思想高度",
    },
    ("数学", "客观题", "小学"): {
        "dimensions": {"计算正确": 60, "理解题意": 40},
        "description": "小学数学客观题：重点考察基础计算和题意理解",
    },
    ("数学", "客观题", "初中"): {
        "dimensions": {"计算正确": 50, "公式运用": 30, "逻辑推理": 20},
        "description": "初中数学客观题：增加公式运用和逻辑推理",
    },
    ("数学", "客观题", "高中"): {
        "dimensions": {"概念理解": 25, "公式推导": 25, "计算准确": 25, "方法选择": 25},
        "description": "高中数学客观题：四维平衡，强调概念与方法",
    },
    ("数学", "主观题", "小学"): {
        "dimensions": {"理解题意": 20, "列式正确": 30, "计算正确": 30, "书写规范": 20},
        "description": "小学数学解答题：按步骤给分",
    },
    ("数学", "主观题", "初中"): {
        "dimensions": {"审题分析": 15, "建立模型": 25, "推导过程": 30, "计算结果": 20, "检验验证": 10},
        "description": "初中数学大题：五步评分，强调建模和推导",
    },
    ("数学", "主观题", "高中"): {
        "dimensions": {"概念应用": 20, "方法选择": 20, "推导严谨": 30, "计算准确": 15, "结果讨论": 15},
        "description": "高中数学大题：强调方法选择和推导严谨性",
    },
    ("英语", "客观题", "小学"): {
        "dimensions": {"拼写正确": 40, "语法基础": 30, "选择合理": 30},
        "description": "小学英语客观题：基础拼写和语法",
    },
    ("英语", "客观题", "初中"): {
        "dimensions": {"词汇运用": 30, "语法准确": 35, "语境理解": 35},
        "description": "初中英语客观题：词汇、语法、语境三维考察",
    },
    ("英语", "客观题", "高中"): {
        "dimensions": {"词汇深度": 30, "语法精度": 30, "逻辑推理": 20, "文化理解": 20},
        "description": "高中英语客观题：强调词汇深度和文化理解",
    },
    ("英语", "主观题", "小学"): {
        "dimensions": {"内容完整": 30, "单词拼写": 25, "基础语法": 25, "书写规范": 20},
        "description": "小学英语写作：基础表达能力为主",
    },
    ("英语", "主观题", "初中"): {
        "dimensions": {"语法准确性": 30, "词汇多样性": 25, "句式复杂度": 20, "内容切题度": 25},
        "description": "初中英语作文：四维均衡评分",
    },
    ("英语", "主观题", "高中"): {
        "dimensions": {"语法准确性": 25, "词汇丰富度": 20, "句式多样性": 20, "逻辑连贯性": 20, "思想深度": 15},
        "description": "高中英语作文：强调逻辑和思想深度",
    },
}


@tool(response_format="content")
def grading_rubric(subject: str, question_type: str, grade_level: str = "初中") -> str:
    """
    获取指定学科、题型、年级的详细评分标准和各维度权重。
    必须在批改前调用，确保评分符合对应年级的教学要求。

    Args:
        subject: 学科：语文/数学/英语
        question_type: 客观题/主观题
        grade_level: 年级：小学/初中/高中
    """
    key = (subject, question_type, grade_level)
    rubric = RUBRIC_DB.get(key)

    if not rubric:
        for level in ["初中", "小学", "高中"]:
            fallback_key = (subject, question_type, level)
            rubric = RUBRIC_DB.get(fallback_key)
            if rubric:
                break

    if not rubric:
        rubric = {
            "dimensions": {"内容正确": 50, "表达清晰": 30, "格式规范": 20},
            "description": f"通用{question_type}评分标准",
        }

    error_types = {
        "语文": ["错别字", "用词不当", "语句不通", "偏离主题", "逻辑混乱"],
        "数学": ["公式用错", "计算失误", "概念错误", "步骤缺失", "单位错误"],
        "英语": ["拼写错误", "语法错误", "时态混乱", "搭配不当", "中式英语"],
    }

    result = {
        "subject": subject,
        "question_type": question_type,
        "grade_level": grade_level,
        "dimensions": rubric["dimensions"],
        "description": rubric["description"],
        "common_errors": error_types.get(subject, ["计算错误", "概念不清"]),
        "total_weight": sum(rubric["dimensions"].values()),
    }
    return json.dumps(result, ensure_ascii=False)


@tool(response_format="content")
def grade_execute(question: str, user_answer: str, subject: str,
                  question_type: str, grade_level: str = "初中",
                  references: str = "", rubric: str = "",
                  correct_answer: str = "") -> str:
    """
    执行最终批改：综合题目、学生作答进行智能评分。
    依靠LLM的学科知识和教学经验进行判断，参考资料仅作辅助。

    Args:
        question: 题目内容（文字形式）
        user_answer: 学生作答（文字形式）
        subject: 学科：语文/数学/英语
        question_type: 客观题/主观题
        grade_level: 年级：小学/初中/高中
        references: 从knowledge_reference获取的辅助参考资料（仅供参考，非标准答案）
        rubric: 从grading_rubric获取的评分标准（JSON字符串）
        correct_answer: 用户明确提供的标准答案（如"标准答案:xxx"），与参考资料不同
    """
    try:
        from agent.grading import UnifiedGrader

        logger.info(f"[grade_execute 监控] 入参: subject={subject}, question_type={question_type}, grade_level={grade_level}")
        logger.info(f"[grade_execute 监控] question({len(question)}字): {question[:500]}")
        logger.info(f"[grade_execute 监控] user_answer({len(user_answer)}字): {user_answer[:500]}")
        logger.info(f"[grade_execute 监控] correct_answer({len(correct_answer)}字): {correct_answer[:200] if correct_answer else '(空)'}")
        logger.info(f"[grade_execute 监控] rubric({len(rubric)}字): {rubric[:300]}")
        logger.info(f"[grade_execute 监控] references({len(references)}字): {references[:300]}")

        _QT_MAP = {
            "客观题": "auto",
            "主观题": "subjective",
            "选择题": "choice",
            "填空题": "fill_blank",
            "判断题": "true_false",
            "计算题": "calculation",
            "auto": "auto",
            "choice": "choice",
            "fill_blank": "fill_blank",
            "true_false": "true_false",
            "calculation": "calculation",
            "subjective": "subjective",
        }
        normalized_qt = _QT_MAP.get(question_type, question_type)

        rubric_data = {}
        try:
            rubric_data = json.loads(rubric) if rubric else {}
        except Exception as e:
            logger.debug(f"评分标准 JSON 解析失败: {e}")

        # 提取辅助参考资料（与标准答案区分开）
        ref_context = ""
        ref_note = ""
        try:
            ref_data = json.loads(references) if references else {}
            ref_note = ref_data.get("note", "")
            ref_sources = ref_data.get("sources", []) or []
            ref_answer = ref_data.get("answer", "") or ""
            source_type = ref_data.get("source_type", "none")

            if source_type == "none":
                ref_context = ""
            else:
                # 参考资料仅作背景知识，不作为标准答案
                parts = []
                if ref_note:
                    parts.append(f"参考资料说明：{ref_note}")
                if ref_answer:
                    parts.append(f"网络检索摘要：{ref_answer[:500]}")
                if ref_sources:
                    source_texts = []
                    for s in ref_sources[:3]:
                        content = s.get("content", "")[:300]
                        if content:
                            source_texts.append(content)
                    if source_texts:
                        parts.append("相关背景资料：\n" + "\n---\n".join(source_texts))
                ref_context = "\n".join(parts)
        except Exception as e:
            logger.debug(f"参考资料 JSON 解析失败: {e}")
            ref_context = ""
            ref_note = ""

        grader = UnifiedGrader()

        # 只有用户明确提供的标准答案才作为 correct_answer 传给 grader
        actual_correct_answer = correct_answer if correct_answer else ""

        # 将辅助参考资料注入题目上下文（标注仅供参考，LLM会自行判断是否采用）
        enhanced_question = question
        if ref_context:
            enhanced_question = f"{question}\n\n[系统检索到的辅助资料——仅供参考，请优先用你的专业知识判断，如不相关请忽略]\n{ref_context[:1500]}"

        if normalized_qt in ("auto", "choice", "fill_blank", "true_false", "calculation"):
            result = grader.auto_detect_and_grade(
                question=enhanced_question,
                user_answer=user_answer,
                correct_answer=actual_correct_answer[:500] if actual_correct_answer else "",
                subject=subject,
                question_type=normalized_qt,
                grade_level=grade_level,
            )
        else:
            result = grader.auto_detect_and_grade(
                question=enhanced_question,
                user_answer=user_answer,
                correct_answer=actual_correct_answer[:2000] if actual_correct_answer else "",
                subject=subject,
                question_type="subjective",
                grade_level=grade_level,
            )
            dimensions = rubric_data.get("dimensions", {})
            if dimensions and result.details:
                if not isinstance(result.details, dict):
                    result.details = {}
                result.details["rubric_dimensions"] = dimensions
                result.details["rubric_description"] = rubric_data.get("description", "")

        result_dict = result.to_dict()
        result_dict["rubric_applied"] = rubric_data.get("description", "")

        # 将参考资料作为辅助上下文注入结果，供 _final_node 使用
        if ref_context:
            result_dict["reference_context"] = ref_context[:2000]

        return json.dumps(result_dict, ensure_ascii=False)

    except Exception as e:
        logger.error(f"批改执行失败: {e}", exc_info=True)
        return json.dumps({
            "score": 0,
            "max_score": 100,
            "error": f"批改引擎出错: {str(e)}",
            "suggestion": "请检查题目和作答格式后重试",
        }, ensure_ascii=False)


@tool(response_format="content")
def analogy_question(question: str, user_answer: str, subject: str,
                     question_type: str, grade_level: str = "初中",
                     grading_result: str = "") -> str:
    """
    举一反三：根据一道错题，生成3道知识点相同但表述不同的变式题，
    帮助学生巩固薄弱环节。每道变式题包含题目、提示和参考解法。

    Args:
        question: 原始错题内容
        user_answer: 学生的错误作答
        subject: 学科：语文/数学/英语
        question_type: 客观题/主观题
        grade_level: 年级：小学/初中/高中
        grading_result: 批改结果摘要（得分、错误类型等）
    """
    try:
        if not _provider._llm_client:
            return json.dumps({"variants": [], "knowledge_point": "", "error": "LLM未初始化"}, ensure_ascii=False)

        # Step 1: LLM 分析知识点和错误原因
        analysis_prompt = f"""分析以下错题，提取核心知识点和错误原因：

学科: {subject} | 题型: {question_type} | 年级: {grade_level}
题目: {question[:300]}
学生作答: {user_answer[:200]}
批改结果: {grading_result[:200]}

返回JSON格式：
{{"knowledge_point": "知识点名称", "error_reason": "错误原因", "keywords": ["关键词1", "关键词2"]}}"""

        analysis_resp = _provider._llm_client.generate(analysis_prompt, max_tokens=300)
        knowledge_point = question[:60]
        keywords = [question[:20]]
        try:
            json_match = re.search(r'\{[\s\S]*\}', analysis_resp)
            if json_match:
                analysis = json.loads(json_match.group())
                knowledge_point = analysis.get("knowledge_point", question[:60])
                keywords = analysis.get("keywords", [question[:20]])
        except Exception as e:
            logger.debug(f"题目分析 JSON 解析失败: {e}")

        # Step 2: LLM 生成变式题（直接使用预训练知识，不再独立联网搜索）
        gen_prompt = f"""根据以下信息，生成3道举一反三的变式题：

学科: {subject} | 题型: {question_type} | 年级: {grade_level}
核心知识点: {knowledge_point}
错误原因: 学生在这一知识点上出错

要求：
1. 每道题考察同一知识点，换个角度/数字/情境
2. 难度和原题相当，适合{grade_level}学生
3. 每道题附带：题目、解题提示、参考答案
4. 客观题选项不要和原题重复

返回严格JSON格式（不要markdown代码块）：
{{"variants": [
  {{"question": "变式题1", "hint": "解题提示", "reference_answer": "参考答案"}},
  {{"question": "变式题2", "hint": "解题提示", "reference_answer": "参考答案"}},
  {{"question": "变式题3", "hint": "解题提示", "reference_answer": "参考答案"}}
], "knowledge_point": "知识点名称"}}"""

        gen_resp = _provider._llm_client.generate(gen_prompt, max_tokens=1500)
        result = {"variants": [], "knowledge_point": knowledge_point}

        try:
            json_match = re.search(r'\{[\s\S]*\}', gen_resp)
            if json_match:
                result = json.loads(json_match.group())
        except Exception:
            result["raw"] = gen_resp[:500]

        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        logger.error(f"举一反三生成失败: {e}")
        return json.dumps({"variants": [], "error": str(e)}, ensure_ascii=False)


@tool(response_format="content")
def tavily_web_search(query: str, search_depth: str = "basic",
                      max_results: int = 5, include_domains: str = "") -> str:
    """
    联网搜索，rag搜索无结果再使用本工具。

    Args:
        query: 搜索查询词，使用自然语言描述要搜索的内容
        search_depth: 搜索深度：basic（快速结果，约1.5秒）或 advanced（深度搜索，约4秒）
        max_results: 返回结果数量，默认5，最大10
        include_domains: 限定搜索域名（逗号分隔），如'edu.cn,k12.com'。留空则不限制。
    """
    import os

    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        try:
            from core.config_manager import ConfigManager
            config = ConfigManager()
            api_key = config.get("tavily", "api_key", "")
        except Exception as e:
            logger.debug(f"Tavily API key 获取失败: {e}")

    if not api_key:
        return json.dumps({
            "error": "Tavily API Key 未配置",
            "results": [],
            "answer": "",
        }, ensure_ascii=False)

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)

        include_domains_list = None
        if include_domains:
            include_domains_list = [d.strip() for d in include_domains.split(",") if d.strip()]

        depth = search_depth if search_depth in ("basic", "advanced") else "basic"
        count = max(1, min(10, int(max_results)))

        kwargs = {
            "query": query,
            "search_depth": depth,
            "max_results": count,
            "include_answer": True,
        }
        if include_domains_list:
            kwargs["include_domains"] = include_domains_list

        response = client.search(**kwargs)

        results = []
        for item in response.get("results", []) or []:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": (item.get("content", "") or "")[:500],
                "score": round(item.get("score", 0), 4),
            })

        return json.dumps({
            "query": response.get("query", query),
            "answer": (response.get("answer", "") or "")[:600],
            "results": results,
            "total_results": len(results),
            "search_depth": depth,
            "response_time": round(response.get("response_time", 0), 2),
        }, ensure_ascii=False)

    except ImportError:
        return json.dumps({"error": "tavily-python 库未安装", "results": []}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Tavily 搜索失败: {e}")
        return json.dumps({"error": f"搜索失败: {str(e)}", "results": []}, ensure_ascii=False)


@tool(response_format="content")
def graph_search(keywords: list, max_hops: int = 1) -> str:
    """
    知识图谱关联搜索。基于教育知识图谱，从查询中的概念实体出发，
    通过1-2跳关系扩展关联知识。适合探索概念之间的关系、前置知识、应用场景等。

    Args:
        keywords: 从查询中提取的关键概念/术语列表
        max_hops: 最大关系跳数（1-2），默认1
    """
    try:
        from data_processor.graph_builder import KnowledgeGraphManager

        mgr = KnowledgeGraphManager()
        graph = mgr.get_graph()

        if graph is None or graph.entity_count == 0:
            # 如果图谱不存在，触发后台构建并告知 Agent 当前不可用
            mgr.rebuild_async()
            return json.dumps({
                "expanded_keywords": keywords,
                "related_entities": [],
                "note": "知识图谱正在后台构建中，当前查询使用原始关键词",
            }, ensure_ascii=False)

        expanded = graph.expand_query_context(
            list(keywords), max_hops=max_hops, max_expansions=8
        )
        neighbors = []
        matched_entities = []
        for kw in keywords:
            # 精确匹配
            direct = graph.get_neighbors(kw, max_hops=max_hops)
            if direct:
                matched_entities.append(kw)
                for ent, rel, weight, hop in direct:
                    neighbors.append({
                        "entity": ent.display_name or ent.name,
                        "relation": rel,
                        "weight": weight,
                        "entity_type": ent.entity_type,
                        "subject": ent.subject,
                        "grade": ent.grade,
                    })
            else:
                # 模糊匹配（CK12 路径式实体名）
                fuzzy = graph.search_entity(kw, max_results=2)
                for m in fuzzy:
                    matched_entities.append(m.display_name or m.name)
                    for ent, rel, weight, hop in graph.get_neighbors(m.name, max_hops=max_hops):
                        neighbors.append({
                            "entity": ent.display_name or ent.name,
                            "relation": rel,
                            "weight": weight,
                            "entity_type": ent.entity_type,
                            "subject": ent.subject,
                            "grade": ent.grade,
                        })

        return json.dumps({
            "matched_entities": matched_entities,
            "expanded_keywords": expanded,
            "related_entities": neighbors[:10],
            "graph_stats": graph.get_stats(),
        }, ensure_ascii=False)

    except Exception as e:
        logger.warning(f"图谱搜索失败: {e}")
        return json.dumps({"expanded_keywords": keywords, "error": str(e)}, ensure_ascii=False)


# ========================== 工具集合 ==========================

# 全部工具列表
ALL_TOOLS = [
    knowledge_search,
    final_answer,
    ocr_extract,
    knowledge_reference,
    grading_rubric,
    reflect,
    grade_execute,
    analogy_question,
    tavily_web_search,
    graph_search,
]

# 聊天Agent工具（不含批改专用工具）
CHAT_TOOLS = [
    knowledge_search,
    final_answer,
    tavily_web_search,
    graph_search,
    analogy_question,
]

# 批改Agent工具
GRADE_TOOLS = [
    ocr_extract,
    grading_rubric,
    knowledge_reference,
    reflect,
    grade_execute,
    final_answer,
]


def create_langchain_tools(retriever=None, llm_client=None, kb_manager=None,
                           question_image: str = None, answer_image: str = None):
    """
    创建 LangChain 工具集，注入依赖。

    Args:
        retriever: HybridRetriever 实例
        llm_client: LLMClient 实例
        kb_manager: KnowledgeBase 实例
        question_image: 题目图片 base64（可选）
        answer_image: 作答图片 base64（可选）

    Returns:
        (all_tools, chat_tools, grade_tools) 三元组
    """
    _provider.set_dependencies(retriever=retriever, llm_client=llm_client, kb_manager=kb_manager)
    _provider.set_image_context(question_image=question_image, answer_image=answer_image)
    return ALL_TOOLS, CHAT_TOOLS, GRADE_TOOLS


# ========================== 工具监控中间件 ==========================


class ToolMonitor:
    """工具监控中间件：追踪工具调用状态、耗时、错误

    用法：
        monitor = ToolMonitor()
        with monitor.track("ocr_extract"):
            result = ocr_extract(...)
        report = monitor.get_report()  # 获取诊断报告
    """

    def __init__(self):
        self.history: List[Dict] = []
        self._current = None

    def track_start(self, tool_name: str, args: Dict = None):
        """记录工具调用开始"""
        import traceback
        self._current = {
            "tool": tool_name,
            "args": args or {},
            "start_time": time.time(),
            "status": "running",
            "error": None,
            "caller_frame": traceback.extract_stack()[-3],
        }
        logger.info(f"[ToolMonitor] 开始调用工具: {tool_name}, args={args}")
        return self._current

    def track_end(self, result: str = None):
        """记录工具调用结束"""
        if self._current is None:
            return
        duration = time.time() - self._current["start_time"]
        self._current["duration"] = round(duration, 3)
        self._current["status"] = "success"
        self._current["result_length"] = len(result) if result else 0
        self.history.append(self._current)
        logger.info(f"[ToolMonitor] 工具完成: {self._current['tool']}, "
                    f"耗时={self._current['duration']}s, 结果长度={self._current['result_length']}")
        self._current = None

    def track_error(self, error: Exception):
        """记录工具调用失败"""
        import traceback
        if self._current is None:
            return
        duration = time.time() - self._current["start_time"]
        self._current["duration"] = round(duration, 3)
        self._current["status"] = "error"
        self._current["error"] = f"{type(error).__name__}: {error}"
        self._current["traceback"] = traceback.format_exc()
        self.history.append(self._current)
        logger.error(f"[ToolMonitor] 工具失败: {self._current['tool']}, "
                     f"耗时={self._current['duration']}s, 错误={self._current['error']}")
        self._current = None

    def get_report(self) -> Dict:
        """获取工具监控诊断报告"""
        if not self.history:
            return {"status": "no_data", "message": "尚无工具调用记录"}

        total = len(self.history)
        success = sum(1 for h in self.history if h["status"] == "success")
        errors = sum(1 for h in self.history if h["status"] == "error")

        # 按工具统计
        by_tool = {}
        for h in self.history:
            t = h["tool"]
            if t not in by_tool:
                by_tool[t] = {"calls": 0, "errors": 0, "total_time": 0.0, "last_status": None}
            by_tool[t]["calls"] += 1
            if h["status"] == "error":
                by_tool[t]["errors"] += 1
            by_tool[t]["total_time"] += h.get("duration", 0)
            by_tool[t]["last_status"] = h["status"]

        for t, info in by_tool.items():
            info["avg_time"] = round(info["total_time"] / info["calls"], 3)

        return {
            "status": "ok",
            "summary": {
                "total_calls": total,
                "success": success,
                "errors": errors,
                "error_rate": round(errors / total * 100, 1) if total > 0 else 0,
            },
            "by_tool": by_tool,
            "recent_errors": [
                {"tool": h["tool"], "error": h["error"], "duration": h.get("duration")}
                for h in self.history[-5:] if h["status"] == "error"
            ],
        }

    def log_state(self, provider: ToolProvider) -> Dict:
        """记录 ToolProvider 的完整状态快照"""
        state = {
            "has_retriever": provider._retriever is not None,
            "has_llm_client": provider._llm_client is not None,
            "has_kb_manager": provider._kb_manager is not None,
            "question_image_len": len(provider._question_image) if provider._question_image else 0,
            "answer_image_len": len(provider._answer_image) if provider._answer_image else 0,
        }

        # 检查图片 base64 格式
        if provider._question_image:
            img = provider._question_image[:200]
            state["question_image_preview"] = img[:80] + "..." if len(img) > 80 else img
            state["question_image_has_data_uri"] = img.startswith("data:image/")
        if provider._answer_image:
            img = provider._answer_image[:200]
            state["answer_image_preview"] = img[:80] + "..." if len(img) > 80 else img
            state["answer_image_has_data_uri"] = img.startswith("data:image/")

        # LLM 客户端状态
        if provider._llm_client:
            state["llm_info"] = provider._llm_client.get_model_info()

        logger.info(f"[ToolMonitor] ToolProvider 状态: {json.dumps(state, ensure_ascii=False, default=str)}")
        return state


# 全局监控实例
tool_monitor = ToolMonitor()


def get_tool_monitor() -> ToolMonitor:
    """获取全局工具监控实例"""
    return tool_monitor
