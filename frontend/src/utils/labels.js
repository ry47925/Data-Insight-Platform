// ====== 数据管理/存储 通用标签映射 ======
// 集中维护模块来源、产物类型的中文标签、tag 颜色与图标映射，
// 供 DataManagement.vue / AdminStorage.vue 等共用，避免重复维护。
// 中文标签需与后端 backend/app/utils/task_labels.py 中的 MODULE_LABEL_MAP / ARTIFACT_LABEL_MAP 保持一致。

// 模块来源代码 → 中文显示名
export const MODULE_LABEL_MAP = {
  raw: '原始数据',
  upload: '原始数据',
  data_source: '远程数据库',
  cleaning: '数据清洗',
  ml: '机器学习',
  ai: 'AI分析',
  feature_engineering: '特征工程',
  batch_predict: '机器学习',
  data_analysis: '数据分析',
  data_mining: '数据挖掘',
  pipeline: '流程联动'
}

// 产物类型代码 → 中文显示名
export const ARTIFACT_LABEL_MAP = {
  raw_data: '原始数据',
  analysis_data: '原始数据',
  cleaning_result: '数据清洗产物',
  cluster_result: '聚类结果',
  anomaly_result: '异常检测结果',
  association_rules: '关联规则',
  sequential_patterns: '序列模式',
  ml_model: '机器学习模型',
  ml_report: '机器学习报告',
  ml_prediction: '预测结果',
  predict_data: '预测数据',
  feature_result: '特征工程产物',
  feature_selected: '特征选择',
  analysis_report: '数据分析报告'
}

// 产物类型 → el-tag type
// 注意：Element Plus 的 el-tag type 属性仅接受 ''/success/info/warning/danger（不含 primary），
// 传 primary 会无样式并触发控制台警告
// 映射值为空字符串的类型（raw_data/analysis_data/predict_data）会在 getArtifactTagType 中转为 undefined
export const ARTIFACT_TAG_TYPE_MAP = {
  raw_data: '',
  analysis_data: '',
  cleaning_result: 'success',
  cluster_result: 'warning',
  anomaly_result: 'danger',
  association_rules: 'info',
  sequential_patterns: 'success',
  ml_model: 'info',
  ml_report: 'warning',
  ml_prediction: 'info',
  predict_data: '',
  feature_result: 'success',
  analysis_report: 'warning'
}

// 模块来源 → 图标名（与 App.vue 左侧导航栏保持一致）
export const MODULE_ICON_MAP = {
  raw: 'Folder',
  upload: 'Folder',
  data_source: 'Folder',
  cleaning: 'MagicStick',
  ml: 'Cpu',
  ai: 'ChatDotRound',
  feature_engineering: 'Setting',
  batch_predict: 'Cpu',
  data_analysis: 'Histogram',
  data_mining: 'Search'
}

// 获取模块来源中文标签
export function getModuleLabel(source) {
  return MODULE_LABEL_MAP[source] || source || '未知'
}

// 获取产物类型中文标签
export function getArtifactLabel(type) {
  return ARTIFACT_LABEL_MAP[type] || type || '未知'
}

// 获取产物类型对应的 el-tag 颜色
// 返回 undefined 时 el-tag 使用默认样式，避免传空字符串触发 Element Plus 验证警告
export function getArtifactTagType(type) {
  return ARTIFACT_TAG_TYPE_MAP[type] || undefined
}

// 获取模块来源图标名
export function getModuleIconName(source) {
  return MODULE_ICON_MAP[source] || ''
}

// ====== 失败原因分类标签（与后端 task_labels.py FAILURE_CATEGORY_LABELS 保持一致） ======
// 集中维护 failure_category 的中文标签、tag 颜色与可重试判断，
// 供 TaskHistory.vue 详情抽屉/列表操作列共用，避免重复维护。

// failure_category 代码 → 中文显示名
// 注意：system_error 后端为"系统故障"，与 task_labels.py 保持一致
export const FAILURE_CATEGORY_LABELS = {
  param_error: '参数错误',
  data_error: '数据问题',
  system_error: '系统故障',
  timeout: '执行超时',
  network_error: '网络错误',
  unknown: '未知错误',
}

// failure_category → el-tag type 颜色映射
// param_error/data_error 用 danger（红色，强调需用户介入）
// system_error/timeout/network_error 用 warning（橙色，提示可重试）
// unknown 用 info（灰色）
export const FAILURE_CATEGORY_TAG_TYPE = {
  param_error: 'danger',
  data_error: 'danger',
  system_error: 'warning',
  timeout: 'warning',
  network_error: 'warning',
  unknown: 'info',
}

// 可重试的失败分类集合（与后端 RETRYABLE_FAILURE_CATEGORIES 一致）
// param_error / data_error 不可重试（需修改参数或处理数据后重新执行）
// 其余分类允许重试
const RETRYABLE_FAILURE_CATEGORIES = new Set(['system_error', 'timeout', 'network_error', 'unknown'])

// 获取 failure_category 中文标签，未映射时返回空字符串
export function getFailureCategoryLabel(category) {
  return FAILURE_CATEGORY_LABELS[category] || ''
}

// 获取 failure_category 对应的 el-tag type，未映射时返回 info
export function getFailureCategoryTagType(category) {
  return FAILURE_CATEGORY_TAG_TYPE[category] || 'info'
}

// 判断失败分类是否可重试
// param_error / data_error 不可重试；其余分类视为可重试
// 注意：前端对空值（category 为空）返回 True，兼容历史无分类数据；
// 后端 retry_task 接口会从 error_message 重新分类并做最终拦截，
// 因此前端放宽显示限制不会绕过后端校验。
export function isRetryableFailure(category) {
  if (!category) return true
  return RETRYABLE_FAILURE_CATEGORIES.has(category)
}

// ====== 数据集颜色与 ID 展示（2026-08-13 命名方案） ======
// 命名方案：名称保持用户所起（允许重名），区分靠颜色（按 dataset_id 派生，零存储）+ 创建时间 + #id。
// 色板与后端 backend/app/config.py DATASET_PALETTE 保持一致。

export const DATASET_PALETTE = [
  '#5B4CE0', // 紫
  '#14B8A6', // 青
  '#F25F4A', // 珊瑚
  '#2E9DF0', // 蓝
  '#8B5CF6', // 紫罗兰
  '#F59E0B', // 琥珀
  '#EC4899', // 粉
  '#22C55E', // 绿
  '#6366F1', // 靛
  '#EAB308', // 黄
  '#06B6D4', // 青蓝
  '#F97316', // 橙
]

// 获取数据集颜色：优先后端返回的 color（DatasetResponse 已按 id 派生），否则前端按 id 兜底取色
export function getDatasetColor(dataset) {
  if (dataset && dataset.color) return dataset.color
  const id = dataset && dataset.id
  if (id) return DATASET_PALETTE[id % DATASET_PALETTE.length]
  // 无 id 时按名称哈希兜底（如存储管理文件列表）
  if (dataset && dataset.name) {
    let hash = 0
    for (let i = 0; i < dataset.name.length; i++) hash = (hash * 31 + dataset.name.charCodeAt(i)) >>> 0
    return DATASET_PALETTE[hash % DATASET_PALETTE.length]
  }
  return DATASET_PALETTE[0]
}

// 生成数据集显示名：`名称 #id`（同名数据集靠 #id + 颜色区分）
export function formatDatasetName(dataset) {
  if (!dataset) return ''
  const name = dataset && dataset.name ? dataset.name : ''
  const id = dataset && dataset.id != null ? ` #${dataset.id}` : ''
  return `${name}${id}`
}