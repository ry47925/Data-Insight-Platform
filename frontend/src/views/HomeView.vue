<template>
  <div class="home-view">
    <!-- Hero 主视觉区（登录感知） -->
    <div class="hero-section">
      <div class="hero-bg">
        <div class="hero-glow glow-1"></div>
        <div class="hero-glow glow-2"></div>
        <div class="hero-glow glow-3"></div>
        <div class="hero-grid"></div>
        <div class="hero-noise"></div>
      </div>
      <div class="hero-content">
        <div class="hero-badge">
          <span class="badge-dot"></span>
          <span>{{ heroBadge }}</span>
        </div>
        <h1 class="hero-title">
          <span class="title-line">让每一份数据</span>
          <span class="title-line highlight">都能产生价值</span>
        </h1>
        <p class="hero-desc">{{ heroDesc }}</p>
        <div class="hero-actions">
          <el-button type="primary" size="large" class="btn-primary" @click="$router.push('/datasets')">
            {{ isAuthed ? '继续探索' : '立即开始' }}
            <el-icon class="btn-icon"><ArrowRight /></el-icon>
          </el-button>
          <el-button v-if="!isAuthed" size="large" class="btn-ghost" @click="$router.push('/login')">
            登录体验
          </el-button>
        </div>
      </div>
      <!-- 真实数据驱动装饰卡 -->
      <div class="hero-visual">
        <div class="visual-card card-1">
          <div class="visual-bar">
            <div class="bar bar-a"></div>
            <div class="bar bar-b"></div>
            <div class="bar bar-c"></div>
            <div class="bar bar-d"></div>
            <div class="bar bar-e"></div>
          </div>
          <div class="visual-num">{{ isAuthed ? formatNumber(stats.datasets) : '--' }}</div>
          <div class="visual-label">数据集总量</div>
        </div>
        <div class="visual-card card-2">
          <div class="visual-donut">
            <div class="donut-ring"></div>
            <div class="donut-center">{{ isAuthed ? formatNumber(stats.todayAiCalls) : '--' }}</div>
          </div>
          <div class="visual-label">今日 AI 对话</div>
        </div>
      </div>
    </div>

    <!-- 统计数据（登录后真实同步） -->
    <div class="stats-section">
      <div class="section-header">
        <div class="section-tag">我的工作台</div>
        <h2 class="section-title">{{ isAuthed ? '你的数据资产一览' : '平台能力一览' }}</h2>
        <p class="section-desc">
          {{ isAuthed ? '数据实时同步，随时掌握你的分析进度' : '登录后实时同步你的数据集、操作记录与 AI 用量' }}
        </p>
      </div>
      <div class="stats-grid">
        <div class="stat-item" v-for="(stat, idx) in statsData" :key="stat.label" :style="{ animationDelay: idx * 0.08 + 's' }">
          <div class="stat-icon" :class="stat.color">
            <el-icon :size="24"><component :is="stat.icon" /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">
              {{ isAuthed ? stat.display : '--' }}<span class="stat-unit">{{ stat.unit }}</span>
            </div>
            <div class="stat-label">{{ stat.label }}</div>
            <div class="stat-sub">{{ isAuthed ? stat.sub : '登录后查看' }}</div>
          </div>
          <div class="stat-trend" :class="stat.color"></div>
        </div>
      </div>
    </div>

    <!-- 功能模块 -->
    <div class="modules-section">
      <div class="section-header">
        <div class="section-tag">核心能力</div>
        <h2 class="section-title">七大功能模块，覆盖数据分析全链路</h2>
        <p class="section-desc">从原始数据到智能洞察，每一步都为你准备好专业工具</p>
      </div>
      <div class="modules-grid">
        <div
          class="module-card"
          v-for="(card, idx) in moduleCards"
          :key="card.title"
          :style="{ animationDelay: idx * 0.08 + 's' }"
        >
          <div class="card-header">
            <div class="module-icon" :class="card.color">
              <el-icon :size="26"><component :is="card.icon" /></el-icon>
            </div>
            <div class="module-num">0{{ idx + 1 }}</div>
          </div>
          <h3 class="module-title">{{ card.title }}</h3>
          <p class="module-desc">{{ card.desc }}</p>
          <div class="module-tags">
            <span v-for="tag in card.tags" :key="tag" class="tag-dot">{{ tag }}</span>
          </div>
          <div class="module-footer">
            <span>功能概览</span>
            <div class="feature-dots">
              <span v-for="n in 3" :key="n" class="dot"></span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 工作流程（三条路线） -->
    <div class="workflow-section">
      <div class="section-header center">
        <div class="section-tag">使用路径</div>
        <h2 class="section-title">三条路线，满足不同数据分析需求</h2>
        <p class="section-desc">从纯挖掘到深度建模，灵活选择最适合你的数据价值挖掘路径</p>
      </div>
      <!-- 工作流程（SVG 分支流程图，移动端降级为列表） -->
      <div class="flow-container">
        <svg class="flow-svg" viewBox="0 0 1200 400" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="三条数据分析路径分支流程图">
          <defs>
            <linearGradient id="flowEnd" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stop-color="#34d399" />
              <stop offset="100%" stop-color="#059669" />
            </linearGradient>
          </defs>

          <!-- 公共主干：原始数据 → 数据清洗 → 三分叉 -->
          <line x1="90" y1="200" x2="250" y2="200" stroke="#c7d2fe" stroke-width="2.5" />
          <line x1="250" y1="200" x2="285" y2="200" stroke="#c7d2fe" stroke-width="2.5" />
          <path d="M285 200 C 285 145, 295 90, 340 90" fill="none" stroke="#c7d2fe" stroke-width="2.5" />
          <path d="M285 200 L 340 200" fill="none" stroke="#c7d2fe" stroke-width="2.5" />
          <path d="M285 200 C 285 255, 295 310, 340 310" fill="none" stroke="#c7d2fe" stroke-width="2.5" />

          <!-- 主干节点 -->
          <circle cx="90" cy="200" r="15" fill="#fff" stroke="#6366f1" stroke-width="2.5" />
          <circle cx="90" cy="200" r="5" fill="#6366f1" />
          <text x="90" y="232" text-anchor="middle" font-size="13" fill="#4b5563" font-weight="600">原始数据</text>
          <circle cx="250" cy="200" r="15" fill="#fff" stroke="#6366f1" stroke-width="2.5" />
          <circle cx="250" cy="200" r="5" fill="#6366f1" />
          <text x="250" y="232" text-anchor="middle" font-size="13" fill="#4b5563" font-weight="600">数据清洗</text>

          <!-- 路径 A：纯挖掘线 -->
          <g>
            <rect x="250" y="42" width="180" height="26" rx="13" fill="#ccfbf1" />
            <text x="340" y="60" text-anchor="middle" font-size="13" font-weight="700" fill="#0d9488">路径 A · 纯挖掘线</text>
          </g>
          <line x1="340" y1="90" x2="800" y2="90" stroke="#2dd4bf" stroke-width="2" />
          <circle cx="340" cy="90" r="15" fill="#fff" stroke="#0d9488" stroke-width="2.5" />
          <circle cx="340" cy="90" r="5" fill="#0d9488" />
          <text x="340" y="122" text-anchor="middle" font-size="13" fill="#4b5563" font-weight="600">数据挖掘</text>
          <circle cx="570" cy="90" r="15" fill="#0d9488" />
          <circle cx="570" cy="90" r="6" fill="#fff" />
          <text x="570" y="122" text-anchor="middle" font-size="13" fill="#0d9488" font-weight="700">挖掘结果</text>
          <circle cx="800" cy="90" r="15" fill="url(#flowEnd)" />
          <circle cx="800" cy="90" r="5" fill="#fff" />
          <text x="800" y="122" text-anchor="middle" font-size="13" fill="#059669" font-weight="700">业务决策</text>
          <g>
            <rect x="852" y="78" width="108" height="24" rx="12" fill="#f0fdfa" />
            <text x="906" y="94" text-anchor="middle" font-size="12" fill="#0d9488" font-weight="600">无需建模</text>
          </g>

          <!-- 路径 B：建模预测线 -->
          <g>
            <rect x="250" y="152" width="180" height="26" rx="13" fill="#ede9fe" />
            <text x="340" y="170" text-anchor="middle" font-size="13" font-weight="700" fill="#7c3aed">路径 B · 建模预测线</text>
          </g>
          <line x1="340" y1="200" x2="850" y2="200" stroke="#c4b5fd" stroke-width="2" />
          <circle cx="340" cy="200" r="15" fill="#fff" stroke="#7c3aed" stroke-width="2.5" />
          <circle cx="340" cy="200" r="5" fill="#7c3aed" />
          <text x="340" y="232" text-anchor="middle" font-size="13" fill="#4b5563" font-weight="600">特征工程</text>
          <circle cx="510" cy="200" r="15" fill="#fff" stroke="#7c3aed" stroke-width="2.5" />
          <circle cx="510" cy="200" r="5" fill="#7c3aed" />
          <text x="510" y="232" text-anchor="middle" font-size="13" fill="#4b5563" font-weight="600">机器学习</text>
          <circle cx="680" cy="200" r="15" fill="#7c3aed" />
          <circle cx="680" cy="200" r="6" fill="#fff" />
          <text x="680" y="232" text-anchor="middle" font-size="13" fill="#7c3aed" font-weight="700">预测模型</text>
          <circle cx="850" cy="200" r="15" fill="url(#flowEnd)" />
          <circle cx="850" cy="200" r="5" fill="#fff" />
          <text x="850" y="232" text-anchor="middle" font-size="13" fill="#059669" font-weight="700">批量预测</text>
          <g>
            <rect x="902" y="188" width="108" height="24" rx="12" fill="#f5f3ff" />
            <text x="956" y="204" text-anchor="middle" font-size="12" fill="#7c3aed" font-weight="600">自动调优</text>
          </g>

          <!-- 路径 C：挖掘 + 建模组合线 -->
          <g>
            <rect x="250" y="262" width="200" height="26" rx="13" fill="#ffedd5" />
            <text x="350" y="280" text-anchor="middle" font-size="13" font-weight="700" fill="#ea580c">路径 C · 挖掘 + 建模组合</text>
          </g>
          <line x1="340" y1="310" x2="490" y2="310" stroke="#fdba74" stroke-width="2" />
          <line x1="490" y1="310" x2="640" y2="310" stroke="#fdba74" stroke-width="2" stroke-dasharray="6 4" />
          <line x1="640" y1="310" x2="790" y2="310" stroke="#fdba74" stroke-width="2" />
          <line x1="790" y1="310" x2="940" y2="310" stroke="#fdba74" stroke-width="2" />
          <circle cx="340" cy="310" r="15" fill="#fff" stroke="#ea580c" stroke-width="2.5" />
          <circle cx="340" cy="310" r="5" fill="#ea580c" />
          <text x="340" y="342" text-anchor="middle" font-size="13" fill="#4b5563" font-weight="600">数据挖掘</text>
          <circle cx="490" cy="310" r="15" fill="#ea580c" />
          <circle cx="490" cy="310" r="6" fill="#fff" />
          <text x="490" y="342" text-anchor="middle" font-size="13" fill="#ea580c" font-weight="700">挖掘产物</text>
          <text x="565" y="293" text-anchor="middle" font-size="12" fill="#ea580c" font-weight="600">作为特征输入</text>
          <circle cx="640" cy="310" r="15" fill="#fff" stroke="#ea580c" stroke-width="2.5" />
          <circle cx="640" cy="310" r="5" fill="#ea580c" />
          <text x="640" y="342" text-anchor="middle" font-size="13" fill="#4b5563" font-weight="600">特征工程</text>
          <circle cx="790" cy="310" r="15" fill="#fff" stroke="#ea580c" stroke-width="2.5" />
          <circle cx="790" cy="310" r="5" fill="#ea580c" />
          <text x="790" y="342" text-anchor="middle" font-size="13" fill="#4b5563" font-weight="600">机器学习</text>
          <circle cx="940" cy="310" r="15" fill="url(#flowEnd)" />
          <circle cx="940" cy="310" r="5" fill="#fff" />
          <text x="940" y="342" text-anchor="middle" font-size="13" fill="#059669" font-weight="700">预测模型</text>
          <g>
            <rect x="992" y="298" width="108" height="24" rx="12" fill="#fff7ed" />
            <text x="1046" y="314" text-anchor="middle" font-size="12" fill="#ea580c" font-weight="600">效果更优</text>
          </g>
        </svg>

        <!-- 移动端降级：纵向路径列表 -->
        <div class="flow-list">
          <div class="flow-item flow-a">
            <div class="flow-item-title">路径 A · 纯挖掘线</div>
            <div class="flow-item-steps">原始数据 → 数据清洗 → 数据挖掘 → 挖掘结果 → 业务决策</div>
            <div class="flow-item-tags"><span>无需建模</span></div>
          </div>
          <div class="flow-item flow-b">
            <div class="flow-item-title">路径 B · 建模预测线</div>
            <div class="flow-item-steps">原始数据 → 数据清洗 → 特征工程 → 机器学习 → 预测模型 → 批量预测</div>
            <div class="flow-item-tags"><span>自动调优</span></div>
          </div>
          <div class="flow-item flow-c">
            <div class="flow-item-title">路径 C · 挖掘 + 建模组合线</div>
            <div class="flow-item-steps">原始数据 → 数据清洗 → 数据挖掘 → 挖掘产物（作为特征输入）→ 特征工程 → 机器学习 → 预测模型</div>
            <div class="flow-item-tags"><span>效果更优</span></div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, onMounted, onBeforeUnmount, watch } from 'vue'
