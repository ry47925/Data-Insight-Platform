<template>
  <div v-loading="pageLoading" element-loading-text="数据加载中...">
    <!-- 系统健康横幅 -->
    <div v-if="healthBanner" class="health-banner" :class="healthBanner.type">
      <el-icon :size="18"><component :is="healthBanner.icon" /></el-icon>
      <span>{{ healthBanner.text }}</span>
      <span style="margin-left:auto; font-weight: 400; color: #9ca3af;">自动刷新：30 秒</span>
    </div>

    <!-- 数据概览 -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">数据概览</div>
        <span class="text-sm" style="color: #9ca3af;">最后更新: {{ overviewLastUpdate }}</span>
      </div>
      <div class="stats-grid" style="grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));">
        <div class="stat-card">
          <el-icon :size="28" style="color: #3b82f6;"><User /></el-icon>
          <div class="stat-value">{{ overview.total_users || 0 }}</div>
          <div class="stat-label">总用户数</div>
          <div class="stat-sub">今日新增 {{ overview.today_new_users || 0 }}</div>
        </div>
        <div class="stat-card">
          <el-icon :size="28" style="color: #10b981;"><DataAnalysis /></el-icon>
          <div class="stat-value">{{ overview.total_datasets || 0 }}</div>
          <div class="stat-label">总数据集数</div>
        </div>
        <div class="stat-card">
          <el-icon :size="28" style="color: #f59e0b;"><Cloudy /></el-icon>
          <div class="stat-value">{{ formatStorageSize(overview.total_storage_bytes) }}</div>
          <div class="stat-label">总存储量</div>
        </div>
        <div class="stat-card">
          <el-icon :size="28" style="color: #8b5cf6;"><DataBoard /></el-icon>
          <div class="stat-value">{{ overview.total_tasks || 0 }}</div>
          <div class="stat-label">总任务数</div>
          <div class="stat-sub">成功率 {{ overview.task_success_rate != null ? overview.task_success_rate + '%' : '-' }} · 今日 {{ overview.today_tasks || 0 }}</div>
        </div>
        <div class="stat-card">
          <el-icon :size="28" style="color: #06b6d4;"><TrendCharts /></el-icon>
          <div class="stat-value">{{ overview.active_users_today || 0 }}</div>
          <div class="stat-label">今日活跃用户</div>
        </div>
        <div class="stat-card">
          <el-icon :size="28" style="color: #ef4444;"><CircleClose /></el-icon>
          <div class="stat-value" style="color: #e8463a;">{{ overview.errors_today || 0 }}</div>
          <div class="stat-label">今日错误</div>
        </div>
      </div>
    </div>

    <!-- 近 30 天增长趋势 -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">近 30 天增长趋势</div>
      </div>
      <div ref="trendChartRef" style="height: 300px;"></div>
    </div>

    <!-- 服务控制区域 -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">服务状态总览</div>
        <div class="flex-center" style="gap:10px;">
          <el-button size="small" @click="refreshStatus">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
          <el-button size="small" type="warning" @click="restartAllServices" :loading="restarting">
            <el-icon><RefreshRight /></el-icon> 重启所有服务
          </el-button>
          <span class="text-sm">自动刷新：{{ autoRefresh ? '开启' : '关闭' }}</span>
          <el-switch v-model="autoRefresh" active-text="开" inactive-text="关" />
        </div>
      </div>

      <!-- 重启进度提示 -->
      <div v-if="restartProgress.visible" class="restart-progress">
        <el-alert
          :title="restartProgress.title"
          :type="restartProgress.type"
          :closable="false"
          show-icon
        />
        <div v-if="restartProgress.details.length > 0" class="restart-details">
          <div v-for="(detail, index) in restartProgress.details" :key="index" class="restart-detail-item">
            <el-icon :size="14" :class="detail.status === 'success' ? 'icon-success' : 'icon-error'">
              <component :is="detail.status === 'success' ? CircleCheck : CircleClose" />
            </el-icon>
            <span :class="detail.status">{{ detail.message }}</span>
          </div>
        </div>
      </div>

      <div class="stats-grid" style="grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));">
        <div v-for="service in servicesWithMetrics" :key="service.name" class="stat-card" :class="getStatusClass(service.status)">
          <div class="flex-between" style="margin-bottom: 12px;">
            <el-icon :size="32" :class="getStatusIconClass(service.status)">
              <component :is="getIcon(service.icon)" />
            </el-icon>
            <div class="flex-center" style="gap: 6px;">
              <el-tag :type="getStatusTagType(service.status)" size="small">
                {{ service.status === 'online' ? '在线' : '离线' }}
              </el-tag>
              <!-- 关键服务（无降级，停止即系统崩溃）：不提供停止/启动按钮 -->
              <el-tooltip
                v-if="criticalServices.includes(service.key)"
                content="关键服务，无降级能力，禁止在页面停止/启动（请用 docker compose 管理）"
                placement="top"
              >
                <el-tag type="danger" size="small" effect="plain">关键服务</el-tag>
              </el-tooltip>
              <el-button
                v-else-if="service.status === 'online'"
                size="small"
                type="danger"
                @click="stopService(service.key)"
                :loading="service.loading"
              >
                停止
              </el-button>
              <el-button
                v-else
                size="small"
                type="success"
                @click="startService(service.key)"
                :loading="service.loading"
              >
                启动
              </el-button>
            </div>
          </div>
          <div class="stat-value">{{ service.name }}</div>
          <div class="stat-label">{{ service.backend }}</div>
          <div style="font-size: 12px; color: #9ca3af; margin-top: 8px; line-height: 1.4;">
            {{ service.message }}
          </div>

          <!-- 详细指标 -->
          <div v-if="service.metrics && service.status === 'online'" class="service-metrics">
            <div v-for="(value, key) in service.metrics" :key="key" class="metric-item">
              <span class="metric-key">{{ formatMetricKey(key) }}:</span>
              <span class="metric-value">{{ formatMetricValue(key, value) }}</span>
            </div>
          </div>
          <div v-else-if="service.fallbackMetrics" class="service-metrics fallback">
            <div v-for="(value, key) in service.fallbackMetrics" :key="key" class="metric-item">
              <span class="metric-key">{{ formatMetricKey(key) }}:</span>
              <span class="metric-value">{{ value }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 近期动态：今日错误 + 最近任务 -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">近期动态</div>
        <el-button size="small" @click="refreshStatus">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
      </div>
      <div class="recent-grid">
        <div>
          <div class="recent-title">今日错误（ERROR）</div>
          <div v-if="recentErrors.length" class="recent-list">
            <div v-for="(err, i) in recentErrors" :key="i" class="recent-item">
              <!-- :title 悬停显示完整错误消息（消息可能很长，列表内最多显示 2 行） -->
              <span class="recent-msg" style="color: #e8463a;" :title="err.message">{{ err.message }}</span>
              <span class="recent-time">{{ err.time.slice(11) }}</span>
            </div>
          </div>
          <div v-else class="recent-empty">今日暂无错误</div>
          <div class="recent-link">
            <el-link type="primary" :underline="false" @click="$router.push('/logs')">查看全部错误 →</el-link>
          </div>
        </div>
        <div>
          <div class="recent-title">最近任务</div>
          <div v-if="recentTasks.length" class="recent-list">
            <div v-for="task in recentTasks" :key="task.id" class="recent-item">
              <el-tag :type="taskStatusType(task.status_raw)" size="small">{{ taskStatusLabel(task.status) }}</el-tag>
              <span class="recent-msg">{{ task.task_type }}<template v-if="task.status === 'failed'"> · {{ (task.error_message || '').slice(0, 40) }}</template></span>
              <span class="recent-time">{{ formatTaskTime(task.created_at) }}</span>
            </div>
          </div>
          <div v-else class="recent-empty">暂无任务</div>
          <div class="recent-link">
            <el-link type="primary" :underline="false" @click="$router.push('/tasks')">查看全部任务 →</el-link>
          </div>
        </div>
      </div>
    </div>

    <!-- 降级说明 -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">降级说明</div>
      </div>
      <div class="el-table-wrapper" style="max-height: none;">
        <el-table :data="degradeInfo" border>
          <el-table-column prop="service" label="服务" width="120" />
          <el-table-column prop="primary" label="主模式" width="160" />
          <el-table-column prop="fallback" label="降级模式" width="160" />
          <el-table-column prop="description" label="说明" />
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, onActivated, onDeactivated, watch, computed } from 'vue'
import { Refresh, RefreshRight, DataAnalysis, Cloudy, DataBoard, DataLine, TrendCharts, CircleCheck, CircleClose, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { getServicesStatus, getServicesMetrics, startService as apiStartService, stopService as apiStopService, restartAllServices as apiRestartAllServices, getOverview, listLogs, listBusinessTasks } from '../../api/admin.js'

const services = ref([])
const metrics = ref({})
const autoRefresh = ref(true)
const overview = ref({})
const overviewLastUpdate = ref('')
const recentErrors = ref([])
const recentTasks = ref([])
const trendChartRef = ref(null)
// 首次加载（尚无数据）显示转圈；加载成功后自动/手动刷新静默更新，避免每次都闪 loading
const pageLoading = ref(false)
const pageLoaded = ref(false)
let trendChart = null
const restarting = ref(false)
const restartProgress = ref({
  visible: false,
  title: '',
  type: 'info',
  details: []
})
let refreshTimer = null

const degradeInfo = [
  { service: 'Redis', primary: 'Redis 缓存', fallback: '内存 LRU 缓存', description: 'Redis 不可用时自动切换到内存缓存，缓存数据保存在应用内存中；可在页面停止/启动，停止后自动降级' },
  { service: 'MinIO', primary: 'MinIO 对象存储', fallback: '无降级', description: 'MinIO 为唯一对象存储后端，无降级能力；关键服务，页面已禁止停止/启动（停止将导致系统崩溃）' },
  { service: 'Celery', primary: 'Celery 异步任务', fallback: '同步执行', description: 'Celery Worker 不可用时自动降级为同步执行，任务在请求线程中直接执行；可在页面停止/启动' },
  { service: 'PostgreSQL', primary: 'PostgreSQL 数据库', fallback: '无降级', description: 'PostgreSQL 为唯一关系型数据库，无降级能力；关键服务，页面已禁止停止/启动（停止将导致系统崩溃）' },
  { service: 'ClickHouse', primary: 'ClickHouse 分析引擎', fallback: 'Pandas 分析', description: '可选加速服务，未启用或不可用时自动回退 Pandas 分析（功能不受影响，仅无加速效果）；可在页面停止/启动' },
]

const iconMap = {
  cache: DataLine,
  cloud: Cloudy,
  tasks: DataBoard,
  database: DataAnalysis,
  'bar-chart': TrendCharts
}

const serviceKeyMap = {
  'Redis': 'redis',
  'MinIO': 'minio',
  'Celery': 'celery',
  // 后端 /admin/services/metrics 对 PostgreSQL 使用的键为 postgresql（修复键名不匹配）
  'PostgreSQL': 'postgresql',
  'ClickHouse': 'clickhouse'
}

// 关键服务（无降级，停止即系统崩溃）：前端隐藏停止/启动按钮
const criticalServices = ['postgresql', 'minio']

const metricKeyMap = {
  'memory_used_mb': '内存使用',
  'memory_peak_mb': '内存峰值',
  'keys_count': '键数量',
  'expiring_keys': '过期键数',
  'uptime_days': '运行天数',
  'connected_clients': '连接数',
  'total_connections': '总连接数',
  'keyspace_hits': '命中次数',
  'keyspace_misses': '未命中次数',
  'hit_rate': '命中率',
  'database_size_mb': '数据库大小',
  'active_connections': '活跃连接',
  'max_connections': '最大连接数',
  'connection_rate': '连接使用率',
  'table_count': '表数量',
  'database_version': '数据库版本',
  'buckets': '存储桶数',
  'objects': '对象数量',
  'total_size_mb': '总大小',
  'endpoint': '服务端点',
  'workers': 'Worker数',
  'pending_tasks': '待处理任务',
  'active_tasks': '执行中任务',
  'completed_tasks': '已完成任务',
  'failed_tasks': '失败任务',
  'host': '主机',
  'port': '端口',
  'databases': '数据库数',
  'tables': '库内表数',
  'total_rows': '总行数',
  'total_bytes_readable': '存储占用',
  'memory_cache_keys': '内存缓存键数',
  'memory_cache_size': '内存缓存大小',
  'upload_dir': '上传目录'
}

function getIcon(iconName) {
  return iconMap[iconName] || DataAnalysis
}

function getStatusClass(status) {
  return status === 'online' ? 'status-online' : 'status-offline'
}

function getStatusIconClass(status) {
  return status === 'online' ? 'icon-success' : 'icon-warning'
}

function getStatusTagType(status) {
  return status === 'online' ? 'success' : 'warning'
}

function formatMetricKey(key) {
  return metricKeyMap[key] || key
}

function formatMetricValue(key, value) {
  if (key === 'hit_rate' || key === 'connection_rate') return `${value}%`
  if (key === 'memory_used_mb' || key === 'memory_peak_mb' || key === 'database_size_mb' || key === 'total_size_mb') return `${value} MB`
  return value
}

// 系统健康横幅：全部在线为绿色，存在离线服务为黄色
const healthBanner = computed(() => {
  const list = services.value
  if (!list.length) return null
  const offline = list.filter(s => s.status === 'offline')
  if (!offline.length) {
    return { type: 'success', icon: CircleCheck, text: '所有服务运行正常' }
  }
  const names = offline.map(s => s.name).join('、')
  return { type: 'warning', icon: CircleClose, text: `${offline.length} 个服务离线：${names}` }
})

// 任务状态 → el-tag 类型（el-tag 仅支持 success/info/warning/danger/空）
function taskStatusType(statusRaw) {
  return { pending: 'warning', running: 'info', success: 'success', failed: 'danger', cancelled: 'info' }[statusRaw] || 'info'
}

// 任务状态中文标签（后端 /business/tasks 已返回中文，直接展示）
function taskStatusLabel(status) {
  return status
}

// 任务创建时间显示为 MM-DD HH:MM（created_at 为上海时区 ISO 字符串，去掉中间的 T）
function formatTaskTime(createdAt) {
  if (!createdAt) return '-'
  const iso = String(createdAt)
  // ISO 形如 "2026-08-15T14:00:00+08:00"：取日期与时分并拼接为 MM-DD HH:MM
  return `${iso.slice(5, 10)} ${iso.slice(11, 16)}`
}

const servicesWithMetrics = computed(() => {
  return services.value.map(service => {
    const key = serviceKeyMap[service.name]
    const serviceMetrics = metrics.value[key]
    const serviceData = { ...service, key, loading: false }

    if (serviceMetrics) {
      if (serviceMetrics.status === 'online') {
        // 提取关键指标显示
        const { status, container, error, fallback, ...metricData } = serviceMetrics
        serviceData.metrics = metricData
      } else {
        const { status, container, error, fallback, ...fallbackData } = serviceMetrics
        serviceData.fallbackMetrics = fallbackData
        serviceData.message = serviceMetrics.fallback ? `已降级: ${fallback}` : service.message
      }
    }
    return serviceData
  })
})

async function refreshStatus() {
  // 仅首次（尚无数据）显示加载转圈；已有数据后的轮询/手动刷新静默更新
  if (!pageLoaded.value) {
    pageLoading.value = true
  }
  try {
    // 今日错误按上海时区当日日期过滤，避免昨日错误被展示为"今日错误"（修复）
    const todayParts = new Intl.DateTimeFormat('zh-CN', {
      timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'
    }).formatToParts(new Date())
    const getPart = type => todayParts.find(p => p.type === type)?.value || ''
    const todayDate = `${getPart('year')}-${getPart('month')}-${getPart('day')}`
    const [statusRes, metricsRes, overviewRes, errorsRes, tasksRes] = await Promise.all([
      getServicesStatus(),
      getServicesMetrics(),
      getOverview(),
      listLogs({ level: 'ERROR', date: todayDate, page: 1, page_size: 5 }),
      listBusinessTasks({ page: 1, page_size: 5 })
    ])
    services.value = statusRes.data.services || []
    metrics.value = metricsRes.data.metrics || {}
    overview.value = overviewRes.data || {}
    recentErrors.value = errorsRes.data.records || []
    recentTasks.value = tasksRes.data.tasks || []
    overviewLastUpdate.value = new Date().toLocaleTimeString('zh-CN')
    renderTrendChart()
    pageLoaded.value = true
  } catch (e) {
    console.error('获取服务状态失败:', e)
    ElMessage.error('服务总览数据加载失败，请刷新重试')
  } finally {
    pageLoading.value = false
  }
}

// 近 30 天增长趋势图（数据来自 /overview.trends）
function renderTrendChart() {
  const t = overview.value.trends
  if (!t || !trendChartRef.value) return
  if (!trendChart) {
    trendChart = echarts.init(trendChartRef.value)
  }
  trendChart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['新增用户', '新增数据集', '任务数'], top: 0 },
    grid: { left: '4%', right: '4%', bottom: '6%', top: '12%', containLabel: true },
    xAxis: { type: 'category', data: (t.users || []).map(x => x.date) },
    yAxis: { type: 'value' },
    series: [
      { name: '新增用户', type: 'line', smooth: true, symbol: 'circle', symbolSize: 4, data: (t.users || []).map(x => x.value), itemStyle: { color: '#3b82f6' } },
      { name: '新增数据集', type: 'line', smooth: true, symbol: 'circle', symbolSize: 4, data: (t.datasets || []).map(x => x.value), itemStyle: { color: '#10b981' } },
      { name: '任务数', type: 'line', smooth: true, symbol: 'circle', symbolSize: 4, data: (t.tasks || []).map(x => x.value), itemStyle: { color: '#f59e0b' } },
    ],
  })
}

