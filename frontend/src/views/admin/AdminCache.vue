<template>
  <div>
    <el-tabs v-model="activeTab" type="border-card">
      <!-- ===== Tab 1：实时缓存 ===== -->
      <el-tab-pane label="实时缓存" name="live">
        <!-- 指标卡：缓存后端 / 键总数 / 内存占用 / 应用命中率 -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">缓存概览</div>
            <el-button size="small" type="danger" @click="handleClearCache">
              <el-icon><Delete /></el-icon> 清空缓存
            </el-button>
          </div>
          <el-row :gutter="16">
            <el-col :span="6">
              <div class="metric-box">
                <div class="metric-label">缓存后端</div>
                <div style="margin-top: 8px;">
                  <el-tag :type="stats.redis_available ? 'success' : 'warning'">
                    {{ stats.redis_available ? 'Redis' : '内存缓存' }}
                  </el-tag>
                </div>
                <div class="metric-sub">{{ stats.redis_available ? 'Redis 缓存已启用' : '已降级为内存缓存' }}</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="metric-box">
                <div class="metric-label">键总数（应用）</div>
                <div class="metric-value">{{ stats.total_keys ?? stats.memory_cache_size ?? 0 }}</div>
                <div class="metric-sub">{{ stats.redis_available ? '仅统计 data-insight:* 键' : '内存缓存键数' }}</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="metric-box">
                <div class="metric-label">内存占用</div>
                <div class="metric-value">{{ formatBytes(stats.memory_bytes) }}</div>
                <div class="metric-sub">{{ stats.redis_available ? 'Redis 实例 used_memory' : '内存缓存估算值' }}</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="metric-box">
                <div class="metric-label">应用命中率</div>
                <div class="metric-value" :style="hitRateColor">
                  {{ stats.hit_rate != null ? stats.hit_rate + '%' : '样本不足' }}
                </div>
                <div class="metric-sub">进程内埋点采样（{{ stats.hits || 0 }} 命中 / {{ stats.misses || 0 }} 未命中）</div>
              </div>
            </el-col>
          </el-row>
        </div>

        <!-- 按业务分类清理：后端全量聚合统计 -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">按业务分类清理</div>
            <span class="text-sm" style="color: #9ca3af;">实时数据 · 共 {{ categoryTotal }} 键</span>
          </div>
          <el-row :gutter="16">
            <el-col :span="8" v-for="cat in categoryStats" :key="cat.category" style="margin-bottom: 16px;">
              <div class="category-box">
                <div class="flex-center" style="justify-content: space-between; margin-bottom: 8px;">
                  <span class="category-name">{{ cat.category }}</span>
                  <span class="category-count">{{ cat.count }}</span>
                </div>
                <el-progress
                  :percentage="cat.ratio"
                  :stroke-width="6"
                  :show-text="false"
                  color="#409EFF"
                  style="margin-bottom: 10px;"
                />
                <div class="flex-center" style="justify-content: space-between;">
                  <span class="text-sm" style="color: #9ca3af;">占比 {{ cat.ratio }}%</span>
                  <template v-if="cat.count">
                    <el-button size="small" type="danger" plain @click="handleClearCategory(cat.category)">
                      清理该分类
                    </el-button>
                  </template>
                  <span v-else class="text-sm" style="color: #c0c4cc;">暂无键</span>
                </div>
              </div>
            </el-col>
          </el-row>
        </div>

        <!-- 缓存键列表 -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">缓存键列表</div>
            <div class="flex-center" style="gap:10px; flex-wrap:wrap;">
              <el-input v-model="searchPrefix" placeholder="键前缀过滤" clearable style="width:200px;" />
              <el-select v-model="filterCategory" clearable placeholder="按分类筛选" style="width:160px;">
                <el-option
                  v-for="cat in categoryOptions"
                  :key="cat"
                  :label="cat"
                  :value="cat"
                />
              </el-select>
              <el-button size="small" @click="loadCacheKeys">
                <el-icon><Search /></el-icon> 查询
              </el-button>
              <el-button size="small" type="danger" plain :disabled="!selectedKeys.length" @click="handleBatchDelete">
                批量删除 ({{ selectedKeys.length }})
              </el-button>
            </div>
          </div>
          <div class="data-table-wrapper">
            <el-table
              :data="filteredCacheKeys"
              border
              @selection-change="handleSelectionChange"
            >
              <el-table-column type="selection" width="45" />
              <el-table-column prop="key" label="键名" min-width="300" />
              <el-table-column prop="category" label="分类" width="110" />
              <el-table-column prop="type" label="类型" width="70" />
              <el-table-column prop="ttl" label="TTL(秒)" width="90">
                <template #default="scope">
                  <span :class="scope.row.ttl > 0 ? '' : 'text-muted'">
                    {{ scope.row.ttl > 0 ? scope.row.ttl : '永久' }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="大小" width="90">
                <template #default="scope">
                  {{ formatBytes(scope.row.size_bytes) }}
                </template>
              </el-table-column>
              <el-table-column label="操作" width="130">
                <template #default="scope">
                  <el-button size="small" @click="viewKeyDetail(scope.row.key)">查看</el-button>
                  <el-button size="small" type="danger" @click="deleteKey(scope.row.key)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div class="flex-center" style="justify-content: flex-end; margin-top: 16px;">
            <el-pagination
              v-model:current-page="page"
              :page-size="pageSize"
              :total="total"
              layout="total, prev, pager, next"
              @current-change="loadCacheKeys"
            />
          </div>
        </div>
      </el-tab-pane>

      <!-- ===== Tab 2：历史统计 ===== -->
      <el-tab-pane label="历史统计" name="history">
        <!-- 汇总指标卡：来自 cache_stats_hourly 持久化表 -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">历史汇总</div>
            <div class="flex-center" style="gap:10px;">
              <el-radio-group v-model="timeRange" @change="loadHitRate">
                <el-radio-button value="24h">24小时</el-radio-button>
                <el-radio-button value="7d">7天</el-radio-button>
                <el-radio-button value="30d">30天</el-radio-button>
              </el-radio-group>
              <span class="text-sm" style="color: #9ca3af;">自动刷新</span>
              <el-switch v-model="autoRefresh" @change="autoRefresh ? startAutoRefresh() : stopAutoRefresh()" />
              <el-button size="small" @click="immediateRefresh">
                <el-icon><Refresh /></el-icon> 刷新
              </el-button>
              <el-button size="small" type="danger" plain @click="openDeleteHistoryDialog">
                <el-icon><Delete /></el-icon> 删除历史
              </el-button>
            </div>
          </div>
          <el-row :gutter="16">
            <el-col :span="6">
              <div class="metric-box">
                <div class="metric-label">累计请求次数</div>
                <div class="metric-value">{{ summary.total_requests ?? 0 }}</div>
                <div class="metric-sub">范围内 命中 + 未命中</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="metric-box">
                <div class="metric-label">平均命中率</div>
                <div class="metric-value" :style="summary.avg_hit_rate > 80 ? { color: '#1dc981' } : {}">
                  {{ summary.avg_hit_rate != null ? summary.avg_hit_rate + '%' : '样本不足' }}
                </div>
                <div class="metric-sub">加权平均（总量口径）</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="metric-box">
                <div class="metric-label">键数峰值</div>
                <div class="metric-value">{{ summary.peak_keys ?? 0 }}</div>
                <div class="metric-sub">范围内单小时最多键</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div class="metric-box">
                <div class="metric-label">数据起始</div>
                <div class="metric-value" style="font-size: 15px;">{{ summary.data_start || '-' }}</div>
                <div class="metric-sub">cache_stats_hourly 最早记录</div>
              </div>
            </el-col>
          </el-row>
        </div>

        <!-- 三张趋势图 -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">缓存趋势分析</div>
            <el-tag :type="hitRateData.current && hitRateData.current.hit_rate != null && hitRateData.current.hit_rate > 80 ? 'success' : 'warning'">
              当前命中率: {{ hitRateData.current && hitRateData.current.hit_rate != null ? hitRateData.current.hit_rate + '%' : '样本不足' }}
            </el-tag>
          </div>
          <div ref="hitRateChartRef" style="height: 230px;"></div>
          <el-row :gutter="16" style="margin-top: 16px;">
            <el-col :span="12">
              <div class="chart-subtitle">请求量趋势（命中 / 未命中）</div>
              <div ref="reqChartRef" style="height: 200px;"></div>
            </el-col>
            <el-col :span="12">
              <div class="chart-subtitle">缓存键数量趋势</div>
              <div ref="keysChartRef" style="height: 200px;"></div>
            </el-col>
          </el-row>
          <div class="flex-center" style="margin-top: 16px;">
            <span class="text-sm" style="color: #9ca3af;">
              数据来源：{{ hitRateData.source === 'app' ? '应用级埋点 · cache_stats_hourly 持久化表' : '内存缓存' }}
            </span>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="detailVisible" title="缓存键详情" width="600px">
      <div v-if="keyDetail" style="word-break: break-all;">
        <div style="margin-bottom: 16px;">
          <span style="font-weight: 600;">键名：</span>{{ keyDetail.key }}
        </div>
        <div style="margin-bottom: 16px;">
          <span style="font-weight: 600;">值：</span>
          <pre style="background: #f4f6f9; padding: 12px; border-radius: 6px; max-height: 300px; overflow: auto;">{{ JSON.stringify(keyDetail.value, null, 2) }}</pre>
        </div>
      </div>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 删除历史统计弹窗：清空全部 / 按时间范围删除 -->
    <el-dialog v-model="deleteHistoryVisible" title="删除历史统计" width="520px">
      <el-radio-group v-model="deleteHistoryMode">
        <el-radio value="all">清空全部历史统计（cache_stats_hourly 表）</el-radio>
        <el-radio value="range">按时间范围删除</el-radio>
      </el-radio-group>
      <div v-if="deleteHistoryMode === 'range'" style="margin-top: 16px;">
        <el-date-picker
          v-model="deleteHistoryRange"
          type="datetimerange"
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          format="YYYY-MM-DD HH"
          value-format="YYYYMMDDHH"
          style="width: 100%;"
        />
        <div class="text-sm" style="color: #9ca3af; margin-top: 6px;">
          将删除该时间范围内的小时统计记录，当前累计请求/命中率/键数峰值将随之减少。
        </div>
      </div>
      <template #footer>
        <el-button @click="deleteHistoryVisible = false">取消</el-button>
        <el-button type="danger" @click="confirmDeleteHistory">确定删除</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed, nextTick, watch } from 'vue'
