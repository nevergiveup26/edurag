"""
日志配置模块
定义统一的日志格式和处理器配置
"""
import os
import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler


class LoggingConfig:
    """日志配置类"""
    
    # 日志格式
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
    CONSOLE_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
    
    # 日志级别映射
    LEVEL_MAP = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL
    }
    
    @classmethod
    def get_logger(cls, name: str, 
                   log_file: str = "logs/app.log",
                   level: str = "INFO",
                   max_bytes: int = 10 * 1024 * 1024,
                   backup_count: int = 5) -> logging.Logger:
        """获取logger实例"""
        logger = logging.getLogger(name)
        
        # 避免重复添加handler
        if logger.handlers:
            return logger
        
        # 设置日志级别
        log_level = cls.LEVEL_MAP.get(level.upper(), logging.INFO)
        logger.setLevel(log_level)
        
        # 创建日志目录
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        # 文件handler - 按大小轮转
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(cls.LOG_FORMAT, datefmt=cls.DATE_FORMAT)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
        
        # 错误日志单独文件
        error_handler = RotatingFileHandler(
            log_file.replace('.log', '_error.log'),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(file_formatter)
        logger.addHandler(error_handler)
        
        # 控制台handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_formatter = logging.Formatter(cls.CONSOLE_FORMAT, datefmt=cls.DATE_FORMAT)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
        
        return logger
