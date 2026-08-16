<template>
  <div>
    <el-tabs v-model="activeTab" type="border-card">
      <!-- Tab 1: 业务任务历史 -->
      <el-tab-pane label="业务任务历史" name="business-tasks">
        <!-- 队列监控卡（2026-08-15 新增）：运行中/排队中/今日任务/今日失败 + Celery 模式 -->
        <div class="metrics-row">
          <div class="metric-card">
            <div class="metric-num">{{ queueStats.running_count }}</div>
            <div class="metric-lab">运行中</div>
          </div>
          <div class="metric-card">
            <div class="metric-num">{{ queueStats.pending_count }}</div>
            <div class="metric-lab">排队中</div>
          </div>
          <div class="metric-card">
            <div class="metric-num">{{ queueStats.today_total }}</div>
            <div class="metric-lab">今日任务</div>
            <div class="metric-sub">
              <span class="sub-ok">成功 {{ queueStats.today_success }}</span>
            </div>
          </div>
          <div class="metric-card">
            <div class="metric-num danger">{{ queueStats.today_failed }}</div>
            <div class="metric-lab">今日失败</div>
            <div class="metric-sub">
              <el-tag size="small" :type="queueStats.mode === 'celery' ? 'success' : 'warning'">
                {{ queueStats.mode === 'celery' ? 'Celery 异步' : '同步降级' }}
              </el-tag>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <div class="card-title">用户端操作历史</div>
            <div class="flex-center" style="gap:10px; flex-wrap:wrap;">
              <!-- 任务类型筛选（特征工程大类走前缀匹配 5 个子类型；pipeline 为 module_source 概念非任务类型，已移除） -->
              <el-select v-model="taskFilter.task_type" clearable placeholder="任务类型" style="width:150px;" @change="loadBusinessTasks">
                <el-option label="数据上传" value="upload" />
                <el-option label="数据治理" value="dataset" />
                <el-option label="数据清洗" value="cleaning" />
                <el-option label="模型训练" value="ml_training" />
                <el-option label="机器学习" value="ml" />
                <el-option label="特征工程" value="feature_engineering" />
                <el-option label="数据挖掘" value="data_mining" />
                <el-option label="数据分析" value="data_analysis" />
                <el-option label="AI分析" value="ai" />
                <el-option label="账号管理" value="user_admin" />
              </el-select>
              <!-- 用户名搜索（替代原用户ID输入，更友好） -->
              <el-input v-model="taskFilter.username" placeholder="用户名搜索" clearable style="width:130px;" @keyup.enter="loadBusinessTasks" @clear="loadBusinessTasks" />
              <!-- 状态筛选：补全 pending/cancelled -->
              <el-select v-model="taskFilter.status" clearable placeholder="状态" style="width:110px;" @change="loadBusinessTasks">
                <el-option label="成功" value="success" />
                <el-option label="失败" value="failed" />
                <el-option label="执行中" value="running" />
                <el-option label="等待中" value="pending" />
                <el-option label="已取消" value="cancelled" />
              </el-select>
              <!-- 失败分类筛选（2026-08-15 新增） -->
              <el-select v-model="taskFilter.failure_category" clearable placeholder="失败分类" style="width:120px;" @change="loadBusinessTasks">
                <el-option label="参数错误" value="param_error" />
                <el-option label="数据问题" value="data_error" />
                <el-option label="系统故障" value="system_error" />
                <el-option label="执行超时" value="timeout" />
                <el-option label="网络错误" value="network_error" />
                <el-option label="未知错误" value="unknown" />
              </el-select>
              <!-- 时间范围筛选（2026-08-15 新增） -->
              <el-select v-model="timePreset" placeholder="时间范围" clearable style="width:110px;" @change="handleTimePresetChange">
                <el-option label="今天" value="today" />
                <el-option label="最近 7 天" value="7d" />
                <el-option label="最近 30 天" value="30d" />
                <el-option label="自定义" value="custom" />
              </el-select>
              <el-date-picker
                v-if="timePreset === 'custom'"
                v-model="dateRange"
                type="datetimerange"
                range-separator="至"
                start-placeholder="开始时间"
                end-placeholder="结束时间"
                value-format="YYYY-MM-DDTHH:mm:ss"
                style="width:300px;"
                @change="loadBusinessTasks"
              />
              <el-button size="small" @click="loadBusinessTasks">
                <el-icon><Search /></el-icon> 查询
              </el-button>
              <!-- 自动刷新开关 -->
              <el-switch :model-value="autoRefresh" @change="toggleAutoRefresh" active-text="自动刷新" />
              <!-- 手动刷新按钮 -->
              <el-button size="small" :loading="isRefreshing" @click="immediateRefresh">
                <el-icon><Refresh /></el-icon> 刷新
              </el-button>
            </div>
          </div>
          <div class="data-table-wrapper">
            <el-table :data="businessTasks" border :row-class-name="rowClassName">
              <el-table-column prop="id" label="ID" width="70" />
              <el-table-column prop="task_type" label="任务类型" width="100" />
              <el-table-column prop="detail" label="操作详情" min-width="280" show-overflow-tooltip />
              <el-table-column label="所属用户" width="90">
                <template #default="scope">
                  {{ scope.row.username || scope.row.user_id }}
                </template>
              </el-table-column>
              <el-table-column label="耗时" width="90">
                <template #default="scope">
                  {{ scope.row.execution_time_ms ? formatDuration(scope.row.execution_time_ms) : '-' }}
                </template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="scope">
                  <el-tag :type="getStatusType(scope.row.status_raw)">
                    {{ scope.row.status }}
                  </el-tag>
                  <div v-if="isRunningTimeout(scope.row)" class="timeout-tip">◷ 运行超时</div>
                </template>
              </el-table-column>
              <el-table-column label="失败分类" width="100">
                <template #default="scope">
                  <el-tag v-if="scope.row.failure_category" size="small" :type="getFailureType(scope.row.failure_category)">
                    {{ scope.row.failure_category_label }}
                  </el-tag>
                  <span v-else>-</span>
                </template>
              </el-table-column>
              <el-table-column label="创建时间" width="160">
                <template #default="scope">
                  {{ formatTime(scope.row.created_at) }}
                </template>
              </el-table-column>
              <el-table-column label="操作" width="130" fixed="right">
                <template #default="scope">
                  <el-button link type="primary" size="small" @click="openDetail(scope.row.id)">详情</el-button>
                  <el-button
                    v-if="['pending', 'running'].includes(scope.row.status_raw)"
                    link type="danger" size="small" @click="handleCancel(scope.row)"
                  >取消</el-button>
                  <el-button
                    v-if="scope.row.status_raw === 'failed'"
                    link type="primary" size="small" @click="handleRetry(scope.row)"
                  >重试</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div class="flex-center" style="justify-content: flex-end; margin-top: 16px; gap: 12px;">
            <el-select v-model="taskPageSize" style="width:100px;" @change="taskPage = 1; loadBusinessTasks()">
              <el-option label="20 条/页" :value="20" />
              <el-option label="50 条/页" :value="50" />
              <el-option label="100 条/页" :value="100" />
            </el-select>
            <el-pagination
              v-model:current-page="taskPage"
              :page-size="taskPageSize"
              :total="taskTotal"
              layout="total, prev, pager, next"
              @current-change="loadBusinessTasks"
            />
          </div>
        </div>
      </el-tab-pane>

      <!-- Tab 2: 任务统计 -->
      <el-tab-pane label="任务统计" name="business-task-stats">
        <!-- 健康指标卡（2026-08-15 新增）：总数/成功率/失败率/平均耗时 -->
        <div class="metrics-row">
          <div class="metric-card">
            <div class="metric-num">{{ statsMetrics.total }}</div>
            <div class="metric-lab">任务总数</div>
          </div>
          <div class="metric-card">
            <div class="metric-num ok">{{ statsMetrics.success_rate != null ? statsMetrics.success_rate + '%' : '-' }}</div>
            <div class="metric-lab">成功率</div>
          </div>
          <div class="metric-card">
            <div class="metric-num danger">{{ statsMetrics.failed_rate != null ? statsMetrics.failed_rate + '%' : '-' }}</div>
            <div class="metric-lab">失败率</div>
          </div>
          <div class="metric-card">
            <div class="metric-num">{{ statsMetrics.avg_time != null ? formatDuration(statsMetrics.avg_time) : '-' }}</div>
            <div class="metric-lab">平均耗时</div>
          </div>
        </div>

        <!-- 状态分布 + 模块失败 TOP（2026-08-15 新增） -->
        <div class="stats-row">
          <div class="card">
            <div class="card-title">任务状态分布</div>
            <div ref="statusChartRef" style="height: 260px;"></div>
          </div>
          <div class="card">
            <div class="card-title">按模块失败 TOP</div>
            <div ref="failedChartRef" style="height: 260px;"></div>
          </div>
        </div>

        <!-- 原有统计图：按模块/按用户/按日 -->
        <div class="card">
          <div class="card-title">按模块统计</div>
          <div ref="moduleChartRef" style="height: 300px;"></div>
        </div>
        <div class="card">
          <div class="card-title">按用户统计</div>
          <div ref="userChartRef" style="height: 300px;"></div>
        </div>
        <div class="card">
          <div class="card-title">按日统计（任务数与成功率，最近 30 天）</div>
          <div ref="dateChartRef" style="height: 300px;"></div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 任务详情抽屉（2026-08-15 新增） -->
    <el-drawer v-model="detailVisible" title="任务详情" size="560px" :destroy-on-close="false">
      <div v-if="detail" class="detail-body">
        <div class="detail-head">
          <el-tag :type="getStatusType(detail.status_raw)">{{ detail.status }}</el-tag>
          <el-tag v-if="detail.failure_category" size="small" :type="getFailureType(detail.failure_category)">
            {{ detail.failure_category_label }}
          </el-tag>
          <el-tag size="small" type="info">{{ detail.task_type }}</el-tag>
          <el-tag v-if="detail.is_remote" size="small" type="warning">远程</el-tag>
        </div>

        <div class="detail-section">
          <div class="detail-section-title">基础信息</div>
          <el-descriptions :column="2" size="small" border>
            <el-descriptions-item label="任务 ID">{{ detail.id }}</el-descriptions-item>
            <el-descriptions-item label="发起用户">{{ detail.username || detail.user_id }}</el-descriptions-item>
            <el-descriptions-item label="数据来源">{{ detail.is_remote ? '远程数据库' : '本地文件' }}</el-descriptions-item>
            <el-descriptions-item label="关联数据集">{{ detail.dataset_id ? '#' + detail.dataset_id : '-' }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ formatTime(detail.created_at) }}</el-descriptions-item>
            <el-descriptions-item label="完成时间">{{ formatTime(detail.completed_at) }}</el-descriptions-item>
            <el-descriptions-item label="执行耗时">{{ detail.execution_time_ms ? formatDuration(detail.execution_time_ms) : '-' }}</el-descriptions-item>
            <el-descriptions-item label="Celery 任务">{{ detail.celery_task_id || '-' }}</el-descriptions-item>
          </el-descriptions>
        </div>

        <!-- 管理员取消标注 -->
        <el-alert
          v-if="detail.result_summary && detail.result_summary.admin_cancel"
          type="warning"
          :closable="false"
          show-icon
          style="margin-bottom: 16px;"
        >
          <template #title>
            管理员取消：{{ detail.result_summary.admin_cancel.admin }}（{{ formatTime(detail.result_summary.admin_cancel.at) }}）
          </template>
          {{ detail.result_summary.admin_cancel.note }}
        </el-alert>

        <!-- 失败原因 -->
        <div v-if="detail.status_raw === 'failed' && detail.error_message" class="detail-section">
          <div class="detail-section-title" style="color: var(--el-color-danger);">失败原因</div>
          <pre class="detail-error">{{ detail.error_message }}</pre>
        </div>

        <!-- 执行进度 -->
        <div v-if="progressList.length" class="detail-section">
          <div class="detail-section-title">执行进度</div>
          <el-progress
            :percentage="detail.result_summary.current_progress || 100"
            :status="detail.status_raw === 'failed' ? 'exception' : 'success'"
          />
          <div class="progress-msg">{{ detail.result_summary.current_message || detail.result_summary.current_stage }}</div>
          <el-timeline style="margin-top: 12px;">
            <el-timeline-item
              v-for="(p, idx) in progressList" :key="idx"
              :timestamp="formatTime(p.timestamp)"
              :type="detail.status_raw === 'failed' && idx === progressList.length - 1 ? 'danger' : 'primary'"
            >
              {{ p.stage }}（{{ p.progress }}%）{{ p.message ? '：' + p.message : '' }}
            </el-timeline-item>
          </el-timeline>
        </div>

        <!-- 重试历史 -->
        <div v-if="detail.result_summary && detail.result_summary.retry_history && detail.result_summary.retry_history.length" class="detail-section">
          <div class="detail-section-title">重试历史</div>
          <el-timeline>
            <el-timeline-item
              v-for="(r, idx) in detail.result_summary.retry_history" :key="idx"
              :timestamp="formatTime(r.retry_time)"
              type="primary"
            >
              由{{ r.operator === 'admin' ? '管理员 ' + (r.operator_name || '') : '用户' }}重试
              <template v-if="r.previous_error">（原错误：{{ r.previous_error }}）</template>
            </el-timeline-item>
          </el-timeline>
        </div>

        <!-- 执行参数 -->
        <div class="detail-section">
          <div class="detail-section-title">执行参数</div>
          <pre class="detail-json">{{ JSON.stringify(detail.params, null, 2) }}</pre>
        </div>
      </div>
      <template v-else>
        <el-skeleton :rows="8" animated />
      </template>
      <template #footer>
        <div class="detail-footer">
          <el-button @click="detailVisible = false">关闭</el-button>
          <el-button
            v-if="detail && ['pending', 'running'].includes(detail.status_raw)"
            type="danger" @click="handleCancel(detail)"
          >取消任务</el-button>
          <el-button
            v-if="detail && detail.status_raw === 'failed'"
            type="primary" @click="handleRetry(detail)"
          >重试任务</el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import {
  getTaskStats,
  listBusinessTasks,
  getBusinessTaskStats,
  getTaskDetail,
  adminCancelTask,
  adminRetryTask
} from '../../api/admin.js'
import { useAutoRefresh } from '../../composables/useAutoRefresh.js'

