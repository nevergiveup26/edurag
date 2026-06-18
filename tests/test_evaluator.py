"""evaluation.evaluator RAG评估器测试"""
import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from core.models import DocumentChunk, RetrievalResult


# ═══════════════════════════════════ helpers ═══════════════════════════════════

def _make_chunk(doc_id, content="test content", chunk_id="c1", score=0.8):
    chunk = DocumentChunk(
        chunk_id=chunk_id, doc_id=doc_id, content=content, metadata={},
    )
    return RetrievalResult(chunk=chunk, score=score, source="vector")


def _make_eval_sample(**kwargs):
    from evaluation.evaluator import EvalSample
    defaults = {
        "query": "test query",
        "expected_answer": "expected answer",
        "expected_keywords": ["keyword1", "keyword2"],
        "relevant_doc_ids": ["d1", "d2"],
        "category": "math",
    }
    defaults.update(kwargs)
    return EvalSample(**defaults)


# ═══════════════════════════════ dataclasses ══════════════════════════════════

class TestEvalSample:
    def test_default_category(self):
        from evaluation.evaluator import EvalSample
        s = EvalSample(query="q", expected_answer="a",
                       expected_keywords=[], relevant_doc_ids=[])
        assert s.category == "general"

    def test_all_fields(self):
        from evaluation.evaluator import EvalSample
        s = EvalSample(query="q", expected_answer="a",
                       expected_keywords=["k1"], relevant_doc_ids=["d1"],
                       category="math")
        assert s.query == "q"
        assert s.expected_answer == "a"
        assert s.expected_keywords == ["k1"]
        assert s.relevant_doc_ids == ["d1"]
        assert s.category == "math"


class TestRetrievalMetrics:
    def test_all_defaults_zero(self):
        from evaluation.evaluator import RetrievalMetrics
        m = RetrievalMetrics()
        assert m.precision == 0.0
        assert m.recall == 0.0
        assert m.f1_score == 0.0
        assert m.mrr == 0.0
        assert m.ndcg == 0.0
        assert m.hit_rate == 0.0

    def test_custom_values(self):
        from evaluation.evaluator import RetrievalMetrics
        m = RetrievalMetrics(precision=0.8, recall=0.6, f1_score=0.7, mrr=0.5,
                             ndcg=0.9, hit_rate=1.0)
        assert m.precision == 0.8


class TestGenerationMetrics:
    def test_all_defaults(self):
        from evaluation.evaluator import GenerationMetrics
        m = GenerationMetrics()
        assert m.bleu_1 == 0.0
        assert m.bleu_2 == 0.0
        assert m.rouge_l == 0.0
        assert m.keyword_match_rate == 0.0
        assert m.llm_score == 0.0
        assert m.answer_length == 0

    def test_custom_values(self):
        from evaluation.evaluator import GenerationMetrics
        m = GenerationMetrics(bleu_1=0.5, bleu_2=0.3, rouge_l=0.6,
                              keyword_match_rate=0.8, llm_score=0.9,
                              answer_length=100, avg_execution_time=1.5)
        assert m.bleu_1 == 0.5
        assert m.avg_execution_time == 1.5


class TestEvalReport:
    def test_defaults(self):
        from evaluation.evaluator import EvalReport
        r = EvalReport()
        assert r.sample_count == 0
        assert r.total_time == 0.0
        assert r.sample_reports == []
        assert r.charts == {}

    def test_custom(self):
        from evaluation.evaluator import EvalReport, RetrievalMetrics, GenerationMetrics
        rm = RetrievalMetrics(precision=0.9)
        gm = GenerationMetrics(bleu_1=0.7)
        r = EvalReport(retrieval=rm, generation=gm, sample_count=5,
                       total_time=10.0, charts={"a": "b"})
        assert r.retrieval.precision == 0.9
        assert r.generation.bleu_1 == 0.7
        assert r.sample_count == 5


# ═════════════════════════════ text metrics ═══════════════════════════════════

