"""core.models 和 core.config_manager 测试"""
import os
import pytest
from unittest.mock import MagicMock, patch


# ═══════════════════════════ core.models ══════════════════════════════════════

class TestRetrievalStrategy:
    def test_values(self):
        from core.models import RetrievalStrategy
        assert RetrievalStrategy.DIRECT.value == "direct"
        assert RetrievalStrategy.HYDE.value == "hyde"
        assert RetrievalStrategy.SUB_QUERY.value == "sub_query"
        assert RetrievalStrategy.BACKTRACK.value == "backtrack"
        assert RetrievalStrategy.MULTIMODAL.value == "multimodal"


class TestContentType:
    def test_values(self):
        from core.models import ContentType
        assert ContentType.TEXT.value == "text"
        assert ContentType.IMAGE.value == "image"
        assert ContentType.TABLE.value == "table"
        assert ContentType.MIXED.value == "mixed"


class TestRouterType:
    def test_values(self):
        from core.models import RouterType
        assert RouterType.RULE.value == "rule"
        assert RouterType.SIMILARITY.value == "similarity"
        assert RouterType.LLM.value == "llm"


class TestDocument:
    def test_defaults(self):
        from core.models import Document
        doc = Document(content="test")
        assert doc.doc_id is None
        assert doc.title is None
        assert doc.source is None
        assert doc.metadata == {}
        assert doc.created_at is not None

    def test_explicit_created_at(self):
        from core.models import Document
        from datetime import datetime
        dt = datetime(2024, 1, 1)
        doc = Document(content="test", created_at=dt)
        assert doc.created_at == dt

    def test_full_fields(self):
        from core.models import Document
        doc = Document(content="c", doc_id="d1", title="t",
                       source="s", metadata={"k": "v"})
        assert doc.doc_id == "d1"
        assert doc.metadata == {"k": "v"}


class TestDocumentChunk:
    def test_defaults(self):
        from core.models import DocumentChunk
        chunk = DocumentChunk(content="test")
        assert chunk.chunk_id is None
        assert chunk.doc_id is None
        assert chunk.embedding is None
        assert chunk.metadata == {}
        assert chunk.score == 0.0

    def test_with_embedding(self):
        from core.models import DocumentChunk
        chunk = DocumentChunk(content="c", embedding=[0.1, 0.2],
                              chunk_id="c1", doc_id="d1", score=0.8)
        assert chunk.embedding == [0.1, 0.2]
        assert chunk.score == 0.8


class TestRetrievalResult:
    def test_basic(self):
        from core.models import DocumentChunk, RetrievalResult
        chunk = DocumentChunk(content="c", chunk_id="c1")
        result = RetrievalResult(chunk=chunk, score=0.9, source="vector")
        assert result.chunk.chunk_id == "c1"
        assert result.score == 0.9
        assert result.source == "vector"


class TestQueryRequest:
    def test_defaults(self):
        from core.models import QueryRequest, RetrievalStrategy, RouterType
        req = QueryRequest(query="test")
        assert req.query == "test"
        assert req.strategy == RetrievalStrategy.DIRECT
        assert req.router_type == RouterType.SIMILARITY
        assert req.top_k == 5
        assert req.user_id is None
        assert req.history == []
        assert req.enable_self_rag is True
        assert req.enable_multi_query is True
        assert req.metadata_filter == {}

    def test_custom(self):
        from core.models import QueryRequest
        req = QueryRequest(
            query="q", top_k=10, user_id="u1",
            history=[{"role": "user", "content": "hi"}],
            kb_id="kb1", metadata_filter={"subject": "数学"},
            enable_self_rag=False,
        )
        assert req.top_k == 10
        assert req.metadata_filter == {"subject": "数学"}
        assert req.enable_self_rag is False