import {
  FolderOpened,
  DataAnalysis,
  Brush,
  Histogram,
  Cpu,
  ChatDotRound,
  ArrowRight,
  MagicStick,
  Connection,
  Coin,
  Timer
} from '@element-plus/icons-vue'
import {
  isLoggedIn,
  authStore,
  fetchDatasets,
  fetchTaskRecords,
  fetchUsageStats,
  fetchDataSources
} from '../api/index.js'

// ====== 登录状态（响应式，退出登录自动切换） ======
const isAuthed = computed(() => isLoggedIn())

// ====== 真实统计数据 ======
const stats = reactive({
  datasets: 0,
  tasks: 0,
  aiTokens: 0,
  dataSources: 0,
  todayAiCalls: 0
})

// 加载真实统计（仅登录后请求）
async function loadStats() {
  if (!isLoggedIn()) return
  const [dsRes, taskRes, aiRes, srcRes] = await Promise.allSettled([
    // paginated=true + page_size=1：只需总数，避免数据集超过100条时首页统计偏小
    fetchDatasets({ paginated: true, page_size: 1 }),
    fetchTaskRecords({ per_page: 1 }),
    fetchUsageStats(),
    fetchDataSources()
  ])
  const target = { ...stats }
  if (dsRes.status === 'fulfilled') {
    const d = dsRes.value.data
    if (d && typeof d.total === 'number') target.datasets = d.total
    else if (Array.isArray(d)) target.datasets = d.length
  }
  if (taskRes.status === 'fulfilled') {
    target.tasks = taskRes.value.data?.total || 0
  }
  if (aiRes.status === 'fulfilled') {
    target.aiTokens = aiRes.value.data?.total_tokens || 0
    target.todayAiCalls = aiRes.value.data?.today_calls || 0
  }
  if (srcRes.status === 'fulfilled' && Array.isArray(srcRes.value.data)) {
    target.dataSources = srcRes.value.data.length
  }
  animateStats(target)
}

