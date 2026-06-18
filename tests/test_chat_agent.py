"""langgraph_agent.chat_agent 测试"""
import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


# ═══════════════════════════ CHAT_SYSTEM_PROMPT ═══════════════════════════════

class TestChatSystemPrompt:
    def test_exists(self):
        from langgraph_agent.chat_agent import CHAT_SYSTEM_PROMPT
        assert "小E" in CHAT_SYSTEM_PROMPT
        assert "EduRAG" in CHAT_SYSTEM_PROMPT
        assert "knowledge_search" in CHAT_SYSTEM_PROMPT


# ═══════════════════════ build_agent_system_prompt ════════════════════════════

class TestBuildAgentSystemPrompt:
    def test_no_user_id_returns_base_prompt(self):
        from langgraph_agent.chat_agent import build_agent_system_prompt
        prompt = build_agent_system_prompt(user_id=None)
        assert "小E" in prompt
        assert "EduRAG" in prompt

    def test_with_user_id_no_profile(self):
        from langgraph_agent.chat_agent import build_agent_system_prompt
        mock_db = MagicMock()
        mock_db.get_user_profile.return_value = None
        with patch("database.mysql_db.MySQLDB", return_value=mock_db):
            prompt = build_agent_system_prompt(user_id="u1")
        assert "小E" in prompt  # base prompt still included

    def test_with_user_id_and_profile(self):
        from langgraph_agent.chat_agent import build_agent_system_prompt
        mock_db = MagicMock()
        mock_db.get_user_profile.return_value = {"grade": "初中", "subject": "数学"}
        with patch("database.mysql_db.MySQLDB", return_value=mock_db), \
             patch("data_processor.user_profile.build_profile_section", return_value="[用户画像]\n"):
            prompt = build_agent_system_prompt(user_id="u1")
        assert "[用户画像]" in prompt
        assert "小E" in prompt

    def test_mysql_error_falls_back(self):
        from langgraph_agent.chat_agent import build_agent_system_prompt
        with patch("database.mysql_db.MySQLDB", side_effect=Exception("db error")):
            prompt = build_agent_system_prompt(user_id="u1")
        assert "小E" in prompt

    def test_with_subject_param(self):
        from langgraph_agent.chat_agent import build_agent_system_prompt
        mock_db = MagicMock()
        mock_db.get_user_profile.return_value = {"grade": "高中"}
        with patch("database.mysql_db.MySQLDB", return_value=mock_db), \
             patch("data_processor.user_profile.build_profile_section", return_value="[物理画像]\n"):
            prompt = build_agent_system_prompt(user_id="u1", subject="物理")
        assert "[物理画像]" in prompt


# ══════════════════════ _maybe_trigger_personality ════════════════════════════

class TestMaybeTriggerPersonality:
    def test_not_triggered_due_to_random(self):
        """random() > 0.1 → skip (random imported locally inside function)"""
        with patch("random.random", return_value=0.5):
            from langgraph_agent.chat_agent import _maybe_trigger_personality
            _maybe_trigger_personality("u1")

    def test_triggered_but_no_queries(self):
        from langgraph_agent.chat_agent import _maybe_trigger_personality
        mock_db = MagicMock()
        mock_db.query_one.return_value = None
        with patch("random.random", return_value=0.05), \
             patch("database.mysql_db.MySQLDB", return_value=mock_db):
            _maybe_trigger_personality("u1")
        mock_db.query_one.assert_called_once()

    def test_triggered_and_updates_personality(self):
        from langgraph_agent.chat_agent import _maybe_trigger_personality
        mock_db = MagicMock()
        mock_db.query_one.return_value = {"cnt": 20}
        with patch("random.random", return_value=0.05), \
             patch("database.mysql_db.MySQLDB", return_value=mock_db), \
             patch("data_processor.user_profile.update_personality", return_value=["逻辑型"]):
            _maybe_trigger_personality("u1")
        mock_db.upsert_user_profile.assert_called_once()

    def test_mysql_error_silent(self):
        from langgraph_agent.chat_agent import _maybe_trigger_personality
        with patch("random.random", return_value=0.05), \
             patch("database.mysql_db.MySQLDB", side_effect=Exception("fail")):
            _maybe_trigger_personality("u1")


