"""
上下文压缩器

在将检索结果送入LLM生成答案之前，先压缩/去噪：
1. 提取与当前查询最相关的关键事实
2. 去除冗余和无关内容
3. 保留引用编号以便溯源

用法:
    compressor = ContextCompressor(llm_client)
    compressed = compressor.compress(query, retrieved_chunks)
    # → 精炼后的上下文，信息密度更高
"""
from typing import List, Optional
from core.logger import get_logger

logger = get_logger("context_compressor")

COMPRESS_PROMPT = """你是一个信息提取专家。请从以下【参考资料】中提取与【用户问题】相关的关键信息，去除冗余和无关内容。

【压缩规则】
1. 只提取与问题直接相关的信息，忽略无关段落
2. 保留每条信息前的引用编号 [1]、[2] 等
3. 对于相关但冗长的段落，用简洁的语言概括要点
4. 如果有数值、公式、定义等核心数据，务必完整保留
5. 压缩后的总长度应控制在原始资料的 50% 以内
6. 不要添加参考资料中没有的信息
7. 保持原文的学科术语和表述方式

【用户问题】
{query}

【参考资料】
{context}

【压缩结果】"""


class ContextCompressor:
    """上下文压缩器 — 提取关键信息，去除噪声，提高答案质量"""

    def __init__(self, llm_client=None):
        from llm.llm_client import get_fast_llm
        self.llm_client = llm_client or get_fast_llm()  # 压缩用 turbo
        self.max_input_chars = 8000    # 超过这个长度才触发压缩
        self.max_compressed_chars = 3000  # 压缩后目标长度

    def compress(self, query: str, chunks: list,
                 max_input: int = None) -> str:
        """
        压缩检索到的上下文

        Args:
            query: 用户查询
            chunks: 检索结果列表（RetrievalResult 或 dict 列表）
            max_input: 最大输入字符数（超过才压缩）

        Returns:
            压缩后的上下文字符串，格式: "[1] 内容\n\n[2] 内容..."
        """
        # 构建编号上下文
        context_parts = []
        total_len = 0
        for i, chunk in enumerate(chunks):
            # 兼容 RetrievalResult 和 dict 两种格式
            if hasattr(chunk, 'chunk') and chunk.chunk is not None:
                content = chunk.chunk.content if hasattr(chunk.chunk, 'content') else ''
            elif hasattr(chunk, 'get'):
                content = chunk.get('content', str(chunk))
            else:
                content = str(chunk)
            if not content:
                continue
            context_parts.append(f"[{i+1}] {content}")
            total_len += len(content)

        if not context_parts:
            return ""

        raw_context = "\n\n".join(context_parts)

        # 如果内容较短，不需要压缩
        threshold = max_input or self.max_input_chars
        if total_len <= threshold:
            return raw_context

        logger.debug(f"触发上下文压缩: {total_len} → 目标 ≤{self.max_compressed_chars} 字符")

        # LLM 压缩
        prompt = COMPRESS_PROMPT.format(query=query, context=raw_context[:12000])
        try:
            compressed = self.llm_client.generate(
                prompt,
                max_tokens=min(2000, self.max_compressed_chars // 2),
                temperature=0.1
            )
            if compressed and len(compressed) > 20:
                logger.info(f"上下文压缩: {total_len} → {len(compressed)} 字符 "
                           f"({len(compressed)*100//max(total_len,1)}%)")
                return compressed
        except Exception as e:
            logger.warning(f"上下文压缩失败，使用原始内容: {e}")

        return raw_context

    def compress_for_prompt(self, query: str, results: list,
                            max_context_chars: int = 4000) -> str:
        """
        便捷方法：压缩并确保不超过max_context_chars

        Args:
            query: 用户查询
            results: 检索结果列表
            max_context_chars: 最终上下文最大字符数

        Returns:
            适配prompt的上下文字符串
        """
        compressed = self.compress(query, results, max_input=max_context_chars * 2)
        if len(compressed) > max_context_chars:
            # 在 max_context_chars 范围内找最后一个完整句子边界
            truncated = compressed[:max_context_chars]
            # 优先找中文句号/问号/感叹号，其次是换行
            for sep in ['。', '？', '！', '\n', '；', '，']:
                last_sep = truncated.rfind(sep)
                if last_sep > max_context_chars * 0.6:  # 至少保留60%
                    compressed = truncated[:last_sep + 1] + "\n...(内容已截断)"
                    break
            else:
                compressed = truncated + "\n...(内容已截断)"
        return compressed