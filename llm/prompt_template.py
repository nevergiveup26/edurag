"""
提示词模板
定义系统中使用的各种提示词模板，包含RAG专用提示（引用溯源、拒绝回答规则）
"""


class PromptTemplate:
    """提示词模板类"""

    # ========== RAG专用QA模板（含内联引用溯源 + 拒绝回答规则） ==========
    QA_TEMPLATE = """你是一个教育行业智能问答助手。请根据以下【参考资料】回答用户的问题。

{profile_section}【参考资料】
{context}

{history_section}
【用户问题】
{question}

【回答规则】
1. 仅基于参考资料回答，不要编造信息
2. 如果参考资料不足以回答问题，请如实回答"根据现有资料无法回答该问题"
3. 回答要准确、简洁、有条理，使用中文
4. 【重要】在回答中使用内联引用标注来源，格式如 [1]、[2][3]：
   - 每个关键陈述后紧跟对应的引用编号
   - 同一处引用多个来源时写在一起，如 [1][3]
   - 编号对应参考资料中的序号
   - 示例："素质教育强调全面发展 [1]。新课改提出了六大目标 [2][3]。"
5. 确保每个引用的编号确实存在于参考资料中，不要虚构编号
6. 如果问题与教育领域无关，请礼貌说明无法回答
7. 如果对话历史中有相关信息，可以结合使用
8. 不要重复用户的问题，直接给出答案
9. 如果提供了【学生画像】，请根据学生性格调整讲解风格、根据能力层级调整解释深度、针对薄弱知识点做重点讲解和关联

【回答】"""

    # ========== 带内联引用的QA模板（增强版，用于知识库场景） ==========
    QA_TEMPLATE_WITH_CITATIONS = """你是一个教育行业智能问答助手。请严格根据以下【参考资料】回答用户问题，并在回答中使用内联引用标注。

【参考资料】
{context}

【用户问题】
{question}

【内联引用规则 - 必须严格遵守】
1. 从参考资料中提取的信息，必须在句末标注引用编号，如 [1]
2. 同一个陈述引用多个来源时写在一起，如 [1][2]
3. 引用编号必须与参考资料中的序号完全一致，不要虚构不存在的编号
4. 不要在回答开头或结尾处单独列引用，引用必须内联在正文中
5. 如果参考资料无法回答问题，直接回答"根据现有资料无法回答该问题"

【正确示例】
"混合式学习结合了线上和线下教学的优势 [1]。研究表明这种方法能提高学生参与度 [2][3]。"

【回答】"""

    # ========== HyDE假设性文档生成模板 ==========
    HYDE_TEMPLATE = """请根据以下问题，生成一个假设性的回答文档。
这个文档将用于向量检索，请尽可能详细地包含相关知识点。

问题：{question}

假设性回答："""

    # ========== 查询分解模板 ==========
    DECOMPOSE_TEMPLATE = """请将以下复杂问题分解为多个子问题，以便分别检索相关信息。

原始问题：{question}

请以JSON数组格式返回子问题列表，例如：
["子问题1", "子问题2", "子问题3"]

子问题列表："""

    # ========== 子查询答案综合模板 ==========
    SUBQUERY_ANSWER_TEMPLATE = """请综合以下信息回答用户的问题。

原始问题：{question}
子问题：{sub_queries}

参考资料：
{context}

要求：
1. 综合所有参考资料进行回答
2. 确保回答覆盖所有子问题
3. 回答要有条理、逻辑清晰
4. 标注信息来自哪个子问题的检索结果

综合回答："""

    # ========== 答案质量评估模板（用于回溯策略） ==========
    QUALITY_EVAL_TEMPLATE = """请评估以下参考资料对回答问题的充分程度，给出0-1之间的评分。

问题：{question}

参考资料：
{context}

评分标准：
- 0.0-0.3: 资料严重不足，无法回答
- 0.3-0.6: 资料部分相关，但不完整
- 0.6-0.8: 资料较充分，基本可以回答
- 0.8-1.0: 资料非常充分，可以完整回答

仅返回一个0-1之间的数字评分："""

    # ========== 查询优化模板（用于回溯策略） ==========
    QUERY_REFINE_TEMPLATE = """基于以下原始问题和当前检索到的信息，生成一个新的查询以便获取更相关的信息。

原始问题：{question}

当前检索结果：
{context}

请生成一个更精确的查询："""

    # ========== 通用工具模板 ==========
    FAQ_MATCH_TEMPLATE = """请判断以下FAQ是否与用户问题相关。

用户问题：{question}
FAQ问题：{faq_question}

如果相关请返回"YES"，否则返回"NO"。"""

    SUMMARY_TEMPLATE = """请对以下内容进行摘要总结。

内容：
{content}

摘要（不超过200字）："""

    @classmethod
    def generate_qa_prompt(cls, question: str, context: str, history: list = None,
                           user_profile: dict = None) -> str:
        """生成RAG QA提示词（含内联引用溯源 + 可选对话历史 + 可选学生画像）"""
        from data_processor.user_profile import build_profile_section
        return cls.QA_TEMPLATE.format(
            question=question,
            context=context,
            history_section=cls._format_history(history),
            profile_section=build_profile_section(user_profile) if user_profile else "",
        )

    @classmethod
    def generate_qa_with_citations_prompt(cls, question: str, context: str, history: list = None) -> str:
        """生成带强化内联引用规则的QA提示词（含可选对话历史）"""
        template = cls.QA_TEMPLATE_WITH_CITATIONS
        if history:
            history_text = cls._format_history(history)
            template = template.replace("{question}", "{history_section}" + "【用户问题】\n{question}")
            template = template.replace("{context}", "{context}")
            return template.format(question=question, context=context, history_section=history_text)
        return template.format(question=question, context=context)

    @staticmethod
    def _format_history(history: list) -> str:
        """格式化对话历史为 prompt 文本"""
        if not history:
            return ""
        lines = ["【对话历史】"]
        for msg in history[-6:]:  # 最近3轮
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if content:
                label = "学生" if role == "user" else "助手"
                lines.append(f"{label}: {content[:300]}")
        return "\n".join(lines) + "\n\n"

    @classmethod
    def generate_hyde_prompt(cls, question: str) -> str:
        """生成HyDE提示词"""
        return cls.HYDE_TEMPLATE.format(question=question)

    @classmethod
    def generate_decompose_prompt(cls, question: str) -> str:
        """生成查询分解提示词"""
        return cls.DECOMPOSE_TEMPLATE.format(question=question)

    @classmethod
    def generate_subquery_answer_prompt(cls, question: str,
                                         sub_queries: list,
                                         context: str) -> str:
        """生成子查询答案综合提示词"""
        sub_queries_str = "\n".join([f"- {q}" for q in sub_queries])
        return cls.SUBQUERY_ANSWER_TEMPLATE.format(
            question=question,
            sub_queries=sub_queries_str,
            context=context
        )

    @classmethod
    def generate_quality_eval_prompt(cls, question: str, results: list) -> str:
        """生成质量评估提示词"""
        context = "\n\n".join([r.chunk.content for r in results[:5]])
        return cls.QUALITY_EVAL_TEMPLATE.format(
            question=question,
            context=context
        )

    @classmethod
    def generate_query_refine_prompt(cls, question: str, context: str) -> str:
        """生成查询优化提示词"""
        return cls.QUERY_REFINE_TEMPLATE.format(
            question=question,
            context=context
        )

    @classmethod
    def generate_faq_match_prompt(cls, question: str, faq_question: str) -> str:
        """生成FAQ匹配提示词"""
        return cls.FAQ_MATCH_TEMPLATE.format(
            question=question,
            faq_question=faq_question
        )

    @classmethod
    def generate_summary_prompt(cls, content: str) -> str:
        """生成摘要提示词"""
        return cls.SUMMARY_TEMPLATE.format(content=content)