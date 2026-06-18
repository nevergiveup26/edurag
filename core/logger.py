"""
日志模块
提供统一的日志记录接口
"""
import sys
import os

# 添加项目根目录到path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.logging_config import LoggingConfig


def get_logger(name: str = "edurag") -> LoggingConfig:
    """
    获取logger实例
    
    Args:
        name: logger名称
        
    Returns:
        logging.Logger实例
    """
    from core.config_manager import ConfigManager
    
    config = ConfigManager()
    system_config = config.system_config
    
    return LoggingConfig.get_logger(
        name=name,
        log_file=system_config.get("log_file", "logs/app.log"),
        level=system_config.get("log_level", "INFO")
    )


# 创建默认logger
logger = get_logger("edurag")