// 数字滚动动画（600ms ease-out）
let animFrameId = null
function animateStats(target) {
  if (animFrameId) cancelAnimationFrame(animFrameId)
  const from = { ...stats }
  const start = performance.now()
  const dur = 600
  function tick(now) {
    const p = Math.min((now - start) / dur, 1)
    const ease = 1 - Math.pow(1 - p, 3)
    stats.datasets = Math.round(from.datasets + (target.datasets - from.datasets) * ease)
    stats.tasks = Math.round(from.tasks + (target.tasks - from.tasks) * ease)
    stats.aiTokens = Math.round(from.aiTokens + (target.aiTokens - from.aiTokens) * ease)
    stats.dataSources = Math.round(from.dataSources + (target.dataSources - from.dataSources) * ease)
    stats.todayAiCalls = Math.round(from.todayAiCalls + (target.todayAiCalls - from.todayAiCalls) * ease)
    if (p < 1) {
      animFrameId = requestAnimationFrame(tick)
    } else {
      animFrameId = null
    }
  }
  animFrameId = requestAnimationFrame(tick)
}

// 大数字格式化（1 万以上转"万"）
function formatNumber(n) {
  if (n >= 100000000) return (n / 100000000).toFixed(1).replace(/\.0$/, '') + ' 亿'
  if (n >= 10000) return (n / 10000).toFixed(1).replace(/\.0$/, '') + ' 万'
  return String(n || 0)
}

