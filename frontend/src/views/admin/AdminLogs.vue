<template>
  <div>
    <el-tabs v-model="activeTab" type="border-card">
      <!-- ===== Tab 1：当日日志 ===== -->
      <el-tab-pane label="当日日志" name="today">
        <!-- 当日概览卡 -->
        <div class="card">
          <el-row :gutter="16">
            <el-col :span="6">
              <div class="metric-box">
                <div class="metric-label">今日日志条数</div>
                <div class="metric-value">{{ todayTotal }}</div>
                <div class="metric-sub">{{ todayDate }} 全部级别</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="metric-box">
                <div class="metric-label">今日错误</div>
                <div class="metric-value" style="color: #e8463a;">{{ summary.errors_today ?? 0 }}</div>
                <div class="metric-sub">ERROR（已入库）</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="metric-box">
                <div class="metric-label">今日警告</div>
                <div class="metric-value" style="color: #efaa17;">{{ summary.warnings_today ?? 0 }}</div>
                <div class="metric-sub">WARNING（已入库）</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="metric-box">
                <div class="metric-label">今日入库记录</div>
                <div class="metric-value">{{ summary.today_records ?? 0 }}</div>
                <div class="metric-sub">ERROR + WARNING</div>
              </div>
            </el-col>
          </el-row>
        </div>

        <!-- 当日筛选区 -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">当日日志内容（{{ todayDate }}）</div>
            <div class="flex-center" style="gap:10px;">
              <span class="text-sm" style="color: #9ca3af;">共 {{ todayTotal }} 条</span>
              <span class="text-sm" style="color: #9ca3af;">自动刷新</span>
              <el-switch v-model="autoRefresh" @change="autoRefresh ? startAutoRefresh() : stopAutoRefresh()" />
              <el-button size="small" @click="immediateRefresh">
                <el-icon><Refresh /></el-icon> 刷新
              </el-button>
              <el-button size="small" @click="handleExportToday">
                <el-icon><Download /></el-icon> 导出当日
              </el-button>
            </div>
          </div>
          <div class="flex-center" style="gap:10px; flex-wrap: wrap;">
            <el-select v-model="todayFilter.level" clearable placeholder="日志级别" style="width:120px;" @change="resetToday">
              <el-option label="INFO" value="INFO" />
              <el-option label="WARNING" value="WARNING" />
              <el-option label="ERROR" value="ERROR" />
            </el-select>
            <el-select v-model="todayFilter.module" clearable placeholder="模块" style="width:130px;" @change="resetToday">
              <el-option label="API访问" value="api" />
              <el-option label="错误日志" value="error" />
              <el-option label="系统日志" value="system" />
            </el-select>
            <el-input v-model="todayFilter.keyword" placeholder="关键字搜索" clearable style="width:180px;" @keyup.enter="resetToday" @clear="resetToday" />
            <el-button size="small" type="primary" @click="resetToday">
              <el-icon><Search /></el-icon> 查询
            </el-button>
          </div>
        </div>

        <!-- 当日日志表格 -->
        <div class="card">
          <div class="data-table-wrapper">
            <el-table :data="todayLogs" border v-loading="todayLoading" size="default">
              <el-table-column prop="time" label="时间" width="180" />
              <el-table-column label="级别" width="100">
                <template #default="scope">
                  <el-tag :type="levelTagType(scope.row.level)" size="small">{{ scope.row.level }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="模块" width="110">
                <template #default="scope">
                  {{ moduleLabels[scope.row.module] || scope.row.module }}
                </template>
              </el-table-column>
              <el-table-column label="消息" min-width="400">
                <template #default="scope">
                  <span style="font-family: monospace;">{{ scope.row.message }}</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div class="flex-center" style="justify-content: flex-end; margin-top: 16px;">
            <el-pagination
              v-model:current-page="todayPage"
              :page-size="todayPageSize"
              :total="todayTotal"
              layout="total, prev, pager, next"
              @current-change="loadTodayLogs"
            />
          </div>
        </div>
      </el-tab-pane>

      <!-- ===== Tab 2：历史统计 ===== -->
      <el-tab-pane label="历史统计" name="history">
        <!-- 历史汇总卡 -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">历史汇总（数据库累计）</div>
            <span class="text-sm" style="color: #9ca3af;">当日明细请在"当日日志"查看</span>
          </div>
          <el-row :gutter="16">
            <el-col :span="6">
              <div class="metric-box">
                <div class="metric-label">累计入库记录</div>
                <div class="metric-value">{{ summary.db_records_total ?? 0 }}</div>
                <div class="metric-sub">log_records 全部</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="metric-box">
                <div class="metric-label">历史错误</div>
                <div class="metric-value" style="color: #e8463a;">{{ summary.errors_total ?? 0 }}</div>
                <div class="metric-sub">ERROR 累计</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="metric-box">
                <div class="metric-label">历史警告</div>
                <div class="metric-value" style="color: #efaa17;">{{ summary.warnings_total ?? 0 }}</div>
                <div class="metric-sub">WARNING 累计</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="metric-box">
                <div class="metric-label">日志文件占用</div>
                <div class="metric-value">{{ formatBytes(summary.total_file_bytes) }}</div>
                <div class="metric-sub">当前 + 轮转文件</div>
              </div>
            </el-col>
          </el-row>
        </div>

        <!-- 错误/警告趋势图 -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">错误 / 警告趋势</div>
            <div class="flex-center" style="gap:10px;">
              <el-radio-group v-model="trendRange" @change="loadTrend">
                <el-radio-button value="24h">24小时</el-radio-button>
                <el-radio-button value="7d">7天</el-radio-button>
              </el-radio-group>
            </div>
          </div>
          <div ref="trendChartRef" style="height: 260px;"></div>
        </div>

        <!-- 历史日志查询 -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">历史日志查询</div>
            <div class="flex-center" style="gap:10px;">
              <span class="text-sm" style="color: #9ca3af;">共 {{ historyTotal }} 条</span>
              <el-button size="small" @click="handleExportHistory">
                <el-icon><Download /></el-icon> 导出结果
              </el-button>
            </div>
          </div>
          <div class="flex-center" style="gap:10px; flex-wrap: wrap; margin-bottom: 16px;">
            <el-date-picker
              v-model="historyFilter.date"
              type="date"
              placeholder="选择日期"
              format="YYYY-MM-DD"
              value-format="YYYY-MM-DD"
              clearable
              style="width:150px;"
              @change="resetHistory"
            />
            <el-select v-model="historyFilter.file" clearable placeholder="日志文件（含轮转）" style="width:210px;" @change="resetHistory">
              <el-option v-for="f in fileOptions" :key="f" :label="f" :value="f" />
            </el-select>
            <el-select v-model="historyFilter.level" clearable placeholder="级别" style="width:110px;" @change="resetHistory">
              <el-option label="INFO" value="INFO" />
              <el-option label="WARNING" value="WARNING" />
              <el-option label="ERROR" value="ERROR" />
            </el-select>
            <el-select v-model="historyFilter.module" clearable placeholder="模块" style="width:120px;" @change="resetHistory">
              <el-option label="API访问" value="api" />
              <el-option label="错误日志" value="error" />
              <el-option label="系统日志" value="system" />
            </el-select>
            <el-input v-model="historyFilter.keyword" placeholder="关键字" clearable style="width:160px;" @keyup.enter="resetHistory" @clear="resetHistory" />
            <el-button size="small" type="primary" @click="resetHistory">
              <el-icon><Search /></el-icon> 查询
            </el-button>
          </div>
          <div class="data-table-wrapper">
            <el-table :data="historyLogs" border v-loading="historyLoading" size="default">
              <el-table-column prop="time" label="时间" width="180" />
              <el-table-column label="级别" width="100">
                <template #default="scope">
                  <el-tag :type="levelTagType(scope.row.level)" size="small">{{ scope.row.level }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="模块" width="110">
                <template #default="scope">
                  {{ moduleLabels[scope.row.module] || scope.row.module }}
                </template>
              </el-table-column>
              <el-table-column label="消息" min-width="400">
                <template #default="scope">
                  <span style="font-family: monospace;">{{ scope.row.message }}</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div class="flex-center" style="justify-content: flex-end; margin-top: 16px;">
            <el-pagination
              v-model:current-page="historyPage"
              :page-size="historyPageSize"
              :total="historyTotal"
              layout="total, prev, pager, next"
              @current-change="loadHistoryLogs"
            />
          </div>
        </div>

        <!-- 最近错误列表 -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">最近错误（ERROR）</div>
            <el-button size="small" @click="loadRecentErrors">
              <el-icon><Refresh /></el-icon> 刷新
            </el-button>
          </div>
          <div class="data-table-wrapper">
            <el-table :data="recentErrors" border size="small">
              <el-table-column prop="time" label="时间" width="180" />
              <el-table-column label="模块" width="110">
                <template #default="scope">
                  {{ moduleLabels[scope.row.module] || scope.row.module }}
                </template>
              </el-table-column>
              <el-table-column label="错误消息" min-width="400">
                <template #default="scope">
                  <span style="font-family: monospace; color: #e8463a;">{{ scope.row.message }}</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>

        <!-- 日志文件管理 -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">日志文件管理（含历史轮转）</div>
            <span class="text-sm" style="color: #9ca3af;">轮转文件保留最近 30 天，超过自动删除最旧</span>
          </div>
          <div class="data-table-wrapper">
            <el-table :data="logFiles" border size="default">
              <el-table-column label="模块" width="110">
                <template #default="scope">
                  {{ moduleLabels[scope.row.module] || scope.row.module }}
                </template>
              </el-table-column>
              <el-table-column prop="filename" label="文件名" min-width="220" />
              <el-table-column label="类型" width="90">
                <template #default="scope">
                  <el-tag :type="scope.row.rotated ? 'info' : 'success'" size="small">
                    {{ scope.row.rotated ? '轮转' : '当前' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="大小" width="100">
                <template #default="scope">
                  {{ formatBytes(scope.row.size) }}
                </template>
              </el-table-column>
              <el-table-column prop="modified" label="最后修改" width="180" />
              <el-table-column label="操作" width="100">
                <template #default="scope">
                  <el-button size="small" @click="viewFile(scope.row.filename)">查看</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { Search, Refresh, Download } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { listLogs, listLogFiles, getLogSummary, getLogTrend, exportLogs } from '../../api/admin.js'
import { useAutoRefresh } from '../../composables/useAutoRefresh.js'

const activeTab = ref('today')

// 当日（今日）
const todayLogs = ref([])
const todayLoading = ref(false)
const todayTotal = ref(0)
const todayPage = ref(1)
const todayPageSize = ref(50)
const todayFilter = ref({ level: '', module: '', keyword: '' })
// 今日日期（本地时区，用于当日日志查询与展示）
const todayDate = (() => {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
})()

// 历史
const historyLogs = ref([])
const historyLoading = ref(false)
const historyTotal = ref(0)
const historyPage = ref(1)
const historyPageSize = ref(50)
const historyFilter = ref({ date: '', file: '', level: '', module: '', keyword: '' })

const logFiles = ref([])
const recentErrors = ref([])
const fileOptions = ref([])
const summary = ref({})

// 增量刷新基线（当日）
let todayLastTopTime = ''

// 统计概览
const trendRange = ref('24h')
const trendChartRef = ref(null)
let trendChartInstance = null

const moduleLabels = {
  api: 'API访问',
  error: '错误日志',
  system: '系统日志'
}

// 自动刷新（仅当日 Tab 生效，增量查询）
const { autoRefresh, immediateRefresh, startAutoRefresh, stopAutoRefresh } = useAutoRefresh(() => loadTodayLogs({ incremental: true }))

function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return '-'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(2) + ' MB'
}

function levelTagType(level) {
  if (level === 'ERROR') return 'danger'
  if (level === 'WARNING') return 'warning'
  if (level === 'INFO') return 'success'
  return 'info'
}

// ===== 当日日志 =====
function resetToday() {
  todayPage.value = 1
  loadTodayLogs()
}

async function loadTodayLogs({ incremental = false } = {}) {
  todayLoading.value = true
  try {
    const params = { date: todayDate, page: todayPage.value, page_size: todayPageSize.value }
    if (todayFilter.value.level) params.level = todayFilter.value.level
    if (todayFilter.value.module) params.module = todayFilter.value.module
    if (todayFilter.value.keyword) params.keyword = todayFilter.value.keyword
    if (incremental && todayLastTopTime) params.since = todayLastTopTime

    const res = await listLogs(params)
    if (incremental && res.data.records && res.data.records.length === 0) {
      return
    }
    todayLogs.value = res.data.records || []
    todayTotal.value = res.data.total || 0
    if (todayLogs.value.length) todayLastTopTime = todayLogs.value[0].time
  } catch (e) {
    console.error('获取当日日志失败:', e)
  } finally {
    todayLoading.value = false
  }
}

// ===== 历史日志查询 =====
function resetHistory() {
  historyPage.value = 1
  loadHistoryLogs()
}

async function loadHistoryLogs() {
  historyLoading.value = true
  try {
    const params = { page: historyPage.value, page_size: historyPageSize.value }
    if (historyFilter.value.date) params.date = historyFilter.value.date
    if (historyFilter.value.file) params.file = historyFilter.value.file
    if (historyFilter.value.level) params.level = historyFilter.value.level
    if (historyFilter.value.module) params.module = historyFilter.value.module
    if (historyFilter.value.keyword) params.keyword = historyFilter.value.keyword
    const res = await listLogs(params)
    historyLogs.value = res.data.records || []
    historyTotal.value = res.data.total || 0
  } catch (e) {
    console.error('获取历史日志失败:', e)
  } finally {
    historyLoading.value = false
  }
}

// ===== 概览 / 文件 / 趋势 =====
async function loadSummary() {
  try {
    const res = await getLogSummary()
    summary.value = res.data
  } catch (e) {
    console.error('获取日志概览失败:', e)
  }
}

async function loadFiles() {
  try {
    const res = await listLogFiles()
    logFiles.value = res.data.files || []
    fileOptions.value = logFiles.value.map(f => f.filename)
  } catch (e) {
    console.error('获取日志文件列表失败:', e)
  }
}

async function loadRecentErrors() {
  try {
    const res = await listLogs({ level: 'ERROR', page: 1, page_size: 20 })
    recentErrors.value = res.data.records || []
  } catch (e) {
    console.error('获取最近错误失败:', e)
  }
}

async function loadTrend() {
  try {
    const res = await getLogTrend(trendRange.value)
    renderTrendChart(res.data.trend || [])
  } catch (e) {
    console.error('获取错误趋势失败:', e)
  }
}

function renderTrendChart(trend) {
  const items = Array.isArray(trend) ? trend : []
  if (trendChartRef.value) {
    if (!trendChartInstance) {
      trendChartInstance = echarts.init(trendChartRef.value)
    }
    trendChartInstance.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: '6%', right: '5%', bottom: '8%', top: '10%', containLabel: true },
      xAxis: { type: 'category', data: items.map(d => d.time) },
      yAxis: { type: 'value', name: '条数', nameLocation: 'middle', nameGap: 42, minInterval: 1 },
      legend: { data: ['错误', '警告'], top: 0 },
      series: [
        { name: '错误', type: 'bar', stack: 'log', data: items.map(d => d.errors), itemStyle: { color: '#e8463a' }, barMaxWidth: 16 },
        { name: '警告', type: 'bar', stack: 'log', data: items.map(d => d.warnings), itemStyle: { color: '#efaa17' }, barMaxWidth: 16 }
      ]
    }, true)
  }
}

