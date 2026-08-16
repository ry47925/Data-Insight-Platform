import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// API 代理目标：Docker 容器内通过 VITE_API_TARGET 指向 backend 服务，本地开发默认 localhost:8000
const apiTarget = process.env.VITE_API_TARGET || 'http://localhost:8000'

export default defineConfig(({ command }) => ({
  plugins: [vue()],
  // 资源路径：Docker 独立部署用 VITE_BASE 覆盖为 /；默认生产构建用 /static/ 适配后端 nginx 挂载
  base: process.env.VITE_BASE || (command === 'build' ? '/static/' : '/'),
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },
  build: {
    outDir: resolve(__dirname, 'dist'),
    emptyOutDir: true
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true
      },
      '/data': {
        target: apiTarget,
        changeOrigin: true
      },
      '/admin': {
        target: apiTarget,
        changeOrigin: true
      }
    }
  }
}))