// 监听登录状态变化（keep-alive 缓存下退出登录后重置统计）
watch(isAuthed, (authed) => {
  if (authed) {
    loadStats()
  } else {
    Object.assign(stats, { datasets: 0, tasks: 0, aiTokens: 0, dataSources: 0, todayAiCalls: 0 })
  }
})

onMounted(() => {
  if (isAuthed.value) loadStats()
})

onBeforeUnmount(() => {
  if (animFrameId) cancelAnimationFrame(animFrameId)
})

// ====== Hero 个性化文案 ======
const heroBadge = computed(() => {
  if (isAuthed.value) {
    const name = authStore.user?.username || '朋友'
    return `欢迎回来，${name}`
  }
  return 'AI 驱动 · 全链路数据分析'
})

const heroDesc = computed(() => {
  if (isAuthed.value) {
    const parts = []
    if (stats.datasets > 0) parts.push(`${stats.datasets} 个数据集`)
    if (stats.tasks > 0) parts.push(`${stats.tasks} 次操作`)
    if (stats.aiTokens > 0) parts.push(`${formatNumber(stats.aiTokens)} Token`)
    const tail = parts.length ? `你已积累 ${parts.join('、')}，继续探索数据价值。` : '从数据清洗到 AI 智能分析，继续你的数据洞察之旅。'
    return `从数据清洗、特征工程到机器学习与 AI 智能分析，一站式完成数据洞察的全流程。${tail}`
  }
  return '从数据清洗、特征工程到机器学习与 AI 智能分析，一站式完成数据洞察的全流程。'
})

