"""
LLM 评判指标
- Faithfulness (忠实度): 分解评分 — 拆 claims → 逐条验证
- AnswerRelevancy (答案相关性): Prompt 直出
- AnswerCorrectness (正确性): Prompt 直出（需 ground_truth）
"""
import json
import re
from typing import List, Optional
from dataclasses import dataclass, field

from core.logger import get_logger

logger = get_logger("llm_judge")


@dataclass
class RAGQualityMetrics:
    """RAG 质量指标"""
    faithfulness: float = 0.0
    answer_relevancy: float = 0.0
    answer_correctness: float = 0.0


# ═══════════════════════════════════════════════════════════════
# Faithfulness — 分解评分
# ═══════════════════════════════════════════════════════════════

CLAIM_EXTRACTION_PROMPT = """你是一个严谨的事实核查助手。请将以下【答案】拆分为独立的、可验证的事实陈述（claims）。

【问题】
{question}

【答案】
{answer}

规则：
1. 每条 claim 必须是一个独立的事实陈述，可以单独验证真伪
2. 不要拆分同一个事实的不同表述方式
3. 如果答案中没有事实性陈述（如纯问候、纯闲聊），返回空列表
4. 每条 claim 用中文完整表述

返回严格 JSON 格式（不要 markdown 代码块）：
{{"claims": ["事实陈述1", "事实陈述2", ...]}}"""


CLAIM_VERIFICATION_PROMPT = """你是一个严谨的事实核查助手。请判断以下每条【事实陈述】是否被【参考资料】中的信息所支持。

【参考资料】
{contexts}

【事实陈述】
{claims_text}

规则：
1. 对每条陈述，判断参考资料中是否有明确信息支持它
2. "支持"意味着参考资料中包含了该陈述的核心事实，不需要逐字逐句相同
3. 如果参考资料完全没有提到相关事实，标记为"不支持"
4. 如果参考资料部分支持但不够充分，标记为"部分支持"

返回严格 JSON 格式：
{{"verifications": [
  {{"claim_index": 0, "supported": true, "reason": "一句话说明"}},
  {{"claim_index": 1, "supported": false, "reason": "一句话说明"}}
]}}"""


# ═══════════════════════════════════════════════════════════════
# AnswerRelevancy — Prompt 直出
# ═══════════════════════════════════════════════════════════════

ANSWER_RELEVANCY_PROMPT = """你是一个教育领域的答案质量评估专家。请评估以下【答案】与【问题】的相关程度。

【问题】
{question}

【答案】
{answer}

评估维度：
1. 答案是否直接回应了问题（不跑题、不绕弯）
2. 答案是否包含了与问题无关的冗余信息
3. 如果有冗余信息，是否影响了核心回答的清晰度

请给出 0-10 的整数评分，并简要说明理由。

返回严格 JSON 格式：
{{"score": <0-10的整数>, "relevant": <true/false>, "reason": "<一句话说明>"}}"""


# ═══════════════════════════════════════════════════════════════
# AnswerCorrectness — Prompt 直出（需 ground_truth）
# ═══════════════════════════════════════════════════════════════

ANSWER_CORRECTNESS_PROMPT = """你是一个教育领域的答案评判专家。请对比【学生答案】与【标准答案】，评估学生答案的正确性。

【问题】
{question}

【标准答案】
{ground_truth}

【学生答案】
{answer}

请从以下维度评判（0-10分）：
1. 核心结论是否正确（关键事实、答案选项是否一致）
2. 推理过程是否合理（如有分析说明）
3. 是否包含无关或错误信息

返回 JSON 格式：
{{"score": <0-10的整数>, "correct": <true/false>, "reason": "<一句话说明>"}}

仅返回 JSON。"""


def _get_llm():
    """获取 LLM 客户端（qwen-turbo）"""
    from llm.llm_client import get_fast_llm
    return get_fast_llm()


