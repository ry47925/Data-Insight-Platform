<template>
  <div>
    <!-- 存储状态 -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">存储状态</div>
        <div class="flex-center" style="gap:10px;">
          <el-tag :type="stats.minio_available ? 'success' : 'danger'">
            {{ stats.minio_available ? 'MinIO 可用' : 'MinIO 不可用' }}
          </el-tag>
        </div>
      </div>
      <el-descriptions :column="3" border>
        <el-descriptions-item label="存储后端">
          <el-tag :type="stats.minio_available ? 'success' : 'warning'">
            {{ stats.minio_available ? 'MinIO' : '本地存储' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="存储类型">
          {{ stats.storage_type || '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="备注">
          {{ stats.minio_available ? 'MinIO 对象存储已启用' : '已降级为本地文件存储' }}
        </el-descriptions-item>
      </el-descriptions>
    </div>

    <!-- 文件存储统计卡片 -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">分类统计（点击筛选）</div>
      </div>
      <!-- 路径与用户端Tab对应关系说明 -->
      <el-alert type="info" :closable="false" show-icon style="margin-bottom: 12px;">
        <template #title>路径与用户端Tab对应关系</template>
        <div style="font-size: 12px; line-height: 1.8; color: #606266;">
          uploads → 用户端[原始数据] Tab ｜ cleaning → [数据清洗产物] ｜ data_mining → [数据挖掘产物]<br/>
          feature_engineering → [特征工程产物] ｜ models → [机器学习产物]（模型文件） ｜ ml → [机器学习预测数据]<br/>
          reports → [数据分析报告] ｜ trash → 存储用户回收站中的数据文件，可用于恢复用户端回收站
        </div>
      </el-alert>
      <div class="stats-grid" style="grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));">
        <div v-for="(item, key) in typeStats" :key="key" class="stat-card"
             :class="{ 'stat-card-active': selectedType === key }"
             style="cursor: pointer;" @click="filterByType(key)">
          <div class="stat-value">{{ item.label }}</div>
          <div class="stat-count">{{ item.count }}</div>
          <div style="font-size: 12px; color: #6b7280; margin-top: 4px;">
            路径: {{ key }}
          </div>
          <div style="font-size: 12px; color: #9ca3af; margin-top: 2px;">
            {{ formatSize(item.total_size) }}
          </div>
        </div>
      </div>
    </div>

    <!-- 文件列表 -->
    <div class="card">
      <div class="card-header">
        <div class="card-title">文件列表</div>
        <div class="flex-center" style="gap:10px;">
          <el-select v-model="selectedType" placeholder="按类型筛选" clearable style="width:150px;" @change="loadFiles">
            <el-option label="全部" value="" />
            <el-option label="原始数据" value="uploads" />
            <el-option label="数据清洗产物" value="cleaning" />
            <el-option label="数据挖掘产物" value="data_mining" />
            <el-option label="特征工程产物" value="feature_engineering" />
            <el-option label="ML模型" value="models" />
            <el-option label="预测结果" value="ml" />
            <el-option label="分析报告" value="reports" />
            <el-option label="回收站" value="trash" />
            <el-option label="其他" value="other" />
          </el-select>
          <el-select v-model="selectedUserId" placeholder="按用户筛选" clearable filterable style="width:150px;" @change="loadFiles">
            <el-option v-for="u in userList" :key="u.id" :label="u.username" :value="u.id" />
          </el-select>
          <el-input v-model="searchKeyword" placeholder="搜索文件名" clearable style="width:160px;" @keyup.enter="loadFiles" @clear="loadFiles" />
          <el-button size="small" @click="loadFiles">
            <el-icon><Search /></el-icon> 查询
          </el-button>
          <span class="text-sm" style="color: #9ca3af;">自动刷新</span>
          <el-switch v-model="autoRefresh" @change="autoRefresh ? startAutoRefresh() : stopAutoRefresh()" />
          <el-button size="small" @click="immediateRefresh">
            <el-icon><Refresh /></el-icon> 刷新
          </el-button>
        </div>
      </div>
      <div class="table-toolbar" style="margin-bottom: 10px; display: flex; align-items: center; gap: 10px;">
        <el-button 
          type="danger" 
          size="small" 
          :disabled="selectedFiles.length === 0"
          @click="handleBatchDelete"
        >
          <el-icon><Delete /></el-icon> 批量删除 ({{ selectedFiles.length }})
        </el-button>
        <span style="color: var(--text-muted); font-size: 12px;">删除将同时清除文件存储和数据库中所有关联记录</span>
      </div>
      <div class="data-table-wrapper">
        <el-table 
          :data="files" 
          border 
          v-loading="filesLoading"
          @selection-change="handleSelectionChange"
        >
          <el-table-column type="selection" width="50" align="center" />
          <el-table-column prop="name" label="文件名" min-width="200" />
          <el-table-column prop="path" label="路径" min-width="300" />
          <el-table-column label="大小" width="120">
            <template #default="scope">
              {{ formatSize(scope.row.size) }}
            </template>
          </el-table-column>
          <el-table-column label="修改时间" width="180">
            <template #default="scope">
              {{ formatTime(scope.row.modified_time) }}
            </template>
          </el-table-column>
          <el-table-column prop="content_type" label="类型" width="120" />
          <el-table-column label="操作" width="150">
            <template #default="scope">
              <el-button size="small" @click="downloadFile(scope.row.path)">下载</el-button>
              <el-button size="small" type="danger" @click="deleteFile(scope.row.path)">删除</el-button>
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
          @current-change="loadFiles"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { Search, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getStorageStats, listStorageFiles, deleteStorageFile, batchDeleteStorageFiles, getStorageStatsByType, listUsers, downloadStorageFile } from '../../api/admin.js'
import { useAutoRefresh } from '../../composables/useAutoRefresh.js'

const stats = ref({})
// 分类统计标签需与 backend/app/api/admin.py get_storage_stats_by_type 中的 type_mapping 保持一致
const typeStats = ref({
  uploads: { count: 0, total_size: 0, label: '原始数据' },
  cleaning: { count: 0, total_size: 0, label: '数据清洗产物' },
  data_mining: { count: 0, total_size: 0, label: '数据挖掘产物' },
  feature_engineering: { count: 0, total_size: 0, label: '特征工程产物' },
  models: { count: 0, total_size: 0, label: 'ML模型' },
  ml: { count: 0, total_size: 0, label: '预测结果' },
  reports: { count: 0, total_size: 0, label: '分析报告' },
  trash: { count: 0, total_size: 0, label: '回收站' },
  other: { count: 0, total_size: 0, label: '其他' }
})
const files = ref([])
const filesLoading = ref(false)
const searchKeyword = ref('')
const selectedType = ref('')
const selectedUserId = ref('')
const userList = ref([])
const page = ref(1)
const pageSize = ref(100)
const total = ref(0)
const selectedFiles = ref([])

const { autoRefresh, immediateRefresh, startAutoRefresh, stopAutoRefresh } = useAutoRefresh(loadFilesTab)

function formatSize(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(2) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(2) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB'
}

function formatTime(dateStr) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  if (isNaN(date.getTime())) return dateStr
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  }).format(date)
}

function filterByType(type) {
  selectedType.value = selectedType.value === type ? '' : type
  loadFiles()
}

async function loadStats() {
  try {
    const res = await getStorageStats()
    stats.value = res.data
  } catch (e) {
    console.error('获取存储统计失败:', e)
  }
}

async function loadTypeStats() {
  try {
    const res = await getStorageStatsByType()
    const apiStats = res.data.type_stats || {}
    Object.keys(typeStats.value).forEach(key => {
      const stat = apiStats[key] || {}
      typeStats.value[key].count = stat.count || 0
      typeStats.value[key].total_size = stat.total_size || 0
    })
  } catch (e) {
    console.error('获取分类统计失败:', e)
  }
}

async function loadUsers() {
  try {
    const res = await listUsers({ page: 1, page_size: 100 })
    userList.value = res.data.users || []
  } catch (e) {
    console.error('获取用户列表失败:', e)
  }
}

function getApiFileType(type) {
  return type
}

async function loadFiles() {
  filesLoading.value = true
  try {
    const apiFileType = selectedType.value ? getApiFileType(selectedType.value) : ''
    // keyword 传后端全量搜索，避免只过滤当前页；total 用后端返回的真实总数
    const res = await listStorageFiles('', page.value, pageSize.value, apiFileType, selectedUserId.value, searchKeyword.value)
    files.value = res.data.files || []
    total.value = res.data.total || 0
  } catch (e) {
    console.error('获取文件列表失败:', e)
  } finally {
    filesLoading.value = false
  }
}

async function loadFilesTab() {
  await Promise.all([loadStats(), loadTypeStats(), loadFiles()])
}

async function downloadFile(filePath) {
  try {
    // 用 axios blob 下载（自动携带 Authorization 头），不能用 <a> 直链（直链不带 token 会 401）
    const res = await downloadStorageFile(filePath)
    const blob = res.data
    // 优先从 Content-Disposition 解析文件名，否则用路径最后一段
    const disposition = res.headers?.['content-disposition'] || ''
    const match = disposition.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i)
    const filename = decodeURIComponent((match && (match[1] || match[2])) || '') || filePath.split('/').pop() || 'download'
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error('下载失败：' + (e?.response?.data?.detail || e?.message || e))
  }
}

