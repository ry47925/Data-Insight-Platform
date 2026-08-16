# Docker 镜像下载与配置指南

> 本指南列出本项目架构验证与部署所需的全部 Docker 镜像，包含镜像版本、拉取命令、预估大小、国内加速方案及特殊配置参数。

---

## 一、镜像清单总览

| 序号 | 镜像名称 | 版本标签 | 预估大小 | 用途 | 优先级 |
|------|----------|----------|----------|------|--------|
| 1 | redis | 7-alpine | ~30MB | 缓存服务 | **必需** |
| 2 | postgres | 17-alpine | ~90MB | 关系型数据库 | 按需 |
| 3 | clickhouse/clickhouse-server | latest | ~500MB | 分析型数据库 | 按需 |
| 4 | minio/minio | latest | ~250MB | 对象存储 | 按需 |
| 5 | python | 3.11-slim | ~50MB | 后端服务构建 | 必需 |
| 6 | nginx | alpine | ~20MB | 前端服务构建 | 必需 |

**总计基础大小**：约 940MB（实际下载可能因层缓存而减少）

---

## 二、国内镜像加速配置（强烈推荐）

由于 Docker Hub 直连下载速度较慢，建议先配置国内镜像源。

### 2.1 Windows 配置方法

1. 打开 Docker Desktop
2. 点击右上角齿轮图标 → **Settings** → **Docker Engine**
3. 在 JSON 配置中添加 `registry-mirrors`：

```json
{
  "builder": {
    "gc": {
      "defaultKeepStorage": "20GB",
      "enabled": true
    }
  },
  "experimental": false,
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.1panel.live",
    "https://hub.rat.dev",
    "https://docker.m.daocloud.io"
  ]
}
```

4. 点击 **Apply & Restart**

### 2.2 验证加速是否生效

```powershell
docker info | findstr "Registry Mirrors"
```

应输出配置的镜像地址列表。

---

## 三、逐个镜像下载与配置

### 3.1 Redis（缓存服务）

| 属性 | 值 |
|------|-----|
| 镜像 | `redis:7-alpine` |
| 大小 | ~30MB |
| 用途 | 分布式缓存、Celery Broker |
| 端口 | 6379 |
| 密码 | `redis123456` |

**拉取命令**：
```powershell
docker pull redis:7-alpine
```

**docker-compose 配置**：
```yaml
redis:
  image: redis:7-alpine
  container_name: data-insight-redis
  command: redis-server --requirepass redis123456
  ports:
    - "6379:6379"
  volumes:
    - ./docker-data/redis:/data
  restart: unless-stopped
```

**环境变量配置**：
```env
REDIS_ENABLED=true
REDIS_URL=redis://:redis123456@redis:6379/0
```

**特殊说明**：
- Alpine 版本体积最小，适合开发和测试
- 生产环境建议使用 `redis:7`（非 Alpine）以获得更好的稳定性
- `--requirepass` 设置访问密码，必须与 `REDIS_URL` 中的密码一致

---

### 3.2 PostgreSQL（关系型数据库）

| 属性 | 值 |
|------|-----|
| 镜像 | `postgres:17-alpine` |
| 大小 | ~90MB |
| 用途 | 平台唯一支持的关系型数据库（SQLite 已废弃） |
| 端口 | 5432（宿主机映射为 5433） |
| 用户名 | `datainsight` |
| 密码 | `datainsight123` |
| 数据库 | `data_insight` |

**拉取命令**：
```powershell
docker pull postgres:17-alpine
```

**docker-compose 配置**：
```yaml
postgres:
  image: postgres:17-alpine
  container_name: data-insight-postgres
  environment:
    POSTGRES_USER: datainsight
    POSTGRES_PASSWORD: datainsight123
    POSTGRES_DB: data_insight
  ports:
    - "5433:5432"
  volumes:
    - ./docker-data/postgres:/var/lib/postgresql/data
    - ./init.sql:/docker-entrypoint-initdb.d/init.sql
  restart: unless-stopped
```

