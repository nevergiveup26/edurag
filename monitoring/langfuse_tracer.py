"""
Langfuse 全链路追踪模块 (v4 API)

集成 Langfuse v4 实现 RAG 系统的可观测性：
- Trace: 完整查询链（用户Query → 路由 → 检索 → 生成 → 答案）
- Observation: 每个步骤的 span（嵌套在 trace 下）
- Score: 质量评分反馈
- 实时数据存内存供前端即时查询，Langfuse 云端做持久化归档

环境变量配置：
- LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST
"""

import time
import uuid
import os
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

from core.logger import get_logger

logger = get_logger("langfuse_tracer")


class TraceSession:
    """Per-request trace handle — safe for concurrent async requests.

    Each request gets its own TraceSession, avoiding the instance-level
    mutable state problem that would occur with multiple concurrent coroutines.
    """

    def __init__(self, langfuse_client, query: str, conversation_id: str = None,
                 user_id: str = None, strategy: str = "langgraph_agent", top_k: int = 5):
        self._langfuse = langfuse_client
        self.trace_id = str(uuid.uuid4())
        self._span = None
        self.query = query
        self.strategy = strategy
        self.top_k = top_k
        self.start_time = time.time()
        self._observations: List[dict] = []
        self._ended = False  # 防止 span.end() 被重复调用

        # 稳定 trace name，用 strategy 作为 use case 名
        trace_name = strategy if strategy and strategy != "direct" else "chat_query"

        if self._langfuse:
            try:
                self._span = self._langfuse.start_observation(
                    trace_id=self.trace_id,
                    name=trace_name,
                    input={"query": query, "conv_id": conversation_id, "user_id": user_id},
                    metadata={"strategy": strategy, "top_k": top_k,
                              "conversation_id": conversation_id, "user_id": user_id},
                    user_id=user_id,
                )
            except TypeError:
                # v4.7+: trace_id / user_id args removed, use trace_context instead
                try:
                    self._span = self._langfuse.start_observation(
                        name=trace_name,
                        input={"query": query, "conv_id": conversation_id, "user_id": user_id},
                        metadata={"strategy": strategy, "top_k": top_k,
                                  "conversation_id": conversation_id, "user_id": user_id},
                        user_id=user_id,
                    )
                except TypeError:
                    self._span = self._langfuse.start_observation(
                        name=trace_name,
                        input={"query": query, "conv_id": conversation_id, "user_id": user_id},
                        metadata={"strategy": strategy, "top_k": top_k,
                                  "conversation_id": conversation_id, "user_id": user_id},
                    )
                self.trace_id = self._span.trace_id

        logger.debug(f"[Langfuse] Trace created: {self.trace_id} query={query[:50]}")

    def log_observation(self, name: str, input_data: Any = None,
                        output_data: Any = None, metadata: dict = None,
                        start_time: float = None, end_time: float = None,
                        level: str = "DEFAULT", model: str = None,
                        as_type: str = None, usage: dict = None,
                        prompt_name: str = None, completion_start_time: float = None):
        """Log an observation (span/generation) under this trace."""
        latency_ms = None
        if start_time and end_time:
            latency_ms = (end_time - start_time) * 1000

        obs_data = {
            "name": name,
            "input": input_data,
            "output": output_data,
            "metadata": metadata or {},
            "latency_ms": latency_ms,
            "level": level,
        }
        if model:
            obs_data["model"] = model
        if usage:
            obs_data["usage"] = usage
        self._observations.append(obs_data)

        if self._langfuse and self._span:
            try:
                child_kwargs = {
                    "name": name, "input": input_data, "output": output_data,
                    "metadata": metadata, "level": level,
                }
                if model:
                    child_kwargs["model"] = model
                if as_type:
                    child_kwargs["as_type"] = as_type
                if usage:
                    child_kwargs["usage"] = usage
                child = self._span.start_observation(**child_kwargs)
                child.update(output=output_data)
            except TypeError as e:
                # 降级：移除可能不支持的参数
                try:
                    child = self._span.start_observation(
                        name=name, input=input_data, output=output_data,
                        metadata=metadata, level=level,
                    )
                    child.update(output=output_data)
                except TypeError:
                    try:
                        child = self._span.start_observation(
                            name=name, input=input_data, output=output_data,
                            metadata=metadata,
                        )
                        child.update(output=output_data)
                    except Exception as e:
                        logger.debug(f"Langfuse observation fallback 失败: {e}")
            except Exception as e:
                logger.warning(f"Langfuse observation failed: {e}")

        logger.debug(f"[Langfuse] {name}: {latency_ms:.0f}ms" if latency_ms else f"[Langfuse] {name}")

    @contextmanager
    def span(self, name: str, metadata: dict = None):
        """Context manager that auto-records span duration."""
        start = time.time()
        obs_data = {"name": name, "metadata": metadata or {}}
        try:
            yield obs_data
        finally:
            end = time.time()
            self.log_observation(
                name=name, input_data=obs_data.get("input"),
                output_data=obs_data.get("output"),
                metadata=obs_data.get("metadata"),
                start_time=start, end_time=end,
            )

    def update(self, output: Any = None, status: str = None,
               metadata: dict = None, retrieved_chunks: list = None):
        """Update trace with final output and optional token usage."""
        if self._langfuse and self._span:
            try:
                update_kwargs = {}
                if output is not None:
                    update_kwargs["output"] = output
                if metadata:
                    existing_meta = getattr(self._span, "metadata", {}) or {}
                    existing_meta.update(metadata)
                    update_kwargs["metadata"] = existing_meta
                if update_kwargs:
                    self._span.update(**update_kwargs)
                # v4.7.1: 必须调用 end() 才能让 OTEL 导出器发送 span
                if not self._ended:
                    self._span.end()
                    self._ended = True
                    logger.debug(f"[Langfuse] span ended: {self.trace_id}")
            except Exception as e:
                logger.warning(f"Langfuse trace update failed: {e}")

    def score(self, name: str, value: float, comment: str = ""):
        """Record a quality score on this trace."""
        if self._langfuse and self._span:
            try:
                self._span.score(name=name, value=value, comment=comment)
            except Exception as e:
                try:
                    self._langfuse.create_score(
                        trace_id=self.trace_id, name=name, value=value, comment=comment,
                    )
                except Exception as e2:
                    logger.debug(f"Langfuse create_score 失败: {e2}")
        logger.info(f"[Langfuse Score] {name}={value:.4f}")

    def flush(self):
        """Ensure all data is sent to Langfuse."""
        if self._langfuse:
            try:
                self._langfuse.flush()
                logger.info("Langfuse data flushed")
                # v4.7.1: flush 可能不够可靠，额外尝试 force_flush
                if hasattr(self._langfuse, '_task_manager'):
                    tm = self._langfuse._task_manager
                    if hasattr(tm, 'flush'):
                        tm.flush()
                        logger.info("Langfuse task_manager flushed")
            except Exception as e:
                logger.warning(f"Langfuse flush failed: {e}")

    def to_dict(self) -> dict:
        """Convert to dict for in-memory storage / frontend queries."""
        return {
            "id": self.trace_id,
            "trace_id": self.trace_id,
            "query": self.query,
            "strategy": self.strategy,
            "top_k": self.top_k,
            "start_time": self.start_time,
            "observations": self._observations,
        }


