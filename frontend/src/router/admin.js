import { createRouter, createWebHashHistory } from 'vue-router'
import AdminLogin from '../views/admin/AdminLogin.vue'
import AdminDashboard from '../views/admin/AdminDashboard.vue'
import AdminUsers from '../views/admin/AdminUsers.vue'
import AdminCache from '../views/admin/AdminCache.vue'
import AdminStorage from '../views/admin/AdminStorage.vue'
import AdminDatabase from '../views/admin/AdminDatabase.vue'
import AdminDataManagement from '../views/admin/AdminDataManagement.vue'
import AdminDataSources from '../views/admin/AdminDataSources.vue'
import AdminTasks from '../views/admin/AdminTasks.vue'
import AdminLogs from '../views/admin/AdminLogs.vue'
import AdminAIUsage from '../views/admin/AdminAIUsage.vue'
import AdminDashboardScreen from '../views/admin/AdminDashboardScreen.vue'
import { isAdminLoggedIn } from '../api/admin.js'

const routes = [
  { path: '/login', name: 'adminLogin', component: AdminLogin, meta: { title: '管理后台登录' } },
  { path: '/screen', name: 'adminScreen', component: AdminDashboardScreen, meta: { title: '数据大屏', requiresAuth: true } },
  { path: '/dashboard', name: 'adminDashboard', component: AdminDashboard, meta: { title: '服务总览', requiresAuth: true } },
  { path: '/users', name: 'adminUsers', component: AdminUsers, meta: { title: '用户管理', requiresAuth: true } },
  { path: '/cache', name: 'adminCache', component: AdminCache, meta: { title: '缓存管理', requiresAuth: true } },
  { path: '/storage', name: 'adminStorage', component: AdminStorage, meta: { title: '存储管理', requiresAuth: true } },
  { path: '/data-management', name: 'adminDataManagement', component: AdminDataManagement, meta: { title: '数据管理', requiresAuth: true } },
  { path: '/data-sources', name: 'adminDataSources', component: AdminDataSources, meta: { title: '数据源管理', requiresAuth: true } },
  { path: '/database', name: 'adminDatabase', component: AdminDatabase, meta: { title: '数据库管理', requiresAuth: true } },
  { path: '/tasks', name: 'adminTasks', component: AdminTasks, meta: { title: '任务管理', requiresAuth: true } },
  { path: '/logs', name: 'adminLogs', component: AdminLogs, meta: { title: '运行日志', requiresAuth: true } },
  { path: '/ai-usage', name: 'adminAIUsage', component: AdminAIUsage, meta: { title: 'AI 用量', requiresAuth: true } },
  { path: '/', redirect: '/login' },
]

const adminRouter = createRouter({
  history: createWebHashHistory(),
  routes
})

adminRouter.beforeEach((to, from, next) => {
  if (to.meta.title) {
    document.title = `${to.meta.title} - Data Insight 管理后台`
  }

  if (to.meta.requiresAuth) {
    if (!isAdminLoggedIn()) {
      next({ path: '/login', query: { redirect: to.fullPath } })
      return
    }
  }

  if (to.path === '/login' && isAdminLoggedIn()) {
    next('/dashboard')
    return
  }

  next()
})

export default adminRouter
