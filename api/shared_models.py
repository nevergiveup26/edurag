"""共享 Pydantic 模型（routes.py / agent_routes.py 共用）"""
from typing import Optional, List
from pydantic import BaseModel, Field


class QueryRequestModel(BaseModel):
    query: str = Field(..., description="用户查询", min_length=1, max_length=2000)
    images: Optional[List[str]] = Field(default=None, description="base64 图片列表（可选）")
    strategy: str = Field(default="auto", description="检索策略")
    top_k: int = Field(default=5, description="返回结果数量", ge=1, le=20)
    user_id: Optional[str] = Field(default=None, description="用户ID")
    conversation_id: Optional[str] = Field(default=None, description="会话ID")
    history: List[dict] = Field(default=[], description="历史对话记录")
    kb_id: Optional[str] = Field(default=None, description="知识库ID")


class SourceItem(BaseModel):
    content: str = Field(..., description="文档片段内容")
    score: float = Field(..., description="相似度分数")
    source: str = Field(..., description="来源类型: bm25/vector/hybrid/faq")
    metadata: dict = Field(default={}, description="元数据")


class QueryResponseModel(BaseModel):
    answer: str = Field(..., description="生成的答案")
    sources: List[SourceItem] = Field(default=[], description="参考来源列表")
    strategy_used: str = Field(default="", description="实际使用的策略")
    router_used: str = Field(default="", description="实际使用的路由方式")
    execution_time: float = Field(default=0.0, description="执行耗时(秒)")
    conversation_id: Optional[str] = Field(default=None, description="会话ID")


class UploadResponse(BaseModel):
    message: str
    doc_count: int
    chunk_count: int
    skipped_duplicates: int = 0
    chunk_duplicates_removed: int = 0
    dedup_details: List[dict] = []


class ConversationMessage(BaseModel):
    role: str = Field(..., description="角色: user/assistant")
    content: str = Field(..., description="消息内容")
    timestamp: Optional[str] = Field(default=None, description="时间戳")


class FeedbackRequest(BaseModel):
    query_id: Optional[str] = None
    conversation_id: Optional[str] = None
    kb_id: Optional[str] = None
    query: Optional[str] = ""
    answer: Optional[str] = ""
    rating: int = Field(ge=1, le=5, description="评分1-5")
    comment: Optional[str] = ""
    strategy_used: Optional[str] = ""
    router_used: Optional[str] = ""
    response_time_ms: int = 0
    metadata: Optional[dict] = None