async function deleteFile(filePath) {
  try {
    await ElMessageBox.confirm(
      '确定要删除该文件吗？删除将同时清除该文件在数据库中的所有关联记录（数据集、任务记录等），此操作不可恢复！',
      '确认删除',
      { type: 'warning', confirmButtonText: '确定删除', cancelButtonText: '取消' }
    )
    await deleteStorageFile(filePath)
    ElMessage.success('删除成功')
    selectedFiles.value = []
    loadFiles()
    loadTypeStats()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败：' + (e?.message || e))
    }
  }
}

function handleSelectionChange(selection) {
  selectedFiles.value = selection
}

async function handleBatchDelete() {
  if (selectedFiles.value.length === 0) return
  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${selectedFiles.value.length} 个文件吗？删除将同时清除这些文件在数据库中的所有关联记录，此操作不可恢复！`,
      '批量删除确认',
      { type: 'warning', confirmButtonText: '确定删除', cancelButtonText: '取消' }
    )
    const filePaths = selectedFiles.value.map(f => f.path)
    const res = await batchDeleteStorageFiles(filePaths)
    ElMessage.success(res.data?.message || `成功删除 ${res.data?.deleted_count || 0} 个文件`)
    selectedFiles.value = []
    loadFiles()
    loadTypeStats()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error('批量删除失败：' + (e?.message || e))
    }
  }
}

onMounted(() => {
  loadFilesTab()
  loadUsers()
})
</script>

<style scoped>
.card {
  margin-bottom: 16px;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #ebeef5;
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.flex-center {
  display: flex;
  align-items: center;
}

.stats-grid {
  display: grid;
  gap: 12px;
  padding: 16px;
}

.stat-card {
  background: #fff;
  padding: 16px;
  border-radius: 8px;
  border: 2px solid transparent;
  transition: all 0.2s;
  text-align: center;
}

.stat-card:hover {
  border-color: #e4e7ed;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.stat-card-active {
  border-color: #409eff;
  background: #ecf5ff;
}

.stat-value {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.stat-count {
  font-size: 24px;
  font-weight: 600;
  color: #409eff;
  margin-top: 4px;
}

.stat-label {
  font-size: 12px;
  color: #606266;
  margin-top: 4px;
}

.data-table-wrapper {
  padding: 0;
}

.flex-between {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>