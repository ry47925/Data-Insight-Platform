# Data Insight Platform（数据洞察平台）项目文档

> 版本：v2.3.0
> 更新日期：2026-08-16
> 本文档基于项目真实代码深度分析生成，所有功能描述均与代码实现一致。代码中的注释可能描述旧功能，本文档以实际函数调用为准。
> 同步说明：2026-08-13 基于用户端/管理端源码复核 —— 数据库表 10 张（新增 datasource_connections/app_config）；新增远程数据库数据源模块（/api/data-sources 10 路由，全同步 def）；API 路由总数 148（users 3/datasets 23/cleaning 10/ml 12/ai 11/feature_engineering 16/data_analysis 10/data_mining 9/data_sources 10/admin 44）；管理端 AdminStorage 分类统计 9 类（无 ai 类）；数据分析图表前端实际可选 15 种（line 已合并到 multi_line，后端仍支持 16 种）；ML 旧版 9 个算法路由已删除；清洗 correlation/binning 已删除；ml_service.py 已删除；远程数据源接入清洗/分析/挖掘/特征工程/机器学习 5 大模块。
>
> 2026-08-13 二轮复核修正 —— data_service.py 行数 4350→4470；ai_service.py 现约 1059 行（新增功能后增长）；task_labels 公开常量 13→12；labels.js 函数 4→7（补充失败分类三函数）；AIService 删除不存在的 _build_follow_up_system_prompt；各模块异步 handler 行号更新（详见 .ai-context/ai协作文档/dependency_graph.md）。
>
> 2026-08-14 更新 —— 管理后台 4 块修复：①数据管理（admin.py）：/business/datasets 新增 keyword 文件名搜索 + color/source_type/connection_id/table_name 返回字段；恢复/永久删除写入 admin_restore/admin_permanent_delete 任务留痕并清理用户缓存；corrupted 查询自动批量检测 MinIO 文件；②存储管理（AdminStorage.vue）：死代码清理 + keyword 搜索传后端；③数据库管理（AdminDatabase.vue）：表结构/索引说明补充 10 表与新索引；④新增数据源管理模块（AdminDataSources.vue + /admin/datasource-connections 3 路由）。admin.py 全部路由由 async def 改为 def（同步路由线程池执行，修复管理端轮询阻塞事件循环导致用户端超时）；管理端数据管理"已损坏/已清空"筛选卡片标题改为"筛选条件"；操作历史标签补充管理员操作中文（admin_restore→管理员恢复等）。
>
> 2026-08-15 更新 —— 账号安全 + 个人中心 + 联系管理员 + 用户申请管理：①账号安全：登录失败 5 次锁定 15 分钟、管理员禁用账号即时生效（get_current_user 校验 is_active）、登录提示剩余尝试次数/锁定联系管理员；②个人中心（Profile.vue + /api/users 新增 PUT /me、POST /change-password）：查看账号信息（时间上海时区）、改邮箱、改密码（改密后清除 token 跳登录）；③联系管理员（ContactAdmin.vue + /api/support 3 路由公开接口）：恢复永久删除数据集/解锁账户/系统错误上报 3 类申请 + 算术验证码 + 截图上传 MinIO + 频率限制（SUPPORT_RATE_LIMIT_SECONDS，开发 .env 设 0）；④用户申请管理（AdminUsers.vue 新增"用户申请"Tab + /admin/users/messages 4 路由）：分类/状态/关键字筛选、处理弹窗（申请人账号核实 + 一键解锁/恢复 + 处理备注 + 截图预览下载）、删除申请；API 路由总数 148→160（users 3→5 / support 新增 3 / admin 44→51）；数据库表 10→11（新增 support_messages）；User 模型新增 is_active/failed_login_count/locked_until；主应用视图 10→12（新增 Profile.vue / ContactAdmin.vue）。
>
> 2026-08-15 第二轮更新 —— 管理端任务管理增强（AdminTasks.vue 全面改造 + admin.py 51→54 路由）：①队列监控：/admin/tasks/stats 增强（运行中/排队中实时数、今日成功/失败、成功率、平均耗时），顶部 4 项监控卡 + Celery 模式标签；②筛选增强：/business/tasks 新增 username 用户名搜索、failure_category 失败分类、date_from/date_to 时间范围，状态补全 pending/cancelled，返回补 failure_category/is_remote/dataset_id/has_progress；③详情抽屉：新增 GET /admin/tasks/{id} 完整详情（失败原因红框/参数 JSON/进度历史/重试历史/管理员取消标注）；④取消/重试：新增 POST /admin/tasks/{id}/cancel 与 /retry（绕过用户归属校验、只在原任务记录标注 admin_cancel / retry_history.operator=admin，不新建记录避免统计污染）；⑤统计增强：/business/task-stats 新增 by_status 状态分布与 by_module_failed 模块失败 TOP，统计 Tab 新增健康指标卡 + 状态分布环形图 + 失败 TOP；⑥运行超 40 分钟任务列表标红；API 路由总数 160→163。
>
> 2026-08-15 第三轮更新 —— 用户端首页（HomeView.vue）改造：①统计区真实化（并行加载 /api/datasets 数据集数、/datasets/task-records 操作记录数、/ai/usage/stats AI Token 用量与今日对话、/data-sources 数据源连接数，600ms 数字滚动动画）；②Hero 区登录感知（登录显示"欢迎回来，{username}"+ 真实数据装饰卡，未登录显示平台介绍 + "登录体验"按钮，watch 登录态实现 keep-alive 缓存下的重置/刷新）；③数据挖掘卡片文案校正（异常检测→聚类/关联规则/序列模式）；④三条路径改为 SVG 分支流程图（公共主干"原始数据→数据清洗"三分叉、节点分色：普通描边/高亮实心/终点绿色渐变、路径 C 虚线标注"作为特征输入"，窄屏 ≤1080px 降级为纵向列表）；⑤登录成功默认跳转首页 `/`（不再跳数据管理，带 redirect 参数返回原页面）；admin.py 路由数复核校正 54→62（总路由 163→171）；管理端视图 11→13（补登记 AdminAIUsage/AdminDashboardScreen）。
>
> 2026-08-15 第四轮更新（文档核对修正，v2.3.0）—— 以实际代码复核全文档，修正以下过时描述：①数据库表 **10/11 张 → 13 张**（补登记 cache_stats_hourly 缓存命中历史表 + log_records 日志入库表，models/__init__.py 实际含 13 个模型类）；②api/index.js export 115 条 → **113 条**（108 函数 + 4 const + default）；③api/admin.js 具名 export 54 个 → **65 个**（含 adminAuthStore + default adminApi）；④common.py 函数 10 → **11 个**；⑤task_labels 常量数修正（12 公开常量 + 6 私有常量 + 11 公开函数 + 5 私有函数）；⑥管理端路由 admin.js **10 条 → 12 条**（补 /screen 数据大屏、/ai-usage AI 用量）；⑦AIAnalysis.vue 布局为**上端上下文面板 + 下端对话区**（垂直布局，非左/右）；⑧清理目录结构中已不存在的文件描述（修改方案_*.md、数据流转全景文档等）。
>
> 2026-08-15 第五轮更新（前端 UI 统一 + 操作历史增强，v2.3.0）—— ①**5 大模块数据源选择 UI 统一**（清洗/分析/挖掘/特征工程/机器学习）：统一为"数据上传 + 选择数据集"两卡片布局；DataSourceSelector 改 width:100% 自适应撑满卡片；新增公共组件 DataPreview.vue（选择数据集后自动加载前 10 行内嵌预览，远程模式提示暂不支持）；各模块删除页面 h2/冗余标签/按钮；5 模块根容器移除 padding，首个卡片距头部间距统一 28px；global.css 新增 .card-title/.card-title-actions 统一样式。②**AI 分析页**：移除页面 `<h2>AI 智能分析</h2>` 标题，"使用统计"按钮移入上下文注入卡片标题栏，上下文注入卡片与头部间距统一 28px。③**AI 上下文注入**：操作记录展示排除 `user_admin`（账号管理）类（前端 filteredTasks 计算属性过滤）。④**操作历史**：操作大类 8 类 → **9 类**，新增"账号管理"（user_admin，含管理员变更账号状态/重置密码/解锁账号 3 个具体操作，与后端 task_records 留痕对齐）。

---

## 目录