// 当前激活的 Tab
const activeTab = ref('business-tasks')

// ===== 队列监控卡（getTaskStats 增强接口）=====
const queueStats = ref({
  running_count: 0,
  pending_count: 0,
  today_total: 0,
  today_success: 0,
  today_failed: 0,
  mode: 'celery'
})

// ===== 业务任务历史 Tab =====
const businessTasks = ref([])
const taskPage = ref(1)
const taskPageSize = ref(50)
const taskTotal = ref(0)
const taskFilter = ref({
  task_type: '',
  username: '',
  status: '',
  failure_category: ''
})
// 时间范围：预置（今天/7天/30天/自定义）+ 自定义区间
const timePreset = ref('')
const dateRange = ref([])

// ===== 任务详情抽屉 =====
const detailVisible = ref(false)
const detail = ref(null)

// ===== 任务统计 Tab =====
const taskStats = ref({
  by_module: [],
  by_user: [],
  by_date: [],
  by_status: [],
  by_module_failed: []
})
// 统计 Tab 指标卡（成功率/平均耗时来自 getTaskStats，总数来自 by_status 求和）
const statsMetrics = ref({ total: 0, success_rate: null, failed_rate: null, avg_time: null })

// 图表 DOM 容器引用
const moduleChartRef = ref(null)
const userChartRef = ref(null)
const dateChartRef = ref(null)
const statusChartRef = ref(null)
const failedChartRef = ref(null)