class TestQueryResponse:
    def test_defaults(self):
        from core.models import QueryResponse
        resp = QueryResponse(answer="answer")
        assert resp.answer == "answer"
        assert resp.sources == []
        assert resp.strategy_used == ""
        assert resp.execution_time == 0.0

    def test_to_dict_empty(self):
        from core.models import QueryResponse
        resp = QueryResponse(answer="a", strategy_used="hybrid",
                             execution_time=1.0, conversation_id="c1")
        d = resp.to_dict()
        assert d["answer"] == "a"
        assert d["sources"] == []
        assert d["strategy_used"] == "hybrid"
        assert d["execution_time"] == 1.0
        assert d["conversation_id"] == "c1"

    def test_to_dict_with_sources(self):
        from core.models import DocumentChunk, RetrievalResult, QueryResponse
        chunk = DocumentChunk(content="source content", chunk_id="c1",
                              doc_id="d1", metadata={"page": 1})
        src = RetrievalResult(chunk=chunk, score=0.9, source="vector")
        resp = QueryResponse(answer="a", sources=[src])
        d = resp.to_dict()
        assert len(d["sources"]) == 1
        assert d["sources"][0]["content"] == "source content"
        assert d["sources"][0]["score"] == 0.9
        assert d["sources"][0]["metadata"] == {"page": 1}


class TestFAQItem:
    def test_defaults(self):
        from core.models import FAQItem
        faq = FAQItem(question="q", answer="a")
        assert faq.category is None
        assert faq.tags == []
        assert faq.embedding is None
        assert faq.faq_id is None

    def test_full(self):
        from core.models import FAQItem
        faq = FAQItem(question="q", answer="a", category="math",
                      tags=["代数"], embedding=[0.1], faq_id="f1")
        assert faq.tags == ["代数"]
        assert faq.faq_id == "f1"


class TestMultiModalChunk:
    def test_inherits_document_chunk(self):
        from core.models import MultiModalChunk, DocumentChunk
        mm = MultiModalChunk(content="c", chunk_id="c1")
        assert isinstance(mm, DocumentChunk)
        assert mm.content_type == "text"
        assert mm.image_path is None
        assert mm.image_base64 is None
        assert mm.table_data is None

    def test_image_fields(self):
        from core.models import MultiModalChunk
        mm = MultiModalChunk(content="c", content_type="image",
                             image_path="/img/test.png",
                             image_description="A test image")
        assert mm.content_type == "image"
        assert mm.image_path == "/img/test.png"
        assert mm.image_description == "A test image"


class TestAgentMessage:
    def test_defaults(self):
        from core.models import AgentMessage
        msg = AgentMessage(role="user", content="hello")
        assert msg.role == "user"
        assert msg.tool_calls is None
        assert msg.tool_call_id is None

    def test_to_dict(self):
        from core.models import AgentMessage
        msg = AgentMessage(role="assistant", content="result",
                           tool_calls=[{"name": "search"}],
                           tool_call_id="tc1")
        d = msg.to_dict()
        assert d["role"] == "assistant"
        assert d["tool_calls"] == [{"name": "search"}]
        assert d["tool_call_id"] == "tc1"


class TestToolCall:
    def test_defaults(self):
        from core.models import ToolCall
        tc = ToolCall(name="search", arguments={"q": "test"})
        assert tc.name == "search"
        assert tc.arguments == {"q": "test"}
        assert tc.call_id is None
        assert tc.result is None

    def test_full(self):
        from core.models import ToolCall
        tc = ToolCall(name="calc", arguments={"expr": "1+1"},
                      call_id="c1", result="2")
        assert tc.call_id == "c1"
        assert tc.result == "2"


class TestAgentStep:
    def test_defaults(self):
        from core.models import AgentStep
        step = AgentStep(step_index=0)
        assert step.step_index == 0
        assert step.thought == ""
        assert step.action is None
        assert step.observation == ""
        assert step.finished is False

    def test_with_action(self):
        from core.models import AgentStep, ToolCall
        tc = ToolCall(name="search", arguments={"q": "x"})
        step = AgentStep(step_index=1, thought="thinking...",
                         action=tc, observation="found", finished=True)
        assert step.action.name == "search"
        assert step.finished is True


