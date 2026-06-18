# EduRAG 智慧问答系统 Docker 镜像
# 全程云端模型，无需 GPU，镜像体积小
FROM python:3.10-slim

WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# 创建兼容 shim，避免 import 失败
RUN python -c "
import langchain_community, os
path = os.path.join(os.path.dirname(langchain_community.__file__), 'chat_models', 'vertexai.py')
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, 'w') as f:
    f.write('''from langchain_core.language_models.chat_models import BaseChatModel
class ChatVertexAI(BaseChatModel): pass
class VertexAI(BaseChatModel): pass
__all__ = [''ChatVertexAI'', ''VertexAI'']
''')
print(f'vertexai shim created at {path}')
"

# 复制项目代码
COPY . .

# 创建日志目录
RUN mkdir -p logs

# 暴露端口
EXPOSE 8000

# 环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# 启动命令
CMD ["python", "run.py", "--host", "0.0.0.0", "--port", "8000"]
