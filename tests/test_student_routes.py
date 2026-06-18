"""api/student_routes.py 测试"""
import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from io import BytesIO


# ═══════════════════════════ fixtures ═══════════════════════════════════════════

FAKE_STUDENT = {"user_id": "stu_abc123", "username": "testuser", "role": "student"}


@pytest.fixture
def client():
    """创建带 student_router 的 TestClient，注入假用户依赖"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    test_app = FastAPI()
    try:
        from api.student_routes import student_router
    except ImportError:
        pytest.skip("student_routes module not importable")

    from api.auth import require_student

    async def fake_require_student():
        return FAKE_STUDENT

    test_app.dependency_overrides = {require_student: fake_require_student}
    test_app.include_router(student_router)  # router 已有 prefix="/student"
    return TestClient(test_app)


# ═══════════════════════════ 认证 ═══════════════════════════════════════════════

class TestStudentLogin:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.get_user_by_username.return_value = {
            "id": "stu_1", "username": "u1", "role": "student",
            "password_hash": "hashed",
        }
        with patch("api.student_routes.MySQLDB", return_value=mock_db), \
             patch("api.auth.verify_password", return_value=(True, False)), \
             patch("api.auth.create_token", return_value="token_abc"):
            resp = client.post("/student/login", json={"username": "u1", "password": "pwd"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["token"] == "token_abc"
        assert data["user"]["role"] == "student"

    def test_user_not_found(self, client):
        mock_db = MagicMock()
        mock_db.get_user_by_username.return_value = None
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.post("/student/login", json={"username": "bad", "password": "pwd"})
        assert resp.status_code == 401

    def test_not_student_role(self, client):
        mock_db = MagicMock()
        mock_db.get_user_by_username.return_value = {
            "id": "a1", "username": "admin1", "role": "admin",
            "password_hash": "hashed",
        }
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.post("/student/login", json={"username": "admin1", "password": "pwd"})
        assert resp.status_code == 403

    def test_wrong_password(self, client):
        mock_db = MagicMock()
        mock_db.get_user_by_username.return_value = {
            "id": "stu_1", "username": "u1", "role": "student",
            "password_hash": "hashed",
        }
        with patch("api.student_routes.MySQLDB", return_value=mock_db), \
             patch("api.auth.verify_password", return_value=(False, False)):
            resp = client.post("/student/login", json={"username": "u1", "password": "wrong"})
        assert resp.status_code == 401

    def test_password_upgrade(self, client):
        mock_db = MagicMock()
        mock_db.get_user_by_username.return_value = {
            "id": "stu_1", "username": "u1", "role": "student",
            "password_hash": "old_hash",
        }
        with patch("api.student_routes.MySQLDB", return_value=mock_db), \
             patch("api.auth.verify_password", return_value=(True, True)), \
             patch("api.auth.hash_password", return_value="new_hash"), \
             patch("api.auth.create_token", return_value="token"):
            resp = client.post("/student/login", json={"username": "u1", "password": "pwd"})
        assert resp.status_code == 200
        mock_db.execute.assert_called()


class TestStudentRegister:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.get_user_by_username.return_value = None
        with patch("api.student_routes.MySQLDB", return_value=mock_db), \
             patch("api.auth.hash_password", return_value="hash"):
            resp = client.post("/student/register",
                               json={"username": "newuser", "password": "pwd", "display_name": "小明"})
        assert resp.status_code == 200
        assert "user_id" in resp.json()
        mock_db.create_user.assert_called_once()

    def test_duplicate_username(self, client):
        mock_db = MagicMock()
        mock_db.get_user_by_username.return_value = {"id": "existing"}
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.post("/student/register",
                               json={"username": "existing", "password": "pwd"})
        assert resp.status_code == 400


# ═══════════════════════════ 历史/对话 ══════════════════════════════════════════

class TestGetHistory:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {"id": "c1", "title": "对话1", "is_pinned": 1, "message_count": 5},
        ]
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.get("/student/history?limit=10")
        assert resp.status_code == 200
        assert len(resp.json()["conversations"]) == 1


class TestCreateConversation:
    def test_success(self, client):
        mock_db = MagicMock()
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.post("/student/conversation")
        assert resp.status_code == 200
        assert "conversation_id" in resp.json()

    def test_db_error(self, client):
        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("DB down")
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.post("/student/conversation")
        assert resp.status_code == 500


class TestGetConversation:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.query.return_value = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.get("/student/conversation/conv_abc")
        assert resp.status_code == 200
        assert len(resp.json()["messages"]) == 2

    def test_db_error(self, client):
        mock_db = MagicMock()
        mock_db.query.side_effect = Exception("fail")
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.get("/student/conversation/conv_abc")
        assert resp.status_code == 500


class TestListConversations:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.query.side_effect = [
            [{"total": 5}],
            [{"id": "c1", "title": "对话1", "message_count": 3}],
        ]
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.get("/student/conversations?page=1&page_size=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert data["page"] == 1

    def test_empty(self, client):
        mock_db = MagicMock()
        mock_db.query.side_effect = [[], []]
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.get("/student/conversations")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_db_error(self, client):
        mock_db = MagicMock()
        mock_db.query.side_effect = Exception("fail")
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.get("/student/conversations")
        assert resp.status_code == 500


class TestDeleteConversation:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.query_one.return_value = {"id": "conv_abc"}
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.delete("/student/conversation/conv_abc")
        assert resp.status_code == 200
        assert resp.json()["message"] == "对话已删除"

    def test_not_found(self, client):
        mock_db = MagicMock()
        mock_db.query_one.return_value = None
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.delete("/student/conversation/conv_missing")
        assert resp.status_code == 404

    def test_db_error(self, client):
        mock_db = MagicMock()
        mock_db.query_one.side_effect = Exception("fail")
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.delete("/student/conversation/conv_abc")
        assert resp.status_code == 500


class TestPinConversation:
    def test_pin(self, client):
        mock_db = MagicMock()
        mock_db.query_one.return_value = {"id": "c1", "is_pinned": 0}
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.patch("/student/conversation/c1/pin")
        assert resp.status_code == 200
        assert resp.json()["is_pinned"] is True

    def test_unpin(self, client):
        mock_db = MagicMock()
        mock_db.query_one.return_value = {"id": "c1", "is_pinned": 1}
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.patch("/student/conversation/c1/pin")
        assert resp.status_code == 200
        assert resp.json()["is_pinned"] is False

    def test_not_found(self, client):
        mock_db = MagicMock()
        mock_db.query_one.return_value = None
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.patch("/student/conversation/c_missing/pin")
        assert resp.status_code == 404

    def test_db_error(self, client):
        mock_db = MagicMock()
        mock_db.query_one.side_effect = Exception("fail")
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.patch("/student/conversation/c1/pin")
        assert resp.status_code == 500


# ═══════════════════════════ 多模态 ═════════════════════════════════════════════

class TestMultimodalUpload:
    def test_no_file(self, client):
        resp = client.post("/student/multimodal/upload")
        assert resp.status_code == 422

    def test_unsupported_format(self, client):
        fake_file = BytesIO(b"test")
        resp = client.post("/student/multimodal/upload",
                           files=[("file", ("test.xyz", fake_file, "application/octet-stream"))])
        assert resp.status_code == 400

    def test_internal_error(self, client):
        fake_file = BytesIO(b"test content")
        with patch("data_processor.multimodal_loader.MultiModalLoader") as mock_loader:
            mock_loader.return_value.load_document.side_effect = Exception("parse error")
            resp = client.post("/student/multimodal/upload",
                               files=[("file", ("test.pdf", fake_file, "application/pdf"))])
        assert resp.status_code == 500


class TestMultimodalModels:
    def test_success(self, client):
        with patch("data_processor.vision_encoder.VisionEncoder") as mock_cls:
            mock_cls.list_models.return_value = ["qwen-vl-plus", "qwen-vl-max"]
            resp = client.get("/student/multimodal/models")
        assert resp.status_code == 200
        assert len(resp.json()["models"]) == 2

    def test_error(self, client):
        with patch("data_processor.vision_encoder.VisionEncoder") as mock_cls:
            mock_cls.list_models.side_effect = Exception("fail")
            resp = client.get("/student/multimodal/models")
        assert resp.status_code == 500


# ═══════════════════════════ 拍照搜题 ═══════════════════════════════════════════

class TestPhotoSearch:
    def test_no_input(self, client):
        resp = client.post("/student/photo-search", data={"query": ""})
        assert resp.status_code == 400

    def test_text_query_only(self, client):
        """纯文字搜索，走 Tavily + LLM"""
        mock_tavily = MagicMock()
        mock_tavily.invoke.return_value = json.dumps({
            "results": [{"title": "t1", "url": "http://a", "content": "答案"}],
            "answer": "summary",
        })

        mock_llm = MagicMock()
        mock_llm.generate.return_value = "题目解析内容..."

        mock_db = MagicMock()

        with patch("langgraph_agent.tools.tavily_web_search", mock_tavily), \
             patch("llm.llm_client.LLMClient", return_value=mock_llm), \
             patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.post("/student/photo-search", data={"query": "三角形面积"})
        assert resp.status_code == 200
        data = resp.json()
        assert "analysis" in data
        assert "web_sources" in data

    def test_unsupported_image_format(self, client):
        fake_file = BytesIO(b"fake image")
        resp = client.post("/student/photo-search",
                           files=[("file", ("test.svg", fake_file, "image/svg+xml"))],
                           data={"query": ""})
        assert resp.status_code == 400

    def test_image_with_ocr_empty(self, client):
        fake_file = BytesIO(b"fake png")
        mock_ocr = MagicMock()
        mock_ocr.extract_text.return_value = {"extracted_text": "", "error": ""}

        with patch("llm.ocr_client.get_ocr_client", return_value=mock_ocr):
            resp = client.post("/student/photo-search",
                               files=[("file", ("test.png", fake_file, "image/png"))],
                               data={"query": ""})
        assert resp.status_code == 200
        data = resp.json()
        assert data["extracted_text"] == ""

    def test_image_ocr_error(self, client):
        """OCR 处理失败抛出异常"""
        fake_file = BytesIO(b"fake png")
        with patch("llm.ocr_client.get_ocr_client", side_effect=Exception("ocr fail")):
            resp = client.post("/student/photo-search",
                               files=[("file", ("test.png", fake_file, "image/png"))],
                               data={"query": ""})
        assert resp.status_code == 500


# ═══════════════════════════ Agent 查询 ═════════════════════════════════════════

class TestStudentAgentQuery:
    def test_success(self, client):
        mock_agent = MagicMock()

        async def mock_ainvoke(input_data):
            msg = MagicMock()
            msg.content = "agent answer"
            del msg.tool_calls  # 删除 MagicMock 自带的 tool_calls 属性
            return {"messages": [msg]}

        mock_agent.ainvoke = mock_ainvoke

        with patch("api.student_routes._get_cached_retriever", return_value=MagicMock()), \
             patch("langgraph_agent.chat_agent.create_chat_agent", return_value=mock_agent), \
             patch("langgraph_agent.chat_agent.build_agent_system_prompt", return_value="sys"), \
             patch("langgraph_agent.model.create_chat_model"), \
             patch("llm.llm_client.LLMClient"), \
             patch("api.student_routes.MySQLDB"), \
             patch("api.student_routes.save_conversation_message"), \
             patch("monitoring.langfuse_tracer.start_trace", return_value=None):
            resp = client.post("/student/agent/query", json={"query": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["answer"] == "agent answer"
        assert "conversation_id" in data

    def test_with_conversation_id(self, client):
        mock_agent = MagicMock()

        async def mock_ainvoke(input_data):
            msg = MagicMock()
            msg.content = "answer"
            msg.tool_calls = None
            return {"messages": [msg]}

        mock_agent.ainvoke = mock_ainvoke

        with patch("api.student_routes._get_cached_retriever", return_value=MagicMock()), \
             patch("langgraph_agent.chat_agent.create_chat_agent", return_value=mock_agent), \
             patch("langgraph_agent.chat_agent.build_agent_system_prompt", return_value=""), \
             patch("langgraph_agent.model.create_chat_model"), \
             patch("llm.llm_client.LLMClient"), \
             patch("api.student_routes.MySQLDB"), \
             patch("api.student_routes.save_conversation_message"), \
             patch("monitoring.langfuse_tracer.start_trace", return_value=None):
            resp = client.post("/student/agent/query", json={
                "query": "test", "conversation_id": "existing_conv",
            })
        assert resp.status_code == 200
        assert resp.json()["conversation_id"] == "existing_conv"

    def test_empty_query(self, client):
        resp = client.post("/student/agent/query", json={"query": ""})
        assert resp.status_code == 422

    def test_agent_error(self, client):
        mock_agent = MagicMock()

        async def mock_ainvoke(input_data):
            raise RuntimeError("agent crash")

        mock_agent.ainvoke = mock_ainvoke

        with patch("api.student_routes._get_cached_retriever", return_value=MagicMock()), \
             patch("langgraph_agent.chat_agent.create_chat_agent", return_value=mock_agent), \
             patch("langgraph_agent.chat_agent.build_agent_system_prompt", return_value=""), \
             patch("langgraph_agent.model.create_chat_model"), \
             patch("llm.llm_client.LLMClient"), \
             patch("api.student_routes.MySQLDB"), \
             patch("api.student_routes.save_conversation_message"), \
             patch("monitoring.langfuse_tracer.start_trace", return_value=None):
            resp = client.post("/student/agent/query", json={"query": "test"})
        assert resp.status_code == 500


class TestStudentAgentQueryStream:
    def test_basic(self, client):
        from fastapi.responses import StreamingResponse

        with patch("api.student_routes.MySQLDB"), \
             patch("api.student_routes.save_conversation_message"), \
             patch("api.student_routes._langgraph_chat_stream") as mock_stream:

            async def fake_stream(request, user, conv_id):
                async def gen():
                    yield "data: {\"type\": \"done\"}\n\n"
                return StreamingResponse(gen(), media_type="text/event-stream")

            mock_stream.side_effect = fake_stream

            resp = client.post("/student/agent/query/stream", json={"query": "test"})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")


class TestListAgentTools:
    def test_success(self, client):
        mock_tool = MagicMock()
        mock_tool.name = "search"
        mock_tool.description = "搜索知识库"
        mock_tool.args = {"query": "str"}

        with patch("langgraph_agent.tools.ALL_TOOLS", [mock_tool]):
            resp = client.get("/student/agent/tools")
        assert resp.status_code == 200
        tools = resp.json()["tools"]
        assert len(tools) == 1
        assert tools[0]["name"] == "search"

    def test_error(self, client):
        mock_tools = MagicMock()
        mock_tools.__iter__.side_effect = Exception("fail")
        with patch("langgraph_agent.tools.ALL_TOOLS", mock_tools):
            resp = client.get("/student/agent/tools")
        assert resp.status_code == 500


# ═══════════════════════════ 智能批改 ═══════════════════════════════════════════

class TestStudentGrade:
    def test_agent_success(self, client):
        mock_agent = MagicMock()

        async def mock_ainvoke(input_data):
            return {
                "grading_result": json.dumps({"score": 85, "max_score": 100, "feedback": "good"}),
                "tools_used": ["grade_execute"],
                "step": 3,
            }

        mock_agent.ainvoke = mock_ainvoke

        with patch("langgraph_agent.grade_agent.create_grade_agent", return_value=mock_agent), \
             patch("langgraph_agent.model.create_chat_model"), \
             patch("retriever.hybrid_retriever.HybridRetriever"), \
             patch("llm.llm_client.LLMClient"), \
             patch("api.student_routes.MySQLDB"):
            resp = client.post("/student/agent/grade", json={
                "question": "1+1=?", "user_answer": "2",
                "correct_answer": "2", "subject": "数学",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["grading"]["score"] == 85

    def test_agent_fallback_to_direct(self, client):
        """Agent 失败时降级到 _direct_grade"""
        mock_agent = MagicMock()

        async def mock_ainvoke(input_data):
            raise RuntimeError("agent failed")

        mock_agent.ainvoke = mock_ainvoke

        mock_grader = MagicMock()
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"score": 60, "is_correct": True}
        mock_grader.auto_detect_and_grade.return_value = mock_result

        with patch("langgraph_agent.grade_agent.create_grade_agent", return_value=mock_agent), \
             patch("langgraph_agent.model.create_chat_model"), \
             patch("retriever.hybrid_retriever.HybridRetriever"), \
             patch("llm.llm_client.LLMClient"), \
             patch("agent.grading.UnifiedGrader", return_value=mock_grader), \
             patch("api.student_routes.MySQLDB"):
            resp = client.post("/student/agent/grade", json={
                "question": "1+1=?", "user_answer": "2",
                "correct_answer": "2",
            })
        assert resp.status_code == 200
        assert resp.json()["graded_by"] == "direct"

    def test_auto_save_wrong_book(self, client):
        mock_agent = MagicMock()

        async def mock_ainvoke(input_data):
            return {
                "grading_result": json.dumps({"score": 30, "max_score": 100}),
                "tools_used": ["grade_execute"],
                "step": 2,
            }

        mock_agent.ainvoke = mock_ainvoke
        mock_db = MagicMock()

        with patch("langgraph_agent.grade_agent.create_grade_agent", return_value=mock_agent), \
             patch("langgraph_agent.model.create_chat_model"), \
             patch("retriever.hybrid_retriever.HybridRetriever"), \
             patch("llm.llm_client.LLMClient"), \
             patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.post("/student/agent/grade", json={
                "question": "hard", "user_answer": "wrong",
                "correct_answer": "correct", "auto_save": True,
            })
        assert resp.status_code == 200
        assert resp.json()["auto_saved"] is True
        mock_db.insert_wrong_book.assert_called_once()

    def test_exception_returns_500(self, client):
        mock_agent = MagicMock()

        async def mock_ainvoke(input_data):
            raise RuntimeError("agent crash")

        mock_agent.ainvoke = mock_ainvoke

        with patch("langgraph_agent.grade_agent.create_grade_agent", return_value=mock_agent), \
             patch("langgraph_agent.model.create_chat_model"), \
             patch("retriever.hybrid_retriever.HybridRetriever"), \
             patch("llm.llm_client.LLMClient"), \
             patch("agent.grading.UnifiedGrader", side_effect=Exception("total fail")), \
             patch("api.student_routes.MySQLDB"):
            resp = client.post("/student/agent/grade", json={
                "question": "q", "user_answer": "a",
            })
        assert resp.status_code == 500


class TestStudentGradeStream:
    def test_basic(self, client):
        from fastapi.responses import StreamingResponse

        with patch("api.student_routes._langgraph_grade_stream") as mock_stream:

            async def fake_stream(*args, **kwargs):
                async def gen():
                    yield "data: {\"type\": \"done\"}\n\n"
                return StreamingResponse(gen(), media_type="text/event-stream")

            mock_stream.side_effect = fake_stream

            resp = client.post("/student/agent/grade/stream", json={
                "question": "1+1=?", "user_answer": "2",
            })
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")


# ═══════════════════════════ 辅助函数 ═══════════════════════════════════════════

class TestExtractGradingFromText:
    def test_json_block(self):
        from api.student_routes import _extract_grading_from_text
        text = '评分结果：{"score": 90, "max_score": 100, "feedback": "优秀"}'
        result = _extract_grading_from_text(text)
        assert result["score"] == 90
        assert result["max_score"] == 100

    def test_markdown_score(self):
        from api.student_routes import _extract_grading_from_text
        text = "评分：85/100，做得不错"
        result = _extract_grading_from_text(text)
        assert result["score"] == 85
        assert result["max_score"] == 100

    def test_score_pattern(self):
        from api.student_routes import _extract_grading_from_text
        text = "得分：95/100"
        result = _extract_grading_from_text(text)
        assert result["score"] == 95

    def test_no_match_returns_empty(self):
        from api.student_routes import _extract_grading_from_text
        result = _extract_grading_from_text("this is just plain text")
        assert result == {}

    def test_empty_input(self):
        from api.student_routes import _extract_grading_from_text
        assert _extract_grading_from_text("") == {}
        assert _extract_grading_from_text(None) == {}


class TestExtractGradingFromAgentResult:
    def test_from_grade_execute_step(self):
        from api.student_routes import _extract_grading_from_agent_result
        agent_result = {
            "answer": "final answer",
            "steps": [
                {"action": "grade_execute",
                 "result": '{"score": 88, "max_score": 100, "feedback": "good"}'},
            ],
        }
        result = _extract_grading_from_agent_result(agent_result)
        assert result["score"] == 88

    def test_from_final_answer_json(self):
        from api.student_routes import _extract_grading_from_agent_result
        agent_result = {
            "answer": '评分：{"score": 75, "max_score": 100}',
            "steps": [],
        }
        result = _extract_grading_from_agent_result(agent_result)
        assert result["score"] == 75

    def test_from_score_pattern(self):
        from api.student_routes import _extract_grading_from_agent_result
        agent_result = {
            "answer": "得分：92/100 ✅ 正确",
            "steps": [],
        }
        result = _extract_grading_from_agent_result(agent_result)
        assert result["score"] == 92
        assert result["is_correct"] is True

    def test_fallback(self):
        from api.student_routes import _extract_grading_from_agent_result
        result = _extract_grading_from_agent_result({"answer": "", "steps": []})
        assert result["score"] == 0
        assert "feedback" in result


class TestDirectGrade:
    def test_returns_dict(self):
        mock_grader = MagicMock()
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"score": 70, "is_correct": True}
        mock_grader.auto_detect_and_grade.return_value = mock_result

        with patch("agent.grading.UnifiedGrader", return_value=mock_grader):
            from api.student_routes import _direct_grade, GradingRequest
            req = GradingRequest(question="q", user_answer="a", correct_answer="c")
            result = _direct_grade(req)
        assert result["score"] == 70


# ═══════════════════════════ 错题集 ═════════════════════════════════════════════

class TestListWrongBook:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.list_wrong_book.return_value = [
            {"id": "w1", "question": "q", "grading": json.dumps({"score": 30}),
             "created_at": "2024-01-01T00:00:00"},
        ]
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.get("/student/wrong-book?subject=数学&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["wrong_book"][0]["grading"]["score"] == 30

    def test_empty(self, client):
        mock_db = MagicMock()
        mock_db.list_wrong_book.return_value = []
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.get("/student/wrong-book")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


class TestWrongBookStats:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.get_wrong_book_stats.return_value = {"total": 10, "by_subject": {"数学": 5}}
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.get("/student/wrong-book/stats")
        assert resp.status_code == 200
        assert resp.json()["total"] == 10


class TestDeleteWrongBook:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.delete_wrong_book.return_value = 1
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.delete("/student/wrong-book/wb_123")
        assert resp.status_code == 200

    def test_not_found(self, client):
        mock_db = MagicMock()
        mock_db.delete_wrong_book.return_value = 0
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.delete("/student/wrong-book/wb_missing")
        assert resp.status_code == 404


# ═══════════════════════════ 举一反三 ═══════════════════════════════════════════

class TestGenerateAnalogy:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.get_wrong_book_by_id.return_value = {
            "id": "wb_1", "user_id": "stu_abc123",
            "question": "math problem",
            "user_answer": "wrong",
            "subject": "数学", "question_type": "计算题",
            "grading": json.dumps({"score": 30, "feedback": "need work"}),
        }

        mock_tool = MagicMock()
        mock_tool.invoke.return_value = json.dumps({"analogies": [{"q": "q1"}, {"q": "q2"}]})

        with patch("api.student_routes.MySQLDB", return_value=mock_db), \
             patch("langgraph_agent.tools.analogy_question", mock_tool), \
             patch("langgraph_agent.tools.get_tool_provider") as mock_provider, \
             patch("llm.llm_client.LLMClient"):
            mock_provider.return_value.set_dependencies = MagicMock()
            resp = client.post("/student/wrong-book/wb_1/analogy")
        assert resp.status_code == 200
        assert "analogies" in resp.json() or "wb_id" in resp.json()

    def test_not_found_or_wrong_user(self, client):
        mock_db = MagicMock()
        mock_db.get_wrong_book_by_id.return_value = None
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.post("/student/wrong-book/wb_missing/analogy")
        assert resp.status_code == 404

    def test_db_error(self, client):
        mock_db = MagicMock()
        mock_db.get_wrong_book_by_id.side_effect = Exception("fail")
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.post("/student/wrong-book/wb_1/analogy")
        assert resp.status_code == 500


# ═══════════════════════════ 艾宾浩斯 ═══════════════════════════════════════════

class TestEbbinghaus:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.list_wrong_book.return_value = [
            {"id": "w1", "question": "q", "subject": "数学",
             "created_at": "2024-06-01T00:00:00",
             "review_count": 0, "last_reviewed_at": None},
        ]
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.get("/student/wrong-book/ebbinghaus")
        assert resp.status_code == 200
        data = resp.json()
        assert "curve" in data
        assert "items" in data
        assert "review_schedule" in data

    def test_empty(self, client):
        mock_db = MagicMock()
        mock_db.list_wrong_book.return_value = []
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.get("/student/wrong-book/ebbinghaus")
        assert resp.status_code == 200
        assert resp.json()["total_items"] == 0


class TestReviewWrongQuestion:
    def test_success(self, client):
        mock_db = MagicMock()
        mock_db.get_wrong_book_by_id.return_value = {
            "id": "w1", "user_id": "stu_abc123", "review_count": 2,
        }
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.post("/student/wrong-book/w1/review")
        assert resp.status_code == 200
        assert resp.json()["review_count"] == 3
        mock_db.review_wrong_book.assert_called_once_with("w1")

    def test_not_found(self, client):
        mock_db = MagicMock()
        mock_db.get_wrong_book_by_id.return_value = None
        with patch("api.student_routes.MySQLDB", return_value=mock_db):
            resp = client.post("/student/wrong-book/w_missing/review")
        assert resp.status_code == 404


# ═══════════════════════════ 知识图谱 ═══════════════════════════════════════════

class TestGraphData:
    def test_success(self, client):
        mock_entity = MagicMock()
        mock_entity.name = "三角函数"
        mock_entity.entity_type = "概念"
        mock_entity.subject = "数学"
        mock_entity.grade = "初中"
        mock_entity.display_name = "三角函数"

        mock_graph = MagicMock()
        mock_graph.entity_count = 1
        mock_graph.entities = {"三角函数": mock_entity}
        mock_graph.adjacency = {}

        mock_mgr = MagicMock()
        mock_mgr.get_graph.return_value = mock_graph

        with patch("data_processor.graph_builder.KnowledgeGraphManager", return_value=mock_mgr):
            resp = client.get("/student/graph/data?subject=数学&grade=初中")
        assert resp.status_code == 200
        data = resp.json()
        assert "entities" in data
        assert "relations" in data

    def test_empty_graph(self, client):
        mock_mgr = MagicMock()
        mock_mgr.get_graph.return_value = None
        with patch("data_processor.graph_builder.KnowledgeGraphManager", return_value=mock_mgr):
            resp = client.get("/student/graph/data")
        assert resp.status_code == 200
        assert resp.json()["stats"]["entity_count"] == 0

    def test_error(self, client):
        with patch("data_processor.graph_builder.KnowledgeGraphManager",
                   side_effect=Exception("fail")):
            resp = client.get("/student/graph/data")
        assert resp.status_code == 500


class TestGraphStats:
    def test_success(self, client):
        mock_graph = MagicMock()
        mock_graph.entity_count = 10
        mock_graph.get_stats.return_value = {"entity_count": 10, "relation_count": 25}

        mock_mgr = MagicMock()
        mock_mgr.get_graph.return_value = mock_graph

        with patch("data_processor.graph_builder.KnowledgeGraphManager", return_value=mock_mgr):
            resp = client.get("/student/graph/stats")
        assert resp.status_code == 200
        assert resp.json()["entity_count"] == 10

    def test_empty(self, client):
        mock_mgr = MagicMock()
        mock_mgr.get_graph.return_value = None
        with patch("data_processor.graph_builder.KnowledgeGraphManager", return_value=mock_mgr):
            resp = client.get("/student/graph/stats")
        assert resp.status_code == 200
        assert resp.json()["status"] == "empty"

    def test_error(self, client):
        with patch("data_processor.graph_builder.KnowledgeGraphManager",
                   side_effect=Exception("fail")):
            resp = client.get("/student/graph/stats")
        assert resp.status_code == 500


class TestGraphEntityDetail:
    def test_success(self, client):
        mock_entity = MagicMock()
        mock_entity.to_dict.return_value = {"name": "勾股定理", "type": "定理"}

        mock_graph = MagicMock()
        mock_graph.get_entity.return_value = mock_entity
        mock_graph.get_neighbors.return_value = []

        mock_mgr = MagicMock()
        mock_mgr.get_graph.return_value = mock_graph

        with patch("data_processor.graph_builder.KnowledgeGraphManager", return_value=mock_mgr):
            resp = client.get("/student/graph/entity/勾股定理")
        assert resp.status_code == 200
        assert "entity" in resp.json()

    def test_graph_not_loaded(self, client):
        mock_mgr = MagicMock()
        mock_mgr.get_graph.return_value = None
        with patch("data_processor.graph_builder.KnowledgeGraphManager", return_value=mock_mgr):
            resp = client.get("/student/graph/entity/勾股定理")
        assert resp.status_code == 404

    def test_entity_not_found(self, client):
        mock_graph = MagicMock()
        mock_graph.get_entity.return_value = None
        mock_mgr = MagicMock()
        mock_mgr.get_graph.return_value = mock_graph
        with patch("data_processor.graph_builder.KnowledgeGraphManager", return_value=mock_mgr):
            resp = client.get("/student/graph/entity/不存在")
        assert resp.status_code == 404

    def test_error(self, client):
        with patch("data_processor.graph_builder.KnowledgeGraphManager",
                   side_effect=Exception("fail")):
            resp = client.get("/student/graph/entity/勾股定理")
        assert resp.status_code == 500