class TestTokenizeJieba:
    def test_with_jieba(self):
        from evaluation.evaluator import _tokenize_jieba
        tokens = _tokenize_jieba("测试文本内容")
        assert len(tokens) >= 1
        assert "测试" in tokens or "文本" in tokens or "内容" in tokens

    def test_without_jieba_fallback(self):
        import sys
        with patch.dict(sys.modules, {"jieba": None}):
            # Force reload to pick up missing jieba
            import evaluation.evaluator as mod
            original_jieba = sys.modules.get("jieba")
            sys.modules["jieba"] = None
            try:
                tokens = mod._tokenize_jieba("hello world")
                assert tokens == list("hello world")
            finally:
                if original_jieba is not None:
                    sys.modules["jieba"] = original_jieba
                else:
                    sys.modules.pop("jieba", None)


class TestCalcBleu:
    def test_normal(self):
        from evaluation.evaluator import _calc_bleu
        scores = _calc_bleu("这是参考答案", "这是学生答案")
        assert "bleu_1" in scores
        assert "bleu_2" in scores
        assert 0 <= scores["bleu_1"] <= 1.0

    def test_perfect_match(self):
        from evaluation.evaluator import _calc_bleu
        scores = _calc_bleu("完全相同的内容", "完全相同的内容")
        assert scores["bleu_1"] > 0.5

    def test_empty_candidate(self):
        from evaluation.evaluator import _calc_bleu
        scores = _calc_bleu("reference", "")
        assert scores == {"bleu_1": 0.0, "bleu_2": 0.0}

    def test_empty_reference(self):
        from evaluation.evaluator import _calc_bleu
        scores = _calc_bleu("", "candidate")
        assert scores == {"bleu_1": 0.0, "bleu_2": 0.0}

    def test_candidate_too_short_for_bigram(self):
        from evaluation.evaluator import _calc_bleu
        scores = _calc_bleu("完整的参考答案", "单")
        assert scores["bleu_2"] == 0.0


class TestCalcRougeL:
    def test_normal(self):
        from evaluation.evaluator import _calc_rouge_l
        score = _calc_rouge_l("参考答案内容", "学生答案内容")
        assert 0 <= score <= 1.0

    def test_empty_candidate(self):
        from evaluation.evaluator import _calc_rouge_l
        assert _calc_rouge_l("reference", "") == 0.0

    def test_empty_reference(self):
        from evaluation.evaluator import _calc_rouge_l
        assert _calc_rouge_l("", "candidate") == 0.0

    def test_perfect_match(self):
        from evaluation.evaluator import _calc_rouge_l
        assert _calc_rouge_l("完全一样", "完全一样") == 1.0

    def test_no_overlap(self):
        from evaluation.evaluator import _calc_rouge_l
        assert _calc_rouge_l("AAAA", "BBBB") == 0.0


class TestLLMJudgeCorrectness:
    def test_no_expected_returns_negative(self):
        from evaluation.evaluator import _llm_judge_correctness
        assert _llm_judge_correctness("", "answer") == -1.0

    def test_no_generated_returns_negative(self):
        from evaluation.evaluator import _llm_judge_correctness
        assert _llm_judge_correctness("expected", "") == -1.0

    def test_success(self):
        from evaluation.evaluator import _llm_judge_correctness
        mock_llm = MagicMock()
        mock_llm.generate.return_value = '{"score": 8, "correct": true, "reason": "基本正确"}'
        score = _llm_judge_correctness("expected", "answer", "query", llm_client=mock_llm)
        assert score == 0.8  # 8/10

    def test_no_llm_client_fallback(self):
        from evaluation.evaluator import _llm_judge_correctness
        mock_llm = MagicMock()
        mock_llm.generate.return_value = '{"score": 6, "correct": false, "reason": "部分错误"}'
        with patch("llm.llm_client.get_fast_llm", return_value=mock_llm):
            score = _llm_judge_correctness("expected", "answer")
            assert score == 0.6

    def test_llm_client_import_error(self):
        from evaluation.evaluator import _llm_judge_correctness
        with patch("llm.llm_client.get_fast_llm", side_effect=Exception("no config")):
            score = _llm_judge_correctness("expected", "answer")
            assert score == -1.0

    def test_json_with_markdown_wrapper(self):
        from evaluation.evaluator import _llm_judge_correctness
        mock_llm = MagicMock()
        mock_llm.generate.return_value = '```json\n{"score": 10, "correct": true, "reason": "完全正确"}\n```'
        score = _llm_judge_correctness("expected", "answer", llm_client=mock_llm)
        assert score == 1.0

    def test_llm_failure_returns_negative(self):
        from evaluation.evaluator import _llm_judge_correctness
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = Exception("timeout")
        score = _llm_judge_correctness("expected", "answer", llm_client=mock_llm)
        assert score == -1.0

    def test_invalid_json_returns_negative(self):
        from evaluation.evaluator import _llm_judge_correctness
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "not json at all"
        score = _llm_judge_correctness("expected", "answer", llm_client=mock_llm)
        assert score == -1.0


