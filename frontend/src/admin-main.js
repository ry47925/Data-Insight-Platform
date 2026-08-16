import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './assets/styles/global.css'
import adminRouter from './router/admin.js'
import AdminLayout from './views/admin/AdminLayout.vue'

const app = createApp(AdminLayout)
app.use(ElementPlus)
app.use(adminRouter)
app.mount('#admin-app')