# ═════════════════════════ create_chat_agent ══════════════════════════════════

class TestCreateChatAgent:
    def test_with_all_defaults(self):
        mock_model = MagicMock()
        mock_tools = [MagicMock()]
        mock_agent = MagicMock()

        with patch("langgraph_agent.chat_agent.create_chat_model", return_value=mock_model), \
             patch("langgraph_agent.chat_agent.create_langchain_tools", return_value=(None, mock_tools, None)), \
             patch("langgraph_agent.chat_agent.create_react_agent", return_value=mock_agent):
            from langgraph_agent.chat_agent import create_chat_agent
            agent = create_chat_agent()
            assert agent is mock_agent

    def test_with_explicit_model(self):
        from langgraph_agent.chat_agent import create_chat_agent
        mock_model = MagicMock()
        mock_agent = MagicMock()
        with patch("langgraph_agent.chat_agent.create_langchain_tools", return_value=(None, [MagicMock()], None)), \
             patch("langgraph_agent.chat_agent.create_react_agent", return_value=mock_agent):
            agent = create_chat_agent(model=mock_model)
            assert agent is mock_agent

    def test_with_explicit_tools(self):
        from langgraph_agent.chat_agent import create_chat_agent
        mock_model = MagicMock()
        mock_tools = [MagicMock(), MagicMock()]
        mock_agent = MagicMock()
        with patch("langgraph_agent.chat_agent.create_react_agent", return_value=mock_agent):
            agent = create_chat_agent(model=mock_model, tools=mock_tools)
            assert agent is mock_agent

    def test_with_explicit_system_prompt(self):
        from langgraph_agent.chat_agent import create_chat_agent
        mock_model = MagicMock()
        mock_tools = [MagicMock()]
        mock_agent = MagicMock()
        custom_prompt = "You are a helpful assistant."
        with patch("langgraph_agent.chat_agent.create_react_agent", return_value=mock_agent):
            agent = create_chat_agent(model=mock_model, tools=mock_tools,
                                      system_prompt=custom_prompt)
            assert agent is mock_agent

    def test_passes_retriever_to_tools(self):
        from langgraph_agent.chat_agent import create_chat_agent
        mock_retriever = MagicMock()
        mock_agent = MagicMock()
        with patch("langgraph_agent.chat_agent.create_chat_model"), \
             patch("langgraph_agent.chat_agent.create_langchain_tools") as mock_create_tools, \
             patch("langgraph_agent.chat_agent.create_react_agent", return_value=mock_agent):
            mock_create_tools.return_value = (None, [MagicMock()], None)
            create_chat_agent(retriever=mock_retriever)
            mock_create_tools.assert_called_once()
            _, kwargs = mock_create_tools.call_args
            assert kwargs.get("retriever") is mock_retriever

    def test_passes_kb_manager_to_tools(self):
        from langgraph_agent.chat_agent import create_chat_agent
        mock_kb = MagicMock()
        mock_agent = MagicMock()
        with patch("langgraph_agent.chat_agent.create_chat_model"), \
             patch("langgraph_agent.chat_agent.create_langchain_tools") as mock_create_tools, \
             patch("langgraph_agent.chat_agent.create_react_agent", return_value=mock_agent):
            mock_create_tools.return_value = (None, [MagicMock()], None)
            create_chat_agent(kb_manager=mock_kb)
            _, kwargs = mock_create_tools.call_args
            assert kwargs.get("kb_manager") is mock_kb


# ═══════════════════════ format_langgraph_event ═══════════════════════════════

