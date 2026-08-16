# 前端 Dockerfile（多阶段构建：node 构建 → nginx 运行）
# 支持独立容器部署，无需本地安装 Node；VITE_BASE 可覆盖资源路径（默认根路径 /）

# ---------- 构建阶段 ----------
FROM node:20-alpine AS build
WORKDIR /app

# 先复制依赖清单，利用缓存加速
COPY package.json package-lock.json ./
RUN npm ci

# 复制源码并构建（用户端 + 管理端）
COPY . .
ARG VITE_BASE=/
ENV VITE_BASE=$VITE_BASE
RUN npm run build && npm run build:admin

# ---------- 运行阶段 ----------
FROM nginx:alpine
# 用户端产物 → 根路径；管理端入口 → /admin.html（资源随 base 解析）
COPY --from=build /app/dist /usr/share/nginx/html
COPY --from=build /app/dist-admin/admin.html /usr/share/nginx/html/admin.html
# 管理端资源：dist-admin/assets 合并进 nginx assets（Vite 内容哈希文件名，不冲突）
COPY --from=build /app/dist-admin/assets /usr/share/nginx/html/assets

COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