// ECharts 实例
let moduleChartInstance = null
let userChartInstance = null
let dateChartInstance = null
let statusChartInstance = null
let failedChartInstance = null

// 格式化后端返回的 ISO 时间为中文可读格式
function formatTime(dateStr) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  if (isNaN(date.getTime())) return dateStr
  return date.toLocaleString('zh-CN', { hour12: false })
}

// 耗时展示：<1s 显示 ms，否则显示 秒
function formatDuration(ms) {
  if (ms == null) return '-'
  if (ms < 1000) return ms + 'ms'
  return (ms / 1000).toFixed(1) + 's'
}

// 根据任务状态返回 el-tag 类型
function getStatusType(status) {
  const map = {
    success: 'success',
    running: 'warning',
    pending: 'info',
    failed: 'danger',
    cancelled: 'info',
    error: 'danger'
  }
  return map[status] || 'info'
}

// 失败分类 → el-tag 颜色（param/data 需用户介入用 danger；system/timeout/network 可重试用 warning）
function getFailureType(category) {
  const retryable = ['system_error', 'timeout', 'network_error']
  if (retryable.includes(category)) return 'warning'
  return 'danger'
}

// 运行超时标红：running 状态且创建超过 40 分钟（created_at 为带时区 ISO，Date.parse 得到绝对时间戳，可安全与本地时间比较）
const RUNNING_TIMEOUT_MS = 40 * 60 * 1000
function isRunningTimeout(row) {
  if (!row || row.status_raw !== 'running' || !row.created_at) return false
  const created = new Date(row.created_at).getTime()
  return Date.now() - created > RUNNING_TIMEOUT_MS
}

