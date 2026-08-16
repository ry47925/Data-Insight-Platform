# 前端 Dockerfile（测试用单阶段构建）
FROM nginx:alpine

# 复制预构建产物到 Nginx 目录
COPY dist /usr/share/nginx/html

# 复制 Nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 暴露端口
EXPOSE 80

# 启动 Nginx
CMD ["nginx", "-g", "daemon off;"]
