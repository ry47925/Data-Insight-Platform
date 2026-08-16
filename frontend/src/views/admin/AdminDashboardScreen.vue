<template>
  <div class="dash-screen" v-loading="screenLoading" element-loading-text="大屏数据加载中..." element-loading-background="rgba(11,18,32,0.7)">
    <!-- 顶部标题栏 -->
    <div class="dash-header">
      <div class="dash-title">Data Insight 运营数据大屏</div>
      <div class="dash-screen-tag">{{ currentScreen ? currentScreen.title : '' }}</div>
      <div class="dash-time">{{ nowText }} · 自动刷新 60 秒</div>
      <div class="dash-actions">
        <el-switch v-model="autoPlay" active-text="轮播" inactive-text="暂停" size="small" style="--el-switch-on-color:#3b82f6;" />
        <el-button size="small" @click="loadData">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
        <el-button size="small" type="primary" @click="$router.push('/dashboard')">
          <el-icon><Back /></el-icon> 退出大屏
        </el-button>
      </div>
    </div>

    <!-- KPI 指标行 -->
    <div class="kpi-row">
      <div v-for="k in kpiCards" :key="k.label" class="kpi-card">
        <div class="kpi-value" :style="{ color: k.color }">{{ k.value }}</div>
        <div class="kpi-label">{{ k.label }}</div>
      </div>
    </div>

    <!-- 分屏图表区：v-if 仅渲染当前屏 DOM，切屏全量重建，保证内容正确；悬停暂停轮播 -->
    <div class="screen-area" @mouseenter="stopPlay()" @mouseleave="startPlay()">
      <div v-if="currentScreen" class="screen-grid">
        <div v-for="c in currentScreen.charts" :key="c" class="chart-box">
          <div class="chart-title">{{ chartTitles[c] }}</div>
          <div :ref="el => setChartRef(c, el)" class="chart-holder"></div>
        </div>
      </div>
    </div>

    <!-- 轮播控制 -->
    <div class="screen-nav">
      <el-button size="small" circle @click="switchScreen(screenIndex - 1)">
        <el-icon><ArrowLeft /></el-icon>
      </el-button>
      <div class="screen-dots">
        <span
          v-for="(s, i) in screens"
          :key="s.key"
          class="dot"
          :class="{ active: screenIndex === i }"
          @click="switchScreen(i)"
        ></span>
      </div>
      <el-button size="small" circle @click="switchScreen(screenIndex + 1)">
        <el-icon><ArrowRight /></el-icon>
      </el-button>
    </div>

    <!-- 底部实时动态（溢出时缓慢滚动） -->
    <div class="realtime-row">
      <div class="rt-card">
        <div class="rt-title">最近任务</div>
        <div ref="taskListRef" class="rt-list" :class="{ scrolling: taskScrolling }">
          <div class="rt-scroll">
            <template v-if="realtime.recent_tasks.length">
              <div v-for="(t, i) in realtime.recent_tasks" :key="'a' + i" class="rt-item">
                <el-tag :type="statusTagType(t.status_raw)" size="small">{{ t.status }}</el-tag>
                <span class="rt-msg">{{ t.username }} · {{ t.task_type }}</span>
                <span class="rt-time">{{ t.created_at ? t.created_at.slice(5, 16) : '' }}</span>
              </div>
              <div v-for="(t, i) in realtime.recent_tasks" :key="'b' + i" class="rt-item" aria-hidden="true">
                <el-tag :type="statusTagType(t.status_raw)" size="small">{{ t.status }}</el-tag>
                <span class="rt-msg">{{ t.username }} · {{ t.task_type }}</span>
                <span class="rt-time">{{ t.created_at ? t.created_at.slice(5, 16) : '' }}</span>
              </div>
            </template>
            <div v-else class="rt-empty">暂无任务</div>
          </div>
        </div>
      </div>
      <div class="rt-card">
        <div class="rt-title">今日错误（{{ kpis.errors_today || 0 }}）</div>
        <div ref="errListRef" class="rt-list" :class="{ scrolling: errScrolling }">
          <div class="rt-scroll">
            <template v-if="realtime.recent_errors.length">
              <div v-for="(e, i) in realtime.recent_errors" :key="'a' + i" class="rt-item">
                <!-- :title 悬停显示完整错误消息 -->
                <span class="rt-err" :title="e.message">{{ e.message }}</span>
                <span class="rt-time">{{ e.created_at ? e.created_at.slice(11) : '' }}</span>
              </div>
              <div v-for="(e, i) in realtime.recent_errors" :key="'b' + i" class="rt-item" aria-hidden="true">
                <span class="rt-err" :title="e.message">{{ e.message }}</span>
                <span class="rt-time">{{ e.created_at ? e.created_at.slice(11) : '' }}</span>
              </div>
            </template>
            <div v-else class="rt-empty">今日暂无错误</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { Refresh, Back, ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { getDashboardData } from '../../api/admin.js'

const kpis = ref({})
const trends = ref({})
const distributions = ref({})
const realtime = ref({ recent_tasks: [], recent_errors: [] })
const nowText = ref('')
// 首次加载（尚无数据）显示转圈；加载成功后自动/手动刷新静默更新，避免每次都闪 loading
const screenLoading = ref(false)
const screenLoaded = ref(false)
const screenIndex = ref(0)
const autoPlay = ref(true)
const taskListRef = ref(null)
const errListRef = ref(null)
const taskScrolling = ref(false)
const errScrolling = ref(false)

// 分屏定义：每屏 2 张大图，图表最大化显示
const screens = [
  { key: 'growth', title: '增长趋势', charts: ['users', 'datasets'] },
  { key: 'aitask', title: 'AI 与任务', charts: ['ai', 'tasks'] },
  { key: 'dist', title: '分布统计', charts: ['module', 'status'] },
]

// 当前屏（computed 避免 v-if/v-for 同元素的作用域问题）
const currentScreen = computed(() => screens[screenIndex.value] || screens[0])

const chartTitles = {
  users: '用户注册趋势（近 30 天）',
  datasets: '数据集与存储增长（近 30 天）',
  ai: 'AI Token 消耗（近 30 天）',
  tasks: '任务数与成功率（近 30 天）',
  module: '数据集模块分布',
  status: '任务状态分布',
}

// module_source → 中文标签（数据集模块分布图例）
const MODULE_LABELS = {
  upload: '数据上传',
  cleaning: '数据清洗',
  ml: '机器学习',
  ai: 'AI分析',
  feature_engineering: '特征工程',
  data_mining: '数据挖掘',
  data_analysis: '数据分析',
  batch_predict: '机器学习',
  dataset: '数据治理',
  pipeline: '联动分析',
}

const charts = {}
const chartEls = {}
let timer = null
let clockTimer = null
let playTimer = null

function setChartRef(key, el) {
  if (el) {
    chartEls[key] = el
  } else {
    // v-if 销毁屏时清理残留引用，避免在其他屏图表上误初始化
    delete chartEls[key]
  }
}

const kpiCards = computed(() => [
  { label: `用户总数（今日+${kpis.value.today_new_users ?? '-'}）`, value: kpis.value.total_users ?? '-', color: '#3b82f6' },
  { label: '数据集数', value: kpis.value.total_datasets ?? '-', color: '#10b981' },
  { label: '总存储量', value: formatStorage(kpis.value.total_storage_bytes), color: '#f59e0b' },
  { label: '任务数（成功率）', value: `${kpis.value.total_tasks ?? '-'} (${kpis.value.task_success_rate ?? '-'}%)`, color: '#8b5cf6' },
  { label: 'AI Token 消耗', value: formatTokens(kpis.value.total_ai_tokens), color: '#06b6d4' },
  { label: '今日错误', value: kpis.value.errors_today ?? '-', color: '#ef4444' },
])

function formatStorage(bytes) {
  if (!bytes && bytes !== 0) return '-'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB'
  return (bytes / 1024 / 1024 / 1024).toFixed(2) + ' GB'
}

function formatTokens(n) {
  if (!n && n !== 0) return '-'
  if (n >= 1000000) return (n / 1000000).toFixed(2) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  return String(n)
}

function statusTagType(statusRaw) {
  return { pending: 'warning', running: 'info', success: 'success', failed: 'danger', cancelled: 'info' }[statusRaw] || 'info'
}

// 检测实时列表是否溢出：溢出时启用缓慢滚动，数据少不滚动
function checkScroll() {
  nextTick(() => {
    taskScrolling.value = !!taskListRef.value && taskListRef.value.scrollHeight > taskListRef.value.clientHeight + 2
    errScrolling.value = !!errListRef.value && errListRef.value.scrollHeight > errListRef.value.clientHeight + 2
  })
}

// 深色大屏公共 tooltip/axis 样式
const AXIS = {
  axisLine: { lineStyle: { color: '#334155' } },
  axisLabel: { color: '#94a3b8', fontSize: 12 },
  splitLine: { lineStyle: { color: '#1e293b' } },
}

function ensureChart(key) {
  if (!charts[key] && chartEls[key]) {
    charts[key] = echarts.init(chartEls[key], 'dark')
  }
  return charts[key]
}

function renderCharts() {
  const t = trends.value || {}
  const d = distributions.value || {}

  // 1. 用户注册趋势
  const usersChart = ensureChart('users')
  if (usersChart) {
    usersChart.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: '4%', right: '4%', bottom: '6%', top: '10%', containLabel: true },
      xAxis: { type: 'category', data: (t.users || []).map(x => x.date), ...AXIS },
      yAxis: { type: 'value', minInterval: 1, ...AXIS },
      series: [{
        type: 'line', data: (t.users || []).map(x => x.value), smooth: true, symbol: 'circle', symbolSize: 5,
        areaStyle: { opacity: 0.25 }, lineStyle: { color: '#3b82f6', width: 3 }, itemStyle: { color: '#3b82f6' },
      }],
    })
  }

  // 2. 数据集与存储增长（双轴：柱=数据集，线=存储MB）
  const dsChart = ensureChart('datasets')
  if (dsChart) {
    dsChart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['新增数据集', '累计存储(MB)'], top: 0, textStyle: { color: '#94a3b8' } },
      grid: { left: '4%', right: '5%', bottom: '6%', top: '12%', containLabel: true },
      xAxis: { type: 'category', data: (t.datasets || []).map(x => x.date), ...AXIS },
      yAxis: [
        { type: 'value', name: '个数', ...AXIS, nameTextStyle: { color: '#94a3b8', fontSize: 12 } },
        { type: 'value', name: 'MB', ...AXIS, nameTextStyle: { color: '#94a3b8', fontSize: 12 }, splitLine: { show: false } },
      ],
      series: [
        { name: '新增数据集', type: 'bar', data: (t.datasets || []).map(x => x.value), itemStyle: { color: '#10b981' }, barMaxWidth: 18 },
        {
          name: '累计存储(MB)', type: 'line', yAxisIndex: 1, smooth: true, symbol: 'none',
          data: (t.storage || []).map(x => Math.round(x.value / 1024 / 1024)),
          lineStyle: { color: '#f59e0b', width: 3 }, itemStyle: { color: '#f59e0b' },
        },
      ],
    })
  }

  // 3. AI Token 消耗
  const aiChart = ensureChart('ai')
  if (aiChart) {
    aiChart.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: '4%', right: '4%', bottom: '6%', top: '10%', containLabel: true },
      xAxis: { type: 'category', data: (t.ai_tokens || []).map(x => x.date), ...AXIS },
      yAxis: { type: 'value', ...AXIS },
      series: [{
        type: 'bar', data: (t.ai_tokens || []).map(x => x.value),
        itemStyle: { color: '#06b6d4', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 18,
      }],
    })
  }

  // 4. 任务数与成功率（柱+线）
  const taskChart = ensureChart('tasks')
  if (taskChart) {
    taskChart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['任务数', '成功率(%)'], top: 0, textStyle: { color: '#94a3b8' } },
      grid: { left: '4%', right: '5%', bottom: '6%', top: '12%', containLabel: true },
      xAxis: { type: 'category', data: (t.tasks || []).map(x => x.date), ...AXIS },
      yAxis: [
        { type: 'value', name: '个数', ...AXIS, nameTextStyle: { color: '#94a3b8', fontSize: 12 } },
        { type: 'value', name: '%', max: 100, ...AXIS, nameTextStyle: { color: '#94a3b8', fontSize: 12 }, splitLine: { show: false } },
      ],
      series: [
        { name: '任务数', type: 'bar', data: (t.tasks || []).map(x => x.value), itemStyle: { color: '#8b5cf6' }, barMaxWidth: 18 },
        {
          name: '成功率(%)', type: 'line', yAxisIndex: 1, smooth: true, symbol: 'none',
          data: (t.tasks || []).map(x => (x.success_rate == null ? null : x.success_rate)),
          lineStyle: { color: '#10b981', width: 3 }, itemStyle: { color: '#10b981' },
        },
      ],
    })
  }

  // 5. 数据集模块分布（环形）
  const moduleChart = ensureChart('module')
  if (moduleChart) {
    moduleChart.setOption({
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { type: 'scroll', orient: 'vertical', right: 0, top: 'middle', textStyle: { color: '#94a3b8', fontSize: 12 } },
      series: [{
        type: 'pie', radius: ['40%', '68%'], center: ['42%', '50%'],
        label: { show: false },
        labelLine: { show: false },
        // 模块来源（英文）映射为中文标签
        data: (d.dataset_by_module || []).map(x => ({ ...x, name: MODULE_LABELS[x.name] || x.name })),
      }],
    })
  }

  // 6. 任务状态分布（环形）
  const statusChart = ensureChart('status')
  if (statusChart) {
    const colors = { 成功: '#10b981', 执行中: '#3b82f6', 等待中: '#f59e0b', 失败: '#ef4444', 已取消: '#94a3b8' }
    statusChart.setOption({
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { type: 'scroll', orient: 'vertical', right: 0, top: 'middle', textStyle: { color: '#94a3b8', fontSize: 12 } },
      series: [{
        type: 'pie', radius: ['40%', '68%'], center: ['42%', '50%'],
        label: { show: false },
        labelLine: { show: false },
        data: (d.task_by_status || []).map(x => ({ ...x, itemStyle: { color: colors[x.name] } })),
      }],
    })
  }
}