class TestAgentResponse:
    def test_defaults(self):
        from core.models import AgentResponse
        resp = AgentResponse(answer="answer")
        assert resp.answer == "answer"
        assert resp.steps == []
        assert resp.tool_calls == []
        assert resp.strategy_used == "agentic"
        assert resp.execution_time == 0.0

    def test_to_dict_empty(self):
        from core.models import AgentResponse
        resp = AgentResponse(answer="a", execution_time=2.0, conversation_id="c1")
        d = resp.to_dict()
        assert d["answer"] == "a"
        assert d["steps"] == []
        assert d["tool_calls_count"] == 0
        assert d["execution_time"] == 2.0

    def test_to_dict_with_steps(self):
        from core.models import AgentResponse, AgentStep, ToolCall
        tc = ToolCall(name="search", arguments={"q": "x"})
        step = AgentStep(step_index=0, thought="think", action=tc,
                         observation="result")
        resp = AgentResponse(answer="a", steps=[step], tool_calls=[tc])
        d = resp.to_dict()
        assert len(d["steps"]) == 1
        assert d["steps"][0]["thought"] == "think"
        assert d["steps"][0]["action"] == "search"
        assert d["tool_calls_count"] == 1


# ═════════════════════════ core.config_manager ════════════════════════════════

class TestResolveEnv:
    def test_no_env_vars(self):
        from core.config_manager import _resolve_env
        assert _resolve_env("plain_value") == "plain_value"

    def test_env_var_substitution(self):
        from core.config_manager import _resolve_env
        with patch.dict(os.environ, {"MY_VAR": "resolved_value"}):
            assert _resolve_env("${MY_VAR}") == "resolved_value"

    def test_env_var_with_fallback(self):
        from core.config_manager import _resolve_env
        assert _resolve_env("${MISSING_VAR:default}") == "default"

    def test_env_var_empty_fallback(self):
        from core.config_manager import _resolve_env
        assert _resolve_env("${MISSING_VAR}") == ""

    def test_mixed_content(self):
        from core.config_manager import _resolve_env
        with patch.dict(os.environ, {"HOST": "localhost"}):
            result = _resolve_env("${HOST}:8080/path")
            assert result == "localhost:8080/path"

    def test_non_string(self):
        from core.config_manager import _resolve_env
        assert _resolve_env(123) == 123

    def test_empty_string(self):
        from core.config_manager import _resolve_env
        assert _resolve_env("") == ""


# ── ConfigManager fixture to prevent singleton pollution ──

@pytest.fixture(autouse=True)
def _reset_config_manager():
    """每个测试前后重置 ConfigManager 单例，防止 mock 污染"""
    import core.config_manager as cm
    cm.ConfigManager._instance = None
    cm.ConfigManager._config = None
    yield
    cm.ConfigManager._instance = None
    cm.ConfigManager._config = None


class TestConfigManagerSingleton:
    def test_same_instance(self):
        import core.config_manager as cm
        mock_parser = MagicMock()
        with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser):
            c1 = cm.ConfigManager("/fake/path.ini")
            c2 = cm.ConfigManager("/other/path.ini")
            assert c1 is c2


class TestConfigManagerGet:
    def test_get_success(self):
        import core.config_manager as cm
        mock_parser = MagicMock()
        mock_parser.get.return_value = "test_value"
        with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser):
            mgr = cm.ConfigManager("/fake/path.ini")
            assert mgr.get("section", "key") == "test_value"

    def test_get_with_env_var(self):
        import core.config_manager as cm
        mock_parser = MagicMock()
        mock_parser.get.return_value = "${DB_HOST}"
        with patch.dict(os.environ, {"DB_HOST": "prod-db"}):
            with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser):
                mgr = cm.ConfigManager("/fake/path.ini")
                assert mgr.get("db", "host") == "prod-db"

    def test_get_fallback_on_missing_section(self):
        import core.config_manager as cm
        mock_parser = MagicMock()
        from configparser import NoSectionError
        mock_parser.get.side_effect = NoSectionError("missing")
        with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser):
            mgr = cm.ConfigManager("/fake/path.ini")
            assert mgr.get("bad_section", "key", fallback="fb") == "fb"

    def test_get_none_fallback(self):
        import core.config_manager as cm
        mock_parser = MagicMock()
        from configparser import NoOptionError
        mock_parser.get.side_effect = NoOptionError("no", "opt")
        with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser):
            mgr = cm.ConfigManager("/fake/path.ini")
            assert mgr.get("s", "k") is None


class TestConfigManagerGetint:
    def test_getint_success(self):
        import core.config_manager as cm
        mock_parser = MagicMock()
        mock_parser.get.return_value = "8080"
        with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser):
            mgr = cm.ConfigManager("/fake/path.ini")
            assert mgr.getint("db", "port") == 8080

    def test_getint_fallback(self):
        import core.config_manager as cm
        mock_parser = MagicMock()
        mock_parser.get.side_effect = ValueError
        with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser):
            mgr = cm.ConfigManager("/fake/path.ini")
            assert mgr.getint("s", "k", fallback=3000) == 3000


