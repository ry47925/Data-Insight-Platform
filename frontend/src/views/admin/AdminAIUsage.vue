<template>
  <div>
    <!-- 汇总指标卡 -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">AI 用量概览</div>
        <span class="text-sm" style="color: #9ca3af;">数据源 ai_usage_log，自动刷新 60 秒</span>
      </div>
      <div class="stats-grid" style="grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));">
        <div class="stat-card">
          <el-icon :size="28" style="color: #8b5cf6;"><DataBoard /></el-icon>
          <div class="stat-value">{{ summary.total_calls || 0 }}</div>
          <div class="stat-label">总调用次数</div>
        </div>
        <div class="stat-card">
          <el-icon :size="28" style="color: #3b82f6;"><TrendCharts /></el-icon>
          <div class="stat-value">{{ formatTokens(summary.total_tokens) }}</div>
          <div class="stat-label">总 Token 消耗</div>
          <div class="stat-sub">平均 {{ summary.avg_tokens_per_call || 0 }}/次</div>
        </div>
        <div class="stat-card">
          <el-icon :size="28" style="color: #10b981;"><Download /></el-icon>
          <div class="stat-value">{{ formatTokens(summary.prompt_tokens) }}</div>
          <div class="stat-label">输入 Token</div>
        </div>
        <div class="stat-card">
          <el-icon :size="28" style="color: #f59e0b;"><Upload /></el-icon>
          <div class="stat-value">{{ formatTokens(summary.completion_tokens) }}</div>
          <div class="stat-label">输出 Token</div>
        </div>
      </div>
    </div>

    <!-- 近 30 天趋势 -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">近 30 天 Token 消耗趋势</div>
      </div>
      <div ref="trendChartRef" class="chart-container" style="height: 320px;"></div>
    </div>

    <!-- 按用户统计（带用户名筛选） -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">按用户统计</div>
        <div style="display: flex; align-items: center; gap: 8px;">
          <el-input
            v-model="userKeyword"
            placeholder="搜索用户名..."
            clearable
            style="width: 200px;"
            @input="onUserFilterInput"
          >
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <span class="text-sm" style="color: #9ca3af;">共 {{ filteredByUser.length }} 人</span>
        </div>
      </div>
      <div v-if="filteredByUser.length" class="data-table-wrapper">
        <el-table :data="filteredByUser" border>
          <el-table-column prop="username" label="用户" width="160" />
          <el-table-column prop="calls" label="调用次数" width="120" />
          <el-table-column label="总 Token" min-width="120">
            <template #default="scope">{{ formatTokens(scope.row.tokens) }}</template>
          </el-table-column>
        </el-table>
      </div>
      <div v-else class="empty-tip">{{ byUser.length ? '未找到匹配的用户' : '暂无数据' }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { DataBoard, TrendCharts, Download, Upload, Search } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { getAIUsageStats } from '../../api/admin.js'

const summary = ref({})
const byUser = ref([])
const userKeyword = ref('')
const trendChartRef = ref(null)
let trendChart = null
let timer = null

// 按用户名模糊筛选（数据量小，前端本地过滤）
const filteredByUser = computed(() => {
  const kw = userKeyword.value.trim().toLowerCase()
  if (!kw) return byUser.value
  return byUser.value.filter(u => (u.username || '').toLowerCase().includes(kw))
})

function onUserFilterInput() {
  // 空实现：input 事件驱动 computed 实时过滤（保留用于将来接入后端筛选）
}

function formatTokens(n) {
  if (!n && n !== 0) return '-'
  if (n >= 1000000) return (n / 1000000).toFixed(2) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  return String(n)
}

function renderTrendChart(trend) {
  if (!trendChartRef.value) return
  if (!trendChart) {
    trendChart = echarts.init(trendChartRef.value)
  }
  trendChart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['Token 消耗', '调用次数'], top: 0 },
    grid: { left: '4%', right: '5%', bottom: '6%', top: '15%', containLabel: true },
    xAxis: { type: 'category', data: trend.map(t => t.date), axisLabel: { fontSize: 11 } },
    yAxis: [
      { type: 'value', name: 'Token', nameTextStyle: { fontSize: 11 } },
      { type: 'value', name: '次数', nameTextStyle: { fontSize: 11 }, splitLine: { show: false } },
    ],
    series: [
      {
        name: 'Token 消耗', type: 'bar', data: trend.map(t => t.tokens),
        itemStyle: { color: '#8b5cf6' }, barMaxWidth: 18,
      },
      {
        name: '调用次数', type: 'line', yAxisIndex: 1, data: trend.map(t => t.calls),
        itemStyle: { color: '#10b981' }, smooth: true,
      },
    ],
  })
}

async function loadData() {
  try {
    const res = await getAIUsageStats()
    const data = res.data
    summary.value = data.summary || {}
    byUser.value = data.by_user || []
    renderTrendChart(data.trend || [])
  } catch (e) {
    console.error('获取 AI 用量统计失败:', e)
  }
}

onMounted(() => {
  loadData()
  timer = setInterval(loadData, 60000)
  window.addEventListener('resize', onResize)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
  window.removeEventListener('resize', onResize)
  if (trendChart) {
    trendChart.dispose()
    trendChart = null
  }
})

function onResize() {
  if (trendChart) trendChart.resize()
}
</script>

<style scoped>
.stats-grid {
  display: grid;
  gap: 16px;
}

.stat-card {
  background: #f8fafc;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
}

.stat-value {
  font-size: 26px;
  font-weight: 700;
  color: #1f2937;
  margin: 6px 0 4px;
}

.stat-label {
  font-size: 13px;
  color: #6b7280;
}

.stat-sub {
  font-size: 12px;
  color: #9ca3af;
  margin-top: 4px;
}

.empty-tip {
  padding: 40px;
  text-align: center;
  color: #9ca3af;
}
</style>
