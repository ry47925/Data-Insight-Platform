-- PostgreSQL 初始化脚本
-- 创建数据库和用户（如果通过 docker-compose 启动 PostgreSQL）

-- 创建数据洞察平台数据库
CREATE DATABASE data_insight;

-- 连接到新创建的数据库
\c data_insight;

-- 创建扩展（支持 JSON 操作）
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 注释说明
COMMENT ON DATABASE data_insight IS '数据洞察平台数据库';
