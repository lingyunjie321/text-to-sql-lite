# 本地工具阶段 6 设计

## 目标与边界

阶段 6 把现有 FastAPI 后端和 Next.js 前端包装成一个可安装、可启动、可停止的
本地工具，并补齐安装、配置、架构、交接和排障文档。核心 Text-to-SQL Workflow、
Profile API、Connector 与前端业务页面不在本阶段重构。

现有 Connector Factory、Profile Store、Runtime Registry、PostgreSQL/Pagila、
MySQL/Sakila、BM25-only、动态本地模型和前端模型设置测试继续作为阶段 6 的验证
基础，不复制同类测试。完整配置到查询的真实数据库用例继续由既有 Profile-ID API
E2E 承担；前端数据源配置闭环属于阶段 5 后续切片，不在阶段 6 暗中扩展。

## 启动架构

新增 `text-to-sql-lite start` 命令。CLI 先检查 Python 版本、Node.js、npm、前端目录
与已安装依赖，然后创建 `~/.text-to-sql-lite`，再分别启动：

- `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
- `npm run dev -- --hostname 127.0.0.1 --port 3000`

CLI 向前端进程注入 `TEXT_TO_SQL_API_URL=http://127.0.0.1:8000`。后端健康检查
成功后等待前端端口可连接，随后使用系统默认浏览器打开工作台。`--no-open` 用于
CI、远程终端和手动验证；host、port 和等待时间提供显式参数，但默认只绑定回环地址。

## 生命周期与错误处理

两个子进程均由同一个 launcher 持有。收到 Ctrl+C/终止信号、任一子进程提前退出、
或启动超时时，launcher 都会先请求两个进程正常终止，超时后再强制结束。Uvicorn 的
ASGI lifespan 因而会调用现有 `ApplicationServices.close()`，按顺序释放模型运行时、
动态数据源、静态 Connector 和内存凭据。

环境错误使用简短、可操作的公开消息，不输出 Secret。端口冲突和子进程失败保留各自
退出码；启动器自身的环境检查失败返回非零退出码。

## 测试策略

新增测试只保护新增行为：环境缺失时 fail fast、本地目录创建、命令构造与环境注入、
就绪后只打开一次浏览器、任一进程退出时两个进程都收尾。测试使用受控的假进程与
探针，不实际启动浏览器、网络服务或数据库。

完成时执行一次新增测试、一次 Python unit/security 汇总、一次前端 test/typecheck/
lint/build 汇总。真实 PostgreSQL/MySQL 用例不重复拉起环境；仓库已有锁定的集成测试和
文档化命令，阶段 6 只记录其验证入口与当前证据边界。

## 交付文档

README 作为最短入口；其余文档分别覆盖安装启动、添加模型、添加数据库、架构、开发
交接和常见问题。所有说明默认面向本地单用户，明确凭据仅在进程内存、重启后需重输，
并避免暗示当前前端已经交付尚属阶段 5 后续切片的数据源设置能力。
