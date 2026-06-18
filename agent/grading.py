"""
智能批改系统 — 支持客观题与主观题的全方位批改

客观题：选择题/填空题/判断题/计算题（规则匹配 + 过程校验）
主观题：英语作文/语文作文/理科大题（LLM驱动多维度评分）
"""
import re
import json
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from core.logger import get_logger

logger = get_logger("grading")


# ======================== 数据模型 ========================

@dataclass
class GradingResult:
    """批改结果"""
    score: float = 0.0                     # 得分 (0-100)
    max_score: float = 100.0               # 满分
    is_correct: bool = False               # 是否正确（客观题）
    question_type: str = "subjective"      # objective / subjective
    subject: str = "通用"                   # 学科
    feedback: str = ""                     # 总评语
    details: Dict[str, Any] = field(default_factory=dict)  # 详细批改
    highlights: List[Dict] = field(default_factory=list)    # 错误高亮
    steps: List[Dict] = field(default_factory=list)         # 分步批改
    suggestions: List[str] = field(default_factory=list)     # 改进建议

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "max_score": self.max_score,
            "is_correct": self.is_correct,
            "question_type": self.question_type,
            "subject": self.subject,
            "feedback": self.feedback,
            "details": self.details,
            "highlights": self.highlights,
            "steps": self.steps,
            "suggestions": self.suggestions,
        }


# ======================== 客观题批改器 ========================

