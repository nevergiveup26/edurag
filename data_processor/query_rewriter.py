"""
Query Rewriting 模块

将用户的模糊、口语化、不完整查询重写为精准的检索查询。
教育场景专长：识别学生的口语化提问，补充学科术语和上下文。

用法：
    rewriter = QueryRewriter(llm_client)
    rewritten = rewriter.rewrite("那个乘法怎么算来着", history=[...])
    # → "分数乘法的计算方法和步骤"
"""
from typing import List, Optional, Tuple
from llm.llm_client import LLMClient
from core.logger import get_logger

logger = get_logger("query_rewriter")

REWRITE_PROMPT = """你是一个教育领域的查询优化专家。用户的原始查询往往是口语化的、模糊的或不完整的。
请将原始查询重写为一个精准的、适合知识库检索的查询语句。

【重写规则】
1. 识别查询的核心学科归属（数学/语文/英语/物理等）
2. 将口语化表达替换为标准学科术语
   - "那个乘法怎么算" → "分数/小数乘法计算方法"
   - "春晓那首诗" → "《春晓》作者孟浩然 古诗全文及赏析"
   - "牛顿第一定律是啥" → "牛顿第一定律 惯性定律 定义和内容"
   - "一元一次方程怎么解" → "一元一次方程解题步骤和方法"
3. 如果查询包含代词（它、这个、那个），结合对话历史还原上下文
4. 补充查询中隐含的关键词（如提到"勾股定理"可补充"直角三角形""a²+b²=c²"）
5. 不要改变查询的原始意图
6. 如果原始查询已经非常清晰和精准，可以保持不变
7. 仅输出重写后的查询文本，不要添加任何解释或前缀

{history_section}
【原始查询】
{query}

【重写查询】"""


class QueryRewriter:
    """
    查询重写器

    结合对话历史，将用户口语化查询重写为精准的检索查询。
    """
    def __init__(self, llm_client: LLMClient = None):
        self.llm_client = llm_client or LLMClient()
        self.enabled = True

    def rewrite(self, query: str, history: List[dict] = None,
                conversation_id: str = None) -> Tuple[str, bool]:
        """
        重写查询

        Args:
            query: 用户原始查询
            history: 对话历史 [{"role": "user/assistant", "content": "..."}]
            conversation_id: 会话ID

        Returns:
            (rewritten_query, was_rewritten): 重写后的查询和是否发生了重写
        """
        # 快速判断：短查询或包含代词的需要重写
        need_rewrite = self._should_rewrite(query, history)

        if not need_rewrite:
            logger.debug(f"查询已足够清晰，跳过重写: {query[:60]}")
            return query, False

        # 如果提供了conversation_id但没有history，尝试从DB加载
        if (not history or len(history) == 0) and conversation_id:
            history = self._load_history(conversation_id)

        # 构建历史上下文
        history_section = ""
        if history and len(history) > 0:
            recent = history[-6:]  # 最近3轮对话
            history_lines = ["【对话历史】"]
            for msg in recent:
                role = "学生" if msg.get("role") == "user" else "助手"
                content = msg.get("content", "")[:200]
                history_lines.append(f"{role}: {content}")
            history_section = "\n".join(history_lines) + "\n"

        # LLM 重写
        prompt = REWRITE_PROMPT.format(
            history_section=history_section,
            query=query
        )

        try:
            rewritten = self.llm_client.generate(prompt, max_tokens=200).strip()
            # 清理可能的引号或前缀
            rewritten = rewritten.strip('"''"').strip()
            was_rewritten = rewritten and rewritten != query

            if was_rewritten:
                logger.info(f"查询重写: [{query[:50]}] → [{rewritten[:80]}]")
            else:
                logger.debug(f"查询无需重写: {query[:60]}")

            return rewritten if rewritten else query, was_rewritten

        except Exception as e:
            logger.warning(f"查询重写失败，使用原查询: {e}")
            return query, False

    def _should_rewrite(self, query: str, history: List[dict]) -> bool:
        """快速判断是否需要重写"""
        # 太短的查询
        if len(query) <= 8:
            return True

        # 包含代词，需要上下文还原
        pronoun_keywords = ["它", "他", "她", "这个", "那个", "这些", "那些",
                            "怎么算", "怎么做", "怎么解", "什么意思", "是什么"]
        if any(kw in query for kw in pronoun_keywords):
            return True

        # 纯问句且信息量少
        if (query.startswith("为什么") or query.startswith("怎么") or
                query.startswith("什么是")) and len(query) < 15:
            return True

        # 有对话历史时，很可能是追问
        if history and len(history) >= 2:
            return True

        return False

    def _load_history(self, conversation_id: str) -> List[dict]:
        """从数据库加载对话历史"""
        try:
            from database.mysql_db import MySQLDB
            db = MySQLDB()
            rows = db.query(
                "SELECT role, content FROM conversation_messages "
                "WHERE conversation_id = %s ORDER BY created_at ASC LIMIT 20",
                (conversation_id,)
            )
            return [{"role": r["role"], "content": r["content"]} for r in rows]
        except Exception:
            return []