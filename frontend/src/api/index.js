import axios from 'axios'
import { ElMessage } from 'element-plus'
import { reactive } from 'vue'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
  // 数组参数序列化为 key=val&key=val（不带方括号），兼容 FastAPI Query(list) 多值参数
  paramsSerializer: { indexes: null }
})

// ====== 认证相关工具函数 ======
const TOKEN_KEY = 'di_token'
const USER_KEY = 'di_user'

// 响应式的认证状态（全局共享）
export const authStore = reactive({
  user: null,
  token: '',
  isLoggedIn: false
})

// 初始化认证状态
function initAuth() {
  const token = localStorage.getItem(TOKEN_KEY) || ''
  const userStr = localStorage.getItem(USER_KEY)
  authStore.token = token
  authStore.user = userStr ? JSON.parse(userStr) : null
  authStore.isLoggedIn = !!token
}
initAuth()

// 获取 token
export function getToken() {
  return authStore.token
}

// 判断是否已登录
// 不仅检查 token 是否存在，还解析 JWT 过期时间，避免用过期 token 访问需认证页面时内容闪现
export function isLoggedIn() {
  if (!authStore.isLoggedIn || !authStore.token) return false
  try {
    // JWT 结构：header.payload.signature，payload 是 base64url 编码的 JSON
    const payload = JSON.parse(atob(authStore.token.split('.')[1]))
    // exp 是 Unix 时间戳（秒），需转为毫秒与 Date.now() 比较
    return payload.exp * 1000 > Date.now()
  } catch {
    // token 格式异常（非 JWT 或损坏）视为未登录
    return false
  }
}

// 保存认证信息
export function setAuth(token, userInfo) {
  localStorage.setItem(TOKEN_KEY, token)
  authStore.token = token
  authStore.isLoggedIn = true
  if (userInfo) {
    localStorage.setItem(USER_KEY, JSON.stringify(userInfo))
    authStore.user = userInfo
  }
}

// 更新用户信息
export function updateUserInfo(userInfo) {
  localStorage.setItem(USER_KEY, JSON.stringify(userInfo))
  authStore.user = userInfo
}

// 清除认证信息
export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  authStore.token = ''
  authStore.user = null
  authStore.isLoggedIn = false
}

// 跳转到登录页
function redirectToLogin() {
  clearAuth()
  // 如果已经在登录页，不重复跳转
  if (window.location.hash.startsWith('#/login')) {
    return
  }
  const currentPath = window.location.hash.slice(1) || '/'
  window.location.href = `#/login?redirect=${encodeURIComponent(currentPath)}`
}

