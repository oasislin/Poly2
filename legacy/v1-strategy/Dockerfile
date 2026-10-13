FROM python:3.12-slim

WORKDIR /app

# 安装必要的系统工具 (比如 curl，方便健康检查)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖清单并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源代码
COPY src/ ./src/

# 设置默认启动命令为运行主调度守护进程
CMD ["python", "src/main.py"]