import { Delete, Search, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts'
import {
  getCacheStats,
  listCacheKeys,
  getCacheKeyDetail,
  deleteCacheKey,
  clearAllCache,
  getCacheHitRate,
  getCacheCategoryStats,
  clearCacheCategory,
  deleteCacheHistory
} from '../../api/admin.js'
import { useAutoRefresh } from '../../composables/useAutoRefresh.js'

const stats = ref({})
const cacheKeys = ref([])
const searchPrefix = ref('')
const page = ref(1)
const pageSize = ref(100)
const total = ref(0)
const detailVisible = ref(false)
const keyDetail = ref(null)

// 命中率趋势（三图：命中率 / 请求量 / 键数量）
const hitRateData = ref({})
const summary = ref({})
const timeRange = ref('24h')
const activeTab = ref('live')
const hitRateChartRef = ref(null)
const reqChartRef = ref(null)
const keysChartRef = ref(null)
let hitRateChartInstance = null
let reqChartInstance = null
let keysChartInstance = null

// 自动刷新
const { autoRefresh, immediateRefresh, startAutoRefresh, stopAutoRefresh } = useAutoRefresh(loadAll)

// 分类清理（后端全量聚合）
const categoryStats = ref([])
const categoryTotal = ref(0)

// 业务分类下拉（与后端 _CACHE_KEY_CATEGORY_MAP 一致）
const categoryOptions = ['数据集缓存', '用户缓存', 'AI缓存', 'ML缓存', '清洗缓存', '特征工程缓存', '验证码缓存', '通用缓存']
const filterCategory = ref('')

// 多选批量删除
const selectedKeys = ref([])

// 删除历史统计（清空全部 / 按时间范围）
const deleteHistoryVisible = ref(false)
const deleteHistoryMode = ref('all')
const deleteHistoryRange = ref(null)

// 命中率颜色：>80 绿，否则黄
const hitRateColor = computed(() => {
  const rate = stats.value.hit_rate
  if (rate == null) return {}
  return rate > 80 ? { color: '#1dc981' } : { color: '#e6a23c' }
})

// 本地兜底分类（后端未返回 category 时按前缀归类）
function normalizeCategory(item) {
  if (item.category) return item.category
  const key = item.key || ''
  if (key.startsWith('feature_engineering:')) return '特征工程缓存'
  if (key.startsWith('support:')) return '验证码缓存'
  if (key.startsWith('datasets:')) return '数据集缓存'
  if (key.startsWith('users:')) return '用户缓存'
  if (key.startsWith('ai:')) return 'AI缓存'
  if (key.startsWith('ml:')) return 'ML缓存'
  if (key.startsWith('cleaning:')) return '清洗缓存'
  return '通用缓存'
}

// 按业务分类筛选后的缓存键列表
const filteredCacheKeys = computed(() => {
  if (!filterCategory.value) return cacheKeys.value
  return cacheKeys.value.filter(item => normalizeCategory(item) === filterCategory.value)
})

// 字节数格式化（B/KB/MB）
function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return '-'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(2) + ' MB'
}

