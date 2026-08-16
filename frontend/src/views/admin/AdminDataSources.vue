<template>
  <div class="admin-data-sources">
    <!-- 筛选区 -->
    <el-card class="filter-card">
      <div class="filter-row">
        <el-input
          v-model="keyword"
          placeholder="搜索名称 / 主机 / 数据库 / 用户名"
          clearable
          style="width: 280px"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="filterUserId" placeholder="按所属用户筛选" clearable style="width: 200px" @change="handleSearch">
          <el-option v-for="u in userList" :key="u.id" :label="u.username" :value="u.id" />
        </el-select>
        <el-button type="primary" @click="handleSearch">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
      </div>
    </el-card>

    <!-- 连接列表 -->
    <el-card>
      <div class="table-header">
        <span class="table-title">数据源连接列表（{{ pagination.total }} 个）</span>
      </div>
      <el-table :data="connections" border v-loading="loading">
        <el-table-column prop="name" label="连接名称" min-width="150" show-overflow-tooltip />
        <el-table-column label="类型" width="110">
          <template #default="{ row }">
            <el-tag :type="row.db_type === 'mysql' ? 'warning' : 'info'" size="small">
              {{ row.db_type === 'mysql' ? 'MySQL' : 'PostgreSQL' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="host" label="主机" min-width="140" show-overflow-tooltip />
        <el-table-column prop="port" label="端口" width="80" />
        <el-table-column prop="database" label="数据库" min-width="120" show-overflow-tooltip />
        <el-table-column prop="username" label="用户名" width="120" show-overflow-tooltip />
        <el-table-column label="密码" width="90">
          <template #default>
            <span class="masked">••••••</span>
          </template>
        </el-table-column>
        <el-table-column label="所属用户" width="120">
          <template #default="{ row }">
            <span>{{ row.owner_username || '未知用户' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="引用数据集" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.ref_count > 0 ? 'warning' : 'info'" size="small">
              {{ row.ref_count }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="160">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" align="center">
          <template #default="{ row }">
            <el-button size="small" @click="handleTest(row)" :loading="testingId === row.id">测试</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination-wrapper">
        <el-pagination
          @current-change="handleCurrentChange"
          :current-page="pagination.current"
          :page-size="pagination.size"
          layout="total, prev, pager, next, jumper"
          :total="pagination.total"
        />
      </div>
    </el-card>

    <!-- 测试结果弹窗 -->
    <el-dialog v-model="testVisible" title="连接测试结果" width="420px">
      <div v-if="testResult">
        <el-result
          :icon="testResult.success ? 'success' : 'error'"
          :title="testResult.success ? '连接成功' : '连接失败'"
          :sub-title="testResult.message"
        />
      </div>
      <template #footer>
        <el-button @click="testVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listAdminDataSourceConnections, testAdminDataSourceConnection, deleteAdminDataSourceConnection, listUsers } from '../../api/admin.js'

const connections = ref([])
const loading = ref(false)
const keyword = ref('')
const filterUserId = ref('')
const userList = ref([])
const pagination = reactive({ current: 1, size: 20, total: 0 })
const testingId = ref(null)
const testVisible = ref(false)
const testResult = ref(null)

function formatTime(dateStr) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  if (isNaN(date.getTime())) return dateStr
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
  }).format(date)
}

async function loadConnections() {
  loading.value = true
  try {
    const params = { page: pagination.current, page_size: pagination.size }
    if (keyword.value) params.keyword = keyword.value
    if (filterUserId.value) params.user_id = filterUserId.value
    const res = await listAdminDataSourceConnections(params)
    connections.value = res.data.connections || []
    pagination.total = res.data.total || 0
  } catch (e) {
    ElMessage.error('加载数据源连接失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
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

function handleSearch() {
  pagination.current = 1
  loadConnections()
}

function resetFilters() {
  keyword.value = ''
  filterUserId.value = ''
  pagination.current = 1
  loadConnections()
}

function handleCurrentChange(page) {
  pagination.current = page
  loadConnections()
}

async function handleTest(row) {
  testingId.value = row.id
  try {
    const res = await testAdminDataSourceConnection(row.id)
    testResult.value = res.data
    testVisible.value = true
  } catch (e) {
    ElMessage.error('测试失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    testingId.value = null
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定要删除数据源连接「${row.name}」吗？删除后相关数据集将无法再访问远程表。此操作不可恢复！`,
      '删除确认',
      { type: 'warning', confirmButtonText: '确定删除', cancelButtonText: '取消' }
    )
    const res = await deleteAdminDataSourceConnection(row.id)
    ElMessage.success(res.data?.message || '删除成功')
    loadConnections()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error(e.response?.data?.detail || e.message || '删除失败')
    }
  }
}

onMounted(() => {
  loadConnections()
  loadUsers()
})
</script>

<style scoped>
.admin-data-sources {
  padding: 16px;
}
.filter-card {
  margin-bottom: 16px;
}
.filter-row {
  display: flex;
  gap: 12px;
  align-items: center;
}
.table-header {
  margin-bottom: 12px;
}
.table-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.masked {
  color: #909399;
  letter-spacing: 2px;
}
.pagination-wrapper {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