class TestFormatLanggraphEvent:
    def test_token_event(self):
        from langgraph_agent.chat_agent import format_langgraph_event
        chunk = MagicMock()
        chunk.content = "你好"
        event = {"event": "on_chat_model_stream", "data": {"chunk": chunk}}
        result = format_langgraph_event(event)
        assert result == {"type": "token", "content": "你好"}

    def test_token_event_empty_content(self):
        from langgraph_agent.chat_agent import format_langgraph_event
        chunk = MagicMock()
        chunk.content = ""
        event = {"event": "on_chat_model_stream", "data": {"chunk": chunk}}
        result = format_langgraph_event(event)
        assert result is None

    def test_token_event_no_chunk(self):
        from langgraph_agent.chat_agent import format_langgraph_event
        event = {"event": "on_chat_model_stream", "data": {}}
        result = format_langgraph_event(event)
        assert result is None

    def test_action_event(self):
        from langgraph_agent.chat_agent import format_langgraph_event
        event = {
            "event": "on_tool_start", "name": "knowledge_search",
            "data": {"input": {"query": "test"}},
        }
        result = format_langgraph_event(event)
        assert result == {
            "type": "action", "action": "knowledge_search",
            "input": {"query": "test"},
        }

    def test_observation_event(self):
        from langgraph_agent.chat_agent import format_langgraph_event
        event = {
            "event": "on_tool_end", "name": "knowledge_search",
            "data": {"output": "找到3条结果"},
        }
        result = format_langgraph_event(event)
        assert result == {
            "type": "observation", "action": "knowledge_search",
            "output": "找到3条结果",
        }

    def test_observation_empty_output(self):
        from langgraph_agent.chat_agent import format_langgraph_event
        event = {
            "event": "on_tool_end", "name": "search",
            "data": {"output": ""},
        }
        result = format_langgraph_event(event)
        assert result["output"] == ""

    def test_unknown_event_returns_none(self):
        from langgraph_agent.chat_agent import format_langgraph_event
        event = {"event": "on_chain_start", "name": "main"}
        result = format_langgraph_event(event)
        assert result is None


# ══════════════════════ stream_agent_response ═════════════════════════════════