// ====== 统计数据 ======
const statsData = computed(() => [
  {
    value: stats.datasets,
    display: formatNumber(stats.datasets),
    unit: '个',
    label: '可用数据集',
    sub: '本地上传 + 远程数据源',
    icon: FolderOpened,
    color: 'stat-blue'
  },
  {
    value: stats.tasks,
    display: formatNumber(stats.tasks),
    unit: '次',
    label: '操作记录',
    sub: '清洗 / 挖掘 / 建模等',
    icon: Timer,
    color: 'stat-purple'
  },
  {
    value: stats.aiTokens,
    display: formatNumber(stats.aiTokens),
    unit: 'Token',
    label: 'AI Token 用量',
    sub: `今日对话 ${formatNumber(stats.todayAiCalls)} 次`,
    icon: Coin,
    color: 'stat-orange'
  },
  {
    value: stats.dataSources,
    display: formatNumber(stats.dataSources),
    unit: '个',
    label: '数据源连接',
    sub: 'MySQL / PostgreSQL',
    icon: Connection,
    color: 'stat-green'
  }
])

// 七大功能模块
const moduleCards = [
  {
    title: '数据管理',
    color: 'mod-blue',
    icon: FolderOpened,
    desc: '支持 CSV、Excel 等多种格式上传，统一管理原始数据与各模块产物',
    tags: ['CSV', 'Excel', '数据分类']
  },
  {
    title: '数据分析',
    color: 'mod-cyan',
    icon: DataAnalysis,
    desc: '统计摘要、直方图、散点图、热力图等多种可视化分析方式',
    tags: ['统计分析', '可视化', '多图表']
  },
  {
    title: '数据清洗',
    color: 'mod-green',
    icon: Brush,
    desc: '智能检测缺失值、异常值、重复数据，自动生成数据质量报告',
    tags: ['缺失值处理', '异常值检测', '去重']
  },
  {
    title: '数据挖掘',
    color: 'mod-teal',
    icon: Histogram,
    desc: '聚类分析、关联规则、序列模式挖掘，发现数据中的隐藏规律',
    tags: ['聚类', '关联规则', '序列模式']
  },
  {
    title: '特征工程',
    color: 'mod-indigo',
    icon: MagicStick,
    desc: '特征构造、编码、缩放、降维、选择，为建模准备高质量特征',
    tags: ['特征构造', '编码', '降维']
  },
  {
    title: '机器学习',
    color: 'mod-purple',
    icon: Cpu,
    desc: '分类、回归等多种算法，自动训练评估，支持超参数调优',
    tags: ['分类', '回归', '模型训练']
  },
  {
    title: 'AI 智能分析',
    color: 'mod-orange',
    icon: ChatDotRound,
    desc: '自然语言对话式分析，AI 结合数据上下文自动发现洞察',
    tags: ['智能对话', '上下文注入', '洞察发现']
  }
]
</script>

<style scoped>
.home-view {
  position: relative;
  min-height: calc(100vh - 60px);
  padding-bottom: 60px;
}

/* ========== Hero 主视觉区 ========== */
.hero-section {
  position: relative;
  padding: 64px 48px 84px;
  overflow: hidden;
  border-radius: 24px;
  margin-bottom: 40px;
  isolation: isolate;
}

.hero-bg {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, #312e81 0%, #4361ee 45%, #06b6d4 100%);
  z-index: -1;
}

.hero-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(90px);
  opacity: 0.45;
}

.glow-1 {
  width: 320px;
  height: 320px;
  background: #818cf8;
  top: -90px;
  right: 22%;
  animation: float 7s ease-in-out infinite;
}

.glow-2 {
  width: 260px;
  height: 260px;
  background: #22d3ee;
  bottom: -70px;
  left: 8%;
  animation: float 9s ease-in-out infinite reverse;
}

.glow-3 {
  width: 220px;
  height: 220px;
  background: #a78bfa;
  top: 42%;
  right: 4%;
  animation: float 8s ease-in-out infinite;
}