async function loadData() {
  // 仅首次（尚无数据）显示加载转圈；已有数据后的轮询/手动刷新静默更新
  if (!screenLoaded.value) {
    screenLoading.value = true
  }
  try {
    const res = await getDashboardData()
    const data = res.data
    kpis.value = data.kpis || {}
    trends.value = data.trends || {}
    distributions.value = data.distributions || {}
    realtime.value = data.realtime || { recent_tasks: [], recent_errors: [] }
    await nextTick()
    rebuildCharts()
    checkScroll()
    screenLoaded.value = true
  } catch (e) {
    console.error('获取大屏数据失败:', e)
    ElMessage.error('大屏数据加载失败，请点击刷新重试')
  } finally {
    screenLoading.value = false
  }
}

// 销毁全部图表实例并重建当前屏（v-if 仅渲染当前屏 DOM，切屏从零渲染保证内容正确）
function rebuildCharts() {
  Object.values(charts).forEach(c => c && c.dispose())
  Object.keys(charts).forEach(k => { charts[k] = null })
  renderCharts()
}

// 切换分屏：销毁全部实例后重建当前屏图表
async function switchScreen(i) {
  const total = screens.length
  screenIndex.value = ((i % total) + total) % total
  await nextTick()
  rebuildCharts()
}

function tickClock() {
  const fmt = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  })
  nowText.value = fmt.format(new Date())
}