1. [项目概述](#1-项目概述)
2. [用户管理与数据隔离](#2-用户管理与数据隔离)
3. [数据流转与血缘追溯](#3-数据流转与血缘追溯)
4. [功能模块详解（用户端）](#4-功能模块详解用户端)
5. [管理后台模块详解](#5-管理后台模块详解)
6. [系统架构设计](#6-系统架构设计)
7. [技术栈详解](#7-技术栈详解)
8. [项目目录结构](#8-项目目录结构)
9. [环境配置说明](#9-环境配置说明)
10. [本地启动指南](#10-本地启动指南)
11. [Docker Compose 部署指南](#11-docker-compose-部署指南)
12. [废弃代码与未使用文件清单](#12-废弃代码与未使用文件清单)
13. [已知问题与后续优化建议](#13-已知问题与后续优化建议)

---

## 1. 项目概述

### 1.1 项目简介

**Data Insight Platform（数据洞察平台）** 是一款 AI 驱动的通用数据分析平台，面向数据分析师、业务人员和开发者，提供从数据上传、清洗、分析、挖掘到机器学习建模和 AI 智能分析的全链路数据处理能力。

平台采用模块化设计，每个功能模块独立运作又相互关联，支持数据在模块间的流转和追溯。核心设计理念是**"低门槛、全链路、可追溯"**，让用户无需编写代码即可完成复杂的数据分析任务。

### 1.2 核心特性

- **全链路数据处理**：覆盖数据上传 → 清洗 → 分析 → 挖掘 → 特征工程 → 机器学习 → AI 分析的完整流程
- **模块化数据隔离**：每个模块拥有独立的原始数据池，产物通过 `module_source` 和 `artifact_type` 标签化管理
- **AI 智能助手**：基于大语言模型的自然语言对话，支持上下文注入（数据产物 + 操作记录注入对话，辅助分析）
- **数据血缘追溯**：通过 `parent_id` 和 `root_dataset_id` 追踪数据从原始上传到最终产物的完整链路
- **回收站机制**：软删除 + 回收站恢复 + 永久删除的三级数据保护
- **多格式导出**：支持 CSV、Excel、JSON、PDF、Markdown、HTML 等多种导出格式
- **管理后台**：独立的管理员认证体系，提供服务监控、缓存管理、存储管理、数据库管理、日志查看等运维功能

### 1.3 数据库要求

**平台强制使用 PostgreSQL**。`config.py` 在初始化时会检查 `DATABASE_URL`，如果为空或以 `sqlite://` 开头则直接抛出异常。SQLite 已完全废弃，不再支持。

---

## 2. 用户管理与数据隔离

### 2.1 用户认证体系

**文件位置**：`backend/app/api/users.py`、`backend/app/utils/security.py`

平台采用双轨认证体系：普通用户认证和管理员认证。

#### 2.1.1 普通用户认证

| 功能 | 端点 | 说明 |
|------|------|------|
| 用户注册 | `POST /api/users/register` | 用户名 + 密码注册，邮箱自动生成为 `{username}@local` |
| 用户登录 | `POST /api/users/login` | 基于 OAuth2PasswordRequestForm，返回 JWT access_token |
| 获取当前用户 | `GET /api/users/me` | 通过 JWT Token 解析当前登录用户信息（含 email/is_active/last_login_at/last_login_ip，时间为上海时区带 +08:00） |
| 更新资料 | `PUT /api/users/me` | 修改邮箱（格式正则校验 + 唯一性校验），个人中心调用 |
| 修改密码 | `POST /api/users/change-password` | 验证旧密码后设置新密码（6-32 位，不能与旧密码相同）；改密成功后前端清除 token 并跳转登录页 |

**安全机制（2026-08-15 新增）**：
- **密码哈希**：使用 `hashlib.sha256` 进行单向哈希（注意：非 bcrypt，文档中如有 bcrypt 描述均为旧文档残留）
- **JWT 认证**：使用 `python-jose` 签发和验证 Token，算法 HS256，默认有效期 120 分钟
- **登录追踪**：记录 `last_login_at`（最后登录时间）和 `last_login_ip`（最后登录IP，支持 X-Forwarded-For 代理头解析）
- **登录失败锁定**：连续失败 5 次（`MAX_LOGIN_FAILURES`）锁定 15 分钟（`LOCKOUT_MINUTES`）；未达阈值提示"还可尝试 N 次"，已达阈值提示"账号已锁定，请联系管理员解锁（约 N 分钟后自动解锁）"
- **账号禁用**：管理员禁用后登录返回 403；已登录用户的请求由 `get_current_user` 的 `is_active` 校验统一拦截（403"账号已被禁用"），实现即时生效

#### 2.1.2 管理员认证

**文件位置**：`backend/app/api/admin.py`

| 功能 | 端点 | 说明 |
|------|------|------|
| 管理员登录 | `POST /admin/auth/login` | 独立的登录端点，使用 `admin_oauth2_scheme` |
| 获取当前管理员 | `GET /admin/auth/me` | 通过 `get_current_admin` 依赖注入验证管理员身份 |

**管理员初始化**：`ensure_admin_user()` 函数在应用启动时自动检查并创建默认管理员账户（用户名/密码由 `ADMIN_USERNAME`/`ADMIN_PASSWORD` 环境变量配置，config.py 默认 admin/admin，生产以 .env 为准；前端 AdminLogin.vue 提示文案为 admin/admin123 存在不一致，见第 13 章）。

### 2.2 角色与权限

**User 模型字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer | 主键 |
| `username` | String | 用户名，唯一索引 |
| `email` | String | 邮箱，可空（个人中心可修改，唯一） |
| `hashed_password` | String | SHA256 哈希密码 |
| `role` | String | 角色，默认 "user"，管理员为 "admin" |
| `is_active` | Boolean | 账号是否启用（2026-08-15 新增，管理员可禁用/启用，默认 True） |
| `failed_login_count` | Integer | 连续登录失败次数（2026-08-15 新增，用于暴力破解锁定） |
| `locked_until` | DateTime | 登录锁定截止时间（2026-08-15 新增，None 表示未锁定） |
| `last_login_at` | DateTime | 最后登录时间 |
| `last_login_ip` | String | 最后登录IP |
| `created_at` | DateTime | 创建时间 |

**权限控制**：
- 普通用户端点使用 `get_current_user` 依赖注入
- 管理员端点使用 `get_current_admin` 依赖注入
- 管理员通过独立的 `/admin/auth/login` 端点登录，Token 与普通用户分离

### 2.3 数据隔离机制

**核心原则**：所有数据查询必须包含 `user_id` 过滤条件。

数据隔离在以下层面实现：

1. **API 层**：每个查询都通过 `Dataset.user_id == current_user.id` 过滤
2. **工具层**：`get_dataset_or_404(db, dataset_id, user_id)` 统一校验数据集归属
3. **缓存层**：缓存键包含 `user_id`，如 `datasets:user:{user_id}:list`
4. **任务记录**：`TaskRecord.user_id` 记录操作发起者

**用户端与管理端的数据连通**：
- 管理员可查看所有用户的数据集（`GET /admin/business/datasets`）
- 管理员可查看所有用户的任务记录（`GET /admin/business/tasks`）
- 管理员可查看用户统计信息（`GET /admin/users`、`GET /admin/users/stats`）
- 管理员可禁用/启用账号、重置密码、解锁账号（`PUT /admin/users/{id}/status` 等，2026-08-15 新增）
- 管理员可处理用户通过"联系管理员"提交的申请（`/admin/users/messages*`，2026-08-15 新增）
- 管理端不直接修改用户数据，仅做监控和统计（账号状态操作除外）

### 2.4 远程数据库数据源管理

**文件位置**：`backend/app/api/data_sources.py`、`backend/app/models/__init__.py`（DataSourceConnection/AppConfig 表）、`frontend/src/components/DataSourceSelector.vue`、`DataSourceDialog.vue`

平台支持**本地文件上传**（CSV/Excel/JSON，存 MinIO）与**远程数据库**（MySQL/PostgreSQL）两种数据来源。

| 功能 | 端点 | 说明 |
|------|------|------|
| 连接列表 | `GET /api/data-sources/` | 当前用户的连接列表（密码脱敏 password_display=******） |
| 创建连接 | `POST /api/data-sources/` | name/db_type/host/port/database/username/password，密码 Fernet 加密 |
| 更新连接 | `PUT /api/data-sources/{conn_id}` | 修改连接信息 |
| 删除连接 | `DELETE /api/data-sources/{conn_id}` | 删除连接（关联产物处理） |
| 验证连接 | `POST /api/data-sources/verify` | 验证连接配置 |
| 测试连接 | `POST /api/data-sources/test` | 测试连通性 |
| 表列表 | `GET /api/data-sources/{conn_id}/tables` | 列出远程库所有表 |
| 表结构 | `GET /api/data-sources/{conn_id}/tables/{table_name}/schema` | 列名/类型 |
| 表行数 | `GET /api/data-sources/{conn_id}/tables/{table_name}/count` | 行数统计 |
| SQL 下推聚合 | `POST /api/data-sources/{conn_id}/tables/{table_name}/aggregate` | 均值/计数等聚合计算下推到远程库 |

**技术要点**：
- 该模块 10 条路由**全部为同步 `def`**（全项目唯一非 async 模块）
- 连接密码经 `utils/crypto.py` Fernet 加密存储，密钥懒加载自 `app_config` 表（key=`data_source_encryption_key`）
- 连接超时统一 5 秒（`REMOTE_CONNECT_TIMEOUT=5`，data_sources.py）
- 用户通过顶栏"数据源"弹窗（DataSourceDialog）管理连接；各分析模块通过 DataSourceSelector 在本地/远程间切换，5 大模块（清洗/分析/挖掘/特征工程/机器学习）均支持远程数据源

---

## 3. 数据流转与血缘追溯

### 3.1 数据集生命周期

数据集的生命周期通过 `status` 字段管理：

```
上传/创建 → active → 软删除 → deleted（回收站） → 永久删除
                ↓
            corrupted（文件丢失）
```

**状态说明**：
- `active`：正常可用状态（含 NULL 值，兼容旧数据）
- `corrupted`：文件在 MinIO 中不存在（列表查询时自动检测并标记）
- `deleted`：已移入回收站（文件移到 `trash/` 前缀下）

### 3.2 数据集血缘模型

**Dataset 模型的血缘字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `parent_id` | Integer | 直接父数据集ID，标识产物来自哪个数据集 |
| `root_dataset_id` | Integer | 根数据集ID，追溯回最原始的上传数据 |
| `module_source` | String | 产出模块：upload/data_analysis/cleaning/data_mining/feature_engineering/ml/ai/batch_predict/pipeline |
| `module_label` | String | 模块中文标签，与 `module_source` 统一映射：原始数据/数据分析/数据清洗/数据挖掘/特征工程/机器学习/AI分析/批量预测/流程联动 |
| `artifact_type` | String | 产物类型：raw_data/cleaning_result/ml_report/ml_model/ml_prediction/analysis_data/analysis_report/cluster_result/association_rules/sequential_patterns/feature_result/ai_report/pipeline_result/predict_data |
| `algorithm` | String | 使用的算法描述，如"IQR异常值(删除)+均值填充" |
| `report_content` | Text | JSON 格式的报告内容（仅 ml_report/ai_report/analysis_report 使用） |

### 3.3 数据流转路径

```
用户上传文件
    ↓
各模块独立上传（artifact_type=raw_data）
    ↓
┌─────────────────────────────────────────────────────────┐
│  数据清洗模块                                              │
│  raw_data → comprehensive_clean → cleaning_result       │
│  产物保存为新 Dataset，parent_id 指向原始数据               │
└─────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────┐
│  数据分析模块                                              │
│  analysis_data → generate_report → analysis_report      │
│  HTML 报告保存为 Dataset，report_content 存储 HTML 内容    │
└─────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────┐
│  数据挖掘模块                                              │
│  raw_data → cluster_analysis → cluster_result           │
│  raw_data → association_rules_mining → association_rules│
│  raw_data → sequence_mining → sequential_patterns       │
│  注意：异常检测已移除（职责归属各模块预检阶段）              │
└─────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────┐
│  特征工程模块                                              │
│  raw_data → construct/encode/scale/reduce（原地更新）     │
│  raw_data → select_features → 特征得分排名（不生成数据集）│
│  raw_data → export → feature_result                     │
│  注意：构造/编码/缩放/降维不创建新 Dataset，原地更新文件     │
└─────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────┐
│  机器学习模块                                              │
│  raw_data → train_supervised → ml_model（pkl 文件）      │
│  ml_model → batch_predict → ml_prediction               │
│  ml_model → test_evaluate → 评估结果（不生成产物）          │
│  ml_model → export_report → ml_report                   │
│  注：旧版 cluster/anomaly/association 等 9 个路由已删除，  │
│  聚类/关联/降维分别归属数据挖掘/特征工程模块                 │
└─────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────┐
│  AI 分析模块                                               │
│  raw_data → chat（上下文注入对话）→ AIConversation       │
│  AI 模块产物存储在独立的 AIConversation/AIMessage/       │
│  AIConversationContext/AIUsageLog 表中，不创建 Dataset    │
│  记录；AI 方案管理（AIPlan）已从前后端完全移除              │
└─────────────────────────────────────────────────────────┘
```

### 3.4 模块间数据导入

`POST /api/datasets/{dataset_id}/import` 接口支持将任意数据集导入到其他模块：

1. 复制源文件到目标模块的存储路径
2. 创建新的 `raw_data` 类型 Dataset 记录
3. 设置 `parent_id` 指向源数据集
4. 保留 `schema`、`row_count`、`data_preview` 等元数据
5. 特征工程模块导入时额外记录 `original_columns` 到 `tags` 字段

### 3.5 任务记录追踪

所有用户操作通过 `TaskRecord` 模型记录：

| 字段 | 说明 |
|------|------|
| `task_type` | 任务类型（共 14 种）：upload 文件上传/dataset 数据治理/cleaning 数据清洗/data_analysis 数据分析/data_mining 数据挖掘/feature_engineering_select·construct·encode·scale·reduce 特征工程 5 子类/ml 机器学习/ml_training 模型训练/ai AI分析/user_admin 账号管理（管理员禁用/重置密码/解锁留痕用）；**流程联动(pipeline)是 Dataset.module_source 概念，不是任务类型** |
| `user_id` | 操作用户ID |
| `dataset_id` | 关联数据集ID（可为空） |
| `params` | 操作参数（JSON） |
| `status` | 状态：pending/running/success/failed |
| `result_summary` | 结果摘要（JSON） |
| `error_message` | 错误信息 |
| `execution_time` | 执行时间（毫秒） |

---

## 4. 功能模块详解（用户端）

平台共包含 8 大用户端功能模块，每个模块均有独立的后端 API 和数据存储空间。

### 4.1 用户认证模块（Users）

**文件位置**：`backend/app/api/users.py`、`backend/app/utils/security.py`

| 功能 | 端点 | 说明 |
|------|------|------|
| 用户注册 | `POST /api/users/register` | 用户名 + 密码，SHA256 哈希存储 |
| 用户登录 | `POST /api/users/login` | OAuth2PasswordRequestForm，返回 JWT；连续失败 5 次锁定 15 分钟，禁用账号返回 403 |
| 获取当前用户 | `GET /api/users/me` | Token 解析当前用户信息（上海时区） |
| 更新资料 | `PUT /api/users/me` | 修改邮箱（格式 + 唯一性校验），个人中心调用 |
| 修改密码 | `POST /api/users/change-password` | 验证旧密码后改密（6-32 位，不能与旧密码相同） |

**前端页面**：
- **Profile.vue（个人中心，2026-08-15 新增）**：登录后通过顶部栏用户下拉进入（路由 `/profile`）。查看账号信息（用户名/邮箱/角色/注册时间/最后登录，时间为上海时区）；修改邮箱；修改密码（验证旧密码，成功后清除 token 并跳转登录页）。
- **Login.vue**：登录/注册双 Tab；密码错误提示剩余尝试次数，锁定后提示联系管理员解锁；登录页提供"联系管理员 →"链接；**登录成功默认跳转首页 `/`**（2026-08-15 起，带 redirect 参数时返回原页面；已登录访问登录页自动重定向首页，router 守卫 + Login.vue onMounted 双重保障）。

### 4.1.1 联系管理员（Contact Admin）

**文件位置**：`backend/app/api/support.py`、`frontend/src/views/ContactAdmin.vue`

**定位**：公开功能（**无需登录**），供用户向管理员提交三类申请。入口：顶部栏"联系管理员"按钮 + 登录页链接。

| 功能 | 端点 | 说明 |
|------|------|------|
| 获取验证码 | `GET /api/support/captcha` | 算术验证码（如 "3 + 5 = ?"），答案存 Redis 5 分钟 |
| 上传截图 | `POST /api/support/upload` | 仅支持 jpg/jpeg/png/gif/webp 且 ≤5MB，存 MinIO `support/` 目录 |
| 提交申请 | `POST /api/support/messages` | 分类校验 → 验证码校验（一次性）→ 频率限制 → 写入 support_messages |

**三类申请**：
1. **恢复永久删除数据集**（restore_dataset）：填写数据集名称，content 含 dataset_name
2. **解锁账户**（unlock）：填写用户名 + 联系方式（contact 必填），content 含 username
3. **系统错误上报**（error_report）：填写错误描述（可选附截图），content 含 description

**安全机制**：算术验证码一次性防重放；同 IP/用户名频率限制（`SUPPORT_RATE_LIMIT_SECONDS` 配置，默认 600 秒，开发阶段 .env 设 0 关闭）；截图限制格式与大小。

### 4.1.2 使用说明（Usage Guide，2026-08-16 新增）

**文件位置**：`frontend/src/components/UsageGuideDialog.vue`、`frontend/src/guides/`（9 个 Markdown 文档）

**定位**：登录后顶部栏"使用说明"按钮（与"数据源/联系管理员"并列，`App.vue` 顶栏），弹出 960px 弹窗，左侧 9 个模块 Tab（平台总览/数据管理/数据分析/数据清洗/数据挖掘/特征工程/机器学习/AI分析/操作历史），右侧 Markdown 渲染该模块使用说明。

**文档内容**：每个模块按"可用方法、参数调整、推荐原理、注意事项"四部分撰写，全部基于实际功能（如清洗 6 类问题处理策略与执行顺序原理、挖掘算法自动推荐逻辑、ML 14 种算法评分与调参、AI 上下文注入等）。

**技术实现**：
- MD 文档经 Vite `?raw` 导入保持纯 Markdown 格式（`frontend/src/guides/index.js` 聚合导出 `GUIDE_MODULES`/`GUIDE_CONTENT`），便于维护。
- 渲染使用 `marked@18`（新增依赖）；静态文档无外部输入，无 XSS 风险。
- 仅登录后可见（按钮 `v-if="isLoggedIn()"`）；弹窗打开时默认定位"平台总览"。

### 4.2 数据管理模块（Datasets）

**文件位置**：`backend/app/api/datasets.py`

数据管理是平台的核心枢纽，负责所有数据集的统一存储、检索、导出和生命周期管理。前端页面为 `DataManagement.vue`，采用动态列配置框架（`columnConfig` 对象），各 Tab 可独立配置列显隐。

**Tab 列表（共 8 个，无"全部"和"操作历史"Tab，AI 方案 Tab 已移除）**：
- 原始数据、数据分析报告、数据清洗产物、数据挖掘产物、特征工程产物、机器学习产物、机器学习预测数据、回收站
- 机器学习产物 Tab 显示 ml_report 类型；机器学习预测数据 Tab 显示 predict_data 类型；数据挖掘产物内部支持 cluster_result/association_rules/sequential_patterns 三类筛选
- 默认 Tab：原始数据

**操作历史已拆分为独立页面**：`TaskHistory.vue`，路由 `/task-history`，导航栏使用 Timer 图标，与数据管理模块解耦。操作大类筛选共 **9 类**（2026-08-15 新增"账号管理"：task_type=user_admin，含管理员变更账号状态/重置密码/解锁账号 3 个具体操作，与后端管理端账号操作留痕对齐）。

| 功能 | 端点 | 说明 |
|------|------|------|
| 数据集列表 | `GET /api/datasets/` | 支持 module_source/artifact_type/root_dataset_id/status 多维筛选，5分钟缓存 |
| 文件上传 | `POST /api/datasets/` | 支持 CSV/Excel/JSON，自动解析 schema/行数/预览 |
| 上传别名 | `POST /api/datasets/upload` | 兼容前端路径 |
| 创建记录 | `POST /api/datasets/record` | JSON body 创建数据集记录（供模块调用） |
| 编辑元数据 | `PUT /api/datasets/{id}` | 修改名称和标签；**允许重名**（2026-08-13 起不做唯一性校验，同名靠 #id + 颜色 + 创建时间区分） |
| 获取详情 | `GET /api/datasets/{id}` | 获取数据集详情 |
| 删除（软删除） | `DELETE /api/datasets/{id}` | 文件移到 trash/ 前缀，status 改为 deleted |
| 批量删除 | `POST /api/datasets/batch-delete` | 批量移到回收站 |
| 回收站列表 | `GET /api/datasets/trash/list` | 查看已删除数据集 |
| 恢复 | `POST /api/datasets/trash/restore/{id}` | 从回收站恢复 |
| 永久删除 | `DELETE /api/datasets/trash/{id}` | 状态改为 purged（业务回收站） |
| 清空所有 | `DELETE /api/datasets/clear/all` | 清空所有活跃数据集 |
| 清空回收站 | `DELETE /api/datasets/trash/clear/all` | 清空回收站 |
| 数据分页预览 | `GET /api/datasets/{id}/data` | 分页获取数据（1~1000行/页） |
| 数据统计 | `GET /api/datasets/{id}/statistics` | 行数/列数/缺失值/重复行/统计摘要 |
| 数据质量 | `GET /api/datasets/{id}/quality` | 详细数据质量检测 |
| 模块间导入 | `POST /api/datasets/{id}/import` | 复制数据集到目标模块 |
| 多格式导出 | `GET /api/datasets/{id}/export` | CSV/Excel/JSON/PDF/Markdown/HTML；下载名=展示名（Content-Disposition `filename*=UTF-8''` URL 编码） |
| 操作历史 | `GET /api/datasets/task-records` | 当前用户操作历史，支持类型/状态筛选 |
| 数据血缘 | `GET /api/datasets/{id}/lineage` | 获取数据集血缘关系，返回 {self, ancestors(含is_import), descendants(含is_import)} |

**命名规范（2026-08-14 全面修正）**：
- 数据集名称允许重名、不加时间戳/序号后缀；同名区分靠 `#id` + 颜色（`dataset_color(id)` 取模派生）+ 创建时间
- 产物命名统一走 `utils/common.py::build_product_name(source_name, ext)`：源名剥离历史拼接 → 去自身扩展名 → 追加**真实内容后缀**（挖掘聚类 `.csv` / 关联·序列 `.json` / 分析报告 `.html` / 特征工程导出 `.csv` / ML 模型 `.pkl` / 预测 `.csv` / 模型报告 `.html`），杜绝双后缀与名实不符
- 下载名与前端展示名、后缀完全一致（前端下载不再拼时间戳，同名由浏览器自动加 `(1)`）
- 下拉折叠态显示名称（`el-option` 补 `:label`），不再显示数字 id

**产物类型（artifact_type）完整列表**：
- `raw_data`：原始数据
- `cleaning_result`：清洗结果
- `ml_report`：机器学习报告
- `ml_model`：训练好的模型
- `ml_prediction`：批量预测结果
- `analysis_data`：数据分析模块原始数据
- `analysis_report`：数据分析 HTML 报告
- `feature_result`：特征工程导出产物（特征选择导出/列池导出统一类型，`feature_selected` 已废弃）
- `cluster_result`：聚类结果
- `association_rules`：关联规则（JSON 文件）
- `sequential_patterns`：序列模式（JSON 文件）

**回收站机制**：
- 用户端删除：状态改为 deleted，文件移到 trash/ 前缀
- 用户端永久删除：状态改为 purged，数据保留在业务回收站（管理员可恢复）
- 管理员业务回收站：可恢复为 active 或执行物理删除

**数据血缘**：
- 通过 `parent_id` 和 `root_dataset_id` 追踪数据链路
- 血缘接口返回 {self, ancestors(含is_import), descendants(含is_import)}

### 4.3 数据清洗模块（Cleaning）

**文件位置**：`backend/app/api/cleaning.py`、`backend/app/services/data_service.py`（DataCleaningService 类）

数据清洗模块提供全面的数据质量问题检测和修复能力，采用**问题清单驱动 + 管道式执行**的架构。问题清单用于分析数据问题并设置每类问题的处理方式，管道根据问题清单自动生成清洗步骤，最终按管道顺序执行。

**参数关系**：
- `problem_strategies`：问题清单策略，定义缺失值/类型错误/范围错误/异常值/重复值等的处理方式
- `pipeline`：清洗管道，决定问题策略的执行顺序，并允许追加列操作（重命名/删除/类型转换）和行过滤
- `contract`：数据契约，提供类型/范围约束，供类型错误处理和缺失值智能填充使用
- 两者为依赖关系而非独立模式：问题清单设置策略，管道负责执行
- 管道操作支持的异常/范围处理 `method` 包括：
  - `outlier`：remove / replace / mark / clip；其中 `mark` 会新增 `_is_outlier_{列名}` 布尔列
  - `range_error`：clip / drop / mark；其中 `mark` 会新增 `_out_of_range_{列名}` 布尔列
  - 问题清单策略的 `mark` 处理则生成 `{列名}_标记_{类型}` 布尔列，两者命名格式不同
- 注意：当前前端 `comprehensive` 接口调用始终携带 `problem_strategies`，纯 `pipeline` 分支在运行时不可达，但后端 `execute_pipeline` 仍保留该能力

**智能异步分发**：
- ≥1万行：异步提交到 Celery，返回 task_id 供前端轮询进度
- <1万行：同步执行
- Celery 不可用且 ≥1万行：返回 503，不降级

**执行流程**（新模式）：
1. 契约校验 → 检测契约本身矛盾（如 min > max）
2. Dry-run 预检 → 检测列依赖冲突、缺失值填充位置等
3. 警告拦截 → 若存在警告且未强制执行，返回警告让用户确认
4. 执行清洗 → 按用户定义顺序执行
5. 审计报告 → 对比清洗前后差异并计算质量评分

**数据契约（contract）支持字段**：
| 字段 | 说明 |
|------|------|
| `expected_type` | 期望类型：integer/number/string/boolean/date/email/url |
| `ranges` | 数值范围：{min, max} |
| `decimal_places` | 小数位数 |
| `min_date/max_date` | 日期范围 |
| `enum_values` | 枚举值列表 |
| `min_length/max_length` | 字符串长度范围 |
| `bool_representation` | 布尔值表示形式 |
| `allow_missing` | 是否允许缺失值 |
| `allow_duplicate` | 是否允许重复值 |

| 功能 | 端点 | 说明 |
|------|------|------|
| 获取原始数据 | `GET /api/cleaning/raw-data` | 仅返回 cleaning 模块的 raw_data |
| 获取列名 | `GET /api/cleaning/columns/{id}` | 获取数据集列名列表 |
| 获取全部数据 | `GET /api/cleaning/data/{id}` | 获取全部行用于前端质量检测 |
| 上传文件 | `POST /api/cleaning/upload` | 上传到清洗模块 |
| 清洗前预检 | `GET /api/cleaning/precheck/{id}` | 自动检测缺失值、重复行、类型识别、异常值和类型错误（本地） |
| 清洗前预检（远程） | `POST /api/cleaning/precheck` | Body: {dataset_id, remote?}，支持远程表预检 |
| 记录向导步骤 | `POST /api/cleaning/record-step` | 记录向导步骤配置（step: contract_config / problem_strategy），供操作历史展示 |
| 分析问题清单 | `POST /api/cleaning/analyze-problems/{id}` | 根据契约计算六类问题清单（缺失值/类型错误/范围错误/异常值/行重复/列重复） |
| Dry-run 预检 | `POST /api/cleaning/dry-run/{id}` | 检查管道配置合理性，返回警告/错误/建议顺序 |
| 综合清洗 | `POST /api/cleaning/comprehensive` | 执行清洗（支持三种模式），返回审计报告，支持远程（remote 参数） |

> 注：原 `/correlation`（相关性分析）、`/binning`（特征分箱）两个路由已从代码中完全删除，相关功能整合到数据分析/特征工程模块。

**问题类型与处理策略**：

| 问题类型 | 处理策略 |
|----------|----------|
| 缺失值（missing_values） | auto/mean/median/mode/drop/自定义值 |
| 动态缺失值（dynamic_missing） | 同上（处理前面步骤产生的NaN） |
| 类型错误（type_errors） | keep/delete |
| 范围错误（range_errors） | clip/drop/mean/median/mode/mark_missing/fill/自定义值 |
| 异常值（outliers） | remove/clip/mark_missing；检测方法：IQR/Z-Score/Grubbs |
| 行重复（row_duplicates） | keep_first/keep_last/remove_all/手动选择 |
| 列重复（column_duplicates） | 保留指定列 |

**质量评分**：清洗前后对比，返回完整性、一致性、唯一性、准确性、综合评分（0~100分）。

**差异对比**：`generate_audit_report` 函数逐行比较清洗前后数据，标注每行变化类型和具体字段变化，生成详细的审计报告。

**重要说明**：
- 标准化/归一化已移至特征工程模块，清洗模块不再提供 scaling 处理
- pipeline 按用户定义顺序执行
- 缺失值填充必须在其他异常处理完毕后进行（通过 pipeline 顺序控制）

**前端布局说明**：
- 数据集选择器独立为顶部卡片，每步都可切换数据集
- 五步向导（预检→契约→问题清单→管道→审计）在独立卡片中
- 与其他模块（如数据分析）的布局风格一致

### 4.4 数据分析模块（Data Analysis）

**文件位置**：`backend/app/api/data_analysis.py`

提供丰富的数据探索和可视化能力，支持 16 种图表类型（后端支持 16 种，前端实际可选 15 种，line 已合并到 multi_line）。

| 功能 | 端点 | 说明 |
|------|------|------|
| 上传文件 | `POST /api/data-analysis/upload` | artifact_type=analysis_data |
| 原始数据列表 | `GET /api/data-analysis/raw-data` | 获取分析模块数据 |
| 数据预览 | `GET /api/data-analysis/{id}/data` | 分页获取数据 |
| 统计摘要 | `GET /api/data-analysis/{id}/statistics` | 数值列统计 + 分类列 TOP 值 |
| 数据质量 | `GET /api/data-analysis/{id}/quality` | 缺失/无穷大/重复/常量列检测 |
| 图表数据 | `POST /api/data-analysis/{id}/chart` | 16种图表类型 |
| 图表导出 | `GET /api/data-analysis/{id}/chart-export` | PNG 图片导出 |
| 智能图表推荐 | `GET /api/data-analysis/{id}/chart-recommendations` | 返回最多5个最优图表+推荐理由+匹配度+supported_chart_types |
| 生成报告 | `POST /api/data-analysis/{id}/report` | HTML 报告（预览不保存） |
| 保存报告 | `POST /api/data-analysis/{id}/report/save` | 保存为 analysis_report 产物 |

**支持的图表类型**（后端 16 种 / 前端可选 15 种）：
histogram（直方图）、scatter（散点图）、boxplot（箱线图）、line（折线图）、pie（饼图）、heatmap（热力图）、bar（柱状图）、stacked_bar（堆叠柱状图）、area（面积图）、kde（单变量KDE密度图）、qq（标准化QQ图）、bubble（气泡图）、multi_line（多折线图）、dual_axis（双Y轴图）、radar（雷达图）、table_heatmap（表格热力图）

> 注意 1：**前端 DataAnalysis.vue 实际可选 15 种**，`line`（折线图）已合并到 `multi_line`（多折线图）；后端 `supported_types`（data_analysis.py:369-373）仍支持全部 16 种。
> 注意 2：透视表（pivot）作为独立图表类型已从图表列表中移除。但 `table_heatmap` 图表内部仍使用 Pandas `pivot_table` 进行数据变换。
> 注意 3：本模块全部数据类接口（data/statistics/quality/chart/chart-export/chart-recommendations/report/report/save）支持**远程模式**——请求体携带 `remoteConfig: {connection_id, table_name}`，路径参数 `id` 传 0 占位；远程统计/质量/图表推荐由独立函数计算（`_compute_remote_statistics`/`_compute_remote_quality`/`_compute_remote_recommendations`，data_analysis.py:3989/4187/4318）。
> 注意 4（**2026-08-16**）：本地数据集 + ClickHouse 已同步（≥1万行）时，`statistics`/`quality`/`chart-recommendations` 走 CH 全量聚合、`chart` 仅聚合型图表（histogram/bar/stacked_bar/pie）走 CH 全量计算；CH 不可用/未同步/小表/失败自动降级 pandas。判定入口 `_ch_synced_registry`（data_analysis.py），同步触发点见 5.9 节。

**HTML报告生成说明**：
- 后端 `_build_analysis_report` 函数生成完整HTML文档（data_analysis.py:2651）
- 报告内容包裹在 `<div class="report-body">` 中，使用 `.report-body` 类选择器控制样式（而非 body 选择器）
- 前端 `DataAnalysis.vue` 使用 v-html 渲染，`.report-preview` 类设置 margin/padding 为 0
- 预览弹窗无白边问题

### 4.5 数据挖掘模块（Data Mining）

**文件位置**：`backend/app/api/data_mining.py`、`frontend/src/views/DataMining.vue`

基于 scikit-learn、mlxtend 和自实现序列算法（PrefixSpan/GSP）实现经典数据挖掘算法。模块定位为**无需训练的探索性、描述性分析**（区别于机器学习模块的预测性建模）。

**核心特性**：
- 数据预检：检查行数/数值列/缺失值/异常值/时间列/ID列，按错误/警告/提示三级返回
- 算法推荐：根据数据特征为每个具体算法标记"推荐"或"慎用"状态
- 参数自动推荐：auto_params=True 时根据数据特征动态推荐参数
- 结果手动保存：默认不保存，用户点击"保存到数据管理"才创建 Dataset 记录
- 数据预览：返回前20行数据用于结果页展示

**接口清单**：

| 功能 | 端点 | 产物类型 | 说明 |
|------|------|----------|------|
| 原始数据列表 | `GET /api/data-mining/raw-data` | — | 获取挖掘模块数据 |
| 上传文件 | `POST /api/data-mining/upload` | raw_data | 上传到挖掘模块 |
| 数据预检 | `POST /api/data-mining/precheck` | — | 返回 data_profile + checks + recommendations（支持远程 remote 参数） |
| 参数推荐 | `POST /api/data-mining/recommend-params` | — | 返回 recommended_params + param_ranges + columns_used（支持远程） |
| 聚类分析 | `POST /api/data-mining/cluster` | cluster_result | 支持 KMeans/DBSCAN/层次聚类（支持远程） |
| 关联规则 | `POST /api/data-mining/association` | association_rules | 支持 Apriori/FP-Growth（支持远程） |
| 序列模式 | `POST /api/data-mining/sequence` | sequential_patterns | 支持 PrefixSpan/GSP（支持远程） |
| 查看关联规则 | `GET /api/data-mining/association/{id}` | — | 分页读取关联规则 |
| 查看序列模式 | `GET /api/data-mining/sequence/{id}` | — | 分页读取序列模式 |

**算法说明**：

1. **聚类算法**：
   - KMeans：肘部法则+轮廓系数自动推荐K（以轮廓系数为主，肘部法则为辅助参考）
   - DBSCAN：k-距离图自动推荐 eps，数据量分档推荐 min_samples
   - 层次聚类：ward linkage，复用 KMeans 的 K 推荐逻辑
   - 单特征数据：DBSCAN 基于标准差推荐 eps
   - 数据量>5000时采样计算轮廓系数避免性能问题

2. **关联规则算法**：
   - Apriori：经典算法，基于 mlxtend
   - FP-Growth：频繁模式增长算法，数据量较大时效率更高
   - 支持购物篮格式（tid_column + item_column）和自动二值化两种模式
   - 自动二值化：数值列用中位数二值化，类别列唯一值≤10用独热编码，>10用频率编码
   - 数据量分档自动推荐 min_support/min_confidence
   - 0规则时根据 lift 值分析原因（lift<1 提示负相关无价值，lift≥1 但低于阈值提示降低 min_lift）
   - 自动二值化模式置信度全为1时提示"结构性关联，建议切换购物篮格式"

3. **序列模式算法**：
   - PrefixSpan：基于投影数据库的递归挖掘（自实现）
   - GSP：逐层搜索的候选生成-计数算法（自实现）
   - 序列数分档自动推荐 min_support
   - 自动检测时间列、ID列、事件列（ID列检测依赖关键词，命中率低，需用户手动选择）

**参数校验函数**：
- `_validate_cluster_params`：校验特征列非空、为数值列、行数≥2
- `_validate_association_params`：区分 basket/binary 模式，购物篮格式需 tid_column + item_column
- `_validate_sequence_params`：校验三列（seq_id_column + time_column + event_column）非空、存在、行数≥2

**结果保存**：
- 聚类结果：保存为 CSV，每行追加 cluster 列
- 关联规则：保存为 JSON，包含 rules 列表和参数
- 序列模式：保存为 JSON，包含 patterns 列表和参数
- 保存时设置 parent_id 和 root_dataset_id 进行血缘追溯

**前端交互**：
- 数据预检卡片：显示数据概况、预检结果（错误/警告/提示）、算法推荐
- 参数配置3大Tab：聚类/关联规则/序列模式
- 自动推荐提示：基于 `used_recommendation` 标记控制显示（仅点击"自动推荐"按钮且未修改参数时显示）
- 序列模式Tab切换时才触发列自动填充，避免在其他Tab显示无关提示
- 数据管理中序列模式预览：表格显示序号、序列（el-tag 展开）、支持度、序列长度

### 4.6 特征工程模块（Feature Engineering）

**文件位置**：`backend/app/api/feature_engineering.py`

特征工程模块采用**"只增不删"**设计理念，所有操作均新增列，保留原始列。

| 功能 | 端点 | 说明 |
|------|------|------|
| 原始数据列表 | `GET /api/feature_engineering/raw-data` | 获取特征工程原始数据 |
| 数据集列表 | `GET /api/feature_engineering/datasets` | /raw-data 的别名 |
| 数据预览 | `GET /api/feature_engineering/data/{id}` | 前 100 行预览 |
| 列池查看 | `GET /api/feature_engineering/column-pool/{id}` | 列名+类型+是否原始列+来源 |
| 远程列池 | `GET /api/feature_engineering/remote-column-pool` | Query: connection_id/table_name，远程表列池（含工作副本构造列） |
| 删除构造列 | `DELETE /api/feature_engineering/column-pool/{id}` | 仅删构造列，原始列不可删 |
| 上传文件 | `POST /api/feature_engineering/upload` | 记录 original_columns 到 tags |
| 特征构造 | `POST /api/feature_engineering/construct` | 7种操作，原地更新（支持远程，写工作副本） |
| 特征编码 | `POST /api/feature_engineering/encode` | onehot/label，原地更新（支持远程） |
| 特征缩放 | `POST /api/feature_engineering/scale` | standard/minmax，原地更新（支持远程） |
| 特征降维 | `POST /api/feature_engineering/reduce` | pca/tsne，原地更新（支持远程） |
| 特征选择 | `POST /api/feature_engineering/select-features` | 4种方法，**仅返回得分排名，不生成数据集**（支持远程） |
| 预检 | `GET /api/feature_engineering/precheck/{id}` | 检测数据质量，判断 5 类操作可行性（结果缓存 Redis 5 分钟） |
| 进度查询 | `GET /api/feature_engineering/progress/{record_id}` | 任务进度（4 阶段） |
| 导出选择特征 | `POST /api/feature_engineering/export-selected` | 导出选中特征+目标列为 feature_result 产物 |
| 导出列池 | `POST /api/feature_engineering/export-pool` | 导出列池选中列为 feature_result 产物 |

**特征构造支持的 7 种操作**：
1. `arithmetic`：四则运算（除法检测分母是否含0，含0则拒绝）
2. `polynomial`：多项式特征
3. `log_transform`：对数变换
4. `binning`：分箱
5. `time_split`：时间拆解
6. `category_cross`：类别交叉
7. `target_encoding`：Target 编码

**特征选择支持的 4 种方法**：chi2（卡方）、mutual_info（互信息）、pearson（皮尔逊）、tree（树模型重要性）

**列池管理**：
- 上传时自动将原始列名存入 `tags` 字段的 `original_columns`
- 构造列记录在 `tags` 字段的 `generated_columns` 中，标注模块来源和标签
- 构造/编码/缩放/降维操作**不创建新 Dataset**，而是通过 `_update_dataset_file` 原地更新文件
- **特征选择（select-features）不再创建数据集**，仅返回得分排名结果供前端展示（2026-08-08 变更）
- 列池导出（export-pool）、特征选择导出（export-selected）产物类型统一为 `feature_result`
- **远程模式**：构造/编码/缩放/降维结果写入特征工程工作副本（feature_workcopy）而非原表，通过 `remote-column-pool` 获取列池

### 4.7 机器学习模块（ML）

**文件位置**：`backend/app/api/ml.py`、`backend/app/services/algorithm_registry.py`（算法注册表，纯模块级函数，`ml_service.py` 已删除）

提供完整的监督学习模型训练、评估、持久化和批量预测能力。

| 功能 | 端点 | 产物类型 | 说明 |
|------|------|----------|------|
| 原始数据列表 | `GET /api/ml/raw-data` | — | 获取 ML 模块数据 |
| 上传文件 | `POST /api/ml/upload` | raw_data | 上传到 ML 模块 |
| 训练前预检 | `POST /api/ml/precheck` | — | 数据预检（含算法推荐/目标列推荐），结果缓存 5 分钟 |
| 特征推荐 | `POST /api/ml/recommend-features` | — | 选择目标列后推荐特征列（含评分和勾选建议） |
| 有监督训练 | `POST /api/ml/train-supervised` | ml_model | 分类/回归，支持自动调优，智能异步（≥1万行异步，4 阶段进度上报），支持远程 |
| 模型列表 | `GET /api/ml/model-list/{id}` | — | 某数据集的所有模型（含 metrics/feature_columns/task_type） |
| 获取报告 | `GET /api/ml/reports/{id}` | — | 解析 ml_report/ml_model 的报告内容 |
| 批量预测 | `POST /api/ml/batch-predict/{id}` | ml_prediction | 使用已保存模型预测 |
| 测试集评估 | `POST /api/ml/models/{id}/test-evaluate` | — | 独立测试集最终评估（含 per_sample_info） |
| 导出模型 | `GET /api/ml/models/{id}/export` | — | 下载 pkl 文件（DataManagement.vue + MachineLearning.vue 均使用） |
| 导出报告 | `POST /api/ml/models/{id}/export-report` | ml_report | 报告导出到数据管理 |
| 图表导出 | `GET /api/ml/chart-export/{id}` | — | histogram/scatter/line PNG（**前端未使用，保留兼容**） |

> **重要变更**：原 9 个旧版算法路由（`/cluster` `/anomaly` `/association` `/apriori` `/feature-importance` `/dimensionality-reduction` `/random-forest` `/linear-regression` `/dbscan`）已从代码中**完全删除**（不再保留兼容）。聚类/关联/降维等功能迁移到数据挖掘、特征工程模块，或整合进 `train-supervised` 统一训练接口。对应 `MLService` 类与 `ml_service.py` 文件也已删除。

**有监督训练参数**：
- `test_size`：测试集比例（默认 0.2）
- `cv_folds`：交叉验证折数（默认 5）
- `auto_tune`：是否自动调优（默认 false）
- `tune_method`：grid（网格搜索）/ random（随机搜索，默认 20 次迭代）
- `random_seed`：随机种子（默认 42）
- 支持算法（14 种）：逻辑回归、SVM、决策树、朴素贝叶斯、K近邻、线性回归、岭回归、Lasso回归、随机森林、AdaBoost、梯度提升树（GBDT）、XGBoost、LightGBM、多层感知机（MLP）
  - 分类（11 个）：logistic_regression/svm/decision_tree/naive_bayes/knn/random_forest/adaboost/gbdt/xgboost/lightgbm/mlp
  - 回归（12 个）：linear_regression/ridge_regression/lasso_regression/knn/random_forest/adaboost/gbdt/xgboost/lightgbm/svm/decision_tree/mlp
- 训练前预检：自动推荐分类/回归算法及目标列，并标记推荐理由，写入任务配置
- 特征列智能推荐：选择目标列后自动调用 /recommend-features 返回推荐特征列

**训练流程**：
1. 数据准备 → 缺失值均值填充 → 非数值列转数值
2. 数据划分 → 训练+验证集 / 测试集分离
3. Pipeline 构建 → StandardScaler + 模型
4. 可选调优 → GridSearchCV / RandomizedSearchCV
5. 交叉验证 → KFold / StratifiedKFold
6. 模型评估 → 分类：accuracy/precision/recall/f1/roc_auc/混淆矩阵；回归：r2/mse/mae/rmse
7. 模型保存 → joblib 保存完整 pipeline 到 MinIO
8. 测试集保存 → 独立 CSV 文件用于后续评估

### 4.8 AI 分析模块（AI）

**文件位置**：`backend/app/api/ai.py`、`backend/app/services/ai_service.py`

基于 OpenAI 兼容 API（支持 DeepSeek 等）提供智能对话能力，核心特色为**上下文注入**（将数据产物摘要和操作记录注入对话，辅助 AI 分析）。

> **重要变更**：AI 模块已重构为上下文注入对话模式。旧的 `/query`、`/insights`、`/report`、`/metadata`、`/auto-insight`、`/trend-prediction`、`/anomaly-explanation`、`/recommend-steps`、`/follow-up` 路由及整组"AI 方案管理"（`/plans/*`）均已删除。AI 模块的 raw-data/upload 现复用 `/api/datasets/*` 接口。

| 功能 | 端点 | 说明 |
|------|------|------|
| 上下文注入对话 | `POST /api/ai/chat` | 多轮对话，Body: AIChatRequest(question, conversation_id, context_items, dataset_id, start_new_topic)。上下文不足时返回 needs_context 引导补充 |
| 上下文选项 | `GET /api/ai/context/options` | 加载可注入项：datasets（扁平列表，含 category/sub_type 两级分类字段）+ recent_tasks（过滤 upload/dataset/ai 三大类，每项含 group_key 归一化分组/is_remote/remote_connection_name/remote_table_name）+ tasks_pagination。支持 Query 筛选：is_remote（本地/远程）、task_type（cleaning/data_analysis/data_mining/feature_engineering/ml）。**前端 AIAnalysis.vue 展示时额外排除 user_admin（账号管理）类操作记录**（filteredTasks 计算属性过滤，2026-08-15） |
| 上下文预览 | `GET /api/ai/context/preview` | 预览上下文项摘要（type: dataset/operation + ref_id） |
| 会话列表 | `GET /api/ai/conversations` | 按时间倒序 |
| 会话详情 | `GET /api/ai/conversations/{id}` | 单条会话详情 |
| 删除会话 | `DELETE /api/ai/conversations/{id}` | 删除会话 |
| 重命名会话 | `PATCH /api/ai/conversations/{id}/rename` | 修改会话标题（Body: {new_title}） |
| AI 配置查看 | `GET /api/ai/config` | 获取配置状态 |
| AI 配置保存 | `POST /api/ai/config` | 保存提供商/Key/模型 |
| 配置测试 | `POST /api/ai/config/test` | 测试连接 |
| 使用统计 | `GET /api/ai/usage/stats` | Token 消耗统计 |

**AI 会话管理**：
- 会话 30 分钟过期，初始 10 次追问配额
- 对话历史逐条存储于 `ai_messages` 表（role/content/context_items/tokens_used）
- 用户选中的上下文项持久化于 `ai_conversation_contexts` 表（item_type: dataset/operation）
- 超出滑动窗口的旧消息可压缩为摘要存储于会话 `summary` 字段
- 每次对话记录 Token 使用量到 AIUsageLog 表

**时间戳规范**：
- 会话标题时间戳后端用 `shanghai_now()` 生成（上海时区）
- 前端相对时间精确到秒（X 秒前 / X 分 Y 秒前 / X 小时 Y 分 Z 秒前 / X 天 Y 小时 Z 分 W 秒前，超 7 天显示绝对时间）
- 绝对时间格式 yyyy-MM-dd HH:mm:ss

**AI 配置**：
- 支持多配置存储，仅激活配置生效
- 优先使用系统环境变量 `OPENAI_API_KEY`，其次使用数据库配置
- 默认模型：`deepseek-chat`（环境变量配置）

### 4.9 首页（HomeView）

**文件位置**：`frontend/src/views/HomeView.vue`（路由 `/`，无需登录）

**2026-08-15 真实化改造**：
- **统计区真实数据**（登录后并行加载 + 600ms 数字滚动动画）：
  - 可用数据集数：`GET /api/datasets`（返回数组长度）
  - 操作记录数：`GET /api/datasets/task-records`（total 字段）
  - AI Token 用量与今日对话：`GET /api/ai/usage/stats`（total_tokens / today_calls）
  - 数据源连接数：`GET /api/data-sources`（返回数组长度）
  - 未登录时统计卡显示 `--` 与"登录后查看"
- **Hero 区登录感知**：登录显示"欢迎回来，{username}"徽章 + 描述句追加真实累计统计（如"你已积累 N 个数据集、M 次操作、X Token"）+ 按钮切换为"继续探索"；未登录显示平台介绍 + "立即开始/登录体验"双按钮；右侧装饰卡为真实数据驱动（数据集总量/今日 AI 对话）。`watch(isAuthed)` 处理 keep-alive 缓存下退出登录的统计重置
- **数据挖掘卡片文案校正**：异常检测（已移除功能）→ 聚类/关联规则/序列模式
- **三条路径 SVG 分支流程图**：公共主干"原始数据→数据清洗"后三分叉（路径 A 纯挖掘线青色/路径 B 建模预测线紫色/路径 C 挖掘+建模组合线橙色）；节点分色（普通描边圆+实心圆心 / 阶段成果实心色圆 / 终点绿色渐变圆）；路径 C"挖掘产物→特征工程"虚线连接标注"作为特征输入"；**窄屏（≤1080px）自动降级为纵向路径列表**（flow-list），原横向卡片样式已删除

---

## 5. 管理后台模块详解

**文件位置**：`backend/app/api/admin.py`

管理后台提供独立的认证体系和全面的运维管理功能，共 62 个 API 端点（2026-08-15 新增用户管理增强、用户申请管理、任务详情/取消/重试、AI 用量统计、数据大屏聚合等）。

### 5.1 管理员认证

| 端点 | 说明 |
|------|------|
| `POST /admin/auth/login` | 管理员登录，使用独立的 admin_oauth2_scheme |
| `GET /admin/auth/me` | 获取当前管理员信息 |

管理员账户在应用启动时通过 `ensure_admin_user()` 自动创建，用户名/密码由环境变量配置。

### 5.2 服务管理

| 端点 | 说明 |
|------|------|
| `GET /admin/services/status` | 获取所有 Docker 服务状态（运行状态/健康检查/端口映射；**2026-08-15：PostgreSQL 由硬编码 online 改为真实检测**——`_postgres_available()` 执行 SELECT 1） |
| `POST /admin/services/{name}/start` | 启动指定服务 |
| `POST /admin/services/{name}/stop` | 停止指定服务 |
| `POST /admin/services/restart-all` | 重启所有服务 |
| `GET /admin/services/metrics` | 服务资源指标（CPU/内存/网络IO） |

服务管理通过 Docker SDK（`docker` 库）实现，直接操作容器。容器命名规则：`data-insight-{service}`。

### 5.3 缓存管理

| 端点 | 说明 |
|------|------|
| `GET /admin/cache/stats` | 缓存统计（**2026-08-15 增强**：total_keys 应用真实键数/memory_bytes 内存占用/hits/misses/hit_rate 应用级命中埋点；**hit_rate 总请求 <10 时返回 null**，前端显示"样本不足"） |
| `GET /admin/cache/keys` | 缓存键列表（支持前缀模式匹配；**2026-08-15 改 scan_iter 防阻塞 + 每项 size_bytes 值大小**） |
| `GET /admin/cache/keys/{key}` | 查看指定缓存键的值 |
| `DELETE /admin/cache/keys/{key}` | 删除指定缓存键 |
| `POST /admin/cache/clear` | 清空所有缓存 |
| `GET /admin/cache/hit-rate` | 缓存命中率（**2026-08-15 重写**：range=24h/7d/30d；实时值用 cache_manager 进程内埋点，历史趋势从 cache_stats_hourly 表读取；**current.hit_rate 与 summary.avg_hit_rate 总请求 <10 时返回 null**） |
| `GET /admin/cache/category-stats` | 按业务分类全量统计（**2026-08-15 新增**：后端 scan 全量键聚合，替代前端当前页聚合失真） |
| `POST /admin/cache/clear-category` | 按业务分类清理（**2026-08-15 新增**：仅删该分类前缀键，不影响其他模块与验证码等临时键；"通用缓存"分类扫描删除所有非已知前缀键） |
| `DELETE /admin/cache/history` | 删除历史缓存统计（**2026-08-15 新增**：Query start/end 可选 YYYYMMDDHH，不传清空全部、传了按小时范围删除；供历史统计 Tab"删除历史"按钮） |

**缓存键业务分类**（_CACHE_KEY_CATEGORY_MAP，2026-08-15 补全特征工程/验证码）：`feature_engineering:`（特征工程缓存）/`support:`（验证码缓存）/`datasets:`（数据集缓存）/`cleaning:`（清洗缓存）/`users:`（用户缓存）/`ai:`（AI缓存）/`ml:`（ML缓存），其余归"通用缓存"。

**缓存管理模块说明**（AdminCache.vue，2026-08-15 全面改造，**2 Tab 结构**，Tab 样式与任务/数据库模块一致为 border-card）：
- **实时缓存 Tab**（回答"现在有什么缓存、怎么清理"）：
  - **缓存概览指标卡**：缓存后端（Redis/内存）/ 键总数（应用真实计数）/ 内存占用 / 应用命中率（>80% 绿，否则黄；**总请求 <10 显示"样本不足"**）
  - **按业务分类清理**：分类卡片（键数 + 占比条 + 占比）+ "清理该分类"按钮（count=0 时显示"暂无键"）
  - **缓存键列表**：多选批量删除 + 大小列（B/KB/MB）+ 前缀过滤 + 分类筛选 + 查看详情/单键删除 + 清空缓存
- **历史统计 Tab**（回答"过去缓存使用情况如何"，数据来自 cache_stats_hourly 持久化表）：
  - **历史汇总指标卡**：累计请求次数 / 平均命中率（加权，**样本 <10 显示"样本不足"**）/ 键数峰值 / 数据起始时间
  - **三张趋势图**：命中率折线、请求量堆叠柱（命中/未命中）、缓存键数量折线；时间范围切换（24小时/7天/30天）；**切到本 Tab 时对三图执行 resize()（修复 el-tabs 隐藏容器 echarts 宽度为 0 导致的图表不显示）**
  - **删除历史按钮**：弹窗可选"清空全部 / 按时间范围删除"（datetimerange 选择起止），删除后自动刷新图表
- **统一确认弹窗**：单键删除/批量删除/分类清理/清空全部/删除历史均走 ElMessageBox.confirm（type=warning），清空全部额外警示验证码等临时键影响

### 5.4 存储管理

| 端点 | 说明 |
|------|------|
| `GET /admin/storage/stats` | 存储统计（对象数/总大小MB） |
| `GET /admin/storage/files` | 文件列表（支持前缀筛选/分页） |
| `GET /admin/storage/stats-by-type` | 按文件类型统计（9 大类） |
| `DELETE /admin/storage/files` | 删除文件（Query: file_path） |
| `POST /admin/storage/files/batch-delete` | 批量删除（Body: {file_paths: []}，同时删除 MinIO 文件 + Dataset 记录 + TaskRecord 记录） |
| `GET /admin/storage/files/download/{path}` | 下载文件 |
| `GET /admin/storage/download/{path}` | 下载文件（别名） |

**分类统计说明**（9 大类，均基于 MinIO 路径前缀统计，`/admin/storage/stats-by-type`）：
- `uploads`：原始上传数据
- `cleaning`：清洗结果
- `data_mining`：数据挖掘产物
- `feature_engineering`：特征工程产物
- `models`：机器学习模型文件（.pkl）
- `ml`：预测数据和预测结果（ml/路径）
- `reports`：分析报告
- `trash`：回收站文件
- `other`：其他未分类文件（动态归类）

> 注意：无独立 `ai` 分类（AI 相关文件归入 other），前端 AdminStorage.vue 分类卡片与后端 stats-by-type 一致为 9 类。

**文件列表说明**：
- 全部分类时合并 MinIO 下所有文件
- 文件按路径前缀归类（ai/ml 为 MinIO 路径前缀，非数据库表）
- 批量删除同时清理 MinIO 文件、Dataset 数据库记录和关联的 TaskRecord 记录

### 5.5 数据库管理

| 端点 | 说明 |
|------|------|
| `GET /admin/database/tables` | 列出所有数据库表 |
| `GET /admin/database/tables/{name}/data` | 查看表数据（分页） |
| `GET /admin/database/tables/{name}/export` | 导出表数据为 CSV |
| `POST /admin/database/query` | 执行 SQL 查询（仅 SELECT） |
| `GET /admin/database/backup` | 数据库备份（pg_dump） |

**前端页面说明**：管理端数据库管理页面为 4 Tab（表结构/SQL 查询/ClickHouse/索引说明）。表结构支持下拉筛选、表统计（行数/大小/索引数）、数据预览、CSV 导出、表结构弹窗；SQL 查询支持参数化查询、搜索、历史记录（localStorage）。

### 5.6 任务与业务统计

| 端点 | 说明 |
|------|------|
| `GET /admin/tasks/stats` | 任务统计（**2026-08-15 增强**：async_available/mode + running_count 运行中/pending_count 排队中/today_total 今日任务/today_success 今日成功/today_failed 今日失败/success_rate 成功率/avg_execution_time_ms 平均耗时，供任务管理顶部监控卡与统计指标卡） |
| `GET /admin/business/datasets` | 所有用户的数据集列表（Dataset 表，支持 keyword 文件名搜索，返回含 color/source_type/connection_id/table_name） |
| `GET /admin/business/stats` | 业务统计（数据集数/用户数/任务数等） |
| `GET /admin/business/tasks` | 所有用户的任务记录（**2026-08-15 增强**：新增 username 用户名模糊搜索、failure_category 失败分类、date_from/date_to 时间范围筛选、**task_type_prefix 前缀筛选**（如 feature_engineering 匹配 5 个子类型，与 task_type 二选一），状态支持 pending/running/success/failed/cancelled；返回补 failure_category/failure_category_label/is_remote/dataset_id/has_progress；管理员取消的任务 detail 前缀"【管理员取消】"） |
| `GET /admin/business/task-stats` | 任务统计（按类型/状态分组；**2026-08-15 新增** by_status 状态分布、by_module_failed 模块失败数；**by_date 增强**：每项新增 success_count/failed_count/success_rate（当日成功率），供任务统计 Tab"任务数与成功率"双轴图） |
| `GET /admin/tasks/{id}` | 管理端任务详情（2026-08-15 新增：params/result_summary/error_message 等完整信息，供详情抽屉） |
| `POST /admin/tasks/{id}/cancel` | 管理端取消任务（2026-08-15 新增：仅 pending/running 可取消，绕过用户归属校验，标注 result_summary.admin_cancel） |
| `POST /admin/tasks/{id}/retry` | 管理端重试任务（2026-08-15 新增：仅 failed 可重试，不可重试分类拒绝，复用队列容量检查，retry_history 标注 operator=admin） |
| `POST /admin/business/datasets/{id}/restore` | 恢复 purged 数据集到 deleted（用户端回收站可见），写入 admin_restore 任务留痕并清理用户缓存 |
| `DELETE /admin/business/datasets/{id}/permanent-delete` | 管理端物理删除（不可恢复），写入 admin_permanent_delete 任务留痕并清理用户缓存 |

**数据管理模块说明**（AdminDataManagement.vue，3 个 Tab）：
- **数据列表 Tab**：分类统计卡片（7 类，来自 /admin/business/stats）+ 数据集列表（仅查看 Dataset 数据，每行"永久删除"按钮 el-popconfirm，调用 /admin/business/datasets/{id}/permanent-delete 物理删除）
- **已损坏 Tab**：显示 status=corrupted 的数据（物理文件丢失但数据库记录存在），仅提供"删除记录"（物理删除数据库记录，不进入回收站）；**查询时自动批量检测 MinIO 文件是否存在**（一次性拉取对象路径集合内存判断，避免逐条网络请求超时）；筛选卡片标题为"筛选条件"
- **已清空 Tab**（业务回收站）：显示 status=purged 的数据，仅提供"恢复"/"批量恢复"（restore-purged 到 deleted，用户端回收站可见），**不提供删除**；筛选卡片标题为"筛选条件"
- 每个 Tab 支持按用户筛选 + 文件名关键字搜索（keyword 传后端）；每行"详情"按钮打开弹窗（远程数据集显示"数据来源"连接/表名）
- 合并多个分类（如机器学习含 `ml` 和 `batch_predict` 模块数据）后重新按时间排序，再进行分页
- 数据列表操作列仅保留查看功能，下载在存储管理模块中执行

**任务管理模块说明**（AdminTasks.vue，2026-08-15 全面改造，2 Tab）：
- **业务任务历史 Tab**：
  - 顶部**队列监控卡**：运行中/排队中/今日任务/今日失败 4 项实时指标 + Celery 模式标签（celery 异步/同步降级）
  - **筛选区**：任务类型（10 项：上传/治理/清洗/模型训练/机器学习/特征工程/挖掘/分析/AI分析/账号管理；**特征工程走 task_type_prefix 前缀匹配 5 个子类型**；原"流程联动(pipeline)"为 module_source 概念非任务类型，已移除）/用户名搜索/状态（补等待中·已取消）/失败分类（参数错误·数据问题·系统故障·执行超时·网络错误·未知错误）/时间范围（今天·最近7天·最近30天·自定义 datetimerange）/分页条数（20/50/100）
  - **列表**：新增失败分类列；**运行超 40 分钟任务整行标红 + "运行超时"提示**；操作列按状态显示详情/取消（pending·running）/重试（failed）
  - **详情抽屉**（getTaskDetail）：状态/失败分类标签 + 基础信息（用户/数据来源/关联数据集/时间/耗时/Celery 任务 ID）+ 失败原因红框 + 管理员取消标注 + 执行进度（el-progress + 阶段时间线）+ 重试历史（标注用户/管理员重试）+ 执行参数 JSON；底部按状态提供取消/重试快捷按钮
- **任务统计 Tab**：新增**健康指标卡**（任务总数/成功率/失败率/平均耗时）+ **状态分布环形图**（成功/执行中/等待中/失败/已取消）+ **按模块失败 TOP**（前 5 横向条形图）；保留原有按模块/按用户/按日 3 图
- **取消/重试留痕约定**：管理员取消/重试只在**原任务记录**上标注（cancel 写 `result_summary.admin_cancel{admin, at, note}`，retry 写 `retry_history.operator="admin"`），不新建独立记录——用户端操作历史可见"【管理员取消】"前缀与重试来源，且不污染任务统计
- **僵尸任务自动自愈**（2026-08-15 新增）：`/business/tasks` 与 `/tasks/stats` 查询前自动执行 `_auto_heal_zombie_tasks`——将"status=running 且 celery_task_id 为 NULL 且创建超 60 分钟"的记录置为 cancelled 并标注 `admin_cancel{admin: "system"}`（远超 Celery 30 分钟硬超时，必然为进程中断遗留的假运行状态），防止僵尸任务堆积与运行中计数虚高

### 5.6.1 数据源连接管理（2026-08-14 新增）

管理端新增"数据源管理"页面（AdminDataSources.vue + /admin/datasource-connections 3 路由），用于运维审计：

| 端点 | 说明 |
|------|------|
| `GET /admin/datasource-connections` | 数据源连接列表（含用户名、引用数，密码脱敏 `••••••`） |
| `POST /admin/datasource-connections/{id}/test` | 测试连接（复用 data_sources 内部连接测试 + Fernet 解密） |
| `DELETE /admin/datasource-connections/{id}` | 删除连接（引用保护：有数据集引用时 409 拒绝） |

### 5.7 用户管理

**文件位置**：`backend/app/api/admin.py`、`frontend/src/views/admin/AdminUsers.vue`

| 端点 | 说明 |
|------|------|
| `GET /admin/users` | 用户列表（search 搜索 + status 筛选 active/disabled/locked；每用户含账号状态/登录信息/数据集数/存储量/任务数，时间上海时区） |
| `GET /admin/users/stats` | 用户统计（总数/今日活跃/禁用数/锁定数/数据集总数/总存储；**2026-08-15 新增 registration_trend 近 30 天注册趋势**，排除 admin） |
| `PUT /admin/users/{id}/status` | 禁用/启用账号（管理员账号与当前登录管理员不可操作；启用时重置失败计数与锁定；写入 user_admin 任务留痕） |
| `POST /admin/users/{id}/reset-password` | 重置密码（指定或自动生成 10 位随机密码；同时清除锁定状态；不留密码明文） |
| `POST /admin/users/{id}/unlock` | 手动解锁账号（清除失败计数与锁定状态） |

**前端页面（AdminUsers.vue，2 Tab）**：
- **用户列表 Tab**：统计卡（总用户/今日活跃/禁用/锁定）+ 搜索 + 状态筛选 + 行内操作（禁用/启用、重置密码、解锁）+ 详情下钻（账号状态/登录信息/数据集数/任务数/存储量）
- **用户申请 Tab**：联系管理员提交的申请（见 5.7.1）

### 5.7.1 用户申请管理（2026-08-15 新增）

**文件位置**：`backend/app/api/admin.py`（/admin/users/messages* 4 路由）、`frontend/src/views/admin/AdminUsers.vue`

| 端点 | 说明 |
|------|------|
| `GET /admin/users/messages` | 申请列表（category/status/keyword 筛选分页；含分类中文标签/内容摘要/状态中文标签，时间上海时区） |
| `GET /admin/users/messages/{id}` | 申请详情 |
| `POST /admin/users/messages/{id}/process` | 标记已处理（admin_note ≤500 字 + admin_id + processed_at；重复处理 400） |
| `DELETE /admin/users/messages/{id}` | 删除申请（同步删除 MinIO 截图附件） |

**处理弹窗能力**：
- 申请详情展示（分类/申请人/联系方式/内容/提交 IP/提交时间/状态）+ 截图预览/下载
- **申请人账号核实区**：自动查询申请人账号状态（正常/禁用/锁定）、注册时间、数据集数、任务数；恢复类申请自动按申请人名下搜索数据集（供核实归属）；未找到账号时明确提示"系统中未找到用户名「xxx」，请谨慎核实"
- **一键处理**：解锁/恢复调用现有接口（`/admin/users/{id}/unlock`、`/admin/business/datasets/{id}/restore`）+ 处理备注后标记已处理
- **静默搜索约定**：打开弹窗触发的自动搜索静默（silent 不弹提示）；**已处理申请不再自动搜索**，避免弹出"申请人名下未找到匹配的已清空数据集"干扰管理员

### 5.8 系统概览与日志

| 端点 | 说明 |
|------|------|
| `GET /admin/overview` | 系统总览（**2026-08-15 增强**：total_users/total_datasets/total_storage_bytes/total_tasks/task_success_rate/active_users_today/today_new_users/today_tasks/errors_today 共 9 项 + **trends 近 30 天增长趋势**；存储量用 MinIO stats 聚合；今日维度按 UTC 零点；今日错误取 log_records ERROR 计数） |
| `GET /admin/logs` | 查看日志（**2026-08-15 重构**：结构化解析返回 time/level/module/message；级别/日期精确匹配；支持 file 指定轮转文件、since 增量刷新；模块 api/error/system，级别 INFO/WARNING/ERROR） |
| `GET /admin/logs/files` | 日志文件列表（**增强**：含全部轮转文件，标记当前/轮转、大小、修改时间） |
| `GET /admin/logs/summary` | 日志概览（**2026-08-15 新增**：今日+历史入库记录汇总、各模块文件占用） |
| `GET /admin/logs/trend` | 错误/警告趋势（**2026-08-15 新增**：range=24h/7d，基于 log_records 表，上海时区标签） |
| `GET /admin/logs/export` | 导出筛选日志为 txt（**2026-08-15 新增**，流式下载） |

**日志模块说明**（2026-08-15 重构，AdminLogs.vue **2 Tab 结构**，border-card 与缓存/任务模块一致）：
- **当日日志 Tab**：今日概览卡（今日日志条数/今日错误/今日警告/今日入库）+ 当日明细（级别/模块/关键字筛选，增量自动刷新，导出当日），日期固定为今天
- **历史统计 Tab**：历史汇总卡（累计入库/历史错误/历史警告/文件占用）+ 错误/警告趋势图（24h/7d）+ 历史日志查询（日期/轮转文件/级别/模块/关键字 + 分页 + 导出）+ 最近错误列表 + 日志文件管理（查看轮转文件联动查询）
- **入库机制**：`logger.py` 的 DbLogHandler 自动捕获 WARNING/ERROR 异步入库 `log_records` 表（不阻塞主流程），INFO 级 API 日志仅存文件
- **文件轮转**：按天 + 单文件 50MB 上限 + 保留 30 份，自动删除最旧（非覆盖）；logs 目录文件作为原始备份保留

**服务总览模块说明**（AdminDashboard.vue，2026-08-15 增强）：
- **系统健康横幅**：全部服务在线绿色"所有服务运行正常"，有离线黄色并列出离线服务
- **数据概览**：6 指标卡（总用户+今日新增 / 数据集 / 存储量 / 任务+成功率+今日 / 今日活跃 / 今日错误）
- **近 30 天增长趋势图**：新增用户/新增数据集/任务数三线（数据来自 /admin/overview.trends，随 30 秒自动刷新更新）
- **近期动态**：今日错误 TOP5（listLogs level=ERROR）+ 最近任务 TOP5（listBusinessTasks，状态标签/失败摘要/时间）；跳转链接 `#/logs`、`#/tasks`（**管理端为 hash 路由无 /admin 前缀**，2026-08-15 修复写错 `/admin/logs` 导致的白屏）
- **自动刷新**：30 秒间隔（原 5 秒调低）；首次加载立即请求（onMounted 同步调用 refreshStatus）
- 服务状态列表 / 启动/停止 / 重启所有 / 降级说明保留原有功能

**AI 用量与数据大屏模块说明**（2026-08-15 新增，导航项：数据大屏置顶 / AI 用量）：
- **AI 用量页**（AdminAIUsage.vue + `/admin/ai-usage/stats`）：汇总指标卡（总调用/token/平均每次）+ 近 30 天 Token 消耗趋势图 + 按用户统计表（带用户名搜索）。AI 分析重构后会话统一为智能对话（general_chat），不再区分模块，故无按模块统计
- **数据大屏**（AdminDashboardScreen.vue + `/admin/dashboard` 一次聚合接口）：深色全屏运营看板，KPI 行（用户/数据集/存储/任务+成功率/AI Token/今日错误）+ **3 屏×每屏 2 张大图**（增长趋势 / AI 与任务 / 分布统计）+ 底部最近任务与今日错误（溢出缓慢无缝滚动）
- **轮播交互**：自动 5 秒切换（顶部开关暂停、鼠标悬停图表区暂停、底部圆点/箭头手动切换）；echarts 采用 v-if 仅渲染当前屏 + 切屏全量 dispose 重建（修复隐藏容器宽度为 0 导致图表不更新）；数据集模块分布由后端直接返回中文标签
- **趋势融合**：用户管理页注册趋势柱状图（/admin/users/stats.registration_trend）、任务管理按日统计升级为"任务数+成功率"双轴图（/admin/business/task-stats.by_date）

### 5.9 ClickHouse 管理

| 端点 | 说明 |
|------|------|
| `GET /admin/clickhouse/status` | ClickHouse 连接状态 |
| `GET /admin/clickhouse/databases` | 数据库列表 |
| `GET /admin/clickhouse/tables` | 表列表 |
| `POST /admin/clickhouse/query` | 执行 ClickHouse 查询（Body `{"query":"..."}`，仅 SELECT；返回含列名/数据/行数） |
| `GET /admin/clickhouse/sync-status` | 数据集同步状态列表（registry + 阈值/可用性汇总，6 统计卡 + 状态表格） |
| `POST /admin/clickhouse/sync/{id}` | 手动重建单个数据集同步（异步触发；非 raw_data 400 / 不存在 404） |
| `POST /admin/clickhouse/cleanup/{id}` | 清理单个副本（副本表 + 注册记录，源数据不受影响） |
| `POST /admin/clickhouse/cleanup-all` | 清理全部副本 |
| `GET /admin/clickhouse/storage-stats` | 副本存储占用统计（system.tables 汇总） |

**2026-08-16 起 ClickHouse 已参与业务**：数据分析 4 接口（statistics/quality/chart/chart-recommendations）大表（≥1万行原始数据）自动同步副本后走 CH 全量聚合加速，失败/小表自动降级 pandas；**支持中文列名同步**（标识符白名单 Unicode）；同步链路含对拍校验（count/sum/mean/min/max）与注册表（dataset_registry）。管理端 ClickHouse Tab 提供：同步状态概览（重建同步/清理）、查询工具（库下拉**仅显示业务库 analysis**、按分组查询示例、中文列名结果正确展示）。clickhouse_service 所有 client 操作经线程锁串行化，避免并发 concurrent queries。

---

## 6. 系统架构设计

### 6.1 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        前端层 (Frontend)                         │
│  Vue 3 + Vite + Element Plus + ECharts + Axios                  │
│  ├─ 用户端：登录/数据管理/清洗/分析/挖掘/特征工程/ML/AI          │
│  └─ 管理端：服务监控/缓存管理/存储管理/日志查看                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      API 网关层 (Nginx)                          │
│  静态文件服务 / API 反向代理 / 大文件上传支持 (100M)              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    后端服务层 (FastAPI)                          │
│  ├─ 用户端 API (api/)                                           │
│  │   ├─ users.py          → 用户注册/登录/JWT/账号锁定禁用/个人中心 │
│  │   ├─ datasets.py       → 数据集 CRUD/上传/导出/回收站          │
│  │   ├─ cleaning.py       → 数据清洗/质量评分/差异对比            │
│  │   ├─ data_analysis.py  → 图表/智能推荐/分析报告              │
│  │   ├─ data_mining.py    → 聚类/关联规则/序列模式           │
│  │   ├─ feature_engineering.py → 特征构造/编码/缩放/降维/选择     │
│  │   ├─ ml.py             → 模型训练/预测/评估/导出                │
│  │   ├─ ai.py             → 上下文注入对话/会话管理               │
│  │   ├─ data_sources.py   → 远程数据库连接管理（全同步 def）        │
│  │   └─ support.py        → 联系管理员公开接口（无需登录）          │
│  │                                                               │
│  ├─ 管理端 API (api/admin.py)                                    │
│  │   └─ 服务/缓存/存储/数据库/任务/用户/日志/ClickHouse 管理       │
│  │                                                               │
│  ├─ 业务逻辑层 (services/)                                       │
│  │   ├─ data_service.py     → 数据加载/清洗/统计/远程查询（核心）   │
│  │   ├─ algorithm_registry.py → 算法注册表（ML 估算器构造，纯函数） │
│  │   ├─ ai_service.py       → AI 服务封装 + ai_context 子包        │
│  │   ├─ storage_manager.py  → MinIO 对象存储                     │
│  │   ├─ cache_manager.py    → Redis 缓存 + 内存降级               │
│  │   ├─ task_manager.py     → Celery 异步 + 同步降级              │
│  │   └─ task_scheduler.py   → 任务排队调度器（激活 pending 任务）   │
│  │                                                               │
│  ├─ 数据模型层 (models/)                                         │
│  │   ├─ User / Dataset / TaskRecord                              │
│  │   ├─ AIConversation / AIMessage / AIConversationContext / AIUsageLog / AIConfig │
│  │   └─ DataSourceConnection / AppConfig（远程连接 + 应用配置）     │
│  │                                                               │
│  ├─ 工具层 (utils/)                                              │
│  │   ├─ security.py   → JWT/SHA256密码哈希/用户获取               │
│  │   ├─ db.py         → 数据库会话管理 + 建表兼容补丁              │
│  │   ├─ common.py     → 通用工具函数                              │
│  │   ├─ task_records.py → 任务记录管理 + 排队容量统计              │
│  │   ├─ task_labels.py → 中文标签映射引擎（操作历史中文化）         │
│  │   ├─ crypto.py     → Fernet 加密（远程连接密码）                │
│  │   ├─ exception_handlers.py → 全局异常处理                      │
│  │   └─ logger.py     → 日志管理                                 │
│  │                                                               │
│  └─ 配置管理 (config.py)                                         │
│      └─ 强制要求 PostgreSQL，SQLite 已废弃                        │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  PostgreSQL   │    │  Redis        │    │  MinIO        │
│  (主数据库)    │    │  (缓存/任务)  │    │  (对象存储)   │
│  必须启用      │    │  可选/降级    │    │  必须启用      │
└───────────────┘    └───────────────┘    └───────────────┘
                              │
                     ┌───────────────┐
                     │  Celery       │
                     │  (异步任务)   │
                     │  可选/降级    │
                     └───────────────┘
```

### 6.2 分层设计说明

| 层级 | 职责 | 核心文件 |
|------|------|----------|
| 表现层 | 用户界面和交互 | `frontend/src/views/*.vue` |
| API 网关 | 反向代理、静态文件服务 | `frontend/nginx.conf` |
| 接口层 | RESTful API 定义、请求校验 | `backend/app/api/*.py` |
| 业务逻辑层 | 核心业务处理、算法调用 | `backend/app/services/*.py` |
| 数据访问层 | ORM 模型、数据库操作 | `backend/app/models/`、`backend/app/utils/db.py` |
| 基础设施层 | 缓存、任务队列、对象存储 | `backend/app/services/cache_manager.py` 等 |

### 6.3 实际使用的服务层

以下服务层被业务代码实际使用：

| 服务 | 文件 | 使用情况 | 降级机制 |
|------|------|----------|----------|
| DataService | `data_service.py` | 核心服务，所有模块使用（含 7 个远程查询方法） | 无（必需） |
| DataCleaningService | `data_service.py` | 清洗模块使用 | 无（必需） |
| AIService | `ai_service.py` | AI 模块使用 | AI 不可用时使用降级模板 |
| AlgorithmRegistry | `algorithm_registry.py` | ML 训练估算器构造（ml.py _execute_training），纯模块级函数 | 无（必需） |
| StorageManager | `storage_manager.py` | 所有模块使用 | **无降级**（MinIO 不可用时直接报错） |
| CacheManager | `cache_manager.py` | datasets.py 和 admin.py 使用 | Redis 不可用时降级为内存 LRU |
| TaskManager | `task_manager.py` | cleaning/feature_engineering/ml/admin 使用 | Celery 不可用时降级为同步执行 |
| TaskScheduler | `task_scheduler.py` | main.py 启动时 start（CELERY_ENABLED 时） | 独立线程，依赖 task_records.py |
| ai_context 子包 | `services/ai_context/` | AI 上下文注入（builder/extractors/task_summarizer/conversation_compressor/preset_followups + prompts 5 个 txt） | 无（必需） |

> 注：`ml_service.py` 与 `MLService` 类已删除（2026-08-05 起），ML 训练逻辑直接在 ml.py 的 `_execute_training` 中实现。

### 6.4 服务交互关系

1. **用户上传数据** → API 接收文件 → `storage_manager` 保存到 MinIO → `DataService` 解析 → `Dataset` 模型记录
2. **数据清洗** → `cleaning.py` 接收配置 → `DataCleaningService` 分阶段执行 → 保存新文件 → 创建 `cleaning_result`
3. **机器学习** → `ml.py` 接收参数 → `algorithm_registry.build_estimator` 构造模型 → sklearn 训练 → pkl 保存模型到 MinIO → 创建 `ml_model`
4. **AI 分析** → `ai.py` 接收问题 → `AIService` 调用 OpenAI API → 返回结果 / 创建会话记录
5. **模块间导入** → `datasets.py` 的 `import` 接口 → 复制文件 → 创建目标模块的 `raw_data`

---

## 7. 技术栈详解

### 7.1 后端技术栈

| 技术 | 用途 |
|------|------|
| Python 3.11 | 编程语言 |
| FastAPI | Web 框架 |
| Uvicorn | ASGI 服务器 |
| SQLAlchemy 2.0+ | ORM 框架（PostgreSQL） |
| Pydantic 2.5+ | 数据校验和配置管理 |
| Pandas 2.0+ | 数据处理和分析 |
| NumPy | 数值计算 |
| Scikit-learn | 机器学习算法 |
| Matplotlib | 图表生成（PNG/PDF 导出） |
| mlxtend | 关联规则挖掘（Apriori） |
| OpenAI SDK | AI 大语言模型调用 |
| python-jose | JWT Token 签发和验证 |
| hashlib (sha256) | 密码哈希 |
| openpyxl | Excel 读写 |
| python-dotenv | 环境变量加载 |
| minio | MinIO 对象存储 SDK |
| redis-py | Redis 缓存客户端 |
| celery | 异步任务队列 |
| docker | Docker SDK（管理端服务控制） |

### 7.2 前端技术栈

| 技术 | 用途 |
|------|------|
| Vue 3 | 前端框架 |
| Vue Router 4 | 单页应用路由 |
| Vite 5 | 构建工具 |
| Element Plus | UI 组件库 |
| ECharts 5 | 数据可视化图表 |
| Axios | HTTP 客户端 |
| marked | Markdown 渲染（使用说明文档） |

### 7.3 基础设施

| 技术 | 用途 | 是否必需 |
|------|------|----------|
| PostgreSQL 17 | 主数据库 | **必需** |
| MinIO | 对象存储 | **必需**（无降级） |
| Redis | 缓存和任务队列 | 可选（有内存降级） |
| Celery | 异步任务 | 可选（有同步降级） |
| Docker Compose | 多服务编排 | 部署用 |
| Nginx | 前端 Web 服务器和反向代理 | 部署用 |

---

## 8. 项目目录结构

```
data-insight-platform/
├── backend/                          # 后端服务
│   ├── app/                          # 应用代码
│   │   ├── api/                      # API 路由层（11 个模块，171 路由）
│   │   │   ├── __init__.py
│   │   │   ├── users.py              # 用户认证（注册/登录/账号锁定禁用/me/改邮箱/改密码，5 路由）
│   │   │   ├── datasets.py           # 数据集管理（CRUD/上传/导出/回收站/任务记录，23 路由）
│   │   │   ├── cleaning.py           # 数据清洗（预检/契约/问题清单/管道/审计，10 路由）
│   │   │   ├── data_analysis.py      # 数据分析（15 种前端图表/16 种后端图表/报告，10 路由）
│   │   │   ├── data_mining.py        # 数据挖掘（聚类/关联规则/序列模式，9 路由）
│   │   │   ├── feature_engineering.py # 特征工程（构造/编码/缩放/降维/选择/列池/导出，16 路由）
│   │   │   ├── ml.py                 # 机器学习（预检/训练/预测/评估/模型管理，12 路由）
│   │   │   ├── ai.py                 # AI 上下文注入对话（11 路由）
│   │   │   ├── data_sources.py       # 远程数据库连接管理（10 路由，全同步 def）
│   │   │   ├── support.py            # 联系管理员公开接口（验证码/截图上传/提交申请，3 路由，无需登录）
│   │   │   └── admin.py              # 管理后台（62 路由，含用户管理增强、用户申请管理、任务详情/取消/重试、AI 用量、数据大屏）
│   │   ├── models/                   # SQLAlchemy ORM 数据模型
│   │   │   └── __init__.py           # User, Dataset, AIConversation, AIMessage, AIConversationContext, AIUsageLog, AIConfig, TaskRecord, DataSourceConnection, AppConfig, SupportMessage, CacheStatsHourly, LogRecord（13 张表）
│   │   ├── schemas/                  # Pydantic 数据校验模型
│   │   │   ├── user.py               # UserCreate/UserResponse/Token
│   │   │   ├── dataset.py            # DatasetCreate/Update/Response + RemoteSourceConfig 等
│   │   │   ├── response.py           # ErrorResponse
│   │   │   └── ai.py                 # AIChatRequest/AIConfigRequest 等 11 个模型
│   │   ├── services/                 # 业务逻辑层（7 个 .py + ai_context 子包）
│   │   │   ├── data_service.py       # DataService + DataCleaningService（约 4470 行，核心，含 7 个远程查询方法）
│   │   │   ├── algorithm_registry.py # 算法注册表（纯模块级函数，build_estimator 等）
│   │   │   ├── ai_service.py         # AIService（约 28 个方法）
│   │   │   ├── storage_manager.py    # MinIOStorage + StorageManager（MinIO 对象存储）
│   │   │   ├── cache_manager.py      # CacheManager + MemoryCache（Redis + 内存降级）
│   │   │   ├── task_manager.py       # TaskManager（Celery + 同步降级）
│   │   │   ├── task_scheduler.py     # TaskScheduler（任务排队调度器，5 秒轮询激活 pending）
│   │   │   └── ai_context/           # AI 上下文注入子包（builder/extractors/task_summarizer/conversation_compressor/preset_followups + prompts 5 个 txt）
│   │   ├── utils/                    # 工具模块（8 个 .py）
│   │   │   ├── security.py           # JWT/SHA256密码哈希/用户获取
│   │   │   ├── db.py                 # 数据库会话管理 + 6 个建表兼容补丁
│   │   │   ├── common.py             # 通用工具函数（11 函数 + 3 常量）
│   │   │   ├── task_records.py       # 任务记录管理 + 排队容量统计（12 函数）
│   │   │   ├── task_labels.py        # 中文标签映射引擎（12 公开常量 + 11 公开函数 + 6 私有常量 + 5 私有函数）
│   │   │   ├── crypto.py             # Fernet 加密（远程连接密码，密钥存 app_config）
│   │   │   ├── exception_handlers.py # 全局异常处理器（6 个）
│   │   │   └── logger.py             # 日志管理
│   │   ├── static/                   # 前端构建产物（nginx 服务，含 admin.html）
│   │   ├── config.py                 # 配置管理（强制PostgreSQL，排队/异步阈值参数）
│   │   └── main.py                   # FastAPI 入口
│   ├── test_data/                    # 测试数据集（按模块分 5 个子目录，70+ CSV）
│   ├── Dockerfile                    # 后端 Docker 镜像
│   ├── requirements.txt              # Python 依赖列表
│   └── .env.example                  # 环境变量配置示例
│
├── frontend/                         # 前端应用
│   ├── src/
│   │   ├── api/                      # 前端 API 调用（index.js 113 条 export / admin.js 65 具名 + 1 default）
│   │   ├── components/               # GlobalTaskPanel.vue + DataSourceSelector.vue + DataSourceDialog.vue + DataPreview.vue（2026-08-15 新增数据预览公共组件，5 模块选择数据集后自动加载前 10 行）+ UsageGuideDialog.vue（2026-08-16 使用说明弹窗）
│   │   ├── guides/                   # 使用说明 Markdown 文档（9 个 .md，Vite ?raw 导入）+ index.js 聚合
│   │   ├── stores/                   # taskPanel.js（全局任务面板状态）
│   │   ├── composables/              # useAutoRefresh.js（自动刷新）
│   │   ├── utils/                    # labels.js（模块/产物标签映射）
│   │   ├── router/                   # Vue Router 配置（index.js 12 路由 + admin.js 12 路由）
│   │   ├── views/                    # 12 个主视图（含 Profile/ContactAdmin）+ admin/13 个管理端视图（components/ 下 DynamicReport 报告组件树 8 个文件已于 2026-08-16 清理删除）
│   │   ├── App.vue                   # 根组件（含数据源弹窗入口 + 全局任务面板 + 使用说明弹窗入口）
│   │   ├── main.js                   # 前端入口
│   │   └── admin-main.js             # 管理端入口
│   ├── dist-admin/                   # admin 应用构建产物
│   ├── Dockerfile                    # 前端 Docker 镜像（多阶段构建）
│   ├── nginx.conf                    # Nginx 配置
│   ├── package.json                  # Node.js 依赖
│   ├── vite.config.js                # Vite 构建配置（用户端）
│   └── vite.admin.config.js          # Vite 构建配置（管理端）
│
├── docker-compose.yml                # Docker Compose 编排配置（7 个服务）
├── init.sql                          # PostgreSQL 初始化脚本
├── PROJECT_DOCUMENTATION.md          # 本文档
├── DOCKER_IMAGES_GUIDE.md            # Docker 镜像指南
└── .gitignore                        # Git 忽略规则
```

---

## 9. 环境配置说明

### 9.1 配置加载机制

后端使用 `Settings` 类（`backend/app/config.py`）统一管理配置，支持以下加载优先级（高到低）：

1. 环境变量
2. `.env` 文件
3. 默认值

**重要**：`config.py` 在 `__init__` 中强制校验 `DATABASE_URL`，如果为空或以 `sqlite://` 开头则抛出 `ValueError("必须使用 PostgreSQL，SQLite 已废弃")`。

### 9.2 配置项详细说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| **数据库配置** | | |
| `DATABASE_URL` | （无默认值） | **必填**。PostgreSQL 连接串，格式：`postgresql://用户:密码@主机:端口/数据库` |
| `DB_POOL_SIZE` | `10` | 连接池大小 |
| `DB_MAX_OVERFLOW` | `20` | 连接池溢出上限 |
| `DB_POOL_TIMEOUT` | `30` | 连接池超时秒数 |
| **JWT 配置** | | |
| `SECRET_KEY` | `your-secret-key-change-in-production` | JWT 签名密钥，生产环境必须修改 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `120` | JWT Token 有效期（分钟） |
| **管理员配置** | | |
| `ADMIN_USERNAME` | `admin` | 管理员用户名 |
| `ADMIN_PASSWORD` | `admin` | 管理员密码（config.py 默认 "admin"；**注意 AdminLogin.vue 提示文案为 admin/admin123，以 .env 实际配置为准**） |
| **AI 服务配置** | | |
| `OPENAI_API_KEY` | （空） | OpenAI/DeepSeek API Key |
| `OPENAI_API_BASE` | `https://api.deepseek.com/v1` | API Base URL |
| `OPENAI_MODEL` | `deepseek-chat` | 默认模型名称 |
| **Redis 缓存配置** | | |
| `REDIS_ENABLED` | `false` | 是否启用 Redis |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis 连接串 |
| `REDIS_TTL` | `3600` | 缓存过期时间（秒） |
| **MinIO 配置** | | |
| `MINIO_ENABLED` | `false` | 是否启用 MinIO（配置项存在，但 StorageManager 不检查此值，直接初始化 MinIO） |
| `MINIO_ENDPOINT` | `localhost:9000` | MinIO 服务端点 |
| `MINIO_ACCESS_KEY` | （空） | 访问密钥 |
| `MINIO_SECRET_KEY` | （空） | 秘密密钥 |
| `MINIO_BUCKET` | `data-insight` | 默认存储桶 |
| `MINIO_SECURE` | `false` | 是否使用 HTTPS |
| **Celery 配置** | | |
| `CELERY_ENABLED` | `true` | 是否启用 Celery |
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | 消息队列 Broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/2` | 结果存储 Backend |
| `CELERY_CONCURRENCY` | `2` | Worker 并发数（防止系统卡死） |
| `CELERY_TASK_TIME_LIMIT` | `1800` | 任务硬超时（秒） |
| `CELERY_TASK_SOFT_TIME_LIMIT` | `1500` | 任务软超时（秒） |
| `CELERY_WORKER_PREFETCH_MULTIPLIER` | `1` | Worker 预取倍数 |
| **异步与任务排队配置** | | |
| `ASYNC_THRESHOLD` | `10000` | 智能异步分发阈值：数据集行数 ≥ 此值走 Celery 异步，< 此值同步执行 |
| `MAX_RUNNING_PER_USER` | `2` | 单用户同时执行任务上限（超限进 pending 队列） |
| `MAX_PENDING_PER_USER` | `10` | 单用户等待队列上限 |
| `MAX_CONCURRENT_TASKS_PER_USER` | `12` | 单用户任务总上限（running + pending） |
| **联系管理员配置** | | |
| `SUPPORT_RATE_LIMIT_SECONDS` | `600` | 联系管理员申请频率限制（秒）：同 IP/用户名窗口内限 1 条；**0 表示不限制（开发测试用，backend/.env 已设 0）** |
| **ClickHouse 配置** | | |
| `CLICKHOUSE_ENABLED` | `false` | 是否启用 ClickHouse 基础设施（连接配置） |
| `CLICKHOUSE_SYNC_ENABLED` | `true` | **数据同步开关（2026-08-16 一期）**：上传/导入的 raw_data 本地数据集自动同步副本到 ClickHouse，用于聚合分析加速 |
| `CLICKHOUSE_MIN_ROWS` | `10000` | 启用 CH 加速的最小行数：低于此阈值直接走 pandas（小表 pandas 更快） |
| `CLICKHOUSE_QUERY_TIMEOUT` | `5` | CH 查询超时（秒）：超时视为不可用，自动降级 pandas，绝不阻塞请求 |
| `CLICKHOUSE_SYNC_BATCH` | `50000` | 同步分块行数：每批写入行数，控制大表同步内存峰值 |
| **Dask 配置** | | |
| `DASK_ENABLED` | `false` | 是否启用 Dask（配置已预留，Dask 处理器废弃未使用） |
| `DASK_THRESHOLD` | `1000000` | Dask 触发阈值（废弃） |

---

## 10. 本地启动指南

> **推荐方式（2026-08-04 起）**：开发环境统一走项目根目录的 `dev.ps1` 一键脚本——Docker 只跑基础设施（PostgreSQL/Redis/MinIO/ClickHouse/Celery），后端（uvicorn --reload）与前端/管理后台（Vite 热更新）用本地进程运行，改代码实时生效；同时自动启动 Celery 热重载监听（watch-celery.ps1）。详见下文各节说明。

### 10.1 环境准备

- Python 3.11+
- Node.js 18+
- PostgreSQL 15+（**必需**）
- MinIO（**必需**，无降级）
- （可选）Redis 7+（如需缓存功能）
- （可选）Docker Desktop（如需容器化部署）

### 10.2 后端启动

```bash
cd backend
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
copy .env.example .env
# 编辑 .env 文件，配置 DATABASE_URL 和 MinIO 连接信息
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**启动成功后访问**：
- API 文档（Swagger UI）：`http://localhost:8000/docs`
- API 文档（ReDoc）：`http://localhost:8000/redoc`

### 10.3 前端启动

```bash
cd frontend
npm install
npm run dev
```

访问 `http://localhost:5173`，前端开发服务器会自动代理 API 请求到 `http://localhost:8000`。

---

## 11. Docker Compose 部署指南

`docker-compose.yml` **不使用 profile 机制**，7 个服务（backend、frontend、redis、postgres、clickhouse、celery-worker、minio）默认全部启动，无需指定 `--profile` 参数。

### 11.1 启动所有服务

```bash
docker-compose up -d
```

执行上述命令即可启动全部 7 个服务。PostgreSQL 映射到主机端口 `5433`（避免冲突），默认用户名 `datainsight`，密码 `datainsight123`，数据库 `data_insight`。

### 11.2 常用命令

```bash
docker-compose ps                          # 查看服务状态
docker-compose logs -f backend             # 查看日志
docker-compose down                        # 停止所有服务
docker-compose down -v                     # 停止并删除数据卷
docker-compose up -d --build               # 重新构建镜像
```

---

## 12. 废弃代码与未使用文件清单

> **状态**：2026-08-01 扫描识别出的约 65 处死代码已于 **2026-08-04 全量清理完毕**，当前项目无已知死代码。本节保留清理前的记录供追溯（详见 `.ai-context/dependency_graph.md` 第十节）。
> 此前文档中提到的 `database_interface.py`、`postgresql_database.py`、`database_factory.py`、`data_processor.py`、`pandas_processor.py`、`dask_processor.py`、`processor_factory.py`、`api/base.py` 等废弃文件**已全部删除**，不再存在。

### 12.1 services/ 目录已清理（19 处）

**ai_service.py - 流程推荐功能链（7 处，约 950 行）**：`LOCAL_TOOLS`、`_get_tools_list_text`、`_safe_json_dumps`、`_build_system_prompt`、`_get_generic_fallback_template`、`_get_fallback_template`、`_parse_ai_response` —— 已删除。

**algorithm_registry.py（2 处）**：`is_classification_algorithm`、`get_supported_algorithms` —— 已删除。

**storage_manager.py（2 处）**：`MinIOStorage.get_url`、`StorageManager.get_url` —— 已删除。

**task_manager.py（2 处）**：`get_task_status`、`async_task` 装饰器 —— 已删除。

**data_service.py（DataCleaningService，8 处）**：`detect_outliers`、`handle_string_range_errors`、`handle_date_range_errors`、`handle_boolean_range_errors`、`handle_string_enum_range_errors`、`handle_email_url_range_errors`、`normalize_data`、`encode_categorical` —— 已删除。

### 12.2 utils/ 目录已清理（2 处）

| 函数 | 文件 | 清理状态 |
|------|------|---------|
| `strip_suffixes` | `common.py` | 已删除 |
| `save_dataset_result` | `common.py` | 已删除 |

### 12.3 repositories/ 目录已清理（整个文件）

`dataset_repository.py`（515 行，DatasetRepository 类 + 20 方法）已删除，`repositories/` 目录已不存在。项目实际数据库操作直接使用 `db.query(Dataset)` 在 API 层完成。

### 12.4 schemas/ 目录已清理（12 处）

- **schemas/ai.py（4 处）**：`AIInsightRequest`、`RecommendStepsRequest`、`RecommendStepsResponse`、`FollowUpResponse` —— 已删除
- **schemas/response.py（7 处）**：`SuccessResponse`、`PaginatedResponse` 及 5 个封装函数 —— 已删除（保留 `ErrorResponse`）
- **schemas/user.py（1 处）**：`TokenData` —— 已删除

### 12.5 未使用的 import 已清理（10 处）

| 文件 | 已清理的导入 |
|------|-------------|
| `api/admin.py` | `get_logger`、`log_api_request`、`log_error`、`log_task`、`log_system` |
| `api/ai.py` | `AIInsightRequest` |
| `api/ml.py` | `get_algorithm_label`、`is_classification_algorithm`、`get_supported_algorithms` |
| `api/data_analysis.py` | `field_validator` |

### 12.6 当前未使用接口（2026-08-13 复核）

| 接口 | 未使用原因 |
|------|-----------|
| `POST /api/datasets/` | 旧版创建接口，现使用 upload 接口 |
| `POST /api/datasets/record` | 内部调用接口，前端不直接调用 |
| `POST /api/datasets/{id}/import` | 跨模块导入，前端未实现按钮 |
| `GET /api/cleaning/data/{id}` | 前端复用 datasets/data 接口 |
| `GET /api/ml/chart-export/{id}` | 后端存在，前端无调用 |

### 12.7 2026-08-16 死代码与 bug 清理记录

**ml.py NameError 崩溃修复（高严重度）**：`train_supervised_model` 中 `create_task_record` 引用未定义的 `random_seed`/`hyperparams` 变量，导致训练接口 100% 500。已在变量提取处补充定义（ml.py:918-920）。

**后端已清理（函数/方法/配置/Schema/import，约 40 处）**：
- **api 层**：`data_analysis.py` 删除 `_validate_xy_no_overlap`、`_validate_column_for_chart`、`_fig_to_base64_png`、`_build_analysis_report_html`（改为现用的 `_build_analysis_report`）；`admin.py` 删除 `download_storage_file_legacy` 路由、`_map_task_type`（保留其依赖的 `_MODULE_SOURCE_TO_TASK_TYPE` 字典）；`ml.py` 删除 `save_ml_report`。
- **services 层**：`clickhouse_service.py` 删除 `get_row_count`；`ai_service.py` 删除 `_build_chat_system_prompt`；`cache_manager.py` 删除 `hit_rate`/`get_hit_rate_trend`；`conversation_compressor.py` 删除 `build_context_reference`（同步移除 `ai_context/__init__.py` 导出）。
- **utils 层**：`task_records.py` 删除 `count_user_active_async_tasks`、`activate_pending_task`；`logger.py` 删除 `log_task`；`security.py` 删除 `get_current_user_optional`（原 12.6 残留项，已清除）；`common.py` 删除 `SHANGHAI_TZ` 常量。
- **配置/Schema**：`config.py` 删除 8 个死配置（`MAX_UPLOAD_SIZE`、`CELERY_CONCURRENCY`、`MAX_CONCURRENT_TASKS_PER_USER`、`MINIO_ENABLED`、`DASK_THRESHOLD`、`DASK_ENABLED`、`is_production`、`is_postgresql`）；`schemas/dataset.py` 删除 `RemoteSourceConfig`。
- **未使用 import**：13 个文件清理（api 层 8 个 + services 2 个 + utils 3 个）。

**前端已清理（约 40 处）**：
- **api 层**：`api/index.js` 删除 12 个无引用 export（`uploadDataset`、`fetchDatasetStats`、`fetchDataQuality`、`saveAIConfig`、`testAIConfig`、`fetchFERawData`、`getFeatureTaskProgress`、`fetchMiningDatasets`、`clearAllDatasets`、`fetchDatasetsByType`、`fetchCleaningColumns`、`exportChart`）；`api/admin.js` 删除 `adminMe`、`getSupportMessage`。
- **组件树删除**：`views/components/` 下 DynamicReport.vue + 7 个 ReportSection*.vue 全部不可达（无路由、无组件引用），8 个文件整体删除；同步更新 PROJECT_DOCUMENTATION.md 注意 2（移除 ReportSectionPivot 描述）。
- **未用 import/函数**：App.vue（`renderIcon`）、GlobalTaskPanel（taskPanelStore）、DataSourceDialog（MagicStick）、DataManagement（fetchDatasetsByType/clearAllDatasets）、DataCleaning（fetchDatasetsByModule/fetchCleaningColumns/`getQualityStatus`）、DataMining（fetchTableSchema/`formatNum`）、FeatureEngineering（fetchTableSchema/`executeExportPool`）、MachineLearning（fetchTableSchema）、DataAnalysis（exportChart/`xColumnOptions`/`selectableColumns`）、AIAnalysis（`getModuleTagType`）。
- **文档引用修正**：PROJECT_DOCUMENTATION.md 注意 2 与 HTML 报告函数名（`_build_analysis_report_html` → `_build_analysis_report`）。

**验证**：后端 19 个 Python 文件 `py_compile` 全部通过；前端主应用 + admin 应用 `vite build` 均成功（exit 0）。

### 12.8 安全隐患（部分已处理，剩余待优化）

| 文件 | 问题 | 当前状态 |
|------|------|---------|
| `services/data_service.py` | 远程查询标识符拼接 SQL | 已通过 `_validate_identifier` 表名列名校验防注入 |
| `utils/exception_handlers.py` | `general_exception_handler` 响应中包含 traceback | 未处理（开发环境可接受，生产建议隐藏） |
| `utils/security.py` | SHA256 密码哈希不如 bcrypt 安全 | 未处理（建议迁移到 bcrypt/argon2） |

---

## 13. 已知问题与后续优化建议

### 13.1 功能扩展

1. **~~ClickHouse 业务集成~~**：~~配置已就绪，但无业务代码使用 ClickHouse（仅 admin 状态展示）~~（**2026-08-16 已实现一期**：大表分析加速，见 5.9 节 ClickHouse 管理及数据分析 4 接口说明）
2. **StorageManager 降级机制**：当前 MinIO 不可用时直接报错，建议考虑本地存储降级
3. **远程查询超时硬编码**：远程连接超时 5 秒为代码硬编码（data_service.py:330、data_sources.py:100/105/264），无独立配置项

### 13.2 代码质量

4. **ML 训练逻辑位置**：`train_supervised_model` 逻辑主要在 API 层（ml.py `_execute_training`），可考虑下沉到服务层
5. **artifact_type 集中定义**：各模块散落定义 artifact_type 字符串，建议集中到常量模块
6. **AdminDashboard 自动刷新开关未接线**：`el-switch v-model="autoRefresh"` 无 `@change` 处理，用户关闭开关后 30 秒轮询仍持续（**2026-08-15 轮询间隔由 5 秒调为 30 秒**，轮询含 getServicesStatus+getServicesMetrics+getOverview+listLogs+listBusinessTasks），token 过期后持续产生 401。**注**：2026-08-14 admin.py 路由已全部改为同步 def（线程池执行），轮询不再阻塞事件循环/耗尽连接池，但 401 现象仍可能随 token 过期出现
7. ~~**AdminStorage.vue 残留死代码**~~：~~`loadBusinessDatasets`/`loadTrashDatasets`/`restorePurgedDataset` 等函数在模板中无对应 UI 挂载~~（**2026-08-14 已清理**，业务回收站已迁至 AdminDataManagement.vue）
8. **data_sources.py 全同步 def**：10 条路由均非 async；**2026-08-14 admin.py 全部路由也已改为同步 def**（避免管理端轮询阻塞事件循环导致用户端超时）

### 13.3 配置一致性

9. **ADMIN_PASSWORD 默认值不一致**：config.py 默认 `admin`，AdminLogin.vue 提示 `admin/admin123`，backend/.env.example 为占位符 `your-admin-password`
10. **.env.example 缺少排队参数**：无 `MAX_RUNNING_PER_USER`/`MAX_PENDING_PER_USER`（config.py 与 docker-compose 均有）
11. **celery-worker 环境变量硬编码**：docker-compose.yml 中 MINIO_* 与 CLICKHOUSE_* 为硬编码值，不随宿主 .env 插值（与注释"从 .env 读取"不符）

### 13.4 安全优化

12. **密码哈希升级**：从 SHA256 迁移到 bcrypt
13. **生产环境 traceback 隐藏**：异常处理器应根据环境决定是否返回 traceback

---

> 本文档完。如有疑问或发现文档与代码不一致之处，请检查对应源码文件。
