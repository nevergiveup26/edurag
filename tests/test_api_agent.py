"""api层测试：shared_models, conversation_helpers, agent_routes"""
import json
import pytest
from unittest.mock import MagicMock, patch


# ═══════════════════════════ shared_models ════════════════════════════════════

class TestQueryRequestModel:
    def test_minimal_valid(self):
        from api.shared_models import QueryRequestModel
        req = QueryRequestModel(query="test")
        assert req.query == "test"
        assert req.strategy == "auto"
        assert req.top_k == 5
        assert req.user_id is None

    def test_query_min_length(self):
        from api.shared_models import QueryRequestModel
        with pytest.raises(Exception):
            QueryRequestModel(query="")

    def test_query_max_length(self):
        from api.shared_models import QueryRequestModel
        with pytest.raises(Exception):
            QueryRequestModel(query="x" * 2001)

    def test_top_k_min(self):
        from api.shared_models import QueryRequestModel
        with pytest.raises(Exception):
            QueryRequestModel(query="test", top_k=0)

    def test_top_k_max(self):
        from api.shared_models import QueryRequestModel
        with pytest.raises(Exception):
            QueryRequestModel(query="test", top_k=21)

    def test_full_fields(self):
        from api.shared_models import QueryRequestModel
        req = QueryRequestModel(
            query="hello", strategy="hybrid", top_k=10,
            user_id="u1", conversation_id="c1",
            history=[{"role": "user", "content": "hi"}], kb_id="kb1",
        )
        assert req.strategy == "hybrid"
        assert req.history == [{"role": "user", "content": "hi"}]


class TestSourceItem:
    def test_valid(self):
        from api.shared_models import SourceItem
        item = SourceItem(content="c", score=0.9, source="vector")
        assert item.metadata == {}

    def test_with_metadata(self):
        from api.shared_models import SourceItem
        item = SourceItem(content="c", score=1.0, source="bm25",
                          metadata={"doc_id": "d1"})
        assert item.metadata == {"doc_id": "d1"}


class TestQueryResponseModel:
    def test_defaults(self):
        from api.shared_models import QueryResponseModel
        resp = QueryResponseModel(answer="answer")
        assert resp.sources == []
        assert resp.strategy_used == ""
        assert resp.execution_time == 0.0

    def test_with_sources(self):
        from api.shared_models import QueryResponseModel, SourceItem
        src = SourceItem(content="c", score=0.5, source="hybrid")
        resp = QueryResponseModel(answer="a", sources=[src],
                                  strategy_used="hybrid", execution_time=1.5,
                                  conversation_id="c1")
        assert len(resp.sources) == 1
        assert resp.conversation_id == "c1"


class TestUploadResponse:
    def test_defaults(self):
        from api.shared_models import UploadResponse
        resp = UploadResponse(message="ok", doc_count=5, chunk_count=20)
        assert resp.skipped_duplicates == 0
        assert resp.chunk_duplicates_removed == 0


class TestConversationMessage:
    def test_valid(self):
        from api.shared_models import ConversationMessage
        msg = ConversationMessage(role="user", content="hello")
        assert msg.timestamp is None

    def test_with_timestamp(self):
        from api.shared_models import ConversationMessage
        msg = ConversationMessage(role="assistant", content="hi",
                                  timestamp="2024-01-01T00:00:00")
        assert msg.role == "assistant"


class TestFeedbackRequest:
    def test_valid_rating(self):
        from api.shared_models import FeedbackRequest
        fb = FeedbackRequest(rating=3)
        assert fb.rating == 3

    def test_rating_min(self):
        from api.shared_models import FeedbackRequest
        with pytest.raises(Exception):
            FeedbackRequest(rating=0)

    def test_rating_max(self):
        from api.shared_models import FeedbackRequest
        with pytest.raises(Exception):
            FeedbackRequest(rating=6)

    def test_full(self):
        from api.shared_models import FeedbackRequest
        fb = FeedbackRequest(
            query_id="q1", conversation_id="c1", kb_id="k1",
            query="what", answer="that", rating=4, comment="good",
            strategy_used="hybrid", router_used="router",
            response_time_ms=200, metadata={"key": "val"},
        )
        assert fb.response_time_ms == 200
        assert fb.metadata == {"key": "val"}


# ═════════════════════════ conversation_helpers ═══════════════════════════════
# Note: save/load use local `from database.mysql_db import MySQLDB`