class TestConfigManagerGetfloat:
    def test_getfloat_success(self):
        import core.config_manager as cm
        mock_parser = MagicMock()
        mock_parser.get.return_value = "0.7"
        with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser):
            mgr = cm.ConfigManager("/fake/path.ini")
            assert mgr.getfloat("s", "k") == 0.7

    def test_getfloat_fallback(self):
        import core.config_manager as cm
        mock_parser = MagicMock()
        mock_parser.get.side_effect = ValueError
        with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser):
            mgr = cm.ConfigManager("/fake/path.ini")
            assert mgr.getfloat("s", "k", fallback=0.5) == 0.5


class TestConfigManagerGetboolean:
    def test_true_values(self):
        import core.config_manager as cm
        for val in ("true", "yes", "1", "on"):
            # Reset for each iteration since ConfigManager is singleton
            cm.ConfigManager._instance = None
            cm.ConfigManager._config = None
            mock_parser = MagicMock()
            mock_parser.get.return_value = val
            with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser):
                mgr = cm.ConfigManager("/fake/path.ini")
                assert mgr.getboolean("s", "k") is True

    def test_false_values(self):
        import core.config_manager as cm
        for val in ("false", "no", "0", "off"):
            cm.ConfigManager._instance = None
            cm.ConfigManager._config = None
            mock_parser = MagicMock()
            mock_parser.get.return_value = val
            with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser):
                mgr = cm.ConfigManager("/fake/path.ini")
                assert mgr.getboolean("s", "k") is False

    def test_unrecognized_returns_fallback(self):
        import core.config_manager as cm
        mock_parser = MagicMock()
        mock_parser.get.return_value = "maybe"
        with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser):
            mgr = cm.ConfigManager("/fake/path.ini")
            assert mgr.getboolean("s", "k", fallback=True) is True


class TestConfigManagerGetSection:
    def test_has_section(self):
        import core.config_manager as cm
        mock_parser = MagicMock()
        mock_parser.has_section.return_value = True
        mock_parser.__getitem__.return_value = {"host": "localhost", "port": "3306"}
        with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser):
            mgr = cm.ConfigManager("/fake/path.ini")
            assert mgr.get_section("database") == {"host": "localhost", "port": "3306"}

    def test_no_section(self):
        import core.config_manager as cm
        mock_parser = MagicMock()
        mock_parser.has_section.return_value = False
        with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser):
            mgr = cm.ConfigManager("/fake/path.ini")
            assert mgr.get_section("missing") == {}


class TestConfigManagerProperties:
    def _make_mgr(self):
        import core.config_manager as cm
        cm.ConfigManager._instance = None
        cm.ConfigManager._config = None
        mock_parser = MagicMock()
        mock_parser.get.return_value = "test_val"
        mock_parser.has_section.return_value = False
        with patch("core.config_manager.configparser.ConfigParser", return_value=mock_parser):
            return cm.ConfigManager("/fake/path.ini")

    def test_mysql_config(self):
        mgr = self._make_mgr()
        assert "host" in mgr.mysql_config
        assert "charset" in mgr.mysql_config

    def test_milvus_config(self):
        mgr = self._make_mgr()
        assert "host" in mgr.milvus_config
        assert "metric_type" in mgr.milvus_config

    def test_redis_config(self):
        mgr = self._make_mgr()
        assert "host" in mgr.redis_config
        assert "ttl" in mgr.redis_config

    def test_llm_config(self):
        mgr = self._make_mgr()
        assert "model_name" in mgr.llm_config
        assert "temperature" in mgr.llm_config

    def test_retriever_config(self):
        mgr = self._make_mgr()
        assert "top_k" in mgr.retriever_config

    def test_dashscope_config(self):
        mgr = self._make_mgr()
        assert "api_key" in mgr.dashscope_config

    def test_tavily_config(self):
        mgr = self._make_mgr()
        assert "api_key" in mgr.tavily_config

    def test_system_config(self):
        mgr = self._make_mgr()
        assert "app_name" in mgr.system_config
        assert "log_level" in mgr.system_config