class ObjectiveGrader:
    """
    客观题批改器
    支持：选择题、填空题、判断题、计算题（过程+结果双重校验）
    """

    @staticmethod
    def grade_choice(user_answer: str, correct_answer: str,
                     options_label: str = "ABCD") -> GradingResult:
        """批改选择题"""
        ua = user_answer.strip().upper()
        ca = correct_answer.strip().upper()
        is_correct = (ua == ca)
        return GradingResult(
            score=100.0 if is_correct else 0.0,
            max_score=100.0,
            is_correct=is_correct,
            question_type="objective",
            subject="选择题",
            feedback="✅ 回答正确" if is_correct else f"❌ 回答错误，正确答案是 {correct_answer}",
            details={"user_choice": ua, "correct_choice": ca},
        )

    @staticmethod
    def grade_fill_blank(user_answer: str, correct_answer: str,
                          accept_synonyms: List[str] = None) -> GradingResult:
        """批改填空题（支持近义词）"""
        ua = user_answer.strip().lower()
        ca = correct_answer.strip().lower()
        candidates = [ca]
        if accept_synonyms:
            candidates.extend([s.strip().lower() for s in accept_synonyms])

        # 去除标点后比较
        def normalize(s):
            return re.sub(r'[，,。\.\s]', '', s)

        ua_norm = normalize(ua)
        is_correct = any(normalize(c) == ua_norm for c in candidates)

        # 部分匹配
        partial_match = not is_correct and any(c in ua or ua in c for c in candidates)

        score = 100.0 if is_correct else (50.0 if partial_match else 0.0)
        fb = "✅ 正确" if is_correct else (
            f"⚠️ 部分正确，标准答案: {correct_answer}" if partial_match
            else f"❌ 错误，正确答案是: {correct_answer}"
        )
        return GradingResult(
            score=score, max_score=100.0,
            is_correct=is_correct,
            question_type="objective", subject="填空题",
            feedback=fb,
            details={"user_fill": user_answer, "correct_fill": correct_answer,
                      "partial_match": partial_match},
        )

    @staticmethod
    def grade_true_false(user_answer: str, correct_answer: str) -> GradingResult:
        """批改判断题"""
        ua = user_answer.strip()
        ua_bool = ua in ("对", "正确", "√", "✓", "T", "True", "true", "是", "yes", "Yes")
        ca_bool = correct_answer.strip() in ("对", "正确", "√", "✓", "T", "True", "true", "是", "yes", "Yes")
        is_correct = (ua_bool == ca_bool)
        return GradingResult(
            score=100.0 if is_correct else 0.0, max_score=100.0,
            is_correct=is_correct,
            question_type="objective", subject="判断题",
            feedback="✅ 正确" if is_correct else f"❌ 错误，正确答案: {correct_answer}",
            details={"user_judgment": ua, "correct_judgment": correct_answer},
        )

    @staticmethod
    def grade_calculation(question: str, user_answer: str, correct_answer: str,
                           user_steps: str = "", correct_steps: str = "") -> GradingResult:
        """
        批改计算题（过程 + 结果双重校验）

        Returns:
            GradingResult with score breakdown: 过程分 + 结果分
        """
        # 结果校验（数值提取）
        def extract_number(s):
            nums = re.findall(r'-?\d+\.?\d*', str(s))
            return float(nums[-1]) if nums else None

        ua_num = extract_number(user_answer)
        ca_num = extract_number(correct_answer)

        result_correct = (ua_num is not None and ca_num is not None and
                           abs(ua_num - ca_num) < 0.001)
        result_score = 40.0 if result_correct else 0.0

        # 过程校验（基于步骤关键词）
        step_score = 0.0
        process_feedback = ""
        if user_steps and correct_steps:
            correct_keywords = re.findall(r'[\u4e00-\u9fa5]{2,}|\w{3,}', correct_steps)
            user_lower = user_steps.lower()
            matched = sum(1 for kw in correct_keywords if kw.lower() in user_lower)
            step_ratio = min(matched / max(len(correct_keywords), 1), 1.0)
            step_score = round(step_ratio * 60.0, 1)
            process_feedback = f"步骤匹配度: {matched}/{len(correct_keywords)}"
        elif not user_steps:
            step_score = 0.0
            process_feedback = "未提供解题步骤"
        else:
            step_score = 30.0  # 有步骤但无参考答案时给保底分
            process_feedback = "已提供解题过程"

        total_score = result_score + step_score
        is_correct = total_score >= 90

        deductions = []
        if not result_correct:
            deductions.append({"point": "计算结果", "deduction": 40, "reason": f"结果错误，正确答案: {correct_answer}"})
        if step_score < 50:
            deductions.append({"point": "解题步骤", "deduction": round(60 - step_score, 1),
                               "reason": "步骤不完整或存在逻辑错误"})

        return GradingResult(
            score=round(total_score, 1), max_score=100.0,
            is_correct=is_correct,
            question_type="objective", subject="计算题",
            feedback=f"总得分 {total_score}/100（结果{result_score}分 + 过程{step_score}分）",
            details={
                "result_correct": result_correct, "result_score": result_score,
                "step_score": step_score, "process_feedback": process_feedback,
                "user_result": ua_num, "correct_result": ca_num,
            },
            steps=[
                {"step": "最终结果", "score": result_score, "max": 40,
                 "status": "correct" if result_correct else "wrong"},
                {"step": "解题过程", "score": step_score, "max": 60,
                 "status": "correct" if step_score >= 50 else "partial"},
            ],
            suggestions=deductions,
        )

    def grade(self, question_type: str, **kwargs) -> GradingResult:
        """统一入口"""
        if question_type == "choice":
            return self.grade_choice(kwargs.get("user_answer", ""), kwargs.get("correct_answer", ""))
        elif question_type == "fill_blank":
            return self.grade_fill_blank(
                kwargs.get("user_answer", ""), kwargs.get("correct_answer", ""),
                kwargs.get("accept_synonyms", [])
            )
        elif question_type == "true_false":
            return self.grade_true_false(kwargs.get("user_answer", ""), kwargs.get("correct_answer", ""))
        elif question_type == "calculation":
            return self.grade_calculation(
                kwargs.get("question", ""), kwargs.get("user_answer", ""),
                kwargs.get("correct_answer", ""),
                kwargs.get("user_steps", ""), kwargs.get("correct_steps", "")
            )
        else:
            return GradingResult(score=0, feedback="不支持的题型", question_type="objective")


# ======================== 主观题批改器（LLM驱动）========================