**环境变量配置**（后端连接 Docker PostgreSQL）：
```env
DATABASE_URL=postgresql://datainsight:datainsight123@localhost:5433/data_insight
```

**特殊说明**：
- 本地已安装 PostgreSQL（端口 5432），Docker 映射到 5433 避免冲突
- `init.sql` 仅创建 data_insight 数据库和 uuid-ossp 扩展，不包含建表 SQL；实际建表通过 SQLAlchemy 的 Base.metadata.create_all() 在应用启动时自动完成
- 如需连接本地 PostgreSQL 而非 Docker，使用 `postgresql://postgres:ry19823376409@localhost:5432/data_insight`

---

### 3.3 ClickHouse（分析型数据库）

| 属性 | 值 |
|------|-----|
| 镜像 | `clickhouse/clickhouse-server:latest` |
| 大小 | ~500MB |
| 用途 | 大数据分析、日志存储 |
| HTTP 端口 | 8123 |
| 原生端口 | 9000 |
| 密码 | `clickhouse123456` |

**拉取命令**：
```powershell
docker pull clickhouse/clickhouse-server:latest
```

**docker-compose 配置**：
```yaml
clickhouse:
  image: clickhouse/clickhouse-server:latest
  container_name: data-insight-clickhouse
  environment:
    CLICKHOUSE_PASSWORD: clickhouse123456
  ports:
    - "8123:8123"
    - "9004:9000"
  volumes:
    - ./docker-data/clickhouse:/var/lib/clickhouse
  restart: unless-stopped
```

**环境变量配置**：
```env
CLICKHOUSE_ENABLED=true
CLICKHOUSE_HOST=localhost
CLICKHOUSE_PORT=8123
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=clickhouse123456
CLICKHOUSE_DATABASE=analysis
```

**特殊说明**：
- 体积较大（约500MB），网络不佳时可能拉取缓慢
- 如需降低版本以减小体积，可使用 `clickhouse/clickhouse-server:24.8-alpine`（约200MB，但功能可能受限）
- 当前项目后端尚未集成 ClickHouse 业务代码，仅架构层面预留接口

---

### 3.4 MinIO（对象存储）

| 属性 | 值 |
|------|-----|
| 镜像 | `minio/minio:latest` |
| 大小 | ~250MB |
| 用途 | 替代本地文件系统的对象存储 |
| API 端口 | 9000 |
| 控制台端口 | 9001 |
| Root 用户 | `minioadmin` |
| Root 密码 | `minioadmin123` |

**拉取命令**：
```powershell
docker pull minio/minio:latest
```

**docker-compose 配置**：
```yaml
minio:
  image: minio/minio:latest
  container_name: data-insight-minio
  command: server /data --console-address ":9001"
  environment:
    MINIO_ROOT_USER: minioadmin
    MINIO_ROOT_PASSWORD: minioadmin123
  ports:
    - "9000:9000"
    - "9001:9001"
  volumes:
    - ./docker-data/minio:/data
  restart: unless-stopped
```

**环境变量配置**（后端连接）：
```env
MINIO_ENABLED=true
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123
MINIO_BUCKET=data-insight
MINIO_SECURE=false
```

**特殊说明**：
- `--console-address ":9001"` 开启 Web 管理控制台，访问地址：http://localhost:9001
- 首次登录使用 `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`
- 需要在控制台中手动创建名为 `data-insight` 的 bucket，或修改后端代码自动创建

---

### 3.5 Python 3.11 Slim（后端构建）

| 属性 | 值 |
|------|-----|
| 镜像 | `python:3.11-slim` |
| 大小 | ~50MB |
| 用途 | 构建后端 FastAPI 服务镜像 |

**拉取命令**：
```powershell
docker pull python:3.11-slim
```

**Dockerfile 中的使用**：
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**特殊说明**：
- 使用 `-i https://pypi.tuna.tsinghua.edu.cn/simple` 加速 pip 依赖安装
- 如需进一步减小体积，可考虑 `python:3.11-alpine`，但部分依赖（如 pandas、numpy）在 Alpine 上编译较慢