async function loadStats() {
  try {
    const res = await getCacheStats()
    stats.value = res.data
  } catch (e) {
    console.error('获取缓存统计失败:', e)
  }
}

async function loadCacheKeys() {
  try {
    const res = await listCacheKeys(searchPrefix.value, page.value, pageSize.value)
    cacheKeys.value = res.data.keys || []
    total.value = res.data.total || 0
  } catch (e) {
    console.error('获取缓存键列表失败:', e)
  }
}

async function loadCategoryStats() {
  try {
    const res = await getCacheCategoryStats()
    categoryStats.value = res.data.categories || []
    categoryTotal.value = res.data.total || 0
  } catch (e) {
    console.error('获取缓存分类统计失败:', e)
  }
}

async function viewKeyDetail(key) {
  try {
    const res = await getCacheKeyDetail(key)
    keyDetail.value = res.data
    detailVisible.value = true
  } catch (e) {
    ElMessage.error('获取键详情失败')
  }
}

// 删除单个缓存键（统一确认弹窗）
async function deleteKey(key) {
  try {
    await ElMessageBox.confirm(
      `确定要删除缓存键「${key}」吗？删除后需重新生成该缓存。`,
      '删除缓存键',
      { type: 'warning', confirmButtonText: '确定删除', cancelButtonText: '取消' }
    )
  } catch (e) {
    return // 用户取消确认
  }
  try {
    await deleteCacheKey(key)
    ElMessage.success('删除成功')
    await Promise.all([loadCacheKeys(), loadStats(), loadCategoryStats()])
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

// 多选批量删除（统一确认弹窗）
async function handleBatchDelete() {
  if (!selectedKeys.value.length) return
  const names = selectedKeys.value.slice(0, 3).join('、') + (selectedKeys.value.length > 3 ? ` 等 ${selectedKeys.value.length} 个` : '')
  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${selectedKeys.value.length} 个缓存键吗？\n${names}\n删除后需重新生成这些缓存。`,
      '批量删除缓存键',
      { type: 'warning', confirmButtonText: '确定删除', cancelButtonText: '取消' }
    )
  } catch (e) {
    return // 用户取消确认
  }
  try {
    for (const key of selectedKeys.value) {
      await deleteCacheKey(key)
    }
    ElMessage.success(`已删除 ${selectedKeys.value.length} 个缓存键`)
    selectedKeys.value = []
    await Promise.all([loadCacheKeys(), loadStats(), loadCategoryStats()])
  } catch (e) {
    ElMessage.error('批量删除失败')
  }
}

function handleSelectionChange(rows) {
  selectedKeys.value = rows.map(r => r.key)
}

// 按业务分类清理（统一确认弹窗）
async function handleClearCategory(category) {
  try {
    await ElMessageBox.confirm(
      `确定要清理「${category}」吗？将删除该分类前缀下的全部缓存，相关模块需重新计算。此操作不可撤销！`,
      `清理${category}`,
      { type: 'warning', confirmButtonText: '确定清理', cancelButtonText: '取消' }
    )
  } catch (e) {
    return // 用户取消确认
  }
  try {
    const res = await clearCacheCategory(category)
    ElMessage.success(res.data.message || `${category}已清理`)
    await Promise.all([loadCacheKeys(), loadStats(), loadCategoryStats()])
  } catch (e) {
    ElMessage.error('清理失败：' + (e.response?.data?.detail || e.message))
  }
}

// 清空全部缓存（统一确认弹窗 + 二次警示）
async function handleClearCache() {
  try {
    await ElMessageBox.confirm(
      '确定要清空全部缓存吗？将同时清掉验证码、数据集列表、ML预检查等所有临时缓存，正在操作的用户需重新加载数据。此操作不可撤销！',
      '清空全部缓存',
      { type: 'warning', confirmButtonText: '确定清空', cancelButtonText: '取消' }
    )
  } catch (e) {
    return // 用户取消确认
  }
  try {
    const res = await clearAllCache()
    ElMessage.success(res.data.message || '缓存已清空')
    await Promise.all([loadCacheKeys(), loadStats(), loadCategoryStats()])
  } catch (e) {
    ElMessage.error('清空缓存失败')
  }
}

// 打开删除历史统计弹窗
function openDeleteHistoryDialog() {
  deleteHistoryMode.value = 'all'
  deleteHistoryRange.value = null
  deleteHistoryVisible.value = true
}

// 确认删除历史统计（统一确认弹窗，再调接口）
async function confirmDeleteHistory() {
  let desc
  if (deleteHistoryMode.value === 'all') {
    desc = '确定要清空全部历史缓存统计吗？将删除 cache_stats_hourly 表中所有记录，图表将只剩当前进程埋点数据。此操作不可恢复！'
  } else {
    const [start, end] = deleteHistoryRange.value || []
    if (!start || !end) {
      ElMessage.warning('请选择要删除的时间范围')
      return
    }
    desc = `确定要删除 ${start.slice(4, 6)}-${start.slice(6, 8)} ${start.slice(8, 10)}:00 ~ ${end.slice(4, 6)}-${end.slice(6, 8)} ${end.slice(8, 10)}:00 范围内的历史缓存统计吗？此操作不可恢复！`
  }
  try {
    await ElMessageBox.confirm(desc, '删除历史统计', {
      type: 'warning',
      confirmButtonText: '确定删除',
      cancelButtonText: '取消'
    })
  } catch (e) {
    return // 用户取消确认
  }
  try {
    let res
    if (deleteHistoryMode.value === 'all') {
      res = await deleteCacheHistory()
    } else {
      const [start, end] = deleteHistoryRange.value || []
      res = await deleteCacheHistory(start, end)
    }
    ElMessage.success(res.data.message || '删除成功')
    deleteHistoryVisible.value = false
    await loadHitRate()
  } catch (e) {
    ElMessage.error('删除失败：' + (e.response?.data?.detail || e.message))
  }
}

// 渲染三张趋势图：命中率折线 + 请求量堆叠柱 + 键数量折线
function renderTrendCharts(trend) {
  const items = Array.isArray(trend) ? trend : []
  const labels = items.map(d => d.hour)
  const axisStyle = { axisLabel: { interval: 'auto' } }

  // 1. 命中率趋势
  if (hitRateChartRef.value) {
    if (!hitRateChartInstance) {
      hitRateChartInstance = echarts.init(hitRateChartRef.value)
    }
    hitRateChartInstance.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: '6%', right: '5%', bottom: '8%', top: '10%', containLabel: true },
      xAxis: { type: 'category', data: labels, ...axisStyle },
      yAxis: { type: 'value', name: '命中率(%)', nameLocation: 'middle', nameGap: 42, max: 100, min: 0 },
      series: [{
        name: '命中率',
        type: 'line',
        data: items.map(d => d.hit_rate),
        smooth: true,
        itemStyle: { color: '#409EFF' },
        areaStyle: { opacity: 0.2 }
      }]
    }, true)
  }

  // 2. 请求量趋势（命中 / 未命中堆叠柱）
  if (reqChartRef.value) {
    if (!reqChartInstance) {
      reqChartInstance = echarts.init(reqChartRef.value)
    }
    reqChartInstance.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: '4%', right: '4%', bottom: '8%', top: '10%', containLabel: true },
      xAxis: { type: 'category', data: labels, ...axisStyle },
      // 半宽图不设 y 轴名称（标题已说明含义），避免窄容器内名称被裁剪
      yAxis: { type: 'value' },
      legend: { data: ['命中', '未命中'], top: 0 },
      series: [
        { name: '命中', type: 'bar', stack: 'req', data: items.map(d => d.hits), itemStyle: { color: '#409EFF' }, barMaxWidth: 18 },
        { name: '未命中', type: 'bar', stack: 'req', data: items.map(d => d.misses), itemStyle: { color: '#f56c6c' }, barMaxWidth: 18 }
      ]
    }, true)
  }

  // 3. 缓存键数量趋势
  if (keysChartRef.value) {
    if (!keysChartInstance) {
      keysChartInstance = echarts.init(keysChartRef.value)
    }
    keysChartInstance.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: '4%', right: '4%', bottom: '8%', top: '10%', containLabel: true },
      xAxis: { type: 'category', data: labels, ...axisStyle },
      // 半宽图不设 y 轴名称（标题已说明含义），避免窄容器内名称被裁剪
      yAxis: { type: 'value' },
      series: [{
        name: '缓存键数',
        type: 'line',
        data: items.map(d => d.total_keys),
        smooth: true,
        itemStyle: { color: '#67c23a' },
        areaStyle: { opacity: 0.15 }
      }]
    }, true)
  }
}

// 获取缓存趋势数据（按当前时间范围）并触发三图渲染
async function loadHitRate() {
  try {
    const res = await getCacheHitRate(timeRange.value)
    hitRateData.value = res.data
    summary.value = res.data.summary || {}
    nextTick(() => renderTrendCharts(res.data.trend))
  } catch (e) {
    console.error('获取缓存命中率失败:', e)
  }
}

// 切到历史统计 Tab 时图表容器变为可见，需 resize 恢复正确尺寸
// （el-tabs 默认渲染所有 pane，隐藏容器上 echarts.init 宽度为 0）
watch(activeTab, (val) => {
  if (val === 'history') {
    nextTick(() => {
      ;[hitRateChartInstance, reqChartInstance, keysChartInstance].forEach(inst => {
        if (inst) inst.resize()
      })
    })
  }
})

// 一次性加载所有缓存相关数据，供自动刷新统一调用
async function loadAll() {
  await Promise.all([loadStats(), loadCacheKeys(), loadHitRate(), loadCategoryStats()])
}

onMounted(() => {
  loadAll()
})

onUnmounted(() => {
  if (hitRateChartInstance) {
    hitRateChartInstance.dispose()
    hitRateChartInstance = null
  }
  if (reqChartInstance) {
    reqChartInstance.dispose()
    reqChartInstance = null
  }
  if (keysChartInstance) {
    keysChartInstance.dispose()
    keysChartInstance = null
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
.category-box {
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px 14px;
}
.category-name {
  font-size: 14px;
  font-weight: 500;
  color: #1f2937;
}
.category-count {
  font-size: 15px;
  font-weight: 600;
  color: #1f2937;
}
.chart-subtitle {
  font-size: 13px;
  color: #6b7280;
  margin-bottom: 6px;
  padding-left: 2px;
}
</style>