// 切到历史 Tab 时图表容器可见，需 resize
watch(activeTab, (val) => {
  if (val === 'history') {
    nextTick(() => {
      if (trendChartInstance) trendChartInstance.resize()
    })
  }
})

// 从文件管理查看某文件：切到历史 Tab 设置文件筛选
function viewFile(filename) {
  historyFilter.value.file = filename
  historyFilter.value.date = ''
  historyPage.value = 1
  activeTab.value = 'history'
  loadHistoryLogs()
}

// 导出当日日志
async function handleExportToday() {
  const params = { date: todayDate }
  if (todayFilter.value.level) params.level = todayFilter.value.level
  if (todayFilter.value.module) params.module = todayFilter.value.module
  if (todayFilter.value.keyword) params.keyword = todayFilter.value.keyword
  await doExport(params)
}

// 导出历史查询结果
async function handleExportHistory() {
  const params = {}
  if (historyFilter.value.date) params.date = historyFilter.value.date
  if (historyFilter.value.file) params.file = historyFilter.value.file
  if (historyFilter.value.level) params.level = historyFilter.value.level
  if (historyFilter.value.module) params.module = historyFilter.value.module
  if (historyFilter.value.keyword) params.keyword = historyFilter.value.keyword
  await doExport(params)
}

async function doExport(params) {
  try {
    const res = await exportLogs(params)
    const blob = new Blob([res.data], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `logs_export_${Date.now()}.txt`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('日志导出成功')
  } catch (e) {
    ElMessage.error('导出失败')
  }
}

onMounted(() => {
  loadTodayLogs()
  loadHistoryLogs()
  loadSummary()
  loadFiles()
  loadRecentErrors()
  loadTrend()
})

onUnmounted(() => {
  if (trendChartInstance) {
    trendChartInstance.dispose()
    trendChartInstance = null
  }
})
</script>

<style scoped>
.metric-box {
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
  min-height: 96px;
}
.metric-label {
  font-size: 13px;
  color: #6b7280;
}
.metric-value {
  font-size: 22px;
  font-weight: 600;
  margin-top: 6px;
  color: #1f2937;
}
.metric-sub {
  font-size: 12px;
  color: #9ca3af;
  margin-top: 6px;
}
</style>