function startPlay() {
  stopPlay()
  if (!autoPlay.value) return
  playTimer = setInterval(() => {
    switchScreen(screenIndex.value + 1)
  }, 5000)
}

function stopPlay() {
  if (playTimer) {
    clearInterval(playTimer)
    playTimer = null
  }
}

function onResize() {
  Object.values(charts).forEach(c => c && c.resize())
}

onMounted(() => {
  tickClock()
  clockTimer = setInterval(tickClock, 1000)
  loadData()
  timer = setInterval(loadData, 60000)
  startPlay()
  window.addEventListener('resize', onResize)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  if (clockTimer) clearInterval(clockTimer)
  stopPlay()
  window.removeEventListener('resize', onResize)
  Object.values(charts).forEach(c => c && c.dispose())
})
</script>

<style scoped>
.dash-screen {
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: #0b1220;
  color: #e2e8f0;
  display: flex;
  flex-direction: column;
  padding: 12px 22px 10px;
  gap: 10px;
  overflow: hidden;
}

.dash-header {
  display: flex;
  align-items: center;
  gap: 16px;
}

.dash-title {
  font-size: 24px;
  font-weight: 700;
  letter-spacing: 2px;
  background: linear-gradient(90deg, #60a5fa, #a78bfa);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.dash-screen-tag {
  font-size: 15px;
  font-weight: 600;
  color: #cbd5e1;
  padding: 3px 14px;
  border: 1px solid #334155;
  border-radius: 20px;
  background: #111a2e;
}

.dash-time {
  font-size: 13px;
  color: #64748b;
}

.dash-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 10px;
}