// 表格行样式：超时任务标红
function rowClassName({ row }) {
  return isRunningTimeout(row) ? 'row-hot' : ''
}

// 构造业务任务查询参数（过滤空值）
function buildTaskParams() {
  const params = {
    page: taskPage.value,
    page_size: taskPageSize.value
  }
  if (taskFilter.value.task_type) {
    if (taskFilter.value.task_type === 'feature_engineering') {
      // 特征工程大类：task_type 无基础类型记录（均为 5 个子类型），走前缀匹配
      params.task_type_prefix = 'feature_engineering'
    } else {
      params.task_type = taskFilter.value.task_type
    }
  }
  if (taskFilter.value.username) params.username = taskFilter.value.username
  if (taskFilter.value.status) params.status = taskFilter.value.status
  if (taskFilter.value.failure_category) params.failure_category = taskFilter.value.failure_category

  // 时间范围 → date_from/date_to
  const now = new Date()
  if (timePreset.value === 'today') {
    const start = new Date(now)
    start.setHours(0, 0, 0, 0)
    params.date_from = start.toISOString()
  } else if (timePreset.value === '7d') {
    params.date_from = new Date(now.getTime() - 7 * 24 * 3600 * 1000).toISOString()
  } else if (timePreset.value === '30d') {
    params.date_from = new Date(now.getTime() - 30 * 24 * 3600 * 1000).toISOString()
  } else if (timePreset.value === 'custom' && dateRange.value && dateRange.value.length === 2) {
    params.date_from = dateRange.value[0]
    params.date_to = dateRange.value[1]
  }
  return params
}

