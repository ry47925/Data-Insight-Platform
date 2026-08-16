import axios from 'axios'
import { ElMessage } from 'element-plus'

const adminApi = axios.create({
  baseURL: '/admin',
  timeout: 30000
})

const ADMIN_TOKEN_KEY = 'di_admin_token'

export const adminAuthStore = {
  token: localStorage.getItem(ADMIN_TOKEN_KEY) || '',
  isLoggedIn: !!localStorage.getItem(ADMIN_TOKEN_KEY)
}

export function getAdminToken() {
  return adminAuthStore.token
}

export function isAdminLoggedIn() {
  return adminAuthStore.isLoggedIn
}

export function setAdminToken(token) {
  localStorage.setItem(ADMIN_TOKEN_KEY, token)
  adminAuthStore.token = token
  adminAuthStore.isLoggedIn = true
}

export function clearAdminToken() {
  localStorage.removeItem(ADMIN_TOKEN_KEY)
  adminAuthStore.token = ''
  adminAuthStore.isLoggedIn = false
}

adminApi.interceptors.request.use(
  (config) => {
    const token = getAdminToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

adminApi.interceptors.response.use(
  (response) => {
    return response
  },
  (error) => {
    if (error.response && error.response.status === 401) {
      // 已在登录页时不重复跳转,避免死循环和重复提示
      if (!window.location.hash.startsWith('#/login')) {
        ElMessage.error('登录状态已失效，请重新登录')
        clearAdminToken()
        // 使用 hash 路由跳转到管理员登录页,携带 redirect 参数便于登录后返回原页面
        const currentPath = window.location.hash.slice(1) || '/'
        window.location.href = `#/login?redirect=${encodeURIComponent(currentPath)}`
      }
    }
    return Promise.reject(error)
  }
)

export function adminLogin(username, password) {
  return adminApi.post('/auth/login', { username, password })
}

export function getServicesStatus() {
  return adminApi.get('/services/status')
}

export function getServicesMetrics() {
  return adminApi.get('/services/metrics')
}

export function startService(serviceName) {
  return adminApi.post(`/services/${serviceName}/start`)
}

export function stopService(serviceName) {
  return adminApi.post(`/services/${serviceName}/stop`)
}

export function restartAllServices() {
  return adminApi.post('/services/restart-all')
}

export function getCacheStats() {
  return adminApi.get('/cache/stats')
}

export function listCacheKeys(prefix = '', page = 1, pageSize = 100) {
  return adminApi.get('/cache/keys', { params: { prefix, page, page_size: pageSize } })
}

export function getCacheKeyDetail(key) {
  return adminApi.get(`/cache/keys/${key}`)
}

export function deleteCacheKey(key) {
  return adminApi.delete(`/cache/keys/${key}`)
}

export function clearAllCache() {
  return adminApi.post('/cache/clear')
}

export function getStorageStats() {
  return adminApi.get('/storage/stats')
}

// 获取存储按类型分类统计
export function getStorageStatsByType() {
  return adminApi.get('/storage/stats-by-type')
}

// 获取缓存命中率（支持时间范围 24h/7d/30d）
export function getCacheHitRate(range = '24h') {
  return adminApi.get('/cache/hit-rate', { params: { range } })
}

// 获取缓存键按业务分类全量统计（后端聚合）
export function getCacheCategoryStats() {
  return adminApi.get('/cache/category-stats')
}

// 按业务分类清理缓存
export function clearCacheCategory(category) {
  return adminApi.post('/cache/clear-category', { category })
}

// 删除历史缓存统计（cache_stats_hourly 表）；不传 start/end 时清空全部
export function deleteCacheHistory(start = '', end = '') {
  const params = {}
  if (start) params.start = start
  if (end) params.end = end
  return adminApi.delete('/cache/history', { params })
}

export function listStorageFiles(prefix = '', page = 1, pageSize = 100, fileType = '', userId = 0, keyword = '') {
  const params = { prefix, page, page_size: pageSize }
  if (fileType) params.file_type = fileType
  if (userId) params.user_id = userId
  if (keyword) params.keyword = keyword
  return adminApi.get('/storage/files', { params })
}

export function deleteStorageFile(filePath) {
  return adminApi.delete('/storage/files', { params: { file_path: filePath } })
}

export function batchDeleteStorageFiles(filePaths) {
  return adminApi.post('/storage/files/batch-delete', { file_paths: filePaths })
}

export function listDatabaseTables() {
  return adminApi.get('/database/tables')
}

export function getTableData(tableName, limit = 50, offset = 0, search = null) {
  const params = { limit, offset }
  if (search) params.search = search
  return adminApi.get(`/database/tables/${tableName}/data`, { params })
}

export function exportTableData(tableName, search = null) {
  const params = {}
  if (search) params.search = search
  return adminApi.get(`/database/tables/${tableName}/export`, {
    params,
    responseType: 'blob'
  })
}

export function executeQuery(query) {
  return adminApi.post('/database/query', { query })
}

export function listClickHouseDatabases() {
  return adminApi.get('/clickhouse/databases')
}

export function listClickHouseTables(database = 'default') {
  return adminApi.get('/clickhouse/tables', { params: { database } })
}

export function executeClickHouseQuery(query) {
  return adminApi.post('/clickhouse/query', { query })
}

// ============ ClickHouse 同步管理（2026-08-16 新增，批次D）============
export function getClickHouseSyncStatus() {
  return adminApi.get('/clickhouse/sync-status')
}

export function syncClickHouseDataset(datasetId) {
  return adminApi.post(`/clickhouse/sync/${datasetId}`)
}

export function cleanupClickHouseDataset(datasetId) {
  return adminApi.post(`/clickhouse/cleanup/${datasetId}`)
}

export function cleanupAllClickHouse() {
  return adminApi.post('/clickhouse/cleanup-all')
}

export function getClickHouseStorageStats() {
  return adminApi.get('/clickhouse/storage-stats')
}

export function backupDatabase() {
  // 大库备份耗时可能超过默认 30s 超时，单独放宽到 180s（对齐后端 pg_dump 超时）
  return adminApi.get('/database/backup', { responseType: 'blob', timeout: 180000 })
}

export function getTaskStats() {
  return adminApi.get('/tasks/stats')
}

// ===== 业务数据查询 API（对接 /admin/business/* 接口）=====

// 查询所有用户的数据集业务记录，支持 user_id/module_source/status 筛选和分页
export function listBusinessDatasets(params = {}) {
  return adminApi.get('/business/datasets', { params })
}

// 恢复 purged 状态的数据集到 deleted（用户端回收站可见）
export function restorePurgedDataset(datasetId) {
  return adminApi.post(`/business/datasets/${datasetId}/restore`)
}

// 管理端物理删除数据集（不可恢复）
export function adminPermanentDeleteDataset(datasetId) {
  return adminApi.delete(`/business/datasets/${datasetId}/permanent-delete`)
}

// ===== 数据源连接管理 API（对接 /admin/datasource-connections/*）=====

// 管理端：查看所有用户的数据源连接（密码脱敏）
export function listAdminDataSourceConnections(params = {}) {
  return adminApi.get('/datasource-connections', { params })
}

// 管理端：测试指定数据源连接连通性
export function testAdminDataSourceConnection(connId) {
  return adminApi.post(`/datasource-connections/${connId}/test`)
}

// 管理端：删除数据源连接（有活跃引用时拒绝）
export function deleteAdminDataSourceConnection(connId) {
  return adminApi.delete(`/datasource-connections/${connId}`)
}

// 获取业务数据统计（按用户/模块/状态分组）
export function getBusinessStats() {
  return adminApi.get('/business/stats')
}

// 查询用户端实际操作的业务任务历史，支持 module_source/user_id 筛选和分页
export function listBusinessTasks(params = {}) {
  return adminApi.get('/business/tasks', { params })
}

// 获取业务任务统计（按模块/用户/日分组）
export function getBusinessTaskStats() {
  return adminApi.get('/business/task-stats')
}

// 管理端任务详情（含 params/result_summary/error_message 完整信息，供详情抽屉）
export function getTaskDetail(recordId) {
  return adminApi.get(`/tasks/${recordId}`)
}

// 管理端取消异步任务（pending/running 可取消，绕过用户归属校验，标注原任务记录）
export function adminCancelTask(recordId, note = '') {
  return adminApi.post(`/tasks/${recordId}/cancel`, { note })
}

// 管理端重试失败任务（仅 failed 可重试，retry_history 记录 operator=admin）
export function adminRetryTask(recordId) {
  return adminApi.post(`/tasks/${recordId}/retry`)
}

// 获取数据概览
export function getOverview() {
  return adminApi.get('/overview')
}

// AI 用量统计（2026-08-15 新增：汇总/按模块/按用户/近30天趋势）
export function getAIUsageStats() {
  return adminApi.get('/ai-usage/stats')
}

// 数据大屏聚合数据（2026-08-15 新增：一次请求渲染整屏）
export function getDashboardData() {
  return adminApi.get('/dashboard')
}

// 用户管理
export function listUsers(params = {}) {
  return adminApi.get('/users', { params })
}

export function getUsersStats() {
  return adminApi.get('/users/stats')
}

export function updateUserStatus(userId, isActive) {
  return adminApi.put(`/users/${userId}/status`, { is_active: isActive })
}

export function resetUserPassword(userId, newPassword = null) {
  return adminApi.post(`/users/${userId}/reset-password`, { new_password: newPassword })
}

export function unlockUser(userId) {
  return adminApi.post(`/users/${userId}/unlock`)
}

// ====== 用户申请（联系管理员） ======
export function listSupportMessages(params = {}) {
  return adminApi.get('/users/messages', { params })
}

export function processSupportMessage(messageId, adminNote) {
  return adminApi.post(`/users/messages/${messageId}/process`, { admin_note: adminNote })
}

export function deleteSupportMessage(messageId) {
  return adminApi.delete(`/users/messages/${messageId}`)
}

// 下载存储文件（供申请截图预览，返回 blob）
export function downloadStorageFile(filePath) {
  return adminApi.get(`/storage/files/download/${encodeURIComponent(filePath)}`, {
    responseType: 'blob'
  })
}

// 运行日志
export function listLogs(params = {}) {
  return adminApi.get('/logs', { params })
}

export function listLogFiles() {
  return adminApi.get('/logs/files')
}

// 运行日志概览（今日错误/警告数 + 文件占用，供概览卡）
export function getLogSummary() {
  return adminApi.get('/logs/summary')
}

// 错误/警告趋势（24h/7d，基于 log_records 表）
export function getLogTrend(range = '24h') {
  return adminApi.get('/logs/trend', { params: { range } })
}

// 导出筛选后的日志（blob）
export function exportLogs(params = {}) {
  return adminApi.get('/logs/export', { params, responseType: 'blob' })
}

export default adminApi