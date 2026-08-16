// 平台使用说明：模块配置 + MD 内容
// MD 文件通过 Vite `?raw` 导入，保持纯 Markdown 格式，便于维护与二次编辑

import overview from './overview.md?raw'
import dataManagement from './data-management.md?raw'
import dataAnalysis from './data-analysis.md?raw'
import cleaning from './cleaning.md?raw'
import mining from './mining.md?raw'
import feature from './feature.md?raw'
import ml from './ml.md?raw'
import ai from './ai.md?raw'
import taskHistory from './task-history.md?raw'

// 模块顺序即左侧 Tab 展示顺序；icon 为 @element-plus/icons-vue 组件名
export const GUIDE_MODULES = [
  { key: 'overview', label: '平台总览', icon: 'HomeFilled' },
  { key: 'data_management', label: '数据管理', icon: 'Coin' },
  { key: 'data_analysis', label: '数据分析', icon: 'Histogram' },
  { key: 'cleaning', label: '数据清洗', icon: 'MagicStick' },
  { key: 'mining', label: '数据挖掘', icon: 'Search' },
  { key: 'feature', label: '特征工程', icon: 'Setting' },
  { key: 'ml', label: '机器学习', icon: 'Cpu' },
  { key: 'ai', label: 'AI分析', icon: 'ChatDotRound' },
  { key: 'task_history', label: '操作历史', icon: 'Timer' }
]

// 各模块 MD 内容映射（key 与 GUIDE_MODULES.key 对应）
export const GUIDE_CONTENT = {
  overview,
  data_management: dataManagement,
  data_analysis: dataAnalysis,
  cleaning,
  mining,
  feature,
  ml,
  ai,
  task_history: taskHistory
}
