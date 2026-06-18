"""
数据模型
定义系统中使用的核心数据模型
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class RetrievalStrategy(Enum):
    """检索策略枚举"""
    DIRECT = "direct"           # 直接检索
    HYDE = "hyde"              # HyDE策略
    SUB_QUERY = "sub_query"    # 子查询策略
    BACKTRACK = "backtrack"    # 回溯策略
    MULTIMODAL = "multimodal"  # 多模态检索策略


class ContentType(Enum):
    """内容类型枚举"""
    TEXT = "text"              # 纯文本
    IMAGE = "image"            # 图片
    TABLE = "table"            # 表格
    CHART = "chart"            # 图表
    MIXED = "mixed"            # 混合内容


class RouterType(Enum):
    """路由类型枚举"""
    RULE = "rule"              # 规则路由
    SIMILARITY = "similarity"  # 相似度路由
    LLM = "llm"               # LLM路由


@dataclass
class Document:
    """文档数据模型"""
    content: str
    doc_id: Optional[str] = None
    title: Optional[str] = None
    source: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


@dataclass
class DocumentChunk:
    """文档片段数据模型"""
    content: str
    chunk_id: Optional[str] = None
    doc_id: Optional[str] = None
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0


@dataclass
class RetrievalResult:
    """检索结果数据模型"""
    chunk: DocumentChunk
    score: float
    source: str  # bm25 / vector / hybrid


@dataclass
class QueryRequest:
    """查询请求数据模型"""
    query: str
    strategy: RetrievalStrategy = RetrievalStrategy.DIRECT
    router_type: RouterType = RouterType.SIMILARITY
    top_k: int = 5
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None
    history: List[Dict[str, str]] = field(default_factory=list)
    kb_id: Optional[str] = None  # 知识库ID，用于限定检索范围
    rewritten_query: Optional[str] = None  # LLM重写后的查询（用于检索）
    metadata_filter: Dict[str, Any] = field(default_factory=dict)  # 元数据过滤条件 {"subject": "数学", "grade": "初中"}
    enable_self_rag: bool = True  # 是否启用 Self-RAG 质量循环
    enable_multi_query: bool = True  # 是否启用 Multi-Query 多查询检索


@dataclass
class QueryResponse:
    """查询响应数据模型"""
    answer: str
    sources: List[RetrievalResult] = field(default_factory=list)
    strategy_used: str = ""
    router_used: str = ""
    execution_time: float = 0.0
    conversation_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "answer": self.answer,
            "sources": [
                {
                    "content": r.chunk.content,
                    "score": r.score,
                    "source": r.source,
                    "metadata": r.chunk.metadata
                }
                for r in self.sources
            ],
            "strategy_used": self.strategy_used,
            "router_used": self.router_used,
            "execution_time": self.execution_time,
            "conversation_id": self.conversation_id
        }


@dataclass
class FAQItem:
    """FAQ数据模型"""
    question: str
    answer: str
    category: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    embedding: Optional[List[float]] = None
    faq_id: Optional[str] = None


@dataclass
class MultiModalChunk(DocumentChunk):
    """多模态文档片段"""
    content_type: str = "text"           # text/image/table/chart/mixed
    image_path: Optional[str] = None     # 图片文件路径
    image_base64: Optional[str] = None   # 图片base64编码
    image_description: Optional[str] = None  # 图片的文本描述（由视觉模型生成）
    image_embedding: Optional[List[float]] = None  # 图片的CLIP向量
    table_data: Optional[str] = None     # 表格数据（JSON字符串）
    parent_text: Optional[str] = None    # 所属文本上下文


@dataclass
class AgentMessage:
    """Agent对话消息"""
    role: str          # user / assistant / system / tool
    content: str
    tool_calls: Optional[List[dict]] = None
    tool_call_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "tool_calls": self.tool_calls,
            "tool_call_id": self.tool_call_id,
        }


@dataclass
class ToolCall:
    """工具调用"""
    name: str                           # 工具名称
    arguments: Dict[str, Any]           # 调用参数
    call_id: Optional[str] = None       # 调用ID
    result: Optional[str] = None        # 执行结果


@dataclass
class AgentStep:
    """Agent执行步骤（ReAct循环中的单步）"""
    step_index: int                     # 步骤序号
    thought: str = ""                   # 思考过程
    action: Optional[ToolCall] = None   # 执行的动作
    observation: str = ""               # 观察结果
    finished: bool = False              # 是否完成任务


@dataclass
class AgentResponse:
    """Agent最终响应"""
    answer: str                                   # 最终答案
    steps: List[AgentStep] = field(default_factory=list)  # 执行步骤记录
    tool_calls: List[ToolCall] = field(default_factory=list)  # 所有工具调用
    strategy_used: str = "agentic"                # 策略名
    execution_time: float = 0.0                   # 执行耗时
    conversation_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "steps": [
                {
                    "step": s.step_index,
                    "thought": s.thought[:200],
                    "action": s.action.name if s.action else None,
                    "observation": s.observation[:200],
                }
                for s in self.steps
            ],
            "tool_calls_count": len(self.tool_calls),
            "strategy_used": self.strategy_used,
            "execution_time": self.execution_time,
            "conversation_id": self.conversation_id,
        }
