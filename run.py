"""
EduRAG智慧问答系统 - 项目启动入口
"""
import sys
import os
from pathlib import Path

# 添加项目根目录到path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn
from core.config_manager import ConfigManager
from core.logger import get_logger

logger = get_logger("run")


def start_api(host: str = "0.0.0.0", port: int = 8000, reload: bool = False):
    """启动FastAPI服务"""
    logger.info(f"启动API服务: http://{host}:{port}")
    server_kwargs = dict(host=host, port=port, reload=reload, log_level="info")
    if reload:
        # 只监视项目源码目录，避免扫描 .venv / __pycache__ / k6-master 等大目录
        server_kwargs["reload_dirs"] = [
            str(Path(__file__).parent / d)
            for d in ("api", "core", "langgraph_agent", "retriever",
                       "data_processor", "database", "llm", "config", "evaluation", "kb")
            if (Path(__file__).parent / d).is_dir()
        ]
    uvicorn.run("api.main:app", **server_kwargs)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="EduRAG智慧问答系统启动脚本")
    parser.add_argument("--host", default="0.0.0.0", help="API服务地址")
    parser.add_argument("--port", type=int, default=8000, help="API服务端口")
    parser.add_argument("--reload", action="store_true", help="开启热重载（开发模式）")

    args = parser.parse_args()

    start_api(host=args.host, port=args.port, reload=args.reload)