// 时间预置切换：自定义时显示日期选择器，其余直接刷新
function handleTimePresetChange(val) {
  if (val !== 'custom') {
    dateRange.value = []
    loadBusinessTasks()
  }
}

async function loadBusinessTasks() {
  try {
    const res = await listBusinessTasks(buildTaskParams())
    businessTasks.value = res.data.tasks || []
    taskTotal.value = res.data.total || 0
  } catch (e) {
    console.error('获取业务任务历史失败:', e)
  }
}

async function loadQueueStats() {
  try {
    const res = await getTaskStats()
    queueStats.value = {
      running_count: res.data.running_count || 0,
      pending_count: res.data.pending_count || 0,
      today_total: res.data.today_total || 0,
      today_success: res.data.today_success || 0,
      today_failed: res.data.today_failed || 0,
      mode: res.data.mode || 'sync'
    }
    // 统计 Tab 指标卡共用成功率/平均耗时
    statsMetrics.value.success_rate = res.data.success_rate != null ? res.data.success_rate : null
    statsMetrics.value.avg_time = res.data.avg_execution_time_ms != null ? res.data.avg_execution_time_ms : null
  } catch (e) {
    console.error('获取任务队列统计失败:', e)
  }
}

async function loadBusinessTaskStats() {
  try {
    const res = await getBusinessTaskStats()
    taskStats.value = {
      by_module: res.data.by_module || [],
      by_user: res.data.by_user || [],
      by_date: res.data.by_date || [],
      by_status: res.data.by_status || [],
      by_module_failed: res.data.by_module_failed || []
    }
    // 计算统计 Tab 指标：总数/失败率
    const total = (taskStats.value.by_status || []).reduce((s, i) => s + (i.count || 0), 0)
    statsMetrics.value.total = total
    const failed = (taskStats.value.by_status || []).find(i => i.status_raw === 'failed')
    if (statsMetrics.value.success_rate != null) {
      statsMetrics.value.failed_rate = Number((100 - statsMetrics.value.success_rate).toFixed(1))
    } else if (total > 0) {
      statsMetrics.value.failed_rate = failed ? Number(((failed.count / total) * 100).toFixed(1)) : 0
    }
  } catch (e) {
    console.error('获取业务任务统计失败:', e)
  }
}

