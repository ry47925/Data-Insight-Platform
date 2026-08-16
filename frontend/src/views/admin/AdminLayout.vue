<template>
  <div class="app-layout">
    <aside class="sidebar">
      <div class="sidebar-brand">
        <div class="sidebar-logo">
          <el-icon :size="22"><Setting /></el-icon>
        </div>
        <div>
          <div class="sidebar-title">管理后台</div>
          <div class="sidebar-subtitle">Admin Dashboard</div>
        </div>
      </div>
      <nav class="sidebar-nav">
        <router-link v-for="item in navItems" :key="item.path" :to="item.path"
          class="nav-item" :class="{ active: route.path === item.path }">
          <el-icon class="nav-icon"><component :is="item.icon"></component></el-icon>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>
      <div class="sidebar-footer">
        <div class="flex-between" style="color: var(--sidebar-text); font-size: 12px;">
          <span class="flex-center" style="gap:4px;">
            <el-icon :size="14"><User /></el-icon>admin
          </span>
          <span>v2.0.0</span>
        </div>
      </div>
    </aside>

    <div class="main-area">
      <header class="top-header">
        <div class="header-breadcrumb flex-center" style="gap:8px;">
          <el-icon v-if="currentNavItem" :size="20"><component :is="currentNavItem.icon" /></el-icon>
          <span>{{ currentTitle }}</span>
        </div>
        <div class="header-spacer"></div>
        <div class="header-right">
          <div class="header-status">
            <span class="status-dot"></span>
            <span class="status-text">服务运行中</span>
          </div>
          <el-button type="text" size="small" class="logout-btn" @click="handleLogout">退出</el-button>
        </div>
      </header>

      <div class="content-area">
        <router-view v-slot="{ Component }">
          <keep-alive>
            <component :is="Component" />
          </keep-alive>
        </router-view>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  HomeFilled,
  Setting,
  DataAnalysis,
  Cloudy,
  DataLine,
  DataBoard,
  Document,
  User,
  FolderOpened,
  Connection,
  Monitor,
  MagicStick
} from '@element-plus/icons-vue'
import { clearAdminToken } from '../../api/admin.js'

const route = useRoute()
const router = useRouter()

function handleLogout() {
  clearAdminToken()
  router.push('/login')
}

const navItems = [
  { path: '/screen', icon: Monitor, label: '数据大屏' },
  { path: '/dashboard', icon: HomeFilled, label: '服务总览' },
  { path: '/ai-usage', icon: MagicStick, label: 'AI 用量' },
  { path: '/users', icon: User, label: '用户管理' },
  { path: '/storage', icon: Cloudy, label: '存储管理' },
  { path: '/data-management', icon: FolderOpened, label: '数据管理' },
  { path: '/data-sources', icon: Connection, label: '数据源管理' },
  { path: '/cache', icon: DataLine, label: '缓存管理' },
  { path: '/database', icon: DataAnalysis, label: '数据库管理' },
  { path: '/tasks', icon: DataBoard, label: '任务管理' },
  { path: '/logs', icon: Document, label: '运行日志' },
]

const currentTitle = computed(() => {
  const item = navItems.find(i => i.path === route.path)
  return item ? item.label : '管理后台'
})

const currentNavItem = computed(() => {
  return navItems.find(i => i.path === route.path) || null
})
</script>