---

### 3.6 Nginx Alpine（前端构建）

| 属性 | 值 |
|------|-----|
| 镜像 | `nginx:alpine` |
| 大小 | ~20MB |
| 用途 | 托管前端静态资源 |
| 端口 | 80 |

**拉取命令**：
```powershell
docker pull nginx:alpine
```

**Dockerfile 中的使用**：
```dockerfile
FROM nginx:alpine
COPY dist/ /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

---

## 四、批量拉取脚本

创建 `pull-images.ps1`（PowerShell 脚本），一键拉取所有镜像：

```powershell
# 设置国内镜像源（如已配置可省略）
# 逐个拉取镜像
Write-Host "正在拉取 Redis..."
docker pull redis:7-alpine

Write-Host "正在拉取 PostgreSQL..."
docker pull postgres:17-alpine

Write-Host "正在拉取 ClickHouse..."
docker pull clickhouse/clickhouse-server:latest

Write-Host "正在拉取 MinIO..."
docker pull minio/minio:latest

Write-Host "正在拉取 Python..."
docker pull python:3.11-slim

Write-Host "正在拉取 Nginx..."
docker pull nginx:alpine

Write-Host "全部镜像拉取完成！"
docker images
```

**执行方式**：
```powershell
.\pull-images.ps1
```

---

## 五、按优先级分批拉取建议

如果网络条件有限，建议按以下顺序分批拉取：

### 第一批（基础服务，约 100MB）
```powershell
docker pull redis:7-alpine
docker pull python:3.11-slim
docker pull nginx:alpine
```

### 第二批（数据库扩展，约 90MB）
```powershell
docker pull postgres:17-alpine
```

### 第三批（生产级服务，约 750MB）
```powershell
docker pull minio/minio:latest
docker pull clickhouse/clickhouse-server:latest
```

---

## 六、镜像验证命令

拉取完成后，验证各镜像是否正常：

```powershell
# 查看已下载镜像
docker images

# 验证 Redis 启动
docker run -d --name test-redis -p 6379:6379 redis:7-alpine redis-server --requirepass redis123456
docker exec test-redis redis-cli -a redis123456 ping  # 应返回 PONG
docker stop test-redis && docker rm test-redis

# 验证 PostgreSQL 启动
docker run -d --name test-postgres -p 5433:5432 -e POSTGRES_PASSWORD=test postgres:17-alpine
docker exec test-postgres pg_isready -U postgres  # 应返回 accepting connections
docker stop test-postgres && docker rm test-postgres

# 验证 MinIO 启动
docker run -d --name test-minio -p 9000:9000 -p 9001:9001 minio/minio:latest server /data --console-address ":9001"
docker exec test-minio mc alias set local http://localhost:9000 minioadmin minioadmin123
docker stop test-minio && docker rm test-minio
```

---

## 七、常见问题排查

### 7.1 拉取速度极慢或卡住

- **原因**：Docker Hub 直连网络不稳定
- **解决**：确认 `registry-mirrors` 已配置并生效（见 2.1）
- **备选**：使用 VPN 或代理工具加速

### 7.2 `no such host` 错误

- **原因**：配置的镜像源域名无法解析
- **解决**：更换其他镜像源地址，或暂时移除镜像源直接拉取

### 7.3 镜像拉取中断后无法继续

- **解决**：重新执行 `docker pull` 命令，Docker 支持断点续传

### 7.4 磁盘空间不足

- **查看占用**：`docker system df`
- **清理无用镜像**：`docker image prune -a`
- **清理构建缓存**：`docker builder prune`

---

## 八、docker-compose 一键启动命令

镜像全部就绪后，7 个服务默认全部启动：

```powershell
# 一键启动全部服务（backend + frontend + redis + postgres + clickhouse + celery + minio）
docker-compose up -d
```

---

> **提示**：如网络条件确实无法改善，C 类测试（Redis/MinIO/ClickHouse/Celery 验证）可继续标记为跳过。A 类和 B 类测试已覆盖核心抽象层验证，架构重构成果已基本确认。