class SubjectiveGrader:
    """
    主观题批改器
    使用 LLM 进行多维度评分：
    - 英语作文：语法/词汇/句式/切题
    - 语文作文：立意/结构/语言/素材
    - 理科大题：按步骤给分/标注失分点
    """

    def __init__(self, llm_client=None):
        self.llm = llm_client
        if self.llm is None:
            try:
                from llm.llm_client import LLMClient
                self.llm = LLMClient()
            except Exception as e:
                logger.warning(f"LLMClient 初始化失败，批改将不可用: {e}")
                self.llm = None

    def _call_llm(self, prompt: str) -> str:
        """调用LLM"""
        if self.llm is None:
            return json.dumps({"error": "LLM不可用"}, ensure_ascii=False)
        try:
            logger.info(f"[LLM监控] === 即将发送给LLM的prompt (长度={len(prompt)}) ===\n{prompt[:3000]}\n[LLM监控] === prompt结束 ===")
            messages = [{"role": "user", "content": prompt}]
            resp = self.llm.chat(messages, max_tokens=2000)
            logger.info(f"[LLM监控] LLM返回 (长度={len(resp)})：\n{resp[:1500]}")
            return resp
        except Exception as e:
            logger.error(f"LLM调用失败: {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    # ---------- 英语作文批改 ----------

    ENGLISH_ESSAY_PROMPT = """你是一位资深英语教师。请依靠你的专业知识和教学经验，认真批改以下英语作文。

⚠️ 重要：请优先使用你的英语教学专业知识来判断。如果下面的"参考信息"与题目不相关或与你的判断冲突，忽略它，以你的专业判断为准。

## 题目要求
{question}

## 学生作文
{student_answer}

## 评分维度（每项0-100分）
1. **grammar（语法准确性）**: 语法错误数量与严重程度
2. **vocabulary（词汇多样性）**: 词汇丰富度、搭配准确度
3. **sentence_complexity（句式复杂度）**: 句型多样性和衔接
4. **content_relevance（内容切题度）**: 是否紧扣主题
5. **overall（综合评分）**: = (grammar*0.35 + vocabulary*0.25 + complexity*0.2 + relevance*0.2)

## 额外要求
- 找出至少3处语法错误，标注位置并给出修改建议（highlight字段）
- 给出逐句修改建议（corrections字段）
- 给出3-5条提升建议（suggestions字段）

严格按JSON格式返回（不要markdown代码块）：
{{
    "scores": {{"grammar": 85, "vocabulary": 78, "sentence_complexity": 72, "content_relevance": 90, "overall": 82}},
    "highlights": [{{"original": "...", "position": "第X句", "error_type": "grammar/vocabulary/logic", "correction": "...", "explanation": "..."}}],
    "corrections": [{{"original_sentence": "...", "improved_sentence": "...", "comment": "修改理由"}}],
    "suggestions": ["建议1", "建议2", "建议3"],
    "feedback": "总体评语（2-3句，要具体）"
}}
"""

    def grade_english_essay(self, question: str, student_answer: str) -> GradingResult:
        """批改英语作文"""
        prompt = self.ENGLISH_ESSAY_PROMPT.format(
            question=question or "按要求写作",
            student_answer=student_answer[:3000],
        )
        resp = self._call_llm(prompt)
        try:
            # 提取JSON
            json_match = re.search(r'\{[\s\S]*\}', resp)
            data = json.loads(json_match.group()) if json_match else {}
        except Exception as e:
            logger.debug(f"英语作文批改 JSON 解析失败: {e}")
            data = {}

        scores = data.get("scores", {})
        overall = scores.get("overall", 50)
        highlights = data.get("highlights", [])
        corrections = data.get("corrections", [])
        suggestions = data.get("suggestions", [])

        return GradingResult(
            score=round(overall, 1), max_score=100.0,
            question_type="subjective", subject="英语作文",
            feedback=data.get("feedback", f"综合得分: {overall}/100"),
            details=scores,
            highlights=highlights,
            suggestions=suggestions,
            steps=[
                {"step": "语法准确性", "score": scores.get("grammar", 0), "max": 100},
                {"step": "词汇多样性", "score": scores.get("vocabulary", 0), "max": 100},
                {"step": "句式复杂度", "score": scores.get("sentence_complexity", 0), "max": 100},
                {"step": "内容切题度", "score": scores.get("content_relevance", 0), "max": 100},
            ],
        )

    # ---------- 语文作文批改 ----------

    CHINESE_ESSAY_PROMPT = """你是中考语文阅卷老师。批改以下议论文，从5个维度评分（每项0-100），并找出所有逻辑错误。

【题目】
{question}

【作文】
{student_answer}

【年级】{grade_level}

一、评分维度
1. 立意（25%）：是否切题、观点明确、有深度
2. 结构（20%）：开头-本论-结尾是否完整、层次清晰
3. 语言（25%）：是否流畅、用词准确、有文采
4. 素材（15%）：先数清楚文中用了哪些事例（人名、事件），再评价用得对不对、好不好。如果文中已有名人事例，不能写"缺乏名人事例"
5. 逻辑（20%）：重点检查——
   - 前后段落的观点有没有矛盾？（比如前面说"坚持必胜"，后面说"盲目坚持白费"）
   - 例子是不是真的在证明论点？（比如讲"坚持"时扯到"速度"，跑偏了）
   - 有没有"只要…就一定…""完全只靠…"这种绝对化说法？
   - 有没有把复杂成功简单归因为单一因素？（比如"成功全靠坚持，跟天赋、团队无关"）

二、评分锚点
- 立意：跑题0-40 / 平淡40-60 / 正确60-80 / 有深度80-100
- 结构：残缺0-40 / 勉强完整40-60 / 完整但衔接一般60-80 / 严谨80-100
- 语言：多处语病0-40 / 通顺但平淡40-60 / 流畅60-80 / 有文采80-100
- 素材：无事例0 / 有事例但用错20-40 / 准确但单一50-70 / 丰富贴切80-100
- 逻辑：多处严重错误0-40 / 1-2处漏洞40-60 / 基本通顺60-80 / 严密80-100

三、输出JSON（只输出JSON，不要任何其他文字）
{{
  "content_inventory": {{
    "famous_examples": ["列出文中出现的人名"],
    "life_examples": ["列出文中的生活事例"],
    "paragraph_count": 5
  }},
  "scores": {{
    "立意": 75, "结构": 70, "语言": 75, "素材": 65, "逻辑": 60,
    "overall": 计算：(立意*25+结构*20+语言*25+素材*15+逻辑*20)/100 后四舍五入取整
  }},
  "idea_analysis": "立意一句话评价",
  "structure_evaluation": "结构一句话评价",
  "logic_errors": [
    {{
      "original": "有问题的原句（一字不差）",
      "error_type": "自相矛盾/论据偏离/单一归因/绝对化/因果跳跃/其他",
      "explanation": "为什么错",
      "correction": "改写成正确的句子"
    }}
  ],
  "polish": [{{"original": "原句", "improved": "润色后", "reason": "理由"}}],
  "suggestions": ["改进建议1", "改进建议2"],
  "feedback": "总评（80-150字，引用文中具体句子，不准写套话）"
}}"""


    def grade_chinese_essay(self, question: str, student_answer: str,
                            grade_level: str = "初中") -> GradingResult:
        """批改语文作文"""
        prompt = self.CHINESE_ESSAY_PROMPT.format(
            question=question or "按要求写作",
            student_answer=student_answer[:3000],
            grade_level=grade_level,
        )
        resp = self._call_llm(prompt)
        try:
            json_match = re.search(r'\{[\s\S]*\}', resp)
            data = json.loads(json_match.group()) if json_match else {}
        except Exception as e:
            logger.debug(f"语文作文批改 JSON 解析失败: {e}")
            data = {}

        scores = data.get("scores", {})
        overall = scores.get("overall", 50)
        polish = data.get("polish", [])
        logic_errors = data.get("logic_errors", [])

        # 构建分步评分
        steps = [
            {"step": "立意分析", "score": scores.get("立意", 0), "max": 100,
             "status": "correct" if scores.get("立意", 0) >= 70 else ("partial" if scores.get("立意", 0) >= 40 else "wrong")},
            {"step": "结构评价", "score": scores.get("结构", 0), "max": 100,
             "status": "correct" if scores.get("结构", 0) >= 70 else ("partial" if scores.get("结构", 0) >= 40 else "wrong")},
            {"step": "语言表达", "score": scores.get("语言", 0), "max": 100,
             "status": "correct" if scores.get("语言", 0) >= 70 else ("partial" if scores.get("语言", 0) >= 40 else "wrong")},
            {"step": "素材运用", "score": scores.get("素材", 0), "max": 100,
             "status": "correct" if scores.get("素材", 0) >= 70 else ("partial" if scores.get("素材", 0) >= 40 else "wrong")},
            {"step": "逻辑论证", "score": scores.get("逻辑", 0), "max": 100,
             "status": "correct" if scores.get("逻辑", 0) >= 70 else ("partial" if scores.get("逻辑", 0) >= 40 else "wrong")},
        ]

        # 将逻辑错误转为 highlights
        highlights = []
        for le in logic_errors:
            highlights.append({
                "original": le.get("original", ""),
                "paragraph": le.get("paragraph", ""),
                "error_type": le.get("error_type", "逻辑问题"),
                "severity": le.get("severity", "中等"),
                "explanation": le.get("explanation", ""),
                "correction": le.get("correction", ""),
            })

        # 将润色句子也加入 highlights（标记为语言润色）
        for p in polish:
            highlights.append({
                "original": p.get("original", ""),
                "improved": p.get("improved", ""),
                "reason": p.get("reason", ""),
                "error_type": "语言润色",
            })

        return GradingResult(
            score=round(overall, 1), max_score=100.0,
            question_type="subjective", subject="语文作文",
            feedback=data.get("feedback", f"综合得分: {overall}/100（{grade_level}标准）"),
            details={
                "scores": scores,
                "grade_level": grade_level,
                "idea_analysis": data.get("idea_analysis", ""),
                "structure_evaluation": data.get("structure_evaluation", ""),
                "material_suggestions": data.get("material_suggestions", []),
                "logic_errors": logic_errors,
                "content_inventory": data.get("content_inventory", {}),
            },
            highlights=highlights,
            suggestions=data.get("suggestions", []),
            steps=steps,
        )

    # ---------- 理科大题批改 ----------

    SCIENCE_PROMPT = """你是一位资深理科教师。请依靠你的学科专业知识和教学经验，按步骤批改以下理科大题。

⚠️ 重要：请优先使用你的学科专业知识来判断。如果"参考答案"不存在或与题目不匹配，请根据你的专业知识自行拆解题目、设定关键步骤并评分。

## 题目
{question}

## 参考答案（如提供，仅供参考；如不匹配请忽略）
{reference_answer}

## 学生作答
{student_answer}

## 批改要求
1. 将题目拆解为3-6个关键步骤（根据你的专业知识判断拆解是否合理）
2. 每个步骤分配分数（总分100）
3. 对比学生作答，逐步骤判定得分
4. 标注每个失分点的错误类型（公式用错/计算失误/概念错误/步骤缺失/单位错误）
5. 给出各步骤的正确解法
6. 如果参考答案不存在或不匹配，完全依靠你的专业知识来设定正确步骤和判断

严格按JSON格式返回（不要markdown代码块）：
{{
    "steps": [
        {{"step_num": 1, "description": "步骤描述", "max_score": 20, "student_score": 18,
          "status": "correct/partial/wrong/missing",
          "error_type": "公式用错/计算失误/概念错误/步骤缺失/单位错误/无",
          "feedback": "该步骤评价",
          "correct_solution": "该步骤的正确解法"}}
    ],
    "total_score": 85,
    "error_summary": [{{"type": "公式用错", "count": 1, "total_deduction": 5}}],
    "suggestions": ["建议1", "建议2"],
    "feedback": "总体评语（要具体，结合作答内容）"
}}
"""

    def grade_science_problem(self, question: str, student_answer: str,
                               reference_answer: str, subject: str = "数学") -> GradingResult:
        """批改理科大题"""
        prompt = self.SCIENCE_PROMPT.format(
            question=question[:1500],
            reference_answer=reference_answer[:2000],
            student_answer=student_answer[:3000],
        )
        resp = self._call_llm(prompt)
        try:
            json_match = re.search(r'\{[\s\S]*\}', resp)
            data = json.loads(json_match.group()) if json_match else {}
        except Exception as e:
            logger.debug(f"理科批改 JSON 解析失败: {e}")
            data = {}

        steps = data.get("steps", [])
        total_score = data.get("total_score", 0)
        error_summary = data.get("error_summary", [])

        # 构建失分高亮
        highlights = []
        for step in steps:
            if step.get("status") in ("partial", "wrong", "missing"):
                highlights.append({
                    "step": step.get("step_num"),
                    "description": step.get("description", ""),
                    "deduction": round(step.get("max_score", 0) - step.get("student_score", 0), 1),
                    "error_type": step.get("error_type", "其他"),
                    "feedback": step.get("feedback", ""),
                    "correct_solution": step.get("correct_solution", ""),
                })

        return GradingResult(
            score=round(total_score, 1), max_score=100.0,
            question_type="subjective", subject=subject,
            feedback=data.get("feedback", f"总分: {total_score}/100"),
            details={"error_summary": error_summary, "step_count": len(steps)},
            highlights=highlights,
            steps=steps,
            suggestions=data.get("suggestions", []),
        )

    # ---------- 通用主观题 ----------

    def grade_general(self, question: str, student_answer: str,
                       reference_answer: str = "", subject: str = "通用") -> GradingResult:
        """通用主观题批改"""
        prompt = f"""你是{subject}学科的批改老师。按以下步骤批改。

【题目】
{question[:1500]}

【参考答案】
{reference_answer[:1500] or "无"}

【学生作答】
{student_answer[:3000]}

步骤：
1. 从题目中提炼3-5个关键点，逐点判断学生是否覆盖、准确度如何
2. 检查逻辑：前后观点有无矛盾？例子是否支撑论点？有无绝对化表述？有无单一归因？
3. 检查表达：用词是否准确、有无歧义
4. 综合评分

输出JSON：
{{
  "key_points": [
    {{"point": "关键点", "covered": true/false, "quality": "good/partial/missing", "comment": "引用原文评价"}}
  ],
  "logic_score": 70,
  "clarity_score": 80,
  "overall": 75,
  "logic_issues": [
    {{"original": "原句", "issue_type": "自相矛盾/论据偏离/绝对化/因果跳跃/单一归因/其他", "explanation": "为什么错", "correction": "修改为"}}
  ],
  "strengths": ["优点1（引用原文）"],
  "weaknesses": ["不足1（引用原文）"],
  "feedback": "总评（80-150字，不准写套话）",
  "suggestions": ["建议1", "建议2"]
}}

评分锚点：
- logic_score：多处严重错误0-40 / 1-2处漏洞40-60 / 基本通顺60-80 / 严密80-100
- overall = logic_score×0.35 + clarity_score×0.25 + key_points覆盖率×0.4
- 发现逻辑问题必须填入logic_issues，不能只给低分"""
        resp = self._call_llm(prompt)
        # 尝试多种 JSON 提取策略
        data = {}
        try:
            cleaned = resp.strip()
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
            json_match = re.search(r'\{[\s\S]*\}', cleaned)
            if json_match:
                data = json.loads(json_match.group())
        except Exception as e:
            logger.debug(f"通用批改 JSON 解析失败: {e}")

        if not data or "overall" not in data:
            brief = resp.strip()[:200].replace('\n', ' ')
            data = {
                "overall": 60,
                "feedback": brief if brief else "批改完成，请查看评语",
                "key_points": [], "logic_score": 0, "clarity_score": 0,
                "strengths": [], "weaknesses": [], "suggestions": [], "logic_issues": [],
            }

        # 从 key_points 构建分步评分
        key_points = data.get("key_points", [])
        steps = []
        if key_points:
            for kp in key_points:
                point_name = kp.get("point", "")
                quality = kp.get("quality", "missing")
                comment = kp.get("comment", "")
                if quality == "good":
                    score_val, max_val, status = 100, 100, "correct"
                elif quality == "partial":
                    score_val, max_val, status = 50, 100, "partial"
                else:
                    score_val, max_val, status = 0, 100, "missing"
                steps.append({
                    "step": point_name,
                    "score": score_val,
                    "max": max_val,
                    "status": status,
                    "feedback": comment,
                })

        # 添加逻辑评分作为独立步骤
        logic_score = data.get("logic_score", 0)
        if logic_score > 0:
            logic_status = "correct" if logic_score >= 70 else ("partial" if logic_score >= 40 else "wrong")
            steps.append({
                "step": "逻辑论证严密性",
                "score": logic_score,
                "max": 100,
                "status": logic_status,
                "feedback": f"逻辑得分: {logic_score}/100",
            })

        # 构建 highlights（逻辑问题优先）
        highlights = []
        logic_issues = data.get("logic_issues", [])
        for li in logic_issues:
            highlights.append({
                "original": li.get("original", ""),
                "error_type": li.get("issue_type", "逻辑问题"),
                "explanation": li.get("explanation", ""),
                "correction": li.get("correction", ""),
            })

        weaknesses = data.get("weaknesses", [])
        for w in weaknesses:
            highlights.append({
                "description": w,
                "error_type": "需改进",
                "feedback": w,
            })

        return GradingResult(
            score=round(data.get("overall", 60), 1), max_score=100.0,
            question_type="subjective", subject=subject,
            feedback=data.get("feedback", "批改完成，请查看评语"),
            details={
                "key_points": key_points,
                "logic_score": logic_score,
                "clarity_score": data.get("clarity_score", 0),
                "strengths": data.get("strengths", []),
                "weaknesses": weaknesses,
                "logic_issues": logic_issues,
            },
            highlights=highlights,
            steps=steps,
            suggestions=data.get("suggestions", []),
        )

    def grade(self, subject: str, question: str, student_answer: str,
              reference_answer: str = "", **kwargs) -> GradingResult:
        """统一入口"""
        subject_lower = subject.lower()
        if "英语" in subject or "english" in subject_lower:
            return self.grade_english_essay(question, student_answer)
        elif "语文" in subject or "chinese" in subject_lower:
            return self.grade_chinese_essay(
                question, student_answer,
                grade_level=kwargs.get("grade_level", "初中")
            )
        elif any(s in subject for s in ("数学", "物理", "化学", "生物", "理科", "math", "physics", "chemistry")):
            return self.grade_science_problem(
                question, student_answer, reference_answer, subject
            )
        else:
            return self.grade_general(question, student_answer, reference_answer, subject)


# ======================== 统一批改入口 ========================

class UnifiedGrader:
    """统一批改器 — 自动选择客观/主观批改"""

    def __init__(self, llm_client=None):
        self.objective = ObjectiveGrader()
        self.subjective = SubjectiveGrader(llm_client=llm_client)

    def auto_detect_and_grade(self, question: str, user_answer: str,
                               correct_answer: str = "", subject: str = "通用",
                               question_type: str = "auto",
                               user_steps: str = "", reference_steps: str = "",
                               grade_level: str = "初中") -> GradingResult:
        """
        自动检测题型并批改

        Args:
            question: 题目内容
            user_answer: 学生作答
            correct_answer: 正确答案（客观题必填）
            subject: 学科
            question_type: auto / choice / fill_blank / true_false / calculation / subjective
            user_steps: 计算过程
            reference_steps: 标准步骤
            grade_level: 年级
        """
        # 客观题自动检测
        if question_type == "auto":
            if correct_answer and len(correct_answer) <= 3 and correct_answer.strip().upper() in "ABCD":
                question_type = "choice"
            elif subject in ("选择题",):
                question_type = "choice"
            elif subject in ("填空题",):
                question_type = "fill_blank"
            elif subject in ("判断题",):
                question_type = "true_false"
            elif subject in ("计算题", "数学", "物理", "化学"):
                if user_steps or reference_steps:
                    question_type = "calculation"
                elif correct_answer and re.search(r'[\d.]+', correct_answer):
                    question_type = "fill_blank"  # 无步骤的数学题按填空题批改
                else:
                    question_type = "subjective"
            else:
                question_type = "subjective"

        if question_type in ("choice", "fill_blank", "true_false"):
            return self.objective.grade(question_type,
                                        user_answer=user_answer,
                                        correct_answer=correct_answer)
        elif question_type == "calculation":
            return self.objective.grade_calculation(
                question, user_answer, correct_answer,
                user_steps, reference_steps,
            )
        else:
            return self.subjective.grade(
                subject, question, user_answer, correct_answer,
                grade_level=grade_level,
            )