.kpi-row {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
}

.kpi-card {
  background: #111a2e;
  border: 1px solid #1e293b;
  border-radius: 10px;
  padding: 14px 18px;
}

.kpi-value {
  font-size: 30px;
  font-weight: 700;
  white-space: nowrap;
}

.kpi-label {
  font-size: 13px;
  color: #94a3b8;
  margin-top: 4px;
}

/* 分屏图表区：每屏 3 张大图 */
.screen-area {
  flex: 1;
  min-height: 0;
}

.screen-grid {
  height: 100%;
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
}

.chart-box {
  background: #111a2e;
  border: 1px solid #1e293b;
  border-radius: 10px;
  padding: 10px 14px 6px;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.chart-title {
  font-size: 15px;
  font-weight: 600;
  color: #e2e8f0;
  padding: 4px 4px 8px;
}

.chart-holder {
  flex: 1;
  min-height: 0;
}

.screen-nav {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
}

.screen-dots {
  display: flex;
  gap: 8px;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #334155;
  cursor: pointer;
  transition: background 0.2s;
}

.dot.active {
  background: #3b82f6;
  transform: scale(1.2);
}

.realtime-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.rt-card {
  background: #111a2e;
  border: 1px solid #1e293b;
  border-radius: 10px;
  padding: 10px 16px;
}

.rt-title {
  font-size: 14px;
  font-weight: 600;
  color: #cbd5e1;
  margin-bottom: 4px;
}

.rt-list {
  max-height: 96px;
  overflow: hidden;
}

/* 溢出时缓慢无缝滚动（内容复制两份，translateY(-50%) 循环） */
.rt-list.scrolling .rt-scroll {
  animation: rtScroll 16s linear infinite;
}

.rt-list.scrolling .rt-scroll:hover {
  animation-play-state: paused;
}

@keyframes rtScroll {
  0% { transform: translateY(0); }
  100% { transform: translateY(-50%); }
}

.rt-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 5px 0;
  font-size: 13px;
  border-bottom: 1px solid #1e293b;
}

.rt-msg {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #cbd5e1;
}

.rt-err {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  /* 长错误消息自动换行（最多 2 行省略），避免超长文本撑破大屏卡片边框 */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  word-break: break-all;
  color: #f87171;
}

.rt-time {
  color: #64748b;
  flex-shrink: 0;
}

.rt-empty {
  color: #475569;
  padding: 8px 0;
  font-size: 12px;
}

/* 小屏降级为 3 列 KPI */
@media (max-width: 1400px) {
  .kpi-row {
    grid-template-columns: repeat(3, 1fr);
  }
}
</style>