@keyframes float {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(20px, -30px) scale(1.1); }
}

.hero-grid {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.06) 1px, transparent 1px);
  background-size: 42px 42px;
  mask-image: radial-gradient(ellipse at center, black 35%, transparent 82%);
  -webkit-mask-image: radial-gradient(ellipse at center, black 35%, transparent 82%);
}

.hero-noise {
  position: absolute;
  inset: 0;
  opacity: 0.06;
  background-image: radial-gradient(rgba(255, 255, 255, 0.9) 1px, transparent 1px);
  background-size: 26px 26px;
}

.hero-content {
  position: relative;
  z-index: 1;
  max-width: 600px;
  animation: fadeInUp 0.8s ease-out;
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 18px;
  background: rgba(255, 255, 255, 0.14);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.24);
  border-radius: 999px;
  color: rgba(255, 255, 255, 0.92);
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 26px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
}

.badge-dot {
  width: 8px;
  height: 8px;
  background: #4ade80;
  border-radius: 50%;
  box-shadow: 0 0 8px #4ade80;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.6; transform: scale(1.2); }
}

.hero-title {
  font-size: 50px;
  font-weight: 800;
  line-height: 1.2;
  color: white;
  margin: 0 0 22px;
  letter-spacing: -1px;
}

.title-line {
  display: block;
}

.title-line.highlight {
  background: linear-gradient(90deg, #fbbf24, #f472b6, #a78bfa);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.hero-desc {
  font-size: 16px;
  line-height: 1.8;
  color: rgba(255, 255, 255, 0.78);
  margin: 0 0 34px;
}

.hero-actions {
  display: flex;
  gap: 16px;
}

.btn-primary {
  background: white !important;
  color: #312e81 !important;
  border: none !important;
  font-weight: 600 !important;
  padding: 0 28px !important;
  height: 48px !important;
  border-radius: 12px !important;
  transition: all 0.3s ease !important;
  box-shadow: 0 4px 24px rgba(255, 255, 255, 0.35) !important;
}

.btn-primary:hover {
  transform: translateY(-2px) !important;
  box-shadow: 0 10px 34px rgba(255, 255, 255, 0.45) !important;
}

.btn-icon {
  margin-left: 6px;
  font-size: 16px;
  transition: transform 0.3s ease;
}

.btn-primary:hover .btn-icon {
  transform: translateX(4px);
}

.btn-ghost {
  background: rgba(255, 255, 255, 0.1) !important;
  color: white !important;
  border: 1px solid rgba(255, 255, 255, 0.32) !important;
  font-weight: 500 !important;
  padding: 0 24px !important;
  height: 48px !important;
  border-radius: 12px !important;
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  transition: all 0.3s ease !important;
}

.btn-ghost:hover {
  background: rgba(255, 255, 255, 0.18) !important;
  border-color: rgba(255, 255, 255, 0.5) !important;
}

/* Hero 可视化装饰（真实数据） */
.hero-visual {
  position: absolute;
  top: 50%;
  right: 60px;
  transform: translateY(-50%);
  z-index: 1;
  display: flex;
  gap: 20px;
  animation: fadeInRight 1s ease-out 0.2s both;
}

@keyframes fadeInRight {
  from {
    opacity: 0;
    transform: translateY(-50%) translateX(30px);
  }
  to {
    opacity: 1;
    transform: translateY(-50%) translateX(0);
  }
}

.visual-card {
  background: rgba(255, 255, 255, 0.12);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.22);
  border-radius: 18px;
  padding: 20px;
  width: 148px;
  text-align: center;
}

.card-1 {
  transform: translateY(-20px);
  animation: cardFloat 5s ease-in-out infinite;
}

.card-2 {
  transform: translateY(20px);
  animation: cardFloat2 6s ease-in-out infinite;
}

@keyframes cardFloat {
  0%, 100% { transform: translateY(-20px); }
  50% { transform: translateY(-34px); }
}

@keyframes cardFloat2 {
  0%, 100% { transform: translateY(20px); }
  50% { transform: translateY(34px); }
}

.visual-bar {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  height: 96px;
  margin-bottom: 12px;
}

.bar {
  flex: 1;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.85), rgba(255, 255, 255, 0.2));
  border-radius: 4px 4px 0 0;
  transition: height 0.5s ease;
}

.bar-a { animation: barGrow1 3s ease-in-out infinite; }
.bar-b { animation: barGrow2 3.5s ease-in-out infinite; }
.bar-c { animation: barGrow3 2.8s ease-in-out infinite; }
.bar-d { animation: barGrow4 3.2s ease-in-out infinite; }
.bar-e { animation: barGrow5 2.5s ease-in-out infinite; }