// 一次性加载任务历史、队列监控、统计，供自动刷新使用
async function loadAll() {
  await Promise.all([loadBusinessTasks(), loadQueueStats(), loadBusinessTaskStats()])
}

// 自动刷新：30 秒轮询
const { autoRefresh, isRefreshing, immediateRefresh, toggleAutoRefresh } = useAutoRefresh(loadAll)

// ===== 任务详情抽屉 =====
async function openDetail(recordId) {
  detailVisible.value = true
  detail.value = null
  try {
    const res = await getTaskDetail(recordId)
    detail.value = res.data
  } catch (e) {
    ElMessage.error('获取任务详情失败：' + (e.response?.data?.detail || e.message))
  }
}

// 执行进度列表（供详情抽屉渲染）
const progressList = ref([])
watch(detail, (val) => {
  progressList.value = []
  if (val && val.result_summary && Array.isArray(val.result_summary.progress_history)) {
    progressList.value = val.result_summary.progress_history
  }
})

// 取消任务（管理端）
async function handleCancel(row) {
  try {
    await ElMessageBox.confirm(
      `确定取消任务 #${row.id}（${row.task_type}）吗？正在进行的计算将中止，操作将记录到该任务详情。`,
      '取消任务',
      { confirmButtonText: '确定取消', cancelButtonText: '再想想', type: 'warning' }
    )
    const res = await adminCancelTask(row.id)
    if (res.data.status === 'success') {
      ElMessage.success(res.data.message || '任务已取消')
      // 详情抽屉与列表同步刷新
      loadBusinessTasks()
      if (detailVisible.value && detail.value && detail.value.id === row.id) {
        openDetail(row.id)
      }
    } else {
      ElMessage.error(res.data.message || '取消失败')
    }
  } catch (e) {
    if (e === 'cancel' || e === 'close') return // 用户取消确认弹窗
    ElMessage.error('取消失败：' + (e.response?.data?.detail || e.message))
  }
}

// 重试任务（管理端）
async function handleRetry(row) {
  try {
    await ElMessageBox.confirm(
      `确定重试任务 #${row.id}（${row.task_type}）吗？将重新执行该任务的参数配置。`,
      '重试任务',
      { confirmButtonText: '确定重试', cancelButtonText: '再想想', type: 'warning' }
    )
    const res = await adminRetryTask(row.id)
    if (res.data.status === 'error') {
      ElMessage.error(res.data.message || '重试失败')
      return
    }
    ElMessage.success(res.data.message || '任务已重新提交')
    // 重试后进入运行/排队，刷新列表；详情抽屉同步
    loadBusinessTasks()
    if (detailVisible.value && detail.value && detail.value.id === row.id) {
      openDetail(row.id)
    }
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error('重试失败：' + (e.response?.data?.detail || e.message))
  }
}

// ===== 任务统计图表渲染 =====

// 将后端日期（如 2026-08-01 或 2026-08-01T00:00:00）格式化为 MM-DD
function formatShortDate(dateStr) {
  if (!dateStr) return ''
  const parts = String(dateStr).slice(0, 10).split('-')
  if (parts.length === 3) {
    return `${parts[1]}-${parts[2]}`
  }
  return dateStr
}

