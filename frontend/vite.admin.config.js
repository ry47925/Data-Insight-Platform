import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import fs from 'fs'

function adminEntryPlugin() {
  return {
    name: 'admin-entry',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const url = req.url
        if (url === '/' || url === '/index.html') {
          const adminHtmlPath = resolve(__dirname, 'admin.html')
          try {
            let content = fs.readFileSync(adminHtmlPath, 'utf-8')
            // 让 Vite 对 HTML 进行转换（注入 /@vite/client、处理资源路径等）
            content = await server.transformIndexHtml(url, content)
            res.setHeader('Content-Type', 'text/html')
            res.end(content)
          } catch (err) {
            next(err)
          }
          return
        }
        next()
      })
    }
  }
}

export default defineConfig(({ command }) => ({
  plugins: [vue(), adminEntryPlugin()],
  // 资源路径：Docker 独立部署用 VITE_BASE 覆盖为 /；默认生产构建用 /static/ 适配后端 nginx 挂载
  base: process.env.VITE_BASE || (command === 'build' ? '/static/' : '/'),
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },
  build: {
    outDir: resolve(__dirname, 'dist-admin'),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        admin: resolve(__dirname, 'admin.html')
      }
    }
  },
  server: {
    port: 5174,
    proxy: {
      '/admin': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  }
}))