// 将字节数格式化为易读的存储单位（B/KB/MB/GB）
function formatStorageSize(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(2) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(2) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB'
}

async function startService(serviceName) {
  const service = servicesWithMetrics.value.find(s => s.key === serviceName)
  if (service) service.loading = true

  // 服务名称映射为大写显示
  const displayName = serviceName.toUpperCase()

  try {
    restartProgress.value = {
      visible: true,
      title: `正在启动 ${displayName}...`,
      type: 'info',
      details: [{ message: `正在启动 ${displayName}...`, status: 'pending' }]
    }

    const res = await apiStartService(serviceName)

    restartProgress.value.details = [
      { message: `${displayName} 启动完成`, status: 'success' }
    ]
    restartProgress.value.title = `${displayName} 启动完成`
    restartProgress.value.type = 'success'

    setTimeout(() => {
      restartProgress.value.visible = false
    }, 3000)

    await refreshStatus()
  } catch (e) {
    restartProgress.value.details = [
      { message: `${displayName} 启动失败: ${e.message}`, status: 'error' }
    ]
    restartProgress.value.title = `${displayName} 启动失败`
    restartProgress.value.type = 'error'
    console.error('启动服务失败:', e)
  } finally {
    if (service) service.loading = false
  }
}

async function stopService(serviceName) {
  const service = servicesWithMetrics.value.find(s => s.key === serviceName)
  if (service) service.loading = true

  const displayName = serviceName.toUpperCase()

  try {
    restartProgress.value = {
      visible: true,
      title: `正在停止 ${displayName}...`,
      type: 'info',
      details: [{ message: `正在停止 ${displayName}...`, status: 'pending' }]
    }

    const res = await apiStopService(serviceName)

    restartProgress.value.details = [
      { message: res.data.message || `${displayName} 已停止`, status: 'success' }
    ]
    restartProgress.value.title = `${displayName} 已停止`
    restartProgress.value.type = 'warning'

    setTimeout(() => {
      restartProgress.value.visible = false
    }, 3000)

    await refreshStatus()
  } catch (e) {
    restartProgress.value.details = [
      { message: `${displayName} 停止失败: ${e.message}`, status: 'error' }
    ]
    restartProgress.value.title = `${displayName} 停止失败`
    restartProgress.value.type = 'error'
    console.error('停止服务失败:', e)
  } finally {
    if (service) service.loading = false
  }
}