class TestSaveConversationMessage:
    def test_user_message(self):
        mock_db = MagicMock()
        with patch("database.mysql_db.MySQLDB", return_value=mock_db):
            from api.conversation_helpers import save_conversation_message
            save_conversation_message("conv1", "user", "hello world")
        # INSERT IGNORE conversations + INSERT message + UPDATE title
        assert mock_db.execute.call_count >= 3

    def test_assistant_message(self):
        mock_db = MagicMock()
        with patch("database.mysql_db.MySQLDB", return_value=mock_db):
            from api.conversation_helpers import save_conversation_message
            save_conversation_message("conv1", "assistant", "reply")
        assert mock_db.execute.call_count >= 2

    def test_user_message_title_truncation(self):
        mock_db = MagicMock()
        with patch("database.mysql_db.MySQLDB", return_value=mock_db):
            from api.conversation_helpers import save_conversation_message
            long_msg = "第一句话\n第二句话" + "x" * 100
            save_conversation_message("conv1", "user", long_msg)
        calls = [c[0][0] for c in mock_db.execute.call_args_list]
        update_call = [c for c in calls if "UPDATE conversations" in c]
        assert len(update_call) == 1

    def test_content_truncation(self):
        mock_db = MagicMock()
        with patch("database.mysql_db.MySQLDB", return_value=mock_db):
            from api.conversation_helpers import save_conversation_message
            save_conversation_message("conv1", "user", "x" * 3000)
        insert_call = None
        for call_args in mock_db.execute.call_args_list:
            sql = call_args[0][0]
            if "INSERT INTO conversation_messages" in sql:
                insert_call = call_args
        assert insert_call is not None
        content = insert_call[0][1][3]
        assert len(content) <= 2000

    def test_mysql_import_error(self):
        with patch("database.mysql_db.MySQLDB", side_effect=ImportError):
            from api.conversation_helpers import save_conversation_message
            save_conversation_message("conv1", "user", "test")  # no raise

    def test_mysql_execute_error(self):
        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("DB error")
        with patch("database.mysql_db.MySQLDB", return_value=mock_db):
            from api.conversation_helpers import save_conversation_message
            save_conversation_message("conv1", "user", "test")  # no raise

    def test_empty_user_message_title(self):
        mock_db = MagicMock()
        with patch("database.mysql_db.MySQLDB", return_value=mock_db):
            from api.conversation_helpers import save_conversation_message
            save_conversation_message("conv1", "user", "   \n  ")  # no raise


class TestLoadConversationHistory:
    def test_success(self):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        with patch("database.mysql_db.MySQLDB", return_value=mock_db):
            from api.conversation_helpers import load_conversation_history
            history = load_conversation_history("conv1")
        assert len(history) == 2
        assert history[0]["role"] == "user"

    def test_empty_history(self):
        mock_db = MagicMock()
        mock_db.query.return_value = []
        with patch("database.mysql_db.MySQLDB", return_value=mock_db):
            from api.conversation_helpers import load_conversation_history
            history = load_conversation_history("conv1")
        assert history == []

    def test_mysql_error_returns_empty(self):
        with patch("database.mysql_db.MySQLDB", side_effect=Exception("fail")):
            from api.conversation_helpers import load_conversation_history
            history = load_conversation_history("conv1")
            assert history == []

    def test_import_error_returns_empty(self):
        with patch("database.mysql_db.MySQLDB", side_effect=ImportError):
            from api.conversation_helpers import load_conversation_history
            history = load_conversation_history("conv1")
            assert history == []


# ═══════════════════════════ agent_routes ═════════════════════════════════════
# Note: agent_routes uses local imports inside endpoint functions:
#   from langgraph_agent.chat_agent import create_chat_agent, build_agent_system_prompt, stream_agent_response
#   from langgraph_agent.model import create_chat_model
#   from monitoring.langfuse_tracer import start_trace
# Module-level imports (patchable at api.agent_routes.*):
#   from api.conversation_helpers import save_conversation_message, load_conversation_history