# ═══════════════════════════ RAGEvaluator init ════════════════════════════════

class TestRAGEvaluatorInit:
    def test_default_init(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        assert ev.samples == []
        assert ev.use_llm_judge is False
        assert ev._llm_client is None

    def test_init_with_samples(self):
        from evaluation.evaluator import RAGEvaluator
        sample = _make_eval_sample()
        ev = RAGEvaluator(samples=[sample], use_llm_judge=True)
        assert len(ev.samples) == 1
        assert ev.use_llm_judge is True


class TestRAGEvaluatorLLMClient:
    def test_property_creates_client(self):
        from evaluation.evaluator import RAGEvaluator
        mock_llm = MagicMock()
        with patch("llm.llm_client.get_fast_llm", return_value=mock_llm):
            ev = RAGEvaluator()
            client = ev.llm_client
            assert client is mock_llm

    def test_property_cached(self):
        from evaluation.evaluator import RAGEvaluator
        mock_llm = MagicMock()
        with patch("llm.llm_client.get_fast_llm", return_value=mock_llm):
            ev = RAGEvaluator()
            c1 = ev.llm_client
            c2 = ev.llm_client
            assert c1 is c2

    def test_property_import_error(self):
        from evaluation.evaluator import RAGEvaluator
        with patch("llm.llm_client.get_fast_llm", side_effect=Exception("fail")):
            ev = RAGEvaluator()
            assert ev.llm_client is None


# ═════════════════════════ evaluate_retrieval ═════════════════════════════════

class TestEvaluateRetrieval:
    def test_empty_results(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        sample = _make_eval_sample()
        metrics = ev.evaluate_retrieval([], sample)
        assert metrics.precision == 0.0
        assert metrics.hit_rate == 0.0

    def test_doc_id_match_perfect(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        sample = _make_eval_sample(relevant_doc_ids=["d1", "d2"])
        results = [_make_chunk("d1"), _make_chunk("d2")]
        metrics = ev.evaluate_retrieval(results, sample)
        assert metrics.precision == 1.0
        assert metrics.recall == 1.0
        assert metrics.hit_rate == 1.0

    def test_doc_id_partial_match(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        sample = _make_eval_sample(relevant_doc_ids=["d1", "d2", "d3"])
        results = [_make_chunk("d1"), _make_chunk("d4")]
        metrics = ev.evaluate_retrieval(results, sample)
        assert metrics.precision == 0.5
        assert metrics.recall == pytest.approx(1 / 3)

    def test_keyword_fallback(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        sample = _make_eval_sample(relevant_doc_ids=[],
                                   expected_keywords=["勾股定理", "三角形"])
        results = [
            _make_chunk("d1", content="勾股定理是重要的数学定理"),
            _make_chunk("d2", content="其他内容"),
        ]
        metrics = ev.evaluate_retrieval(results, sample)
        assert metrics.precision == 0.5  # only first result matches
        assert metrics.hit_rate == 1.0

    def test_no_keywords_no_doc_ids(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        sample = _make_eval_sample(relevant_doc_ids=[], expected_keywords=[])
        results = [_make_chunk("d1"), _make_chunk("d2")]
        metrics = ev.evaluate_retrieval(results, sample)
        assert metrics.precision == 0.0

    def test_top_k_limits(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        sample = _make_eval_sample(relevant_doc_ids=["d1", "d2", "d3"])
        results = [_make_chunk("d1"), _make_chunk("d4"), _make_chunk("d5")]
        metrics = ev.evaluate_retrieval(results, sample, top_k=1)
        assert metrics.precision == 1.0  # only first within top_k=1

    def test_mrr_first_position(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        sample = _make_eval_sample(relevant_doc_ids=["d1"])
        results = [_make_chunk("d1")]
        metrics = ev.evaluate_retrieval(results, sample)
        assert metrics.mrr == 1.0

    def test_mrr_second_position(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        sample = _make_eval_sample(relevant_doc_ids=["d2"])
        results = [_make_chunk("d1"), _make_chunk("d2")]
        metrics = ev.evaluate_retrieval(results, sample)
        assert metrics.mrr == 0.5

    def test_mrr_no_match(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        sample = _make_eval_sample(relevant_doc_ids=["d99"])
        results = [_make_chunk("d1"), _make_chunk("d2")]
        metrics = ev.evaluate_retrieval(results, sample)
        assert metrics.mrr == 0.0


class TestCalcNDCG:
    def test_perfect_ranking(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        ndcg = ev._calc_ndcg([True, True, False, False], 4)
        assert ndcg == 1.0

    def test_all_irrelevant(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        ndcg = ev._calc_ndcg([False, False, False], 3)
        assert ndcg == 0.0

    def test_partial(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        ndcg = ev._calc_ndcg([True, False, True], 3)
        assert 0 < ndcg < 1.0


# ═════════════════════════ evaluate_generation ════════════════════════════════

class TestEvaluateGeneration:
    def test_basic(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        sample = _make_eval_sample(
            expected_answer="正确答案内容",
            expected_keywords=["正确", "答案"],
        )
        metrics = ev.evaluate_generation("学生写出了正确答案内容", sample)
        assert metrics.bleu_1 > 0
        assert metrics.rouge_l > 0
        assert metrics.keyword_match_rate == 1.0
        assert metrics.answer_length > 0

    def test_no_keywords(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        sample = _make_eval_sample(expected_keywords=[])
        metrics = ev.evaluate_generation("任意答案", sample)
        assert metrics.keyword_match_rate == 0.0

    def test_no_expected_answer(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        sample = _make_eval_sample(expected_answer="")
        metrics = ev.evaluate_generation("答案", sample)
        assert metrics.bleu_1 == 0.0
        assert metrics.rouge_l == 0.0

    def test_with_llm_judge_disabled(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator(use_llm_judge=False)
        sample = _make_eval_sample(expected_answer="正确答案")
        metrics = ev.evaluate_generation("学生答案", sample)
        assert metrics.llm_score == -1.0

    def test_with_llm_judge_enabled(self):
        from evaluation.evaluator import RAGEvaluator
        mock_llm = MagicMock()
        mock_llm.generate.return_value = '{"score": 7, "correct": true, "reason": "ok"}'
        ev = RAGEvaluator(use_llm_judge=True)
        ev._llm_client = mock_llm
        sample = _make_eval_sample(expected_answer="正确答案")
        metrics = ev.evaluate_generation("学生答案", sample)
        assert metrics.llm_score == 0.7

    def test_with_exec_time(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        sample = _make_eval_sample()
        metrics = ev.evaluate_generation("answer", sample, exec_time=2.5)
        assert metrics.avg_execution_time == 2.5


# ════════════════════════ run_full_evaluation ═════════════════════════════════

class TestRunFullEvaluation:
    def test_empty_samples(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator(samples=[])
        query_func = MagicMock()
        report = ev.run_full_evaluation(query_func)
        assert report.sample_count == 0
        query_func.assert_not_called()

    def test_success(self):
        from evaluation.evaluator import RAGEvaluator
        sample = _make_eval_sample()
        ev = RAGEvaluator(samples=[sample])

        mock_sources = [_make_chunk("d1", content="keyword1 在这里")]
        mock_response = MagicMock()
        mock_response.sources = mock_sources
        mock_response.answer = "学生答案包含keyword1和keyword2"

        query_func = MagicMock(return_value=mock_response)
        report = ev.run_full_evaluation(query_func)
        assert report.sample_count == 1
        assert report.total_time >= 0

    def test_query_func_raises_exception(self):
        from evaluation.evaluator import RAGEvaluator
        sample = _make_eval_sample()
        ev = RAGEvaluator(samples=[sample])
        query_func = MagicMock(side_effect=RuntimeError("timeout"))
        report = ev.run_full_evaluation(query_func)
        # sample_count counts all samples including errors
        assert report.sample_count == 1
        assert len(report.sample_reports) == 1
        assert "error" in report.sample_reports[0]

    def test_multiple_samples(self):
        from evaluation.evaluator import RAGEvaluator
        samples = [_make_eval_sample(query=f"q{i}") for i in range(3)]
        ev = RAGEvaluator(samples=samples)

        mock_response = MagicMock()
        mock_response.sources = [_make_chunk("d1")]
        mock_response.answer = "answer text"
        query_func = MagicMock(return_value=mock_response)
        report = ev.run_full_evaluation(query_func)
        assert report.sample_count == 3

    def test_response_without_sources_attr(self):
        from evaluation.evaluator import RAGEvaluator
        sample = _make_eval_sample()
        ev = RAGEvaluator(samples=[sample])
        mock_response = MagicMock(spec=[])  # no sources/answer attr
        query_func = MagicMock(return_value=mock_response)
        report = ev.run_full_evaluation(query_func)
        assert report.sample_count == 1

    def test_no_matplotlib(self):
        from evaluation.evaluator import RAGEvaluator
        sample = _make_eval_sample()
        ev = RAGEvaluator(samples=[sample])
        mock_response = MagicMock()
        mock_response.sources = []
        mock_response.answer = "answer"
        query_func = MagicMock(return_value=mock_response)

        with patch("evaluation.evaluator.HAS_MATPLOTLIB", False):
            report = ev.run_full_evaluation(query_func)
            assert report.charts == {}


# ═══════════════════════ run_full_evaluation_stream ═══════════════════════════

class TestRunFullEvaluationStream:
    def test_empty_samples(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator(samples=[])
        events = list(ev.run_full_evaluation_stream(MagicMock()))
        assert len(events) == 1
        assert events[0]["event"] == "complete"
        assert events[0]["sample_count"] == 0

    def test_progress_and_complete(self):
        from evaluation.evaluator import RAGEvaluator
        sample = _make_eval_sample()
        ev = RAGEvaluator(samples=[sample])
        mock_response = MagicMock()
        mock_response.sources = [_make_chunk("d1")]
        mock_response.answer = "answer text"
        query_func = MagicMock(return_value=mock_response)

        events = list(ev.run_full_evaluation_stream(query_func))
        event_types = [e["event"] for e in events]
        assert "progress" in event_types
        assert "sample_done" in event_types
        assert "complete" in event_types

        complete = events[-1]
        assert complete["event"] == "complete"
        assert "retrieval" in complete
        assert "generation" in complete

    def test_cancel(self):
        import threading
        from evaluation.evaluator import RAGEvaluator
        samples = [_make_eval_sample(query=f"q{i}") for i in range(5)]
        ev = RAGEvaluator(samples=samples)

        cancel_event = threading.Event()
        cancel_event.set()

        events = list(ev.run_full_evaluation_stream(
            MagicMock(), cancel_event=cancel_event))
        assert events[0]["event"] == "cancelled"

    def test_query_error(self):
        from evaluation.evaluator import RAGEvaluator
        sample = _make_eval_sample()
        ev = RAGEvaluator(samples=[sample])
        query_func = MagicMock(side_effect=RuntimeError("fail"))

        events = list(ev.run_full_evaluation_stream(query_func))
        sample_done = [e for e in events if e["event"] == "sample_done"]
        assert len(sample_done) == 1
        assert "error" in sample_done[0]

    def test_cumulative_metrics_in_sample_done(self):
        from evaluation.evaluator import RAGEvaluator
        sample = _make_eval_sample()
        ev = RAGEvaluator(samples=[sample])
        mock_response = MagicMock()
        mock_response.sources = [_make_chunk("d1")]
        mock_response.answer = "answer with keyword1"
        query_func = MagicMock(return_value=mock_response)

        events = list(ev.run_full_evaluation_stream(query_func))
        sample_done = [e for e in events if e["event"] == "sample_done" and "sample" in e]
        assert len(sample_done) == 1
        assert "cumulative_metrics" in sample_done[0]
        assert "retrieval" in sample_done[0]["cumulative_metrics"]

    def test_no_matplotlib(self):
        from evaluation.evaluator import RAGEvaluator
        sample = _make_eval_sample()
        ev = RAGEvaluator(samples=[sample])
        mock_response = MagicMock()
        mock_response.sources = []
        mock_response.answer = "a"
        query_func = MagicMock(return_value=mock_response)

        with patch("evaluation.evaluator.HAS_MATPLOTLIB", False):
            events = list(ev.run_full_evaluation_stream(query_func))
            complete = events[-1]
            assert complete["charts"] == {}

    def test_progress_callback_called(self):
        from evaluation.evaluator import RAGEvaluator
        sample = _make_eval_sample()
        ev = RAGEvaluator(samples=[sample])
        mock_response = MagicMock()
        mock_response.sources = []
        mock_response.answer = "a"
        query_func = MagicMock(return_value=mock_response)

        callback = MagicMock()
        events = list(ev.run_full_evaluation_stream(query_func, progress_callback=callback))
        assert len(events) >= 2


# ═══════════════════════════ generate_charts ══════════════════════════════════

class TestGenerateCharts:
    def test_has_matplotlib(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        reports = [
            {"query": "q1", "precision": 0.8, "recall": 0.6, "f1": 0.7,
             "mrr": 0.5, "bleu_1": 0.4, "rouge_l": 0.5,
             "keyword_match_rate": 0.9, "execution_time": 1.2},
        ]
        with patch("evaluation.evaluator.HAS_MATPLOTLIB", True):
            charts = ev.generate_charts(reports)
            assert "retrieval_metrics" in charts
            assert "generation_metrics" in charts
            assert "execution_time" in charts

    def test_empty_reports_handled(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        charts = ev.generate_charts([])
        # Empty reports still produce chart images (albeit with zero values)
        assert "retrieval_metrics" in charts

    def test_font_fallback(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        reports = [{"query": "q1", "precision": 0.5, "recall": 0.5, "f1": 0.5,
                    "mrr": 0.5, "bleu_1": 0.3, "rouge_l": 0.4,
                    "keyword_match_rate": 0.6, "execution_time": 0.5}]
        # SimHei may not be available on Windows, but should fallback
        with patch("evaluation.evaluator.HAS_MATPLOTLIB", True):
            charts = ev.generate_charts(reports)
            assert "retrieval_metrics" in charts

    def test_more_than_20_samples(self):
        from evaluation.evaluator import RAGEvaluator
        ev = RAGEvaluator()
        reports = [
            {"query": f"q{i}", "precision": 0.5, "recall": 0.5, "f1": 0.5,
             "mrr": 0.5, "bleu_1": 0.3, "rouge_l": 0.4,
             "keyword_match_rate": 0.6, "execution_time": 0.5}
            for i in range(25)
        ]
        with patch("evaluation.evaluator.HAS_MATPLOTLIB", True):
            charts = ev.generate_charts(reports)
            assert "retrieval_metrics" in charts


# ═══════════════════════════ print_report ═════════════════════════════════════

class TestPrintReport:
    def test_basic(self, capsys):
        from evaluation.evaluator import RAGEvaluator, EvalReport
        ev = RAGEvaluator()
        report = EvalReport(sample_count=1, total_time=1.5,
                           sample_reports=[{
                               "query": "test query",
                               "bleu_1": 0.5, "rouge_l": 0.6,
                               "keyword_match_rate": 0.8,
                               "precision": 0.9, "recall": 0.7,
                               "execution_time": 1.2,
                           }])
        ev.print_report(report)
        captured = capsys.readouterr()
        assert "EduRAG" in captured.out
        assert "test query" in captured.out

    def test_with_llm_score(self, capsys):
        from evaluation.evaluator import RAGEvaluator, EvalReport, GenerationMetrics
        ev = RAGEvaluator()
        gm = GenerationMetrics(llm_score=0.85)
        report = EvalReport(generation=gm, sample_reports=[])
        ev.print_report(report)
        captured = capsys.readouterr()
        assert "LLM评判分数" in captured.out