async function restartAllServices() {
  if (restarting.value) return
  restarting.value = true

  restartProgress.value = {
    visible: true,
    title: '正在重启所有服务...',
    type: 'info',
    details: []
  }

  try {
    const res = await apiRestartAllServices()
    const results = res.data.results || []

    restartProgress.value.details = results.map(r => ({
      message: `${r.service.toUpperCase()} ${r.action === 'stop' ? '停止' : '启动'}${r.status === 'success' ? '完成' : '失败'}`,
      status: r.status
    }))

    restartProgress.value.title = `所有服务重启完成 (${new Date().toLocaleTimeString()})`
    restartProgress.value.type = 'success'

    setTimeout(() => {
      restartProgress.value.visible = false
    }, 5000)

    await refreshStatus()
  } catch (e) {
    restartProgress.value.details = [
      { message: `重启失败: ${e.message}`, status: 'error' }
    ]
    restartProgress.value.title = '重启失败'
    restartProgress.value.type = 'error'
    console.error('重启所有服务失败:', e)
  } finally {
    restarting.value = false
  }
}

onMounted(() => {
  refreshStatus()
  window.addEventListener('resize', onWindowResize)
  if (autoRefresh.value) {
    refreshTimer = setInterval(refreshStatus, 30000)
  }
})