// ====== 请求拦截器：自动添加 token ======
api.interceptors.request.use(
  (config) => {
    const token = getToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// ====== 响应拦截器：401 跳转到登录页 ======
// 并发请求同时返回 401 时，通过标志位避免重复提示和重复跳转
let isRedirectingTo401 = false

api.interceptors.response.use(
  (response) => {
    return response
  },
  (error) => {
    if (error.response && error.response.status === 401) {
      // 仅第一个 401 触发提示和跳转，避免并发请求重复弹窗
      if (!isRedirectingTo401) {
        isRedirectingTo401 = true
        // 如果不在登录页时才提示
        if (!window.location.hash.startsWith('#/login')) {
          ElMessage.error('登录状态已失效，请重新登录')
        }
        redirectToLogin()
        // 2 秒后重置标志，允许后续跳转完成
        setTimeout(() => { isRedirectingTo401 = false }, 2000)
      }
    }
    return Promise.reject(error)
  }
)

// ====== 用户认证 API ======
// 登录
export function login(username, password) {
  const formData = new FormData()
  formData.append('username', username)
  formData.append('password', password)
  return api.post('/users/login', formData)
}

// 注册
export function register(username, password) {
  return api.post('/users/register', { username, password })
}

// 获取当前用户信息
export function getCurrentUser() {
  return api.get('/users/me')
}

// 更新用户资料（当前支持修改邮箱）
export function updateProfile(data) {
  return api.put('/users/me', data)
}

// 修改密码（需验证旧密码）
export function changePassword(oldPassword, newPassword) {
  return api.post('/users/change-password', {
    old_password: oldPassword,
    new_password: newPassword
  })
}

// ====== 联系管理员（无需登录） ======
export function getSupportCaptcha() {
  return api.get('/support/captcha')
}

export function uploadSupportImage(file) {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/support/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

export function submitSupportMessage(data) {
  return api.post('/support/messages', data)
}

// 退出登录
export function logout() {
  clearAuth()
  ElMessage.success('已退出登录')
}

// ====== 数据集相关 ======
export function fetchDatasets(params = {}) {
  return api.get('/datasets/', { params })
}

export function fetchDatasetData(id, page = 1, pageSize = 100) {
  return api.get(`/datasets/${id}/data`, { params: { page, page_size: pageSize } })
}

export function deleteDataset(id) {
  return api.delete(`/datasets/${id}`)
}

// 批量删除（移到回收站）
export function batchDeleteDatasets(ids) {
  return api.post('/datasets/batch-delete', { ids })
}

// 回收站列表
export function fetchTrashList() {
  return api.get('/datasets/trash/list')
}

// 从回收站恢复
export function restoreDataset(id) {
  return api.post(`/datasets/trash/restore/${id}`)
}

// 永久删除
export function permanentDeleteDataset(id) {
  return api.delete(`/datasets/trash/${id}`)
}

// 清空回收站
export function clearTrash() {
  return api.delete('/datasets/trash/clear/all')
}

export function updateDataset(id, data) {
  return api.put(`/datasets/${id}`, data)
}

export function getDatasetLineage(id) {
  return api.get(`/datasets/${id}/lineage`)
}

export function exportDataset(id, format, reportType = '') {
  const params = { format }
  if (reportType) params.report_type = reportType
  return api.get(`/datasets/${id}/export`, { params, responseType: 'blob', timeout: 0 })  // 导出大文件不超时
}

export function fetchDatasetsByModule(moduleSource, artifactType = null) {
  const params = {}
  if (moduleSource) params.module_source = moduleSource
  if (artifactType) params.artifact_type = artifactType
  return api.get('/datasets/', { params })
}

export function fetchTaskRecords(params = {}) {
  return api.get('/datasets/task-records', { params })
}

// 取消异步任务
// 参数 taskId 为 Celery 任务 ID（字符串），由异步分发响应返回，前端保存在 trainingTask.taskId 中
export function cancelTask(taskId) {
  return api.post(`/datasets/tasks/${taskId}/cancel`)
}

// 重试失败的异步任务
// 参数 taskId 为 task_records 表主键 ID（前端 taskRecordId），
// 后端会验证任务归属与失败状态后复用原 params 重新提交
export function retryTask(taskId) {
  return api.post(`/datasets/tasks/${taskId}/retry`)
}

// 查询异步任务的实时进度（兼容 ML 训练、清洗、特征工程任务）
// 通过单条记录精确查询接口获取，避免列表接口分页限制导致找不到目标任务。
// 参数 taskRecordId 对应各执行接口返回的 task_record_id。
// 参数 taskType 保留用于兼容已有调用方签名，实际不再需要按类型筛选。
export async function getTaskProgress(taskRecordId, taskType = 'ml_training') {
  const res = await api.get(`/datasets/task-records/${taskRecordId}`)
  return res.data
}

// ====== 清洗模块上传 ======
export function uploadCleaningFile(file) {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/cleaning/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

// 获取清洗模块专用的原始数据列表
export function fetchCleaningRawData() {
  return api.get('/cleaning/raw-data')
}

// 获取清洗预检结果（缺失值/重复行/类型识别/异常值/类型错误）
// 后端返回结构：{ missing_values, duplicate_rows, type_detection, outliers, type_errors }
export function getCleaningPrecheck(datasetId) {
  return api.get(`/cleaning/precheck/${datasetId}`)
}

// 预检（POST版，支持远程数据源）
export function postCleaningPrecheck(body) {
  return api.post('/cleaning/precheck', body)
}

// 执行综合清洗（新契约 + 问题清单 + 管道）
// 参数 data: { dataset_id, contract, pipeline, problem_strategies, force, save_result }
// 返回：
//   - { status: "warning", warnings: [...] }  当 dry_run 检测到警告且 force=false
//   - { status: "success", audit_report: {...}, cleaned_dataset_id: int }  同步执行成功
//   - { status: "queued", task_id: xxx, task_record_id: xxx }  大数据集异步执行
export function executeCleaningComprehensive(data) {
  return api.post(`/cleaning/comprehensive`, data)
}

// 记录清洗向导步骤配置（阶段1契约/阶段2问题清单）
// 参数 data: { dataset_id, step, contract?, problem_strategies? }
// step: 'contract_config' | 'problem_strategy'
export function recordCleaningStep(data) {
  return api.post(`/cleaning/record-step`, data)
}

// dry-run 预检：检查用户配置的管道合理性，不实际执行清洗
// Task 8：在执行清洗前调用，根据返回的 warnings/errors 决定是否阻断或强制执行
// 参数 datasetId: 数据集 ID（远程模式传 0 占位）
// 参数 data: { contract, problem_strategies, pipeline }
// 参数 remote: 远程配置对象（可选），{ use_remote, connection_id, table_name }
// 返回：{ valid: bool, warnings: [...], errors: [...], suggested_order: [...] }
export function dryRunPipeline(datasetId, data, remote = null) {
  const body = { ...data }
  if (remote) body.remote = remote
  const id = datasetId || 0
  return api.post(`/cleaning/dry-run/${id}`, body)
}

// 基于契约分析问题清单（Step 3 问题清单页面使用）
// 参数 datasetId: 数据集 ID（远程模式传 0 占位）
// 参数 contract: buildContract() 构建的契约字典
// 参数 remote: 远程配置对象（可选），{ use_remote, connection_id, table_name }
// 返回：{ summary: {...}, problems: { missing_values, type_errors, range_errors, outliers, row_duplicates, column_duplicates } }
export function analyzeProblems(datasetId, contract, remote = null) {
  const body = { contract: contract }
  if (remote) body.remote = remote
  const id = datasetId || 0
  return api.post(`/cleaning/analyze-problems/${id}`, body)
}

// ====== 机器学习 ======
// 以下 uploadMLFile / fetchMLRawData 为 ML 模块文件上传和数据列表接口,前端实际使用。
// 新版统一训练接口请使用 trainSupervised / batchPredict 等(见文件末尾"ML 模型训练与预测"区块)。
export function uploadMLFile(file) {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/ml/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

// 获取ML模块专用的原始数据列表
export function fetchMLRawData() {
  return api.get('/ml/raw-data')
}

// ====== AI分析 ======
// 智能对话（基于上下文注入的多轮对话）
// contextItems: [{ type: 'dataset'|'operation', ref_id: number }]
// startNewTopic: 是否开始新话题（清空之前上下文关联）
export function aiChat(question, contextItems = [], conversationId = null, datasetId = null, startNewTopic = false) {
  const data = { question, context_items: contextItems }
  if (conversationId) data.conversation_id = conversationId
  if (datasetId) data.dataset_id = datasetId
  if (startNewTopic) data.start_new_topic = true
  return api.post('/ai/chat', data)
}

// 获取上下文项可选项列表（数据产物按模块分组 + 操作记录分页）
// taskPage: 任务记录页码，taskPageSize: 每页条数
// options.isRemote: 数据来源筛选（true=远程，false=本地，缺省=全部）
// options.taskType: 模块筛选（cleaning/data_analysis/data_mining/feature_engineering/ml）
export function fetchContextOptions(taskPage = 1, taskPageSize = 20, options = {}) {
  const params = { task_page: taskPage, task_page_size: taskPageSize, _t: Date.now() }
  if (options.isRemote !== undefined && options.isRemote !== null) params.is_remote = options.isRemote
  if (options.taskType) params.task_type = options.taskType
  // 增加_t时间戳参数，避免浏览器或中间层缓存GET请求
  return api.get('/ai/context/options', { params })
}

// 预览单个上下文项的摘要内容
export function previewContextItem(type, refId) {
  return api.get('/ai/context/preview', { params: { type, ref_id: refId } })
}

// 获取指定数据产物血缘链上的最近操作记录（选产物自动带出血缘操作用）
export function fetchBloodlineOps(datasetId, limit = 10) {
  return api.get('/ai/context/blood-ops', { params: { dataset_id: datasetId, limit } })
}

// ====== AI 产品问答（数据仓库精确问答/预测） ======
// 基于数据目录（多个/全部数据产物）的精确问答：两步选表 → 本地精确计算 → AI 解读
// datasetIds: 数据目录数据集ID列表
// startNewTopic: 是否开始新话题
export function qaChat(question, datasetIds = [], conversationId = null, startNewTopic = false) {
  const data = { question, dataset_ids: datasetIds }
  if (conversationId) data.conversation_id = conversationId
  if (startNewTopic) data.start_new_topic = true
  return api.post('/ai/qa', data)
}

// 构建问答数据目录（轻量 schema 信息，不载入全量数据）
export function buildQaCatalog(datasetIds = []) {
  return api.post('/ai/qa/catalog', { dataset_ids: datasetIds })
}

// 列出用户保存的常驻目录
export function listQaCatalogs() {
  return api.get('/ai/qa/catalogs')
}

// 保存/更新常驻目录（catalog_id 传则更新，不传则新建）
export function saveQaCatalog(data) {
  return api.post('/ai/qa/catalogs', data)
}

// 删除常驻目录
export function deleteQaCatalog(catalogId) {
  return api.delete(`/ai/qa/catalogs/${catalogId}`)
}

// AI配置
export function getAIConfig() {
  return api.get('/ai/config')
}

// 会话管理
export function fetchConversations() {
  return api.get('/ai/conversations')
}

export function fetchConversation(id) {
  return api.get(`/ai/conversations/${id}`)
}

export function deleteConversation(id) {
  return api.delete(`/ai/conversations/${id}`)
}

// 重命名会话（支持重名校验）
export function renameConversation(id, title) {
  return api.patch(`/ai/conversations/${id}/rename`, { title })
}

// 使用统计
export function fetchUsageStats() {
  return api.get('/ai/usage/stats')
}

// ====== 特征工程 ======
// 获取特征工程模块可用的数据集（向后兼容别名）
export function fetchFeatureDatasets() {
  return api.get('/feature_engineering/datasets')
}

// 上传文件到特征工程模块
export function uploadFeatureFile(file) {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/feature_engineering/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

// 构造特征
// remote 通过 query string 传递（JSON字符串），避免与 operations 的 Body 参数冲突
// datasetId 为 null 时（远程模式）不传 dataset_id 参数，避免空字符串导致 Pydantic 422 验证失败
export function constructFeatures(datasetId, operations, remote = null) {
  let url = '/feature_engineering/construct'
  const params = []
  if (datasetId) params.push(`dataset_id=${datasetId}`)
  if (remote) params.push(`remote=${encodeURIComponent(JSON.stringify(remote))}`)
  if (params.length) url += '?' + params.join('&')
  return api.post(url, operations)
}

// 特征选择
// remote 通过 query string 传递（JSON字符串），避免与 config 的 Body 参数冲突
export function selectFeatures(config, remote = null) {
  let url = '/feature_engineering/select-features'
  const params = []
  if (config.dataset_id) params.push(`dataset_id=${config.dataset_id}`)
  if (remote) params.push(`remote=${encodeURIComponent(JSON.stringify(remote))}`)
  if (params.length) url += '?' + params.join('&')
  // 移除 dataset_id 和 remote 字段，只保留其他参数作为 Body
  const { dataset_id, remote: _remote, ...rest } = config
  return api.post(url, rest)
}

// 特征编码
export function encodeFeatures(datasetId, config, remote = null) {
  let url = '/feature_engineering/encode'
  const params = []
  if (datasetId) params.push(`dataset_id=${datasetId}`)
  if (remote) params.push(`remote=${encodeURIComponent(JSON.stringify(remote))}`)
  if (params.length) url += '?' + params.join('&')
  return api.post(url, config)
}

// 特征缩放
export function scaleFeatures(datasetId, config, remote = null) {
  let url = '/feature_engineering/scale'
  const params = []
  if (datasetId) params.push(`dataset_id=${datasetId}`)
  if (remote) params.push(`remote=${encodeURIComponent(JSON.stringify(remote))}`)
  if (params.length) url += '?' + params.join('&')
  return api.post(url, config)
}

// 特征降维
export function reduceFeatures(datasetId, config, remote = null) {
  let url = '/feature_engineering/reduce'
  const params = []
  if (datasetId) params.push(`dataset_id=${datasetId}`)
  if (remote) params.push(`remote=${encodeURIComponent(JSON.stringify(remote))}`)
  if (params.length) url += '?' + params.join('&')
  return api.post(url, config)
}

// 获取单个数据集详情
export function fetchDatasetById(id) {
  return api.get(`/datasets/${id}`)
}

// 获取特征工程数据预览（后端分页）
export function fetchFeatureData(id, page = 1, pageSize = 100) {
  return api.get(`/feature_engineering/data/${id}`, { params: { page, page_size: pageSize } })
}

// 获取数据集列池（可选列列表）
export function fetchColumnPool(datasetId) {
  return api.get(`/feature_engineering/column-pool/${datasetId}`)
}

// 获取远程表当前生效的列池（含特征工程动态新增的构造列，无则回退数据库原始列）
export function fetchRemoteColumnPool(connectionId, tableName) {
  return api.get('/feature_engineering/remote-column-pool', {
    params: { connection_id: connectionId, table_name: tableName }
  })
}

// 预检数据集：检测所有列的数据质量问题，判断 5 类特征工程操作的可行性
// 远程模式：remote 为 {use_remote, connection_id, table_name}，dataset_id 传 0
export function precheckFeatureDataset(datasetId, remote = null) {
  return api.get(`/feature_engineering/precheck/${datasetId}`, {
    params: remote ? { remote: JSON.stringify(remote) } : {}
  })
}

// 删除构造列
// 使用查询参数传递 column_name，避免列名中包含 / 等特殊字符时被当作路径分隔符
export function deleteConstructedColumn(datasetId, columnName) {
  return api.delete(`/feature_engineering/column-pool/${datasetId}`, { params: { column_name: columnName } })
}

// 删除远程表工作副本中的构造列（原始数据库表不受影响）
export function deleteRemoteConstructedColumn(remote, columnName) {
  return api.delete('/feature_engineering/column-pool/0', {
    params: {
      column_name: columnName,
      remote: JSON.stringify(remote)
    }
  })
}

// 重命名列（原始列与构造列均可，本地/远程统一走该接口，持久化到数据文件与 tags）
export function renameFeatureColumn(datasetId, column, newName, remote = null) {
  return api.post('/feature_engineering/rename-column', {
    dataset_id: datasetId,
    column,
    new_name: newName,
    remote: remote || null
  })
}

// 导出特征选择产物
// remote 通过 query string 传递（JSON字符串），避免与 config 的 Body 参数冲突
export function exportSelectedFeatures(config, remote = null) {
  let url = '/feature_engineering/export-selected'
  const params = []
  if (config.dataset_id) params.push(`dataset_id=${config.dataset_id}`)
  if (remote) params.push(`remote=${encodeURIComponent(JSON.stringify(remote))}`)
  if (params.length) url += '?' + params.join('&')
  const { dataset_id, remote: _remote, ...rest } = config
  return api.post(url, rest)
}

// 导出列池产物
// remote 通过 query string 传递（JSON字符串），避免与 config 的 Body 参数冲突
export function exportColumnPool(config, remote = null) {
  let url = '/feature_engineering/export-pool'
  const params = []
  if (config.dataset_id) params.push(`dataset_id=${config.dataset_id}`)
  if (remote) params.push(`remote=${encodeURIComponent(JSON.stringify(remote))}`)
  if (params.length) url += '?' + params.join('&')
  const { dataset_id, remote: _remote, ...rest } = config
  return api.post(url, rest)
}

// ====== ML 模型训练与预测 ======
// 机器学习训练前数据预检(切换数据集自动调用)
export function mlPrecheck(datasetId, remote = null) {
  const body = { dataset_id: datasetId }
  if (remote) body.remote = remote
  return api.post('/ml/precheck', body)
}

// 特征列智能推荐(选择目标列后自动调用)
export function recommendFeatures(datasetId, targetColumn, remote = null) {
  const body = { dataset_id: datasetId, target_column: targetColumn }
  if (remote) body.remote = remote
  return api.post('/ml/recommend-features', body)
}

// 训练有监督学习模型
export function trainSupervised(config) {
  return api.post('/ml/train-supervised', config)
}

// 批量预测
export function batchPredict(modelId, body) {
  return api.post(`/ml/batch-predict/${modelId}`, body)
}

// 列出数据集训练的所有模型（后端分页）
export function listModels(datasetId, page = 1, pageSize = 50) {
  return api.get(`/ml/model-list/${datasetId}`, { params: { page, page_size: pageSize, paginated: true } })
}

// 导出模型文件
export function exportModelFile(modelId) {
  return api.get(`/ml/models/${modelId}/export`, {
    responseType: 'blob'
  })
}

// 测试集独立评估
export function testSetEvaluate(modelId) {
  return api.post(`/ml/models/${modelId}/test-evaluate`)
}

// 导出模型报告到数据管理
export function exportModelReport(modelId) {
  return api.post(`/ml/models/${modelId}/export-report`)
}

// 获取模型报告详细内容
export function fetchModelReport(reportId) {
  return api.get(`/ml/reports/${reportId}`)
}

// ====== 数据分析 ======
export function uploadAnalysisFile(file) {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/data-analysis/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

// 获取数据分析模块专用的原始数据列表
export function fetchAnalysisRawData() {
  return api.get('/data-analysis/raw-data')
}

// 获取数据预览（分页）
// 远程模式：id 传 0 占位，remoteConfig 拆分为 use_remote/connection_id/table_name 三个独立 query 参数
export function fetchAnalysisData(id, page = 1, pageSize = 100, remoteConfig = null) {
  const params = { page, page_size: pageSize }
  if (remoteConfig && remoteConfig.use_remote) {
    params.use_remote = true
    params.connection_id = remoteConfig.connection_id
    params.table_name = remoteConfig.table_name
  }
  const urlId = (remoteConfig && remoteConfig.use_remote) ? 0 : id
  return api.get(`/data-analysis/${urlId}/data`, { params })
}

// 获取统计摘要
export function fetchAnalysisStats(id, remoteConfig = null) {
  const params = {}
  if (remoteConfig && remoteConfig.use_remote) {
    params.use_remote = true
    params.connection_id = remoteConfig.connection_id
    params.table_name = remoteConfig.table_name
  }
  const urlId = (remoteConfig && remoteConfig.use_remote) ? 0 : id
  return api.get(`/data-analysis/${urlId}/statistics`, { params })
}

// 获取数据质量检测结果
export const fetchAnalysisQuality = (id, remoteConfig = null) => {
  const params = {}
  if (remoteConfig && remoteConfig.use_remote) {
    params.use_remote = true
    params.connection_id = remoteConfig.connection_id
    params.table_name = remoteConfig.table_name
  }
  const urlId = (remoteConfig && remoteConfig.use_remote) ? 0 : id
  return api.get(`/data-analysis/${urlId}/quality`, { params })
}

// 获取图表数据
export function fetchChartData(id, config, remoteConfig = null) {
  const body = { ...config }
  if (remoteConfig) {
    body.remote = remoteConfig
  }
  const urlId = (remoteConfig && remoteConfig.use_remote) ? 0 : id
  return api.post(`/data-analysis/${urlId}/chart`, body)
}

// 获取图表智能推荐
export function fetchChartRecommendations(id, columns = null, chart_type = null, remoteConfig = null) {
  const params = {}
  if (columns) params.columns = columns
  if (chart_type) params.chart_type = chart_type
  if (remoteConfig && remoteConfig.use_remote) {
    params.use_remote = true
    params.connection_id = remoteConfig.connection_id
    params.table_name = remoteConfig.table_name
  }
  const urlId = (remoteConfig && remoteConfig.use_remote) ? 0 : id
  return api.get(`/data-analysis/${urlId}/chart-recommendations`, { params })
}

// 数据分析报告（支持传入报告配置与自定义图表）
export const generateAnalysisReport = (id, data = {}, remoteConfig = null) => {
  const body = { ...data }
  if (remoteConfig) {
    body.remote = remoteConfig
  }
  const urlId = (remoteConfig && remoteConfig.use_remote) ? 0 : id
  return api.post(`/data-analysis/${urlId}/report`, body)
}

// 保存分析报告到数据管理模块
export const saveAnalysisReport = (id, body, remoteConfig = null) => {
  const reqBody = { ...body }
  if (remoteConfig) {
    reqBody.remote = remoteConfig
  }
  const urlId = (remoteConfig && remoteConfig.use_remote) ? 0 : id
  return api.post(`/data-analysis/${urlId}/report/save`, reqBody)
}

// ====== 数据挖掘 ======
// 上传文件到数据挖掘模块
export function uploadMiningFile(file) {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/data-mining/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

// 获取数据挖掘模块专用的原始数据列表
export function fetchMiningRawData() {
  return api.get('/data-mining/raw-data')
}

// 聚类分析（支持KMeans/DBSCAN/层次聚类）
export function runDataMiningClustering(datasetId, params) {
  return api.post('/data-mining/cluster', { dataset_id: datasetId, ...params })
}

// 关联规则挖掘（支持Apriori/FP-Growth）
export function runDataMiningAssociationRules(datasetId, params) {
  return api.post('/data-mining/association', { dataset_id: datasetId, ...params })
}

// 序列模式挖掘（支持PrefixSpan/GSP）
export function runDataMiningSequence(datasetId, params) {
  return api.post('/data-mining/sequence', { dataset_id: datasetId, ...params })
}

// 数据预检 + 算法推荐
export function precheckMiningData(datasetId, remote = null) {
  const body = { dataset_id: datasetId }
  if (remote) body.remote = remote
  return api.post('/data-mining/precheck', body)
}

// 参数推荐
export function recommendMiningParams(datasetId, algorithmType, algorithm = null, columns = null, remote = null) {
  const params = { dataset_id: datasetId, algorithm_type: algorithmType }
  if (algorithm) params.algorithm = algorithm
  if (columns) params.columns = columns
  if (remote) params.remote = remote
  return api.post('/data-mining/recommend-params', params)
}

// 获取关联规则详情（分页）
export function fetchAssociationRules(datasetId, page = 1, pageSize = 50) {
  return api.get(`/data-mining/association/${datasetId}`, { params: { page, page_size: pageSize } })
}

// 获取序列模式详情（分页）
export function fetchSequencePatterns(datasetId, page = 1, pageSize = 50) {
  return api.get(`/data-mining/sequence/${datasetId}`, { params: { page, page_size: pageSize } })
}

// ====== 数据源管理 ======
// 获取数据源连接列表
export function fetchDataSources() {
  return api.get('/data-sources/')
}

// 创建数据源连接
export function createDataSource(data) {
  return api.post('/data-sources/', data)
}

// 更新数据源连接
export function updateDataSource(id, data) {
  return api.put(`/data-sources/${id}`, data)
}

// 删除数据源连接
export function deleteDataSource(id) {
  return api.delete(`/data-sources/${id}`)
}

// 测试数据源连接（不保存）
export function testDataSourceConnection(data) {
  return api.post('/data-sources/test', data)
}

// 获取远程数据库表列表
export function fetchDataSourceTables(id) {
  return api.get(`/data-sources/${id}/tables`)
}

// 获取表结构
export function fetchTableSchema(connId, tableName) {
  return api.get(`/data-sources/${connId}/tables/${encodeURIComponent(tableName)}/schema`)
}

// 获取表行数
export function fetchTableCount(connId, tableName) {
  return api.get(`/data-sources/${connId}/tables/${encodeURIComponent(tableName)}/count`)
}

export default api
export { api }