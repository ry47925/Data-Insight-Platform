<template>
  <div class="app-layout">
    <!-- 侧边栏 -->
    <aside class="sidebar">
      <div class="sidebar-brand">
        <div class="sidebar-logo">
          <el-icon :size="22"><DataAnalysis /></el-icon>
        </div>
        <div>
          <div class="sidebar-title">Data Insight</div>
          <div class="sidebar-subtitle">数据分析平台</div>
        </div>
      </div>
      <nav class="sidebar-nav">
        <router-link v-for="item in navItems" :key="item.path" :to="item.path"
          class="nav-item" :class="{ active: route.path === item.path }">
          <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>
      <div class="sidebar-footer">
        <div class="flex-between" style="color: var(--sidebar-text); font-size: 12px;">
          <span class="flex-center" style="gap:4px;"><el-icon :size="14"><Document /></el-icon>{{ datasetStore.datasets.length }} 个数据集</span>
          <span>v2.0.0</span>
        </div>
      </div>
    </aside>

    <!-- 主区域 -->
    <div class="main-area">
      <!-- 顶部栏 -->
      <header class="top-header">
        <div class="header-breadcrumb flex-center" style="gap:8px;">
          <el-icon v-if="currentNavItem" :size="20"><component :is="currentNavItem.icon" /></el-icon>
          <span>{{ currentTitle }}</span>
        </div>
        <div class="header-spacer"></div>
        <div class="header-right">
          <!-- 数据源管理按钮（未登录时提示先登录） -->
          <el-button size="small" @click="openDsDialog" aria-label="数据源管理">
            <el-icon style="margin-right:4px;"><Coin /></el-icon>数据源
          </el-button>
          <!-- 联系管理员（登录后常驻入口） -->
          <el-button v-if="isLoggedIn()" size="small" @click="$router.push('/contact-admin')" aria-label="联系管理员">
            <el-icon style="margin-right:4px;"><Service /></el-icon>联系管理员
          </el-button>
          <!-- 使用说明（登录后常驻入口，与数据源/联系管理员并列） -->
          <el-button v-if="isLoggedIn()" size="small" @click="guideVisible = true" aria-label="使用说明">
            <el-icon style="margin-right:4px;"><Reading /></el-icon>使用说明
          </el-button>
          <!-- 用户信息 -->
          <el-dropdown v-if="isLoggedIn()" trigger="click" @command="handleUserCommand">
            <div class="user-info" aria-label="用户菜单">
              <el-icon :size="16" class="user-icon"><User /></el-icon>
              <span class="user-name">{{ currentUser?.username || '用户' }}</span>
              <el-icon :size="12" style="color: var(--text-secondary);"><ArrowDown /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile" aria-label="个人中心">
                  <el-icon style="margin-right: 6px;"><Setting /></el-icon>个人中心
                </el-dropdown-item>
                <el-dropdown-item command="logout" divided aria-label="退出登录">
                  <el-icon style="margin-right: 6px;"><SwitchButton /></el-icon>退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button v-else type="primary" size="small" @click="$router.push('/login')">登录</el-button>
          <div class="header-status">
            <span class="status-dot"></span>
            <span class="status-text">服务运行中</span>
            <span class="version-tag">v2.0.0</span>
          </div>
        </div>
      </header>

      <!-- 内容区 -->
      <div class="content-area">
        <router-view v-slot="{ Component }">
          <keep-alive>
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </div>
    </div>

    <!-- 全局浮动任务面板（登录后显示） -->
    <GlobalTaskPanel v-if="isLoggedIn()" />

    <!-- 数据源管理弹窗 -->
    <DataSourceDialog v-model="dsDialogVisible" @imported="onDsImported" />

    <!-- 使用说明弹窗（登录后显示） -->
    <UsageGuideDialog v-model="guideVisible" />
  </div>
</template>

<script setup>
import { computed, reactive, provide, onMounted, h, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  HomeFilled,
  DataAnalysis,
  Histogram,
  MagicStick,
  Search,
  Setting,
  Cpu,
  ChatDotRound,
  Document,
  List,
  User,
  Timer,
  Coin,
  ArrowDown,
  SwitchButton,
  Service,
  Reading
} from '@element-plus/icons-vue'
import { isLoggedIn, logout, fetchDatasets, authStore, getCurrentUser, updateUserInfo } from './api/index.js'
import GlobalTaskPanel from './components/GlobalTaskPanel.vue'
import DataSourceDialog from './components/DataSourceDialog.vue'
import UsageGuideDialog from './components/UsageGuideDialog.vue'
import { clearAllTasks, restoreRunningTasks } from './stores/taskPanel.js'

const route = useRoute()
const router = useRouter()

// 使用说明弹窗
const guideVisible = ref(false)

// 数据源弹窗
const dsDialogVisible = ref(false)
// 打开数据源弹窗前的登录守卫：未登录跳转到登录页
function openDsDialog() {
  if (!isLoggedIn()) {
    ElMessage.warning('请先登录后再管理数据源')
    router.push('/login?redirect=' + encodeURIComponent(route.fullPath))
    return
  }
  dsDialogVisible.value = true
}
function onDsImported() {
  // 导入后刷新数据集列表
  datasetStore.loading = true
  fetchDatasets().then(res => {
    datasetStore.datasets = res.data || []
  }).catch(() => {
    datasetStore.datasets = []
  }).finally(() => {
    datasetStore.loading = false
  })
}

// 当前用户信息（响应式，从全局 authStore 获取）
const currentUser = computed(() => authStore.user)

// 用户下拉菜单命令
function handleUserCommand(command) {
  if (command === 'profile') {
    router.push('/profile')
  } else if (command === 'logout') {
    handleLogout()
  }
}

// 退出登录
function handleLogout() {
  // 清空任务面板，停止所有轮询
  clearAllTasks()
  logout()
  router.push('/')
}

// 全局共享的数据集状态
const datasetStore = reactive({
  datasets: [],
  selectedId: null,
  loading: false
})
provide('datasetStore', datasetStore)

// 全局加载数据集，确保所有页面可用（仅在已登录时加载）
onMounted(async () => {
  if (!isLoggedIn()) return
  
  // 获取当前用户信息（确保用户名等信息正确）
  try {
    const userRes = await getCurrentUser()
    updateUserInfo(userRes.data)
  } catch {
    // 获取用户信息失败，忽略
  }
  
  datasetStore.loading = true
  try {
    const res = await fetchDatasets()
    datasetStore.datasets = res.data || []
  } catch {
    datasetStore.datasets = []
  } finally {
    datasetStore.loading = false
  }

  // 恢复运行中和等待中的任务到面板（页面刷新后进度不丢失）
  await restoreRunningTasks()
})

const navItems = [
  { path: '/', icon: HomeFilled, label: '首页' },
  { path: '/datasets', icon: DataAnalysis, label: '数据管理' },
  { path: '/task-history', icon: Timer, label: '操作历史' },
  { path: '/analysis', icon: Histogram, label: '数据分析' },
  { path: '/cleaning', icon: MagicStick, label: '数据清洗' },
  { path: '/mining', icon: Search, label: '数据挖掘' },
  { path: '/feature', icon: Setting, label: '特征工程' },
  { path: '/ml', icon: Cpu, label: '机器学习' },
  { path: '/ai', icon: ChatDotRound, label: 'AI分析' },
]

const currentTitle = computed(() => {
  const item = navItems.find(i => i.path === route.path)
  return item ? item.label : 'Data Insight Platform'
})

const currentNavItem = computed(() => {
  return navItems.find(i => i.path === route.path) || null
})
</script>