// 自动刷新开关实时生效：关闭时停止轮询，开启时恢复（修复开关形同虚设）
watch(autoRefresh, (val) => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
  if (val) {
    refreshTimer = setInterval(refreshStatus, 30000)
  }
})

// keep-alive 下切走时停止轮询、切回时按开关状态恢复，避免定时器泄漏（onUnmounted 不触发）
onDeactivated(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
  window.removeEventListener('resize', onWindowResize)
})

onActivated(() => {
  window.addEventListener('resize', onWindowResize)
  if (autoRefresh.value && !refreshTimer) {
    refreshTimer = setInterval(refreshStatus, 30000)
  }
})

function onWindowResize() {
  if (trendChart) trendChart.resize()
}

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
  }
  window.removeEventListener('resize', onWindowResize)
  if (trendChart) {
    trendChart.dispose()
    trendChart = null
  }
})
</script>

<style scoped>
.status-online {
  border: 1px solid #d1fae5;
  background: #f0fff4;
}

.status-offline {
  border: 1px solid #fef3c7;
  background: #fffbeb;
}

.icon-success {
  color: #10b981;
}

.icon-warning {
  color: #f59e0b;
}

.icon-error {
  color: #ef4444;
}

.restart-progress {
  margin-bottom: 20px;
}

