# Data Insight Platform（数据洞察平台）

一站式数据分析平台：数据接入 → 数据治理（清洗）→ 分析可视化 → 数据挖掘 → 特征工程 → 机器学习建模 → AI 智能分析，面向从入门到进阶的所有用户。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | Vue 3 + Element Plus + ECharts 5 + Vite 5 |
| 后端 | FastAPI + SQLAlchemy 2 + Celery（异步任务） |
| 数据库 | PostgreSQL 17（主库）、Redis（缓存/消息队列）、ClickHouse（大表分析加速） |
| 对象存储 | MinIO |
| 部署 | Docker Compose / Nginx |

## 目录结构

```
backend/        # FastAPI 后端（app/api 路由、services 业务层、utils 工具）
frontend/       # Vue3 前端（src/ 源码，dev 端口 5173；admin 5174）
docker-compose.example.yml  # 编排模板（复制为 docker-compose.yml 并填写密码后使用）
init.sql        # PostgreSQL 初始化脚本
dev.ps1         # 本地开发一键启动脚本（Windows）
watch-celery.ps1    # Celery + Backend 容器热重载监听（改 .py 自动重启容器）
```

> `docker-compose.yml` 含本地密码配置，已被 `.gitignore` 排除，需自行从模板复制生成。

## 快速开始（Docker）

1. 克隆仓库并进入目录。
2. 生成 compose 配置（模板中的密码均为本地开发默认值，生产环境请修改）：

```powershell
copy docker-compose.example.yml docker-compose.yml
# 可选：在项目根目录创建 .env 覆盖默认密码/密钥（POSTGRES_PASSWORD、REDIS_PASSWORD、MINIO_ACCESS_KEY 等）
```

3. 配置后端环境变量（复制模板）：

```powershell
cd backend
copy .env.example .env
# 编辑 .env：填写 DATABASE_URL、SECRET_KEY、OPENAI_API_KEY（如需 AI 分析）、各中间件连接信息
```

4. 启动全部服务：

```powershell
cd ..
docker-compose up -d --build
```

- 用户端（nginx 80）：`http://localhost`
- 管理后台：`http://localhost/admin.html`
- 后端 API 文档：`http://localhost:8000/docs`

> 基础设施默认凭据见 `docker-compose.yml`（开发默认值），生产环境请修改并妥善保管。

## 本地开发

```powershell
# 1. 启动基础设施（PostgreSQL/Redis/MinIO/ClickHouse/Celery）
./dev.ps1
# 或手动：
docker-compose up -d postgres redis clickhouse minio celery-worker

# 2. 启动后端（热重载，端口 8000）
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 3. 启动前端（用户端 5173 / 管理端 5174）
cd frontend
npm install
npm run dev        # 用户端 http://localhost:5173
npm run dev:admin  # 管理端 http://localhost:5174/admin.html
```

### 后端环境变量（backend/.env）

| 变量 | 说明 |
| --- | --- |
| `DATABASE_URL` | PostgreSQL 连接串（平台强制 PostgreSQL，不支持 SQLite） |
| `SECRET_KEY` | JWT 签名密钥（生产环境务必更换） |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 管理后台初始账号 |
| `OPENAI_API_KEY` / `OPENAI_API_BASE` / `OPENAI_MODEL` | AI 分析服务（OpenAI 兼容接口，默认 DeepSeek） |
| `REDIS_ENABLED` / `REDIS_URL` | 缓存与任务队列 |
| `CLICKHOUSE_ENABLED` / `CLICKHOUSE_*` | 大表分析加速（≥1 万行走 ClickHouse 聚合） |
| `CELERY_ENABLED` / `CELERY_BROKER_URL` | Celery 异步任务 |
| `ASYNC_THRESHOLD` | 异步触发阈值（行数，默认 10000） |
| `MINIO_ENDPOINT` / `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | MinIO 对象存储（必需） |

## 功能模块

- **数据管理**：数据集与产物统一管理、数据血缘、回收站、跨模块导入、远程数据源（MySQL/PostgreSQL）
- **数据分析**：15 种图表、统计摘要、数据质量概览、一键生成分析报告
- **数据清洗**：五步向导（预检 → 契约 → 问题清单 → 管道 → 审计）
- **数据挖掘**：聚类（KMeans/DBSCAN/层次）、关联规则（Apriori/FP-Growth）、序列模式（PrefixSpan/GSP）
- **特征工程**：构造/编码/缩放/降维/选择 5 大模块
- **机器学习**：14 种分类/回归算法、自动调参、批量预测
- **AI 分析**：上下文注入 + 自然语言对话分析

> 平台内顶部栏"使用说明"提供了各模块的详细使用方法、参数与推荐原理。

## 说明

- 本项目已排除内部文档、测试数据与本地配置文件（详见 `.gitignore`），克隆后需按上文配置 `backend/.env` 方可运行。
- 完整开发文档见 `PROJECT_DOCUMENTATION.md`。
