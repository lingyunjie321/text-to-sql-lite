# Text-to-SQL Agent

当前仓库正在按 MVP 规格重新实现 PostgreSQL + Pagila 的安全
Text-to-SQL 闭环。

第一开发阶段已实现：

- 固定 PostgreSQL 16.14 和 Pagila 3.1.0 快照；
- 环境变量配置与启动校验；
- psycopg 3 连接池；
- 数据库强制只读执行；
- 30 秒默认超时、1000 行返回上限和截断标记；
- PostgreSQL 值的 JSON 稳定表示；
- SQLSTATE 错误归一化、脱敏和有限连接重试；
- 单元测试与真实 PostgreSQL 集成测试。

Schema introspection 和版本指纹属于第二阶段，尚未实现。

## 本地准备

需要：

- Python 3.12；
- Docker Desktop 和 Docker Compose 5；
- 可访问 GitHub 以首次下载锁定 Pagila 快照。

创建环境并安装依赖：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
```

下载并校验 Pagila：

```bash
.venv/bin/python tools/fetch_pagila.py \
  --manifest infrastructure/pagila/manifest.json \
  --output tests/fixtures/pagila/upstream
```

下载的 SQL 文件属于可再生成的本地 fixture，已被 Git 忽略。

## 启动 PostgreSQL

在当前终端创建仅用于本地开发的临时凭据：

```bash
export PAGILA_POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export PAGILA_APP_USER="text_to_sql_reader"
export PAGILA_APP_PASSWORD="$(openssl rand -hex 24)"
export PAGILA_HOST_PORT="55432"
export TEXT_TO_SQL_DATABASE_DSN="postgresql://${PAGILA_APP_USER}:${PAGILA_APP_PASSWORD}@127.0.0.1:${PAGILA_HOST_PORT}/pagila"
```

启动并等待健康检查：

```bash
docker compose -f infrastructure/pagila/compose.yaml config --quiet
docker compose -f infrastructure/pagila/compose.yaml up -d --wait
```

数据库首次创建时会导入锁定 Pagila 数据，并创建只读应用角色。

## 运行测试

单元测试不需要数据库：

```bash
.venv/bin/pytest tests/unit -v
```

集成测试要求上述容器正在运行，且同一终端仍保留
`TEXT_TO_SQL_DATABASE_DSN`：

```bash
.venv/bin/pytest tests/integration -v -m integration
```

运行确定性检查：

```bash
.venv/bin/python -m compileall -q app tools tests
docker compose -f infrastructure/pagila/compose.yaml config --quiet
```

## 停止服务

正常停止不会删除 Pagila 数据卷：

```bash
docker compose -f infrastructure/pagila/compose.yaml down
```

不要把删除数据卷作为日常 teardown。只有确认不再需要本地 Pagila 数据时，
才应单独决定是否删除该命名卷。

## 安全说明

- 不要把真实 DSN 或密码写进 `.env.example`、源码、提交或日志；
- Connector 不负责 SQL 安全解析，SQLGlot AST 安全门属于后续阶段；
- 第一阶段的只读账号和只读事务是数据库侧第二道防线，不替代上层校验。