// 按模块统计：横向柱状图
function renderModuleChart(data) {
  if (!moduleChartRef.value) return
  if (!moduleChartInstance) {
    moduleChartInstance = echarts.init(moduleChartRef.value)
  }
  const items = Array.isArray(data) ? data : []
  moduleChartInstance.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '8%', bottom: '3%', top: '10%', containLabel: true },
    xAxis: { type: 'value', name: '任务数' },
    yAxis: {
      type: 'category',
      data: items.map(d => d.task_type || d.module_source || '-'),
      axisLabel: { interval: 0 }
    },
    series: [{
      name: '任务数',
      type: 'bar',
      data: items.map(d => d.count || 0),
      itemStyle: { color: '#409EFF' }
    }]
  }, true)
}

// 按用户统计：纵向柱状图
function renderUserChart(data) {
  if (!userChartRef.value) return
  if (!userChartInstance) {
    userChartInstance = echarts.init(userChartRef.value)
  }
  const items = Array.isArray(data) ? data : []
  userChartInstance.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '5%', bottom: '15%', top: '10%', containLabel: true },
    xAxis: {
      type: 'category',
      data: items.map(d => d.username || d.user_id || '-'),
      axisLabel: { interval: 0, rotate: items.length > 6 ? 30 : 0 }
    },
    yAxis: { type: 'value', name: '操作次数' },
    series: [{
      name: '操作次数',
      type: 'bar',
      data: items.map(d => d.count || 0),
      itemStyle: { color: '#67C23A' }
    }]
  }, true)
}

// 按日统计：任务数折线 + 成功率折线（双轴，最近 30 天）
function renderDateChart(data) {
  if (!dateChartRef.value) return
  if (!dateChartInstance) {
    dateChartInstance = echarts.init(dateChartRef.value)
  }
  const items = Array.isArray(data) ? data : []
  dateChartInstance.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['任务数', '成功率(%)'], top: 0 },
    grid: { left: '3%', right: '5%', bottom: '8%', top: '12%', containLabel: true },
    xAxis: {
      type: 'category',
      data: items.map(d => formatShortDate(d.date)),
      axisLabel: { interval: 'auto' }
    },
    yAxis: [
      { type: 'value', name: '任务数' },
      { type: 'value', name: '%', max: 100, splitLine: { show: false } },
    ],
    series: [
      {
        name: '任务数',
        type: 'line',
        data: items.map(d => d.count || 0),
        smooth: true,
        itemStyle: { color: '#E6A23C' },
        areaStyle: { opacity: 0.2 }
      },
      {
        name: '成功率(%)',
        type: 'line',
        yAxisIndex: 1,
        data: items.map(d => (d.success_rate == null ? null : d.success_rate)),
        smooth: true,
        itemStyle: { color: '#1DC981' }
      }
    ]
  }, true)
}

// 状态分布：环形图（成功/执行中/等待中/失败/已取消）
const STATUS_COLORS = {
  success: '#1DC981',
  running: '#EFAA17',
  pending: '#A9AEFF',
  failed: '#E8463A',
  cancelled: '#D3D4DA'
}
function renderStatusChart(data) {
  if (!statusChartRef.value) return
  if (!statusChartInstance) {
    statusChartInstance = echarts.init(statusChartRef.value)
  }
  const items = Array.isArray(data) ? data : []
  statusChartInstance.setOption({
    tooltip: { trigger: 'item', formatter: '{b}：{c}（{d}%）' },
    legend: { bottom: 0, textStyle: { fontSize: 12 } },
    series: [{
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['50%', '45%'],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 4, borderColor: 'transparent' },
      label: { show: false },
      emphasis: { label: { show: true, fontWeight: 'bold' } },
      data: items.map(i => ({
        name: i.status,
        value: i.count || 0,
        itemStyle: { color: STATUS_COLORS[i.status_raw] || '#D3D4DA' }
      }))
    }]
  }, true)
}

