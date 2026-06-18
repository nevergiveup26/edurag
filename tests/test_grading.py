"""agent.grading 智能批改系统测试"""
import json
import pytest
from unittest.mock import MagicMock, patch


# ======================== GradingResult ========================


class TestGradingResult:
    def test_default_values(self):
        from agent.grading import GradingResult
        r = GradingResult()
        assert r.score == 0.0
        assert r.max_score == 100.0
        assert r.is_correct is False
        assert r.question_type == "subjective"
        assert r.details == {}
        assert r.highlights == []

    def test_to_dict(self):
        from agent.grading import GradingResult
        r = GradingResult(
            score=85.5, max_score=100.0, is_correct=True,
            question_type="objective", subject="数学",
            feedback="做得很好", details={"key": "val"},
            highlights=[{"error": "typo"}],
            steps=[{"step": 1, "score": 40}],
            suggestions=["改进建议"],
        )
        d = r.to_dict()
        assert d["score"] == 85.5
        assert d["subject"] == "数学"
        assert d["details"]["key"] == "val"
        assert len(d["highlights"]) == 1
        assert len(d["steps"]) == 1


# ======================== ObjectiveGrader ========================


class TestGradeChoice:
    def test_correct(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_choice("A", "A")
        assert r.is_correct is True
        assert r.score == 100.0

    def test_wrong(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_choice("B", "A")
        assert r.is_correct is False
        assert r.score == 0.0

    def test_case_insensitive(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_choice("a", "A")
        assert r.is_correct is True

    def test_whitespace_trimmed(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_choice("  C  ", "C")
        assert r.is_correct is True


class TestGradeFillBlank:
    def test_exact_match(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_fill_blank("牛顿", "牛顿")
        assert r.is_correct is True
        assert r.score == 100.0

    def test_wrong(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_fill_blank("爱因斯坦", "牛顿")
        assert r.is_correct is False
        assert r.score == 0.0

    def test_synonym_accepted(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_fill_blank("速度", "速率", accept_synonyms=["速度"])
        assert r.is_correct is True

    def test_partial_match(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_fill_blank("牛顿第一定律", "牛顿")
        assert r.is_correct is False
        assert r.score == 50.0  # 部分匹配得50分

    def test_normalize_punctuation(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_fill_blank("3.14", "3，14")  # 中文逗号 vs 句号
        # 标点被 normalize 去除后比较
        assert r.score == 100.0


class TestGradeTrueFalse:
    def test_correct_true(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_true_false("对", "正确")
        assert r.is_correct is True

    def test_correct_false(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_true_false("错", "错误")
        assert r.is_correct is True  # 两者都表达"错误"

    def test_wrong(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_true_false("对", "错误")
        assert r.is_correct is False

    def test_symbols(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_true_false("√", "正确")
        assert r.is_correct is True

    def test_english_t_f(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_true_false("T", "True")
        assert r.is_correct is True


class TestGradeCalculation:
    def test_full_correct(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_calculation(
            question="1+1=?", user_answer="2", correct_answer="2",
            user_steps="一步一步计算", correct_steps="一步一步计算",
        )
        assert r.score == 100.0
        assert r.is_correct is True

    def test_result_wrong_process_right(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_calculation(
            question="1+1=?", user_answer="3", correct_answer="2",
            user_steps="一步一步计算", correct_steps="一步一步计算",
        )
        assert r.score == 60.0  # 结果0 + 过程60
        assert r.is_correct is False

    def test_result_right_no_process(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_calculation(
            question="1+1=?", user_answer="2", correct_answer="2",
            user_steps="", correct_steps="",
        )
        assert r.score == 40.0  # 结果40 + 过程0 (无步骤)
        assert r.is_correct is False  # < 90

    def test_no_user_steps_with_correct_steps(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_calculation(
            question="求解", user_answer="42", correct_answer="42",
            user_steps="", correct_steps="步骤1: ..., 步骤2: ...",
        )
        assert r.score == 40.0  # 结果40 + 过程0 (未提供步骤)

    def test_user_steps_no_reference(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_calculation(
            question="求解", user_answer="42", correct_answer="42",
            user_steps="我的解题步骤", correct_steps="",
        )
        assert r.score == 70.0  # 结果40 + 过程30(保底)

    def test_extract_number_from_text(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_calculation(
            question="x=?", user_answer="答案是42", correct_answer="x=42",
        )
        assert r.details["result_correct"] is True

    def test_float_tolerance(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_calculation(
            question="π=?", user_answer="3.1415", correct_answer="3.1416",
        )
        assert r.details["result_correct"] is True  # 差值 < 0.001

    def test_deductions_in_suggestions(self):
        from agent.grading import ObjectiveGrader
        r = ObjectiveGrader.grade_calculation(
            question="1+1=?", user_answer="3", correct_answer="2",
        )
        assert len(r.suggestions) >= 1


class TestObjectiveGradeDispatch:
    def test_choice(self):
        from agent.grading import ObjectiveGrader
        grader = ObjectiveGrader()
        r = grader.grade("choice", user_answer="A", correct_answer="A")
        assert r.question_type == "objective"

    def test_fill_blank(self):
        from agent.grading import ObjectiveGrader
        grader = ObjectiveGrader()
        r = grader.grade("fill_blank", user_answer="牛顿", correct_answer="牛顿")
        assert r.is_correct is True

    def test_true_false(self):
        from agent.grading import ObjectiveGrader
        grader = ObjectiveGrader()
        r = grader.grade("true_false", user_answer="对", correct_answer="正确")
        assert r.is_correct is True

    def test_calculation(self):
        from agent.grading import ObjectiveGrader
        grader = ObjectiveGrader()
        r = grader.grade("calculation", question="1+1",
                         user_answer="2", correct_answer="2")
        assert r.score == 40.0

    def test_unknown_type(self):
        from agent.grading import ObjectiveGrader
        grader = ObjectiveGrader()
        r = grader.grade("unknown")
        assert r.score == 0
        assert "不支持" in r.feedback


# ======================== SubjectiveGrader ========================


def _make_mock_llm(json_data):
    """创建返回指定 JSON 的 mock LLM"""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = json.dumps(json_data, ensure_ascii=False)
    return mock_llm


class TestSubjectiveGraderInit:
    def test_init_with_client(self):
        from agent.grading import SubjectiveGrader
        mock_llm = MagicMock()
        grader = SubjectiveGrader(llm_client=mock_llm)
        assert grader.llm is mock_llm

    def test_init_without_client(self):
        from agent.grading import SubjectiveGrader
        with patch("llm.llm_client.LLMClient") as mock_client_cls:
            mock_client_cls.return_value = MagicMock()
            grader = SubjectiveGrader()
            assert grader.llm is not None

    def test_init_failure_graceful(self):
        from agent.grading import SubjectiveGrader
        with patch("llm.llm_client.LLMClient", side_effect=Exception("no config")):
            grader = SubjectiveGrader()
            assert grader.llm is None


class TestCallLLM:
    def test_call_llm_success(self):
        from agent.grading import SubjectiveGrader
        mock_llm = MagicMock()
        mock_llm.chat.return_value = '{"result": "ok"}'
        grader = SubjectiveGrader(llm_client=mock_llm)
        resp = grader._call_llm("test prompt")
        assert "result" in resp

    def test_call_llm_none(self):
        from agent.grading import SubjectiveGrader
        grader = SubjectiveGrader(llm_client=None)
        grader.llm = None
        resp = grader._call_llm("test")
        data = json.loads(resp)
        assert "error" in data

    def test_call_llm_exception(self):
        from agent.grading import SubjectiveGrader
        mock_llm = MagicMock()
        mock_llm.chat.side_effect = Exception("API error")
        grader = SubjectiveGrader(llm_client=mock_llm)
        resp = grader._call_llm("test")
        data = json.loads(resp)
        assert "error" in data


class TestGradeEnglishEssay:
    def test_success(self):
        from agent.grading import SubjectiveGrader
        mock_llm = _make_mock_llm({
            "scores": {"grammar": 85, "vocabulary": 78, "sentence_complexity": 72,
                       "content_relevance": 90, "overall": 82},
            "highlights": [{"original": "He go", "position": "第1句",
                           "error_type": "grammar", "correction": "He goes",
                           "explanation": "主谓一致"}],
            "corrections": [],
            "suggestions": ["多用复杂句", "注意时态"],
            "feedback": "整体不错，需注意语法细节",
        })
        grader = SubjectiveGrader(llm_client=mock_llm)
        r = grader.grade_english_essay("Write about...", "My essay...")
        assert r.score == 82.0
        assert r.subject == "英语作文"
        assert r.question_type == "subjective"
        assert len(r.highlights) == 1
        assert len(r.suggestions) == 2
        assert len(r.steps) == 4

    def test_json_parse_failure(self):
        from agent.grading import SubjectiveGrader
        mock_llm = MagicMock()
        mock_llm.chat.return_value = "not valid json at all"
        grader = SubjectiveGrader(llm_client=mock_llm)
        r = grader.grade_english_essay("Q", "A")
        assert r.score == 50.0  # default
        assert r.feedback is not None


class TestGradeChineseEssay:
    def test_success(self):
        from agent.grading import SubjectiveGrader
        mock_llm = _make_mock_llm({
            "content_inventory": {"famous_examples": ["鲁迅"], "life_examples": [], "paragraph_count": 3},
            "scores": {"立意": 75, "结构": 70, "语言": 75, "素材": 65, "逻辑": 60, "overall": 65},
            "idea_analysis": "观点明确但不够深刻",
            "structure_evaluation": "结构完整",
            "logic_errors": [{"original": "只要坚持就能成功", "error_type": "绝对化",
                             "explanation": "过于绝对", "correction": "坚持是成功的重要因素之一"}],
            "polish": [{"original": "很好", "improved": "表现出色", "reason": "用词更丰富"}],
            "suggestions": ["建议1"],
            "feedback": "总评内容",
        })
        grader = SubjectiveGrader(llm_client=mock_llm)
        r = grader.grade_chinese_essay("题目", "作文内容", grade_level="初中")
        assert r.score == 65.0
        assert r.subject == "语文作文"
        assert len(r.steps) == 5  # 五项评分步骤
        assert len(r.highlights) >= 1

    def test_json_parse_failure(self):
        from agent.grading import SubjectiveGrader
        mock_llm = MagicMock()
        mock_llm.chat.return_value = "invalid json"
        grader = SubjectiveGrader(llm_client=mock_llm)
        r = grader.grade_chinese_essay("Q", "A")
        assert r.score == 50.0


class TestGradeScienceProblem:
    def test_success(self):
        from agent.grading import SubjectiveGrader
        mock_llm = _make_mock_llm({
            "steps": [
                {"step_num": 1, "description": "审题", "max_score": 20, "student_score": 20,
                 "status": "correct", "error_type": "无", "feedback": "正确",
                 "correct_solution": "正确审题"},
                {"step_num": 2, "description": "列方程", "max_score": 30, "student_score": 15,
                 "status": "partial", "error_type": "公式用错", "feedback": "公式部分错误",
                 "correct_solution": "x+2=5"},
                {"step_num": 3, "description": "求解", "max_score": 50, "student_score": 50,
                 "status": "correct", "error_type": "无", "feedback": "正确",
                 "correct_solution": "x=3"},
            ],
            "total_score": 85,
            "error_summary": [{"type": "公式用错", "count": 1, "total_deduction": 15}],
            "suggestions": ["注意公式记忆"],
            "feedback": "总体还可以",
        })
        grader = SubjectiveGrader(llm_client=mock_llm)
        r = grader.grade_science_problem("解方程", "x=3", "x=3", subject="数学")
        assert r.score == 85.0
        assert r.subject == "数学"
        assert len(r.steps) == 3
        # 有1个 partial 步骤 → 1个 highlight
        assert len(r.highlights) == 1

    def test_no_errors_no_highlights(self):
        from agent.grading import SubjectiveGrader
        mock_llm = _make_mock_llm({
            "steps": [
                {"step_num": 1, "description": "求解", "max_score": 100, "student_score": 100,
                 "status": "correct", "error_type": "无", "feedback": "完全正确",
                 "correct_solution": "x=2"},
            ],
            "total_score": 100,
            "error_summary": [],
            "suggestions": [],
            "feedback": "完美",
        })
        grader = SubjectiveGrader(llm_client=mock_llm)
        r = grader.grade_science_problem("Q", "A", "R")
        assert r.score == 100.0
        assert r.highlights == []

    def test_json_parse_failure(self):
        from agent.grading import SubjectiveGrader
        mock_llm = MagicMock()
        mock_llm.chat.return_value = "not json"
        grader = SubjectiveGrader(llm_client=mock_llm)
        r = grader.grade_science_problem("Q", "A", "R")
        assert r.score == 0.0


class TestGradeGeneral:
    def test_success(self):
        from agent.grading import SubjectiveGrader
        mock_llm = _make_mock_llm({
            "key_points": [
                {"point": "要点1", "covered": True, "quality": "good",
                 "comment": "正确覆盖"},
                {"point": "要点2", "covered": True, "quality": "partial",
                 "comment": "部分正确"},
                {"point": "要点3", "covered": False, "quality": "missing",
                 "comment": "未提及"},
            ],
            "logic_score": 75,
            "clarity_score": 80,
            "overall": 70,
            "logic_issues": [{"original": "绝对化表述", "issue_type": "绝对化",
                             "explanation": "太绝对", "correction": "改为..."}],
            "strengths": ["逻辑清晰"],
            "weaknesses": ["审题不够深入"],
            "feedback": "总体合格",
            "suggestions": ["改进建议"],
        })
        grader = SubjectiveGrader(llm_client=mock_llm)
        r = grader.grade_general("题目", "作答", "参考答案", subject="历史")
        assert r.score == 70.0
        assert r.subject == "历史"
        assert len(r.steps) >= 3  # 3个key_points + 逻辑步骤
        assert len(r.highlights) >= 1  # logic_issues + weaknesses

    def test_missing_overall(self):
        """JSON 缺少 overall → 默认60分"""
        from agent.grading import SubjectiveGrader
        mock_llm = _make_mock_llm({"feedback": "评语内容"})
        grader = SubjectiveGrader(llm_client=mock_llm)
        r = grader.grade_general("Q", "A")
        assert r.score == 60.0

    def test_json_parse_failure(self):
        from agent.grading import SubjectiveGrader
        mock_llm = MagicMock()
        mock_llm.chat.return_value = "not json"
        grader = SubjectiveGrader(llm_client=mock_llm)
        r = grader.grade_general("Q", "A")
        assert r.score == 60.0  # fallback
        assert r.feedback is not None


class TestSubjectiveGradeDispatch:
    def test_english(self):
        from agent.grading import SubjectiveGrader
        mock_llm = _make_mock_llm({
            "scores": {"grammar": 80, "vocabulary": 80, "sentence_complexity": 80,
                       "content_relevance": 80, "overall": 80},
            "highlights": [], "corrections": [], "suggestions": [], "feedback": "ok",
        })
        grader = SubjectiveGrader(llm_client=mock_llm)
        r = grader.grade("英语", "Q", "A")
        assert r.subject == "英语作文"

    def test_chinese(self):
        from agent.grading import SubjectiveGrader
        mock_llm = _make_mock_llm({
            "content_inventory": {}, "scores": {"立意": 70, "结构": 70, "语言": 70,
                                                 "素材": 70, "逻辑": 70, "overall": 70},
            "idea_analysis": "", "structure_evaluation": "",
            "logic_errors": [], "polish": [], "suggestions": [], "feedback": "ok",
        })
        grader = SubjectiveGrader(llm_client=mock_llm)
        r = grader.grade("语文", "Q", "A")
        assert r.subject == "语文作文"

    def test_math(self):
        from agent.grading import SubjectiveGrader
        mock_llm = _make_mock_llm({
            "steps": [{"step_num": 1, "description": "解", "max_score": 100,
                       "student_score": 90, "status": "correct", "error_type": "无",
                       "feedback": "ok", "correct_solution": "x=1"}],
            "total_score": 90, "error_summary": [], "suggestions": [], "feedback": "ok",
        })
        grader = SubjectiveGrader(llm_client=mock_llm)
        r = grader.grade("数学", "Q", "A")
        assert r.score == 90.0

    def test_physics_is_science(self):
        from agent.grading import SubjectiveGrader
        mock_llm = _make_mock_llm({
            "steps": [{"step_num": 1, "description": "解", "max_score": 100,
                       "student_score": 80, "status": "correct", "error_type": "无",
                       "feedback": "ok", "correct_solution": "F=ma"}],
            "total_score": 80, "error_summary": [], "suggestions": [], "feedback": "ok",
        })
        grader = SubjectiveGrader(llm_client=mock_llm)
        r = grader.grade("物理", "Q", "A")
        assert r.score == 80.0

    def test_unknown_subject(self):
        from agent.grading import SubjectiveGrader
        mock_llm = _make_mock_llm({
            "key_points": [{"point": "p1", "covered": True, "quality": "good", "comment": ""}],
            "logic_score": 70, "clarity_score": 70, "overall": 70,
            "logic_issues": [], "strengths": [], "weaknesses": [],
            "feedback": "ok", "suggestions": [],
        })
        grader = SubjectiveGrader(llm_client=mock_llm)
        r = grader.grade("未知学科", "Q", "A")
        assert r.score == 70.0


# ======================== UnifiedGrader ========================


class TestUnifiedGraderAutoDetect:
    def test_short_abc_answer_is_choice(self):
        from agent.grading import UnifiedGrader
        grader = UnifiedGrader()
        grader.objective.grade = MagicMock(return_value=MagicMock(score=100))
        grader.auto_detect_and_grade(
            question="Q", user_answer="A", correct_answer="A",
            question_type="auto",
        )
        grader.objective.grade.assert_called_once_with(
            "choice", user_answer="A", correct_answer="A",
        )

    def test_subject_choice_dispatches_to_choice(self):
        from agent.grading import UnifiedGrader
        grader = UnifiedGrader()
        grader.objective.grade = MagicMock(return_value=MagicMock(score=100))
        grader.auto_detect_and_grade(
            question="Q", user_answer="A", correct_answer="A",
            subject="选择题", question_type="auto",
        )
        grader.objective.grade.assert_called_once()

    def test_subject_fill_blank(self):
        from agent.grading import UnifiedGrader
        grader = UnifiedGrader()
        grader.objective.grade = MagicMock(return_value=MagicMock(score=100))
        grader.auto_detect_and_grade(
            question="Q", user_answer="ans", correct_answer="ans",
            subject="填空题", question_type="auto",
        )
        grader.objective.grade.assert_called_once_with(
            "fill_blank", user_answer="ans", correct_answer="ans",
        )

    def test_subject_true_false(self):
        from agent.grading import UnifiedGrader
        grader = UnifiedGrader()
        grader.objective.grade = MagicMock(return_value=MagicMock(score=100))
        grader.auto_detect_and_grade(
            question="Q", user_answer="对", correct_answer="正确",
            subject="判断题", question_type="auto",
        )
        grader.objective.grade.assert_called_once()

    def test_math_with_steps_is_calculation(self):
        from agent.grading import UnifiedGrader
        grader = UnifiedGrader()
        with patch.object(grader, 'objective') as mock_obj:
            mock_obj.grade_calculation.return_value = MagicMock(score=85)
            grader.auto_detect_and_grade(
                question="解方程", user_answer="x=3", correct_answer="x=3",
                subject="数学", question_type="auto",
                user_steps="移项得x=3",
            )
            mock_obj.grade_calculation.assert_called_once()

    def test_math_without_steps_is_fill_blank(self):
        from agent.grading import UnifiedGrader
        grader = UnifiedGrader()
        grader.objective.grade = MagicMock(return_value=MagicMock(score=100))
        grader.auto_detect_and_grade(
            question="1+1=?", user_answer="2", correct_answer="2",
            subject="数学", question_type="auto",
        )
        grader.objective.grade.assert_called_once_with(
            "fill_blank", user_answer="2", correct_answer="2",
        )

    def test_defaults_to_subjective(self):
        from agent.grading import UnifiedGrader
        grader = UnifiedGrader()
        grader.subjective.grade = MagicMock(return_value=MagicMock(score=75))
        grader.auto_detect_and_grade(
            question="论述题", user_answer="作答", correct_answer="",
            subject="通用", question_type="auto",
        )
        grader.subjective.grade.assert_called_once()

    def test_explicit_choice_type(self):
        from agent.grading import UnifiedGrader
        grader = UnifiedGrader()
        grader.objective.grade = MagicMock(return_value=MagicMock(score=100))
        grader.auto_detect_and_grade(
            question="Q", user_answer="B", correct_answer="B",
            question_type="choice",
        )
        grader.objective.grade.assert_called_once()

    def test_explicit_subjective_type(self):
        from agent.grading import UnifiedGrader
        grader = UnifiedGrader()
        grader.subjective.grade = MagicMock(return_value=MagicMock(score=70))
        grader.auto_detect_and_grade(
            question="Q", user_answer="A", correct_answer="R",
            subject="语文", question_type="subjective",
        )
        grader.subjective.grade.assert_called_once()
