# syntax=docker/dockerfile:1

# Text-to-SQL Agent 后端镜像。
# 说明：生产 Bootstrap 依赖完整仓库检出（evaluation/ 语义 manifest 等），
# 因此构建上下文必须是仓库根目录，而不是仅安装 wheel。

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv/text-to-sql-agent

# 仅先拷贝依赖声明，最大化构建缓存命中。
COPY pyproject.toml README.md LICENSE ./
COPY app ./app
COPY tools ./tools
COPY evaluation ./evaluation

RUN pip install --no-cache-dir . \
    && pip install --no-cache-dir "uvicorn==0.35.0"

# 非 root 运行。
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# 必需环境变量（示例，见 docs/部署与回滚.md）：
#   TEXT_TO_SQL_DATABASE_DSN          只读账号 DSN
#   TEXT_TO_SQL_LLM_BASE_URL / API_KEY / MODEL_NAME
#   TEXT_TO_SQL_EMBEDDING_*           Embedding 服务配置
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=4).status==200 else 1)" || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