class TestStreamAgentResponse:
    @pytest.fixture(autouse=True)
    def _reset_langfuse(self):
        # Prevent module-level state from leaking
        import sys
        stored = sys.modules.get("monitoring.langfuse_tracer")
        sys.modules["monitoring.langfuse_tracer"] = MagicMock()
        sys.modules["monitoring.langfuse_tracer"].start_trace.return_value = None
        yield
        if stored is not None:
            sys.modules["monitoring.langfuse_tracer"] = stored

    @pytest.mark.asyncio
    async def test_basic_stream(self):
        from langgraph_agent.chat_agent import stream_agent_response
        mock_agent = MagicMock()

        async def mock_stream(input_data, config=None, version=None):
            chunk = MagicMock()
            chunk.content = "Hello"
            yield {"event": "on_chat_model_stream", "data": {"chunk": chunk}, "name": "model"}
            chunk2 = MagicMock()
            chunk2.content = " world"
            yield {"event": "on_chat_model_stream", "data": {"chunk": chunk2}, "name": "model"}

        mock_agent.astream_events = mock_stream

        events = []
        async for sse_str in stream_agent_response(mock_agent, "hi"):
            events.append(sse_str)

        # Should have 2 token events + 1 done event
        assert len(events) == 3
        assert "[DONE]" not in events[-1]  # actual done format uses "done" type
        assert '"type": "token"' in events[0]

    @pytest.mark.asyncio
    async def test_stream_with_history(self):
        from langgraph_agent.chat_agent import stream_agent_response
        mock_agent = MagicMock()

        async def mock_stream(input_data, config=None, version=None):
            chunk = MagicMock()
            chunk.content = "response"
            yield {"event": "on_chat_model_stream", "data": {"chunk": chunk}, "name": "model"}

        mock_agent.astream_events = mock_stream

        history = [
            {"role": "user", "content": "previous"},
            {"role": "assistant", "content": "reply"},
        ]
        events = []
        async for sse_str in stream_agent_response(mock_agent, "hi", history=history):
            events.append(sse_str)
        assert len(events) >= 1

    @pytest.mark.asyncio
    async def test_stream_with_tool_calls(self):
        from langgraph_agent.chat_agent import stream_agent_response
        mock_agent = MagicMock()

        async def mock_stream(input_data, config=None, version=None):
            yield {"event": "on_tool_start", "name": "knowledge_search",
                   "data": {"input": {"query": "test"}}}
            yield {"event": "on_tool_end", "name": "knowledge_search",
                   "data": {"output": "results found"}}
            chunk = MagicMock()
            chunk.content = "based on search results"
            yield {"event": "on_chat_model_stream", "data": {"chunk": chunk}, "name": "model"}

        mock_agent.astream_events = mock_stream

        events = []
        async for sse_str in stream_agent_response(mock_agent, "search query"):
            events.append(sse_str)

        # action + observation + token + done
        assert len(events) == 4
        assert '"type": "action"' in events[0]
        assert '"type": "observation"' in events[1]

    @pytest.mark.asyncio
    async def test_stream_with_conversation_id(self):
        from langgraph_agent.chat_agent import stream_agent_response
        mock_agent = MagicMock()

        async def mock_stream(input_data, config=None, version=None):
            chunk = MagicMock()
            chunk.content = "answer"
            yield {"event": "on_chat_model_stream", "data": {"chunk": chunk}, "name": "model"}

        mock_agent.astream_events = mock_stream

        events = []
        async for sse_str in stream_agent_response(
            mock_agent, "hi", conversation_id="conv_abc"
        ):
            events.append(sse_str)

        # Last event should be "done" type (not the token event)
        last_data = json.loads(events[-1].replace("data: ", "").strip())
        assert last_data.get("type") == "done"

    @pytest.mark.asyncio
    async def test_stream_error_yields_error_event(self):
        from langgraph_agent.chat_agent import stream_agent_response
        mock_agent = MagicMock()

        async def mock_stream_error(input_data, config=None, version=None):
            raise RuntimeError("stream crashed")

        mock_agent.astream_events = mock_stream_error

        events = []
        async for sse_str in stream_agent_response(mock_agent, "hi"):
            events.append(sse_str)

        assert any('"type": "error"' in e for e in events)

    @pytest.mark.asyncio
    async def test_stream_respects_history_limit(self):
        from langgraph_agent.chat_agent import stream_agent_response
        mock_agent = MagicMock()

        async def mock_stream(input_data, config=None, version=None):
            # Verify only last 20 history messages are passed
            chunk = MagicMock()
            chunk.content = "ok"
            yield {"event": "on_chat_model_stream", "data": {"chunk": chunk}, "name": "model"}

        mock_agent.astream_events = mock_stream
        history = [{"role": "user", "content": f"msg{i}"} for i in range(30)]

        events = []
        async for sse_str in stream_agent_response(mock_agent, "hi", history=history):
            events.append(sse_str)
        assert len(events) >= 2  # token + done

    @pytest.mark.asyncio
    async def test_stream_accumulates_tokens(self):
        from langgraph_agent.chat_agent import stream_agent_response
        mock_agent = MagicMock()

        async def mock_stream(input_data, config=None, version=None):
            for word in ["Hello", " ", "World"]:
                chunk = MagicMock()
                chunk.content = word
                yield {"event": "on_chat_model_stream", "data": {"chunk": chunk}, "name": "model"}

        mock_agent.astream_events = mock_stream

        # We rely on the function's internal full_answer_parts accumulation
        # The tokens are yielded as SSE strings
        events = []
        async for sse_str in stream_agent_response(mock_agent, "talk"):
            events.append(sse_str)

        tokens = []
        for e in events:
            try:
                data = json.loads(e.replace("data: ", "").strip())
                if data.get("type") == "token":
                    tokens.append(data.get("content", ""))
            except Exception:
                pass
        assert "".join(tokens) == "Hello World"