def _extract_json(text: str) -> dict:
    """从 LLM 响应中提取 JSON"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:]) if lines[0].startswith("```") else text
        if text.endswith("```"):
            text = text[:-3]
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        return json.loads(json_match.group())
    return {}


async def calc_faithfulness(
    question: str,
    answer: str,
    contexts: List[str],
    llm=None,
) -> float:
    """
    计算 Faithfulness（忠实度）— 分解评分

    1. LLM 将 answer 拆分为 claims
    2. LLM 逐条验证每一条 claim 是否被 contexts 支持
    3. 得分 = supported_count / total_count

    Args:
        question: 用户问题
        answer: 系统生成的答案
        contexts: 检索到的上下文列表
        llm: LLMClient 实例（不传则自动获取 get_fast_llm()）

    Returns:
        0-1 之间的忠实度分数
    """
    if not answer or not contexts:
        return 0.0

    if llm is None:
        llm = _get_llm()

    try:
        # Step 1: 拆解 claims
        extract_prompt = CLAIM_EXTRACTION_PROMPT.format(
            question=question[:500],
            answer=answer[:1000],
        )
        extract_resp = llm.generate(extract_prompt, max_tokens=800, temperature=0.0)
        extract_data = _extract_json(extract_resp)
        claims = extract_data.get("claims", [])

        if not claims:
            return 1.0

        logger.info(f"[Faithfulness] 拆解出 {len(claims)} 条 claims")

        # Step 2: 逐条验证（批量一次请求）
        contexts_text = "\n\n---\n\n".join(
            f"[参考资料 {i+1}]\n{ctx[:500]}" for i, ctx in enumerate(contexts[:5])
        )
        claims_text = "\n".join(
            f"[{i}] {claim}" for i, claim in enumerate(claims)
        )
        verify_prompt = CLAIM_VERIFICATION_PROMPT.format(
            contexts=contexts_text[:3000],
            claims_text=claims_text,
        )
        verify_resp = llm.generate(verify_prompt, max_tokens=1000, temperature=0.0)
        verify_data = _extract_json(verify_resp)
        verifications = verify_data.get("verifications", [])

        if not verifications:
            return 0.0

        supported = sum(
            1 for v in verifications
            if v.get("supported") is True or v.get("supported") == "true"
        )
        score = supported / len(claims)
        logger.info(f"[Faithfulness] 得分: {supported}/{len(claims)} = {score:.4f}")
        return round(score, 4)

    except Exception as e:
        logger.warning(f"[Faithfulness] 计算失败: {e}")
        return 0.0


async def calc_answer_relevancy(
    question: str,
    answer: str,
    llm=None,
) -> float:
    """
    计算 AnswerRelevancy（答案相关性）— Prompt 直出

    Args:
        question: 用户问题
        answer: 系统生成的答案
        llm: LLMClient 实例

    Returns:
        0-1 之间的相关性分数
    """
    if not answer:
        return 0.0

    if llm is None:
        llm = _get_llm()

    try:
        prompt = ANSWER_RELEVANCY_PROMPT.format(
            question=question[:500],
            answer=answer[:1000],
        )
        resp = llm.generate(prompt, max_tokens=300, temperature=0.0)
        data = _extract_json(resp)
        raw_score = float(data.get("score", 0))
        return round(raw_score / 10.0, 4)
    except Exception as e:
        logger.warning(f"[AnswerRelevancy] 计算失败: {e}")
        return 0.0


async def calc_answer_correctness(
    question: str,
    answer: str,
    ground_truth: str,
    llm=None,
) -> float:
    """
    计算 AnswerCorrectness（正确性）— Prompt 直出

    Args:
        question: 用户问题
        answer: 系统生成的答案
        ground_truth: 标准答案
        llm: LLMClient 实例

    Returns:
        0-1 之间的正确性分数
    """
    if not answer or not ground_truth:
        return 0.0

    if llm is None:
        llm = _get_llm()

    try:
        prompt = ANSWER_CORRECTNESS_PROMPT.format(
            question=question[:200],
            ground_truth=ground_truth[:500],
            answer=answer[:500],
        )
        resp = llm.generate(prompt, max_tokens=300, temperature=0.0)
        data = _extract_json(resp)
        raw_score = float(data.get("score", 0))
        return round(raw_score / 10.0, 4)
    except Exception as e:
        logger.warning(f"[AnswerCorrectness] 计算失败: {e}")
        return 0.0