class LangfuseTracer:
    """
    Langfuse v4 追踪器

    - v4 API: start_observation() 创建 trace/span，span.start_observation() 创建子 span
    - 内存存储会话内 trace 供前端即时查询
    - Langfuse 云端持久化，可通过 get_trace_url() 跳转查看
    """

    def __init__(self):
        from core.config_manager import ConfigManager
        self._config = ConfigManager()
        self._langfuse = None
        self._available = False
        self._traces: List[dict] = []  # 内存存储（实时查询用）
        self._sessions: List[TraceSession] = []  # 活跃的 TraceSession
        self.enabled = (
            os.getenv("LANGFUSE_ENABLED",
                      self._config.get("langfuse", "enabled", "true")).lower() != "false"
        )
        self._init_langfuse()

    def _init_langfuse(self):
        """初始化 Langfuse v4 客户端"""
        if not self.enabled:
            logger.info("Langfuse 追踪已禁用 (LANGFUSE_ENABLED=false)")
            return

        try:
            from langfuse import Langfuse
            public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
            secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")

            host = (
                os.getenv("LANGFUSE_HOST", "")
                or self._config.get("langfuse", "host", "")
                or "https://us.cloud.langfuse.com"
            )

            if public_key and secret_key:
                env = os.getenv("LANGFUSE_ENV", "default")
                self._langfuse = Langfuse(
                    public_key=public_key,
                    secret_key=secret_key,
                    host=host,
                    environment=env,
                )
                self._langfuse.auth_check()
                self._available = True
                # 检查 OTEL tracer provider 是否被代理（ProxyTracerProvider 不发送数据）
                try:
                    if hasattr(self._langfuse, '_resources') and self._langfuse._resources:
                        tp = self._langfuse._resources.tracer_provider
                        tp_type = type(tp).__name__
                        from opentelemetry import trace as _otel_trace
                        is_proxy = isinstance(tp, _otel_trace.ProxyTracerProvider)
                        logger.info(f"Langfuse 追踪已启用: {host} (env={env}) [OTEL: {tp_type}, proxy={is_proxy}]")
                    else:
                        logger.info(f"Langfuse 追踪已启用: {host} (env={env})")
                except Exception:
                    logger.info(f"Langfuse 追踪已启用: {host} (env={env})")
            else:
                logger.info("Langfuse 凭据未配置，使用内存模拟追踪")
        except ImportError:
            logger.info("langfuse 未安装，使用内存模拟追踪 (pip install langfuse)")
        except Exception as e:
            logger.warning(f"Langfuse 初始化失败: {e}，使用内存模拟追踪")

    def start_session(self, query: str, conversation_id: str = None,
                      user_id: str = None, strategy: str = "langgraph_agent",
                      top_k: int = 5) -> TraceSession:
        """Create a new TraceSession — safe for concurrent use.

        This is the recommended API for instrumenting request handlers.
        Each call creates an isolated session with its own trace_id and state.
        """
        session = TraceSession(
            langfuse_client=self._langfuse if self._available else None,
            query=query,
            conversation_id=conversation_id,
            user_id=user_id,
            strategy=strategy,
            top_k=top_k,
        )
        self._sessions.append(session)
        self._traces.append(session.to_dict())
        return session

    # ======================== Trace 生命周期 ========================

    def create_trace(self, query: str, conversation_id: str = None,
                     user_id: str = None, strategy: str = "direct",
                     top_k: int = 5) -> str:
        """创建追踪，返回 trace_id"""
        import uuid
        trace_id = str(uuid.uuid4())
        self._current_trace_id = trace_id

        trace_data = {
            "id": trace_id,
            "name": f"query: {query[:80]}",
            "query": query,
            "strategy": strategy,
            "top_k": top_k,
            "status": "running",
            "start_time": time.time(),
            "input": {"query": query, "conv_id": conversation_id, "user_id": user_id},
            "metadata": {"conversation_id": conversation_id, "user_id": user_id},
            "observations": [],
            "retrieved_chunks": [],
        }
        self._traces.append(trace_data)

        # v4 API: start_observation 创建顶层 trace
        if self._available:
            try:
                self._current_span = self._langfuse.start_observation(
                    trace_id=trace_id,
                    name=trace_data["name"],
                    input=trace_data["input"],
                    metadata={"strategy": strategy, "top_k": top_k, **trace_data["metadata"]},
                )
            except TypeError:
                # v4.7+ 移除了 trace_id 参数，改用 trace_context
                self._current_span = self._langfuse.start_observation(
                    name=trace_data["name"],
                    input=trace_data["input"],
                    metadata={"strategy": strategy, "top_k": top_k, **trace_data["metadata"]},
                )
                self._current_trace_id = self._current_span.trace_id
                trace_data["id"] = self._current_span.trace_id
            except Exception as e:
                logger.warning(f"Langfuse trace 创建失败: {e}")

        logger.debug(f"[Langfuse] Trace 创建: {self._current_trace_id} query={query[:50]}")
        return self._current_trace_id

    def update_trace(self, output: Any = None, metadata: dict = None,
                      status: str = None, strategy: str = None,
                      end_time: float = None, retrieved_chunks: list = None):
        """更新当前追踪"""
        if not self._current_trace_id:
            return

        for t in self._traces:
            if t["id"] == self._current_trace_id:
                if output is not None:
                    t["output"] = output
                if metadata:
                    t["metadata"].update(metadata)
                if status is not None:
                    t["status"] = status
                if strategy is not None:
                    t["strategy"] = strategy
                if end_time is not None:
                    t["end_time"] = end_time
                if retrieved_chunks is not None:
                    t["retrieved_chunks"] = retrieved_chunks
                break

        if self._available and self._current_span:
            try:
                update_kwargs = {}
                if output is not None:
                    update_kwargs["output"] = output
                if metadata:
                    update_kwargs["metadata"] = metadata
                if update_kwargs:
                    self._current_span.update(**update_kwargs)
            except Exception as e:
                logger.warning(f"Langfuse trace 更新失败: {e}")

    # ======================== Observation (Span) ========================

    def log_observation(self, name: str, input_data: Any = None,
                        output_data: Any = None, metadata: dict = None,
                        start_time: float = None, end_time: float = None):
        """记录一个观察（span 或 generation），挂载在当前 trace 下"""
        if not self._current_trace_id:
            return

        latency_ms = None
        if start_time and end_time:
            latency_ms = (end_time - start_time) * 1000

        obs_data = {
            "name": name,
            "input": input_data,
            "output": output_data,
            "metadata": metadata or {},
            "latency_ms": latency_ms,
        }

        for t in self._traces:
            if t["id"] == self._current_trace_id:
                t["observations"].append(obs_data)
                break

        if self._available and self._current_span:
            try:
                child = self._current_span.start_observation(
                    name=name,
                    input=input_data,
                    output=output_data,
                    metadata=metadata,
                )
                child.update(output=output_data)
            except Exception as e:
                logger.warning(f"Langfuse observation 记录失败: {e}")

        logger.debug(
            f"[Langfuse] {name}: {latency_ms:.0f}ms" if latency_ms else f"[Langfuse] {name}"
        )

    @contextmanager
    def span(self, name: str, metadata: dict = None):
        """上下文管理器 — 自动记录 span 耗时"""
        start = time.time()
        obs = {"name": name, "metadata": metadata or {}}
        try:
            yield obs
        finally:
            end = time.time()
            self.log_observation(
                name=name,
                input_data=obs.get("input"),
                output_data=obs.get("output"),
                metadata=obs.get("metadata"),
                start_time=start,
                end_time=end,
            )

    # ======================== Score ========================

    def log_score(self, name: str, value: float, comment: str = ""):
        """记录质量评分"""
        if self._available and self._current_span:
            try:
                self._current_span.score(name=name, value=value, comment=comment)
            except Exception as e:
                logger.warning(f"Langfuse score 记录失败: {e}")
                try:
                    self._langfuse.create_score(
                        trace_id=self._current_trace_id,
                        name=name,
                        value=value,
                        comment=comment,
                    )
                except Exception as e2:
                    logger.debug(f"Langfuse create_score 备用失败: {e2}")
        logger.info(f"[Langfuse Score] {name}={value:.4f}")

    # ======================== Flush ========================

    def flush(self):
        """确保所有数据发送到 Langfuse"""
        if self._available:
            try:
                self._langfuse.flush()
                logger.debug("Langfuse 数据已刷新")
            except Exception as e:
                logger.warning(f"Langfuse flush 失败: {e}")

    # ======================== 查询 ========================

    def get_current_trace(self) -> Optional[dict]:
        """获取当前追踪的完整数据"""
        if not self._current_trace_id:
            return None
        for t in self._traces:
            if t["id"] == self._current_trace_id:
                return {
                    "trace_id": t["id"],
                    "name": t["name"],
                    "input": t["input"],
                    "output": t.get("output"),
                    "observations": t["observations"],
                    "duration_s": time.time() - t["start_time"],
                }
        return None

    def get_trace_url(self, trace_id: str = None) -> Optional[str]:
        """获取 Langfuse 上该 trace 的 URL"""
        if self._available:
            try:
                return self._langfuse.get_trace_url(trace_id=trace_id or self._current_trace_id)
            except Exception as e:
                logger.debug(f"Langfuse get_trace_url 失败: {e}")
        return None

    def list_traces(self, limit: int = 20) -> List[dict]:
        """列出最近的追踪 — 云端 + 内存合并"""
        from datetime import datetime
        seen_ids = set()
        result = []

        # 从 Langfuse 云端拉取历史
        if self._available:
            try:
                raw = self._langfuse.api.trace.list(limit=limit, order_by="timestamp.desc")
                for t in (raw.data or []):
                    seen_ids.add(t.id)
                    result.append({
                        "trace_id": t.id,
                        "query": (t.input or {}).get("query", "")[:80] if t.input else (t.name or ""),
                        "strategy": (t.metadata or {}).get("strategy", "direct") if t.metadata else "direct",
                        "duration_ms": round(t.duration) if t.duration else 0,
                        "status": "success",
                        "timestamp": t.timestamp.isoformat() if t.timestamp else None,
                    })
            except Exception as e:
                logger.warning(f"Langfuse 云端查询失败: {e}")

        # 内存中的会话 trace（实时，未被云端覆盖的部分）
        for t in reversed(self._traces):
            if t["id"] not in seen_ids:
                start_ts = t.get("start_time", 0)
                end_ts = t.get("end_time") or time.time()
                duration_ms = round((end_ts - start_ts) * 1000)
                result.append({
                    "trace_id": t["id"],
                    "query": t.get("query", "")[:80],
                    "strategy": t.get("strategy", "direct"),
                    "duration_ms": duration_ms,
                    "status": t.get("status", "unknown"),
                    "timestamp": datetime.fromtimestamp(start_ts).isoformat() if start_ts else None,
                })

        return result[:limit]

    def get_trace(self, trace_id: str) -> Optional[dict]:
        """获取 trace 详情 — 内存优先（实时），云端 fallback"""
        from datetime import datetime

        # 内存查找（会话内的实时 trace）
        for t in self._traces:
            if t["id"] == trace_id:
                start_ts = t.get("start_time", 0)
                end_ts = t.get("end_time") or time.time()
                duration_ms = round((end_ts - start_ts) * 1000)
                steps = []
                for obs in t.get("observations", []):
                    steps.append({
                        "name": obs.get("name", "unknown"),
                        "description": str(obs.get("output", ""))[:200] if obs.get("output") else "",
                        "duration_ms": round(obs.get("latency_ms", 0)) if obs.get("latency_ms") else None,
                        "status": "error" if obs.get("name") == "error" else "success",
                    })
                return {
                    "trace_id": t["id"],
                    "query": t.get("query", ""),
                    "strategy": t.get("strategy", "direct"),
                    "duration_ms": duration_ms,
                    "status": t.get("status", "unknown"),
                    "top_k": t.get("top_k", 5),
                    "timestamp": datetime.fromtimestamp(start_ts).isoformat() if start_ts else None,
                    "steps": steps,
                    "retrieved_chunks": t.get("retrieved_chunks", []),
                    "langfuse_url": self.get_trace_url(trace_id),
                }

        # 云端 fallback
        if self._available:
            try:
                t = self._langfuse.api.trace.get(trace_id)
                steps = []
                try:
                    obs_list = self._langfuse.api.observations.get_many(
                        trace_id=trace_id, limit=50
                    )
                    for obs in (obs_list.data or []):
                        steps.append({
                            "name": obs.name or "unknown",
                            "description": (str(obs.output)[:200]) if obs.output else "",
                            "duration_ms": round(obs.latency) if obs.latency else None,
                            "status": "error" if getattr(obs, 'level', '') == "ERROR" else "success",
                        })
                except Exception as e:
                    logger.debug(f"Langfuse observations 获取失败: {e}")
                return {
                    "trace_id": t.id,
                    "query": (t.input or {}).get("query", "") if t.input else (t.name or ""),
                    "strategy": (t.metadata or {}).get("strategy", "direct") if t.metadata else "direct",
                    "duration_ms": round(t.duration) if t.duration else 0,
                    "status": "success",
                    "top_k": (t.metadata or {}).get("top_k", 5) if t.metadata else 5,
                    "timestamp": t.timestamp.isoformat() if t.timestamp else None,
                    "steps": steps,
                    "retrieved_chunks": (t.metadata or {}).get("retrieved_chunks", []) if t.metadata else [],
                    "langfuse_url": self.get_trace_url(trace_id),
                }
            except Exception as e:
                logger.warning(f"Langfuse 云端读取失败: {e}")

        return None


# 全局单例
_tracer: Optional[LangfuseTracer] = None


def get_tracer() -> LangfuseTracer:
    global _tracer
    if _tracer is None:
        _tracer = LangfuseTracer()
    return _tracer


def start_trace(query: str, conversation_id: str = None, user_id: str = None,
                strategy: str = "langgraph_agent", top_k: int = 5) -> TraceSession:
    """Shortcut: create a new TraceSession from the global tracer."""
    return get_tracer().start_session(
        query=query, conversation_id=conversation_id, user_id=user_id,
        strategy=strategy, top_k=top_k,
    )
