"""
配置管理器
读取config.ini配置文件并提供配置访问接口
支持 ${ENV_VAR} 环境变量插值
"""
import os
import re
import configparser
import threading
from typing import Any, Optional

_ENV_VAR_PATTERN = re.compile(r'\$\{(\w+)(?::([^}]*))?\}')


def _resolve_env(value: str) -> str:
    """将 ${VAR} 或 ${VAR:fallback} 替换为环境变量值"""
    if not isinstance(value, str):
        return value
    if not value:
        return value
    def _replacer(match):
        var_name = match.group(1)
        fallback = match.group(2) if match.group(2) is not None else ""
        return os.getenv(var_name, fallback)
    return _ENV_VAR_PATTERN.sub(_replacer, value)


class ConfigManager:
    """配置管理器单例类"""

    _instance = None
    _config = None
    _lock = threading.Lock()

    def __new__(cls, config_path: Optional[str] = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    if config_path is None:
                        config_path = os.path.join(
                            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "config", "config.ini"
                        )
                    cls._instance._config = configparser.ConfigParser()
                    cls._instance._config.read(config_path, encoding='utf-8')
        return cls._instance

    def get(self, section: str, key: str, fallback: Any = None) -> str:
        """获取配置值，自动解析 ${ENV_VAR} 引用"""
        try:
            raw = self._config.get(section, key, fallback=fallback)
            return _resolve_env(raw) if raw else raw
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback
    
    def getint(self, section: str, key: str, fallback: int = 0) -> int:
        """获取整数配置值，自动解析 ${ENV_VAR} 引用"""
        try:
            raw = self._config.get(section, key, fallback=str(fallback))
            resolved = _resolve_env(raw)
            return int(resolved) if resolved else fallback
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
            return fallback

    def getfloat(self, section: str, key: str, fallback: float = 0.0) -> float:
        """获取浮点数配置值，自动解析 ${ENV_VAR} 引用"""
        try:
            raw = self._config.get(section, key, fallback=str(fallback))
            resolved = _resolve_env(raw)
            return float(resolved) if resolved else fallback
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError):
            return fallback

    def getboolean(self, section: str, key: str, fallback: bool = False) -> bool:
        """获取布尔配置值，自动解析 ${ENV_VAR} 引用"""
        try:
            raw = self._config.get(section, key, fallback=str(fallback))
            resolved = _resolve_env(raw).lower()
            if resolved in ("true", "yes", "1", "on"):
                return True
            if resolved in ("false", "no", "0", "off"):
                return False
            return fallback
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback
    
    def get_section(self, section: str) -> dict:
        """获取整个section的配置"""
        if self._config.has_section(section):
            return dict(self._config[section])
        return {}
    
    # 便捷方法 - 数据库配置
    @property
    def mysql_config(self) -> dict:
        return {
            "host": self.get("database", "mysql_host", "localhost"),
            "port": self.getint("database", "mysql_port", 3306),
            "user": self.get("database", "mysql_user", "root"),
            "password": self.get("database", "mysql_password", ""),
            "database": self.get("database", "mysql_database", "edurag_db"),
            "charset": self.get("database", "mysql_charset", "utf8mb4")
        }
    
    @property
    def milvus_config(self) -> dict:
        return {
            "host": self.get("database", "milvus_host", "localhost"),
            "port": self.getint("database", "milvus_port", 19530),
            "collection": self.get("database", "milvus_collection", "edurag_collection"),
            "embedding_model": self.get("database", "embedding_model", ""),
            "embedding_dim": self.getint("database", "milvus_embedding_dim", 1024),
            "index_type": self.get("database", "milvus_index_type", "IVF_FLAT"),
            "metric_type": self.get("database", "milvus_metric_type", "L2")
        }
    
    @property
    def redis_config(self) -> dict:
        return {
            "host": self.get("database", "redis_host", "localhost"),
            "port": self.getint("database", "redis_port", 6379),
            "password": self.get("database", "redis_password", None) or None,
            "db": self.getint("database", "redis_db", 0),
            "ttl": self.getint("database", "redis_ttl", 3600)
        }
    
    # 便捷方法 - LLM配置
    @property
    def llm_config(self) -> dict:
        return {
            "model_name": self.get("llm", "model_name", "gpt-3.5-turbo"),
            "api_base": self.get("llm", "api_base", "https://api.openai.com/v1"),
            "api_key": self.get("llm", "api_key", ""),
            "temperature": self.getfloat("llm", "temperature", 0.7),
            "max_tokens": self.getint("llm", "max_tokens", 2000),
            "top_p": self.getfloat("llm", "top_p", 0.9),
            "timeout": self.getint("llm", "timeout", 60)
        }
    
    # 便捷方法 - 检索配置
    @property
    def retriever_config(self) -> dict:
        return {
            "top_k": self.getint("retriever", "top_k", 5),
            "similarity_threshold": self.getfloat("retriever", "similarity_threshold", 0.7),
            "bm25_weight": self.getfloat("retriever", "bm25_weight", 0.3),
            "vector_weight": self.getfloat("retriever", "vector_weight", 0.7),
            "rerank_enabled": self.getboolean("retriever", "rerank_enabled", True),
            "rerank_top_k": self.getint("retriever", "rerank_top_k", 3)
        }
    
    # 便捷方法 - DashScope 配置
    @property
    def dashscope_config(self) -> dict:
        return {
            "api_key": self.get("dashscope", "api_key", ""),
            "ocr_model": self.get("dashscope", "ocr_model", "qwen-vl-ocr"),
        }

    # 便捷方法 - Tavily 配置
    @property
    def tavily_config(self) -> dict:
        return {
            "api_key": self.get("tavily", "api_key", ""),
            "default_search_depth": self.get("tavily", "default_search_depth", "basic"),
            "default_max_results": self.getint("tavily", "default_max_results", 5),
        }

    # 便捷方法 - 系统配置
    @property
    def system_config(self) -> dict:
        return {
            "app_name": self.get("system", "app_name", "EduRAG智慧问答系统"),
            "debug": self.getboolean("system", "debug", False),
            "log_level": self.get("system", "log_level", "INFO"),
            "log_file": self.get("system", "log_file", "logs/app.log"),
            "max_concurrent_requests": self.getint("system", "max_concurrent_requests", 10),
            "request_timeout": self.getint("system", "request_timeout", 30)
        }