class TestAgentQueryRoute:
    def test_success(self):
        from api.shared_models import QueryRequestModel
        req = QueryRequestModel(query="test query", user_id="u1")

        mock_agent = MagicMock()

        async def mock_ainvoke(input_data):
            msg = MagicMock()
            msg.content = "agent answer"
            msg.tool_calls = None
            return {"messages": [msg]}

        mock_agent.ainvoke = mock_ainvoke

        with patch("langgraph_agent.model.create_chat_model"), \
             patch("langgraph_agent.chat_agent.build_agent_system_prompt", return_value="system"), \
             patch("langgraph_agent.chat_agent.create_chat_agent", return_value=mock_agent), \
             patch("monitoring.langfuse_tracer.start_trace", return_value=None), \
             patch("api.agent_routes.load_conversation_history", return_value=[]), \
             patch("api.agent_routes.save_conversation_message"):
            import asyncio
            from api.agent_routes import agent_query

            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(agent_query(req))
            loop.close()

        assert result.answer == "agent answer"
        assert result.strategy_used == "langgraph_agent"
        assert result.router_used == "agent"
        assert result.conversation_id is not None

    def test_no_conversation_id_generates_uuid(self):
        from api.shared_models import QueryRequestModel
        req = QueryRequestModel(query="q", conversation_id=None)

        mock_agent = MagicMock()

        async def mock_ainvoke(input_data):
            msg = MagicMock()
            msg.content = "ans"
            msg.tool_calls = None
            return {"messages": [msg]}

        mock_agent.ainvoke = mock_ainvoke

        with patch("langgraph_agent.model.create_chat_model"), \
             patch("langgraph_agent.chat_agent.build_agent_system_prompt", return_value=""), \
             patch("langgraph_agent.chat_agent.create_chat_agent", return_value=mock_agent), \
             patch("monitoring.langfuse_tracer.start_trace", return_value=None), \
             patch("api.agent_routes.load_conversation_history", return_value=[]), \
             patch("api.agent_routes.save_conversation_message"):
            import asyncio
            import uuid
            from api.agent_routes import agent_query

            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(agent_query(req))
            loop.close()

        assert result.conversation_id is not None
        uuid.UUID(result.conversation_id)

    def test_with_tool_calls(self):
        from api.shared_models import QueryRequestModel
        req = QueryRequestModel(query="q")

        mock_agent = MagicMock()

        async def mock_ainvoke(input_data):
            msg_tool = MagicMock()
            msg_tool.tool_calls = [{"name": "search", "args": {"query": "test"}}]
            msg_answer = MagicMock()
            msg_answer.content = "final answer"
            msg_answer.tool_calls = None
            return {"messages": [msg_tool, msg_answer]}

        mock_agent.ainvoke = mock_ainvoke

        with patch("langgraph_agent.model.create_chat_model"), \
             patch("langgraph_agent.chat_agent.build_agent_system_prompt", return_value=""), \
             patch("langgraph_agent.chat_agent.create_chat_agent", return_value=mock_agent), \
             patch("monitoring.langfuse_tracer.start_trace", return_value=None), \
             patch("api.agent_routes.load_conversation_history", return_value=[]), \
             patch("api.agent_routes.save_conversation_message"):
            import asyncio
            from api.agent_routes import agent_query

            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(agent_query(req))
            loop.close()

        assert result.answer == "final answer"
        assert len(result.sources) == 1
        assert result.sources[0].source == "search"

    def test_with_history(self):
        from api.shared_models import QueryRequestModel
        req = QueryRequestModel(query="new question", conversation_id="conv_old")

        mock_agent = MagicMock()

        async def mock_ainvoke(input_data):
            msg = MagicMock()
            msg.content = "answer with context"
            msg.tool_calls = None
            return {"messages": [msg]}

        mock_agent.ainvoke = mock_ainvoke
        history = [
            {"role": "user", "content": "previous question"},
            {"role": "assistant", "content": "previous answer"},
        ]

        with patch("langgraph_agent.model.create_chat_model"), \
             patch("langgraph_agent.chat_agent.build_agent_system_prompt", return_value=""), \
             patch("langgraph_agent.chat_agent.create_chat_agent", return_value=mock_agent), \
             patch("monitoring.langfuse_tracer.start_trace", return_value=None), \
             patch("api.agent_routes.load_conversation_history", return_value=history), \
             patch("api.agent_routes.save_conversation_message"):
            import asyncio
            from api.agent_routes import agent_query

            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(agent_query(req))
            loop.close()

        assert result.answer == "answer with context"

    def test_agent_raises_http_exception(self):
        """agent query 异常时抛出"""
        from api.shared_models import QueryRequestModel
        req = QueryRequestModel(query="q")

        mock_agent = MagicMock()

        async def mock_ainvoke(input_data):
            raise RuntimeError("agent crash")

        mock_agent.ainvoke = mock_ainvoke

        with patch("langgraph_agent.model.create_chat_model"), \
             patch("langgraph_agent.chat_agent.build_agent_system_prompt", return_value=""), \
             patch("langgraph_agent.chat_agent.create_chat_agent", return_value=mock_agent), \
             patch("monitoring.langfuse_tracer.start_trace", return_value=None), \
             patch("api.agent_routes.load_conversation_history", return_value=[]), \
             patch("api.agent_routes.save_conversation_message"):
            import asyncio
            from api.agent_routes import agent_query

            loop = asyncio.new_event_loop()
            with pytest.raises(RuntimeError, match="agent crash"):
                loop.run_until_complete(agent_query(req))
            loop.close()


