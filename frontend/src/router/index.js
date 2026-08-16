import { createRouter, createWebHashHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import Login from '../views/Login.vue'
import DataManagement from '../views/DataManagement.vue'
import DataAnalysis from '../views/DataAnalysis.vue'
import DataCleaning from '../views/DataCleaning.vue'
import FeatureEngineering from '../views/FeatureEngineering.vue'
import MachineLearning from '../views/MachineLearning.vue'
import TaskHistory from '../views/TaskHistory.vue'
import DataMining from '../views/DataMining.vue'
import AIAnalysis from '../views/AIAnalysis.vue'
import Profile from '../views/Profile.vue'
import ContactAdmin from '../views/ContactAdmin.vue'
import { isLoggedIn } from '../api/index.js'

const routes = [
  { path: '/', name: 'home', component: HomeView, meta: { title: '首页', requiresAuth: false } },
  { path: '/login', name: 'login', component: Login, meta: { title: '登录', requiresAuth: false } },
  { path: '/profile', name: 'profile', component: Profile, meta: { title: '个人中心', requiresAuth: true } },
  { path: '/contact-admin', name: 'contactAdmin', component: ContactAdmin, meta: { title: '联系管理员', requiresAuth: false } },
  { path: '/datasets', name: 'datasets', component: DataManagement, meta: { title: '数据管理', requiresAuth: true } },
  { path: '/task-history', name: 'taskHistory', component: TaskHistory, meta: { title: '操作历史', requiresAuth: true } },
  { path: '/analysis', name: 'analysis', component: DataAnalysis, meta: { title: '数据分析', requiresAuth: true } },
  { path: '/cleaning', name: 'cleaning', component: DataCleaning, meta: { title: '数据清洗', requiresAuth: true } },
  { path: '/feature', name: 'feature', component: FeatureEngineering, meta: { title: '特征工程', requiresAuth: true } },
  { path: '/mining', name: 'DataMining', component: DataMining, meta: { title: '数据挖掘', requiresAuth: true } },
  { path: '/ml', name: 'ml', component: MachineLearning, meta: { title: '机器学习', requiresAuth: true } },
  { path: '/ai', name: 'ai', component: AIAnalysis, meta: { title: 'AI分析', requiresAuth: true } },
  // 通配符路由：所有未匹配的路径重定向到首页，避免页面空白无提示
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes
})

// 路由守卫：检查登录状态
router.beforeEach((to, from, next) => {
  // 设置页面标题
  if (to.meta.title) {
    document.title = `${to.meta.title} - Data Insight 数据分析平台`
  }

  // 需要登录的页面
  if (to.meta.requiresAuth) {
    if (!isLoggedIn()) {
      // 未登录，跳转到登录页，携带当前路径以便登录后返回
      next({
        path: '/login',
        query: { redirect: to.fullPath }
      })
      return
    }
  }

  // 登录页已登录时跳转到首页（登录后可浏览首页真实统计）
  if (to.path === '/login' && isLoggedIn()) {
    next('/')
    return
  }

  next()
})

export default router