@keyframes barGrow1 { 0%, 100% { height: 60%; } 50% { height: 75%; } }
@keyframes barGrow2 { 0%, 100% { height: 85%; } 50% { height: 65%; } }
@keyframes barGrow3 { 0%, 100% { height: 45%; } 50% { height: 62%; } }
@keyframes barGrow4 { 0%, 100% { height: 70%; } 50% { height: 50%; } }
@keyframes barGrow5 { 0%, 100% { height: 90%; } 50% { height: 74%; } }

.visual-donut {
  position: relative;
  width: 80px;
  height: 80px;
  margin: 0 auto 10px;
}

.donut-ring {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  border: 8px solid rgba(255, 255, 255, 0.15);
  border-top-color: rgba(255, 255, 255, 0.92);
  border-right-color: rgba(255, 255, 255, 0.55);
  animation: spin 4s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.donut-center {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 15px;
  font-weight: 700;
  color: white;
}

.visual-num {
  font-size: 22px;
  font-weight: 800;
  color: white;
  margin-bottom: 4px;
  line-height: 1.2;
}

.visual-label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.72);
}

/* ========== 统计数据 ========== */
.stats-section {
  margin-bottom: 60px;
  padding: 0 20px;
}

.section-header {
  text-align: left;
  margin-bottom: 28px;
}

.section-header.center {
  text-align: center;
}

.section-tag {
  display: inline-block;
  padding: 6px 16px;
  background: linear-gradient(135deg, #e0e7ff, #f3e8ff);
  color: #4f46e5;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 14px;
}

.section-title {
  font-size: 30px;
  font-weight: 800;
  color: var(--text-primary);
  margin: 0 0 10px;
  letter-spacing: -0.5px;
}

.section-desc {
  font-size: 15px;
  color: var(--text-secondary);
  margin: 0;
  line-height: 1.6;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
}

.stat-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 26px 24px;
  background: var(--card-bg);
  border-radius: 18px;
  box-shadow: var(--card-shadow);
  overflow: hidden;
  opacity: 0;
  animation: cardFadeIn 0.6s ease-out forwards;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}

.stat-item:hover {
  transform: translateY(-4px);
  box-shadow: var(--card-hover-shadow);
}

.stat-trend {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  opacity: 0;
  transition: opacity 0.3s ease;
}

.stat-item:hover .stat-trend {
  opacity: 1;
}