class TestAgentQueryStreamRoute:
    def test_stream_basic(self):
        from api.shared_models import QueryRequestModel
        req = QueryRequestModel(query="stream query")

        mock_agent = MagicMock()

        async def mock_stream(agent, query, **kwargs):
            yield "data: {\"type\": \"thinking\", \"content\": \"thinking...\"}\n\n"
            yield "data: {\"type\": \"token\", \"content\": \"Hello\"}\n\n"
            yield "data: {\"type\": \"token\", \"content\": \" world\"}\n\n"
            yield "data: [DONE]\n\n"

        with patch("langgraph_agent.model.create_chat_model"), \
             patch("langgraph_agent.chat_agent.build_agent_system_prompt", return_value=""), \
             patch("langgraph_agent.chat_agent.create_chat_agent", return_value=mock_agent), \
             patch("langgraph_agent.chat_agent.stream_agent_response", side_effect=mock_stream), \
             patch("api.agent_routes.load_conversation_history", return_value=[]), \
             patch("api.agent_routes.save_conversation_message"):
            import asyncio
            from api.agent_routes import agent_query_stream

            loop = asyncio.new_event_loop()
            response = loop.run_until_complete(agent_query_stream(req))
            loop.close()

        from fastapi.responses import StreamingResponse
        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"

    def test_stream_error_handling(self):
        from api.shared_models import QueryRequestModel
        req = QueryRequestModel(query="stream query")

        mock_agent = MagicMock()

        async def mock_stream_error(agent, query, **kwargs):
            raise RuntimeError("stream failure")

        with patch("langgraph_agent.model.create_chat_model"), \
             patch("langgraph_agent.chat_agent.build_agent_system_prompt", return_value=""), \
             patch("langgraph_agent.chat_agent.create_chat_agent", return_value=mock_agent), \
             patch("langgraph_agent.chat_agent.stream_agent_response", side_effect=mock_stream_error), \
             patch("api.agent_routes.load_conversation_history", return_value=[]), \
             patch("api.agent_routes.save_conversation_message"):
            import asyncio
            from api.agent_routes import agent_query_stream

            loop = asyncio.new_event_loop()
            response = loop.run_until_complete(agent_query_stream(req))
            loop.close()

        async def collect():
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)
            return chunks

        loop2 = asyncio.new_event_loop()
        chunks = loop2.run_until_complete(collect())
        loop2.close()

        combined = "".join(chunks)
        assert '"type": "error"' in combined
        assert "[DONE]" in combined

    def test_correct_headers(self):
        from api.shared_models import QueryRequestModel
        req = QueryRequestModel(query="q")

        mock_agent = MagicMock()

        async def mock_stream(agent, query, **kwargs):
            yield "data: [DONE]\n\n"

        with patch("langgraph_agent.model.create_chat_model"), \
             patch("langgraph_agent.chat_agent.build_agent_system_prompt", return_value=""), \
             patch("langgraph_agent.chat_agent.create_chat_agent", return_value=mock_agent), \
             patch("langgraph_agent.chat_agent.stream_agent_response", side_effect=mock_stream), \
             patch("api.agent_routes.load_conversation_history", return_value=[]), \
             patch("api.agent_routes.save_conversation_message"):
            import asyncio
            from api.agent_routes import agent_query_stream

            loop = asyncio.new_event_loop()
            response = loop.run_until_complete(agent_query_stream(req))
            loop.close()

        assert response.headers["Cache-Control"] == "no-cache"
        assert response.headers["Connection"] == "keep-alive"
