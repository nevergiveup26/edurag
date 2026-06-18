"""
Guardrails — RAG安全防护与质量门控

提供三个核心防护：
1. 幻觉检测：检查答案是否基于参考资料，检测无依据的编造
2. 置信度评分：对答案质量进行综合评分（0-1）
3. 来源溯源：强制执行来源引用标注

用法:
    guard = RAGGuard(llm_client)
    check = guard.check(query, answer, sources)
    if check["has_hallucination"]:
        answer = "[根据资料无法准确回答该问题。]"
    if not check["has_sources"]:
        answer += "\n\n⚠ 以上回答未标注来源，仅供参考。"
"""
import re
from typing import List, Dict
from core.logger import get_logger

logger = get_logger("guardrails")

HALLUCINATION_CHECK_PROMPT = """你是一个事实核查专家。请检查以下【答案】是否完全基于【参考资料】。

【核查要点】
1. 答案中是否有来自参考资料之外的内容？
2. 答案中的数字、日期、人名是否与参考资料一致？
3. 答案是否有过度推断或编造的结论？

【参考资料】
{context}

【用户问题】
{query}

【生成的答案】
{answer}

请以JSON格式返回：
{{
    "has_hallucination": true/false,
    "hallucinated_parts": ["具体编造的部分"],
    "confidence_score": 0.0-1.0,
    "groundedness": 0.0-1.0,
    "explanation": "核查说明"
}}
只返回JSON。"""


class RAGGuard:
    """RAG 质量门控 — 幻觉检测 + 置信度 + 来源检查"""

    def __init__(self, llm_client=None):
        from llm.llm_client import LLMClient
        self.llm_client = llm_client or LLMClient()
        self.hallucination_threshold = 0.7   # groundedness 低于此值标记为幻觉
        self.min_confidence = 0.3            # 最低置信度

    def check(self, query: str, answer: str, sources: List = None) -> Dict:
        """
        执行安全与质量检查

        Returns:
            {
                "has_hallucination": bool,
                "hallucinated_parts": [str],
                "confidence_score": float (0-1),
                "groundedness": float (0-1),
                "has_sources": bool,
                "missing_citations": bool,
                "passed": bool,  # 综合判定是否通过
            }
        """
        # 1. 来源检查（无需LLM）
        has_sources = bool(sources and len(sources) > 0)
        has_citations = self._check_citations(answer, sources) if has_sources else False

        # 2. 幻觉检测
        hallucination_result = self._detect_hallucination(query, answer, sources)

        # 3. 置信度计算
        confidence = self._compute_confidence(hallucination_result)

        return {
            "has_hallucination": hallucination_result.get("has_hallucination", False),
            "hallucinated_parts": hallucination_result.get("hallucinated_parts", []),
            "confidence_score": confidence,
            "groundedness": hallucination_result.get("groundedness", 0.0),
            "has_sources": has_sources,
            "missing_citations": not has_citations,
            "passed": (not hallucination_result.get("has_hallucination", False)
                       and confidence >= self.min_confidence
                       and has_sources),
        }

    def _detect_hallucination(self, query: str, answer: str,
                               sources: List = None) -> Dict:
        """检测幻觉"""
        # 构建参考资料摘要
        context = "无参考资料"
        if sources:
            snippets = []
            for i, s in enumerate(sources[:5]):
                content = s.chunk.content if hasattr(s, 'chunk') else str(s)
                snippets.append(f"[{i+1}] {content[:400]}")
            context = "\n\n".join(snippets)

        prompt = HALLUCINATION_CHECK_PROMPT.format(
            context=context[:3000],
            query=query[:500],
            answer=answer[:2000],
        )

        try:
            import json
            response = self.llm_client.generate(prompt, max_tokens=400, temperature=0.1)
            # 提取第一个 { 到最后一个 } 之间的 JSON（避免贪婪匹配误匹配）
            start = response.find('{')
            end = response.rfind('}')
            if start != -1 and end > start:
                result = json.loads(response[start:end+1])
                return result
        except Exception as e:
            logger.warning(f"幻觉检测失败: {e}")

        # 快速规则检测（fallback）
        return self._rule_hallucination_check(query, answer, sources)

    def _rule_hallucination_check(self, query: str, answer: str,
                                   sources: List = None) -> Dict:
        """基于规则的快速幻觉检测（fallback）"""
        # 检查是否包含"无法回答"等诚实表述
        honesty_phrases = ["无法回答", "暂无信息", "资料未提及", "没有相关信息",
                          "据现有资料", "根据上述资料", "根据参考资料"]
        is_honest = any(p in answer for p in honesty_phrases)

        # 检查答案长度是否合理
        if not sources or len(sources) == 0:
            return {"has_hallucination": not is_honest, "hallucinated_parts": [],
                    "groundedness": 0.7 if is_honest else 0.3,
                    "confidence_score": 0.5 if is_honest else 0.2}

        # 检查答案中是否有参考资料中的关键词
        context_keywords = set()
        for s in sources[:3]:
            content = s.chunk.content if hasattr(s, 'chunk') else str(s)
            for word in re.findall(r'[\u4e00-\u9fff]{2,6}', content):
                context_keywords.add(word)

        answer_words = set(re.findall(r'[\u4e00-\u9fff]{2,6}', answer[:500]))
        if answer_words:
            overlap = len(answer_words & context_keywords) / max(len(answer_words), 1)
            groundedness = min(1.0, overlap * 2)  # 放大显著
        else:
            groundedness = 0.5

        return {
            "has_hallucination": groundedness < self.hallucination_threshold and not is_honest,
            "hallucinated_parts": [],
            "groundedness": round(groundedness, 2),
            "confidence_score": round(groundedness, 2),
        }

    def _check_citations(self, answer: str, sources: List) -> bool:
        """检查答案中是否引用了来源"""
        # 检测引用标记 [1] [2] 等
        has_bracket_refs = bool(re.search(r'\[\d+\]', answer))
        # 检测资料编号
        has_ref_keywords = any(kw in answer for kw in ["参考资料", "来源", "参考"])
        return has_bracket_refs or has_ref_keywords

    def _compute_confidence(self, hallucination_result: Dict) -> float:
        """计算综合置信度"""
        groundedness = hallucination_result.get("groundedness", 0.5)
        has_hallucination = hallucination_result.get("has_hallucination", False)
        confidence = hallucination_result.get("confidence_score", groundedness)

        if has_hallucination:
            confidence *= 0.7  # 幻觉惩罚
        return round(min(1.0, max(0.0, confidence)), 2)

    @staticmethod
    def generate_missing_source_warning(check: Dict) -> str:
        """生成来源缺失警告"""
        warnings = []
        if check.get("missing_citations"):
            warnings.append("⚠ 以上回答未标注参考资料来源，准确性请自行核实。")
        if check.get("has_hallucination"):
            warnings.append("⚠ 部分内容可能不在参考资料范围内，已标记。")
        if check.get("confidence_score", 0) < 0.5:
            warnings.append(f"⚠ 回答置信度较低（{check['confidence_score']:.0%}），建议查阅原始资料。")
        return "\n".join(warnings)