.stat-trend.stat-blue { background: linear-gradient(90deg, #60a5fa, #3b82f6); }
.stat-trend.stat-purple { background: linear-gradient(90deg, #a78bfa, #7c3aed); }
.stat-trend.stat-orange { background: linear-gradient(90deg, #fbbf24, #f97316); }
.stat-trend.stat-green { background: linear-gradient(90deg, #34d399, #059669); }

.stat-icon {
  width: 54px;
  height: 54px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: transform 0.3s ease;
}

.stat-item:hover .stat-icon {
  transform: scale(1.08) rotate(-4deg);
}

.stat-blue { background: linear-gradient(135deg, #dbeafe, #bfdbfe); color: #2563eb; }
.stat-purple { background: linear-gradient(135deg, #ede9fe, #ddd6fe); color: #7c3aed; }
.stat-green { background: linear-gradient(135deg, #d1fae5, #a7f3d0); color: #059669; }
.stat-orange { background: linear-gradient(135deg, #ffedd5, #fed7aa); color: #ea580c; }

.stat-info { flex: 1; }

.stat-value {
  font-size: 30px;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.stat-unit {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-left: 3px;
}

.stat-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-top: 6px;
}

.stat-sub {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 3px;
}

/* ========== 功能模块 ========== */
.modules-section {
  margin-bottom: 60px;
  padding: 0 20px;
}

.modules-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 20px;
}

.module-card {
  position: relative;
  background: var(--card-bg);
  border-radius: 20px;
  padding: 28px;
  box-shadow: var(--card-shadow);
  transition: transform 0.35s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.35s cubic-bezier(0.4, 0, 0.2, 1);
  border: 1px solid transparent;
  overflow: hidden;
  opacity: 0;
  animation: cardFadeIn 0.6s ease-out forwards;
}

@keyframes cardFadeIn {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.module-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: var(--card-accent, #3b82f6);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform 0.4s ease;
}

.module-card:hover {
  transform: translateY(-5px);
  box-shadow: var(--card-hover-shadow);
}

.module-card:hover::before {
  transform: scaleX(1);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}

.module-icon {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.3s ease;
}

.mod-blue { background: #dbeafe; color: #2563eb; }
.mod-cyan { background: #cffafe; color: #0891b2; }
.mod-green { background: #d1fae5; color: #059669; }
.mod-teal { background: #ccfbf1; color: #0d9488; }
.mod-indigo { background: #e0e7ff; color: #4f46e5; }
.mod-purple { background: #ede9fe; color: #7c3aed; }
.mod-orange { background: #ffedd5; color: #ea580c; }

.module-card:hover .module-icon {
  transform: scale(1.1) rotate(-6deg);
}

.module-num {
  font-size: 32px;
  font-weight: 800;
  color: var(--text-secondary);
  opacity: 0.15;
  line-height: 1;
  transition: all 0.3s ease;
}

.module-card:hover .module-num {
  opacity: 0.3;
  color: var(--card-accent, #3b82f6);
}

.module-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 10px;
}

.module-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.7;
  margin: 0 0 16px;
}

.module-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 20px;
}

.tag-dot {
  padding: 4px 12px;
  background: var(--bg-secondary, #f3f4f6);
  border-radius: 8px;
  font-size: 12px;
  color: var(--text-secondary);
  transition: all 0.3s ease;
}

.module-card:hover .tag-dot {
  background: var(--card-accent, #3b82f6);
  color: white;
}

.module-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 16px;
  border-top: 1px solid var(--border-color, #e5e7eb);
  font-size: 13px;
  font-weight: 600;
  color: var(--card-accent, #3b82f6);
}

.feature-dots {
  display: flex;
  gap: 6px;
}

.feature-dots .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--card-accent, #3b82f6);
  opacity: 0.4;
}

.feature-dots .dot:nth-child(2) {
  opacity: 0.7;
}

.feature-dots .dot:nth-child(3) {
  opacity: 1;
}

/* 模块卡片的主题色变量 */
.module-card:nth-child(1) { --card-accent: #2563eb; }
.module-card:nth-child(2) { --card-accent: #0891b2; }
.module-card:nth-child(3) { --card-accent: #059669; }
.module-card:nth-child(4) { --card-accent: #0d9488; }
.module-card:nth-child(5) { --card-accent: #4f46e5; }
.module-card:nth-child(6) { --card-accent: #7c3aed; }
.module-card:nth-child(7) { --card-accent: #ea580c; }

/* ========== 三条路线（SVG 分支流程图） ========== */
.workflow-section {
  padding: 0 20px;
}

.flow-container {
  margin-top: 36px;
  background: var(--card-bg);
  border-radius: 20px;
  padding: 32px 20px 24px;
  box-shadow: var(--card-shadow);
  border: 1px solid var(--border-color, #e5e7eb);
  overflow: hidden;
}

.flow-svg {
  display: block;
  width: 100%;
  height: auto;
}

/* 移动端降级列表（默认隐藏，窄屏显示） */
.flow-list {
  display: none;
}

/* ========== 响应式适配 ========== */
@media (max-width: 1280px) {
  .hero-visual {
    right: 32px;
  }
}

@media (max-width: 1080px) {
  .hero-visual {
    display: none;
  }

  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  /* SVG 流程图窄屏隐藏，降级为纵向列表 */
  .flow-svg {
    display: none;
  }

  .flow-list {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .flow-item {
    padding: 16px 18px;
    border-radius: 14px;
    background: var(--bg-secondary, #f3f4f6);
    border-left: 4px solid;
  }

  .flow-a { border-color: #0d9488; }
  .flow-b { border-color: #7c3aed; }
  .flow-c { border-color: #ea580c; }

  .flow-item-title {
    font-size: 14px;
    font-weight: 700;
    color: var(--text-primary);
    margin-bottom: 8px;
  }

  .flow-item-steps {
    font-size: 13px;
    line-height: 1.8;
    color: var(--text-secondary);
  }

  .flow-item-tags {
    margin-top: 8px;
  }

  .flow-item-tags span {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    background: var(--card-bg);
    color: var(--text-secondary);
  }
}

@media (max-width: 768px) {
  .hero-section {
    padding: 40px 24px 60px;
    border-radius: 16px;
  }

  .hero-title {
    font-size: 32px;
  }

  .hero-desc {
    font-size: 14px;
  }

  .hero-actions {
    flex-direction: column;
  }

  .btn-primary {
    width: 100%;
  }

  .stats-grid {
    grid-template-columns: 1fr;
  }

  .section-title {
    font-size: 24px;
  }

  .modules-grid {
    grid-template-columns: 1fr;
  }
}
</style>