.restart-details {
  margin-top: 10px;
  padding: 10px;
  background: #f8fafc;
  border-radius: 6px;
}

.restart-detail-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 13px;
}

.restart-detail-item .success {
  color: #10b981;
}

.restart-detail-item .error {
  color: #ef4444;
}

.restart-detail-item .pending {
  color: #6b7280;
}

.service-metrics {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #e5e7eb;
}

.service-metrics.fallback {
  border-top-color: #fbbf24;
}

.metric-item {
  display: flex;
  justify-content: space-between;
  padding: 3px 0;
  font-size: 12px;
}

.metric-key {
  color: #6b7280;
}

.metric-value {
  color: #374151;
  font-weight: 500;
}

/* 健康横幅 */
.health-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-radius: 8px;
  margin-bottom: 20px;
  font-size: 14px;
  font-weight: 500;
}

.health-banner.success {
  background: #f0fff4;
  border: 1px solid #d1fae5;
  color: #047857;
}

.health-banner.warning {
  background: #fffbeb;
  border: 1px solid #fef3c7;
  color: #b45309;
}

/* 近期动态 */
.recent-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

.recent-title {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 10px;
}

.recent-list {
  max-height: 260px;
  overflow-y: auto;
}

.recent-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid #f3f4f6;
  font-size: 13px;
}

.recent-msg {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  /* 长错误消息自动换行（最多 2 行省略），避免超长文本把 flex 布局撑破导致边框显示不完整 */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  word-break: break-all;
  color: #374151;
}

.recent-time {
  color: #9ca3af;
  font-size: 12px;
  flex-shrink: 0;
}

.recent-empty {
  color: #9ca3af;
  font-size: 13px;
  padding: 12px 0;
}

.recent-link {
  margin-top: 8px;
  text-align: right;
}
</style>