// 按模块失败 TOP：横向条形图（前 5，失败为风险编码用红色系）
function renderFailedChart(data) {
  if (!failedChartRef.value) return
  if (!failedChartInstance) {
    failedChartInstance = echarts.init(failedChartRef.value)
  }
  const items = (Array.isArray(data) ? data : []).slice(0, 5)
  failedChartInstance.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '8%', bottom: '3%', top: '10%', containLabel: true },
    xAxis: { type: 'value', name: '失败次数' },
    yAxis: {
      type: 'category',
      data: items.map(d => d.task_type || '-'),
      axisLabel: { interval: 0 }
    },
    series: [{
      name: '失败次数',
      type: 'bar',
      data: items.map(d => d.count || 0),
      itemStyle: { color: '#E8463A' }
    }]
  }, true)
}

// 一次性渲染全部统计图表
function renderAllCharts() {
  if (!taskStats.value) return
  renderModuleChart(taskStats.value.by_module)
  renderUserChart(taskStats.value.by_user)
  renderDateChart(taskStats.value.by_date)
  renderStatusChart(taskStats.value.by_status)
  renderFailedChart(taskStats.value.by_module_failed)
}

// 重绘图表尺寸（Tab 从隐藏切到可见时恢复）
function resizeAllCharts() {
  const instances = [moduleChartInstance, userChartInstance, dateChartInstance, statusChartInstance, failedChartInstance]
  instances.forEach(inst => inst && inst.resize())
}

// 监听统计数据变化，重新渲染图表
watch(taskStats, (newVal) => {
  if (newVal) {
    nextTick(() => renderAllCharts())
  }
}, { deep: true })

// 监听 Tab 切换：切到统计时渲染并 resize
watch(activeTab, (newTab) => {
  if (newTab === 'business-task-stats') {
    nextTick(() => {
      renderAllCharts()
      resizeAllCharts()
    })
  }
})

onMounted(() => {
  // 默认加载任务历史、队列监控和统计
  loadBusinessTasks()
  loadQueueStats()
  loadBusinessTaskStats()
})

onUnmounted(() => {
  // 清理 ECharts 实例，避免内存泄漏
  const instances = [moduleChartInstance, userChartInstance, dateChartInstance, statusChartInstance, failedChartInstance]
  instances.forEach((inst, idx) => {
    if (inst) {
      inst.dispose()
      instances[idx] = null
    }
  })
})
</script>

<style scoped>
/* 队列监控/统计指标卡 */
.metrics-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}
.metric-card {
  background: var(--surface, #fff);
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.metric-num {
  font-size: 24px;
  font-weight: 600;
  line-height: 32px;
  font-family: 'Inter', system-ui, sans-serif;
}
.metric-num.ok { color: var(--el-color-success); }
.metric-num.danger { color: var(--el-color-danger); }
.metric-lab {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.metric-sub {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.sub-ok { color: var(--el-color-success); }

/* 统计 Tab 双图并排 */
.stats-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}
@media (max-width: 1200px) {
  .stats-row { grid-template-columns: 1fr; }
  .metrics-row { grid-template-columns: repeat(2, 1fr); }
}

/* 卡片样式（沿用管理端风格） */
.card {
  background: var(--surface, #fff);
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
}
.flex-center {
  display: flex;
  align-items: center;
}
.data-table-wrapper {
  overflow-x: auto;
}

/* 运行超时标红 */
:deep(.el-table .row-hot) {
  --el-table-tr-bg-color: rgba(232, 70, 58, 0.05);
}
.timeout-tip {
  margin-top: 2px;
  color: var(--el-color-danger);
  font-size: 12px;
}

/* 详情抽屉 */
.detail-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.detail-section {
  margin-bottom: 16px;
}
.detail-section-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 8px;
}
.detail-error {
  background: rgba(232, 70, 58, 0.06);
  border: 1px solid var(--el-color-danger-light-5);
  border-radius: 6px;
  padding: 10px 12px;
  margin: 0;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--el-text-color-primary);
}
.detail-json {
  background: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 10px 12px;
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  max-height: 300px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
.progress-msg {
  margin-top: 8px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.detail-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
