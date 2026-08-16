<template>
  <el-dialog
    v-model="visible"
    title="数据源管理"
    width="750px"
    top="5vh"
    destroy-on-close
    aria-label="数据源管理弹窗"
    @closed="resetState"
  >
    <!-- 连接列表 -->
    <div v-if="!editing && !browsing" class="ds-container">
      <div class="ds-toolbar">
        <el-button type="primary" size="small" @click="startCreate">新建连接</el-button>
      </div>
      <el-table :data="connections" style="width: 100%" size="small" empty-text="暂无数据源连接">
        <el-table-column prop="name" label="名称" min-width="120" />
        <el-table-column prop="db_type" label="类型" width="80" />
        <el-table-column label="地址" min-width="180">
          <template #default="{ row }">{{ row.host }}:{{ row.port }}/{{ row.database }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="startBrowse(row)">浏览表</el-button>
            <el-button type="primary" link size="small" @click="startEdit(row)">编辑</el-button>
            <el-button type="danger" link size="small" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 编辑/新建表单 -->
    <div v-if="editing" class="ds-form">
      <div class="ds-form-title">{{ isCreate ? '新建连接' : '编辑连接' }}</div>
      <el-form :model="form" label-width="100px" size="small">
        <el-form-item label="连接名称" required>
          <el-input v-model="form.name" placeholder="如：生产数据库" />
        </el-form-item>
        <el-form-item label="数据库类型" required>
          <el-select v-model="form.db_type" style="width: 100%">
            <el-option label="MySQL" value="mysql" />
            <el-option label="PostgreSQL" value="postgresql" />
          </el-select>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="16">
            <el-form-item label="主机地址" required>
              <el-input v-model="form.host" placeholder="如：192.168.1.100" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="端口">
              <el-input-number v-model="form.port" :min="1" :max="65535" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="数据库名" required>
          <el-input v-model="form.database" placeholder="数据库名称" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="用户名" required>
              <el-input v-model="form.username" placeholder="数据库用户名" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="密码">
              <el-input v-model="form.password" type="password" show-password placeholder="留空则不修改" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="额外参数">
          <el-input v-model="form.extra_params" placeholder="如：charset=utf8mb4&connect_timeout=10" />
        </el-form-item>
        <el-form-item>
          <el-button @click="handleTestConnection" :loading="testing">测试连接</el-button>
          <span v-if="testResult" :class="testResult.success ? 'test-ok' : 'test-fail'">{{ testResult.message }}</span>
        </el-form-item>
      </el-form>
      <div class="ds-form-actions">
        <el-button @click="cancelEdit">取消</el-button>
        <el-button type="primary" @click="handleSave" :loading="saving">{{ isCreate ? '创建' : '保存' }}</el-button>
      </div>
    </div>

    <!-- 浏览表 -->
    <div v-if="browsing" class="ds-browse">
      <div class="ds-browse-header">
        <el-button type="default" size="small" @click="browsing = false">返回列表</el-button>
        <span class="ds-browse-title">{{ browsingConn.name }} — 表列表</span>
      </div>
      <el-table :data="tables" style="width: 100%" size="small" v-loading="loadingTables" empty-text="暂无表或加载中">
        <el-table-column prop="name" label="表名" min-width="150">
          <template #default="{ row }">{{ row.name }}</template>
        </el-table-column>
        <el-table-column label="行数" width="120" align="right">
          <template #default="{ row }">{{ row.row_count != null ? row.row_count.toLocaleString() : '-' }}</template>
        </el-table-column>
        <el-table-column label="列数" width="80" align="right">
          <template #default="{ row }">{{ row.col_count != null ? row.col_count : '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="handleUseInModule(row)">在模块中使用</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 模块选择弹窗 -->
    <el-dialog
      v-model="moduleDialogVisible"
      title="选择目标模块"
      width="420px"
      append-to-body
      :close-on-click-modal="false"
    >
      <div class="module-list">
        <div
          v-for="m in moduleOptions"
          :key="m.path"
          class="module-item"
          @click="navigateToModule(m)"
        >
          <el-icon :size="20"><component :is="m.icon" /></el-icon>
          <span class="module-name">{{ m.label }}</span>
          <span class="module-desc">{{ m.desc }}</span>
        </div>
      </div>
    </el-dialog>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, watch, markRaw } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Search, DataAnalysis, Setting, TrendCharts, Tools
} from '@element-plus/icons-vue'
import {
  fetchDataSources, createDataSource, updateDataSource, deleteDataSource,
  testDataSourceConnection, fetchDataSourceTables, fetchTableSchema, fetchTableCount,
  isLoggedIn
} from '../api/index.js'

const router = useRouter()

// 模块选项
const moduleOptions = [
  { path: '/cleaning', label: '数据清洗', desc: '数据预检、契约校验、问题清单清洗', icon: markRaw(Search) },
  { path: '/analysis', label: '数据分析', desc: '统计概览、图表可视化、相关分析', icon: markRaw(DataAnalysis) },
  { path: '/ml', label: '机器学习', desc: '分类/回归模型训练与预测', icon: markRaw(Setting) },
  { path: '/mining', label: '数据挖掘', desc: '聚类分析、异常检测、关联规则', icon: markRaw(TrendCharts) },
  { path: '/feature', label: '特征工程', desc: '特征构造、编码、缩放、降维', icon: markRaw(Tools) },
]

const props = defineProps({
  modelValue: Boolean
})
const emit = defineEmits(['update:modelValue', 'use-in-module'])

const visible = ref(false)
watch(() => props.modelValue, (v) => { visible.value = v })
watch(visible, (v) => {
  emit('update:modelValue', v)
  // 弹窗打开时重新加载连接列表，确保登录后或新建连接后能看到最新列表
  // 修复：原 setup 时直接调用 loadConnections，登录前组件已初始化导致列表为空
  if (v && isLoggedIn()) {
    loadConnections()
  }
})

// 状态
const connections = ref([])
const editing = ref(false)
const isCreate = ref(false)
const editingId = ref(null)
const browsing = ref(false)
const browsingConn = ref(null)
const tables = ref([])
const loadingTables = ref(false)
const saving = ref(false)
const testing = ref(false)
const testResult = ref(null)

// 模块选择弹窗
const moduleDialogVisible = ref(false)
// 暂存待使用的远程表信息
const pendingTable = ref(null)

const form = reactive({
  name: '', db_type: 'mysql', host: '', port: 3306,
  database: '', username: '', password: '', extra_params: ''
})

// 加载连接列表
async function loadConnections() {
  // 登录守卫：未登录不请求
  if (!isLoggedIn()) {
    connections.value = []
    return
  }
  try {
    const res = await fetchDataSources()
    connections.value = res.data || []
  } catch {
    connections.value = []
  }
}

// 重置状态
function resetState() {
  editing.value = false
  browsing.value = false
  testResult.value = null
}

// 新建
function startCreate() {
  resetForm()
  isCreate.value = true
  editingId.value = null
  editing.value = true
}

// 编辑
function startEdit(row) {
  resetForm()
  Object.assign(form, {
    name: row.name, db_type: row.db_type, host: row.host,
    port: row.port, database: row.database, username: row.username,
    password: '', extra_params: row.extra_params || ''
  })
  isCreate.value = false
  editingId.value = row.id
  editing.value = true
}

// 取消编辑
function cancelEdit() {
  editing.value = false
  testResult.value = null
}

function resetForm() {
  form.name = ''; form.db_type = 'mysql'; form.host = ''; form.port = 3306
  form.database = ''; form.username = ''; form.password = ''; form.extra_params = ''
  testResult.value = null
}

// 测试连接
async function handleTestConnection() {
  if (!isLoggedIn()) { ElMessage.warning('请先登录'); return }
  testing.value = true
  testResult.value = null
  try {
    const res = await testDataSourceConnection({
      db_type: form.db_type, host: form.host, port: form.port,
      database: form.database, username: form.username, password: form.password,
      extra_params: form.extra_params || null
    })
    testResult.value = res.data
  } catch (e) {
    testResult.value = { success: false, message: '请求失败: ' + (e.response?.data?.message || e.response?.data?.detail || e.message) }
  } finally {
    testing.value = false
  }
}

// 保存
async function handleSave() {
  if (!isLoggedIn()) { ElMessage.warning('请先登录'); return }
  if (!form.name || !form.host || !form.database || !form.username) {
    ElMessage.warning('请填写必填字段')
    return
  }
  saving.value = true
  try {
    const data = { ...form }
    if (isCreate.value) {
      if (!form.password) { ElMessage.warning('新建连接需要填写密码'); saving.value = false; return }
      await createDataSource(data)
      ElMessage.success('连接创建成功')
    } else {
      if (!data.password) delete data.password
      await updateDataSource(editingId.value, data)
      ElMessage.success('连接更新成功')
    }
    editing.value = false
    await loadConnections()
  } catch (e) {
    // 后端异常处理器对字符串 detail 会设置 message 字段（detail 字段为 None）
    // 所以优先取 message，其次 detail，最后 axios 默认消息
    const errMsg = e.response?.data?.message || e.response?.data?.detail || e.message
    ElMessage.error('保存失败: ' + errMsg)
  } finally {
    saving.value = false
  }
}

// 删除
async function handleDelete(row) {
  if (!isLoggedIn()) { ElMessage.warning('请先登录'); return }
  try {
    await ElMessageBox.confirm(`确定要删除连接「${row.name}」吗？`, '删除确认', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
    })
    await deleteDataSource(row.id)
    ElMessage.success('已删除')
    await loadConnections()
  } catch (e) {
    // 取消操作（e === 'cancel' 或 instanceof Error 来自 ElMessageBox）
    if (e !== 'cancel' && e !== 'close' && e?.constructor?.name !== 'Error') {
      const msg = e?.response?.data?.detail || e?.response?.data?.message || e?.message || '删除失败'
      ElMessage.error(typeof msg === 'string' ? msg : '删除失败')
    }
  }
}

// 浏览表
async function startBrowse(row) {
  // 登录守卫
  if (!isLoggedIn()) {
    ElMessage.warning('请先登录')
    return
  }
  browsingConn.value = row
  browsing.value = true
  loadingTables.value = true
  tables.value = []
  try {
    const tableNames = (await fetchDataSourceTables(row.id)).data || []
    const tableInfos = []
    for (const name of tableNames) {
      try {
        const [schemaRes, countRes] = await Promise.all([
          fetchTableSchema(row.id, name),
          fetchTableCount(row.id, name)
        ])
        tableInfos.push({
          name,
          col_count: (schemaRes.data || []).length,
          row_count: countRes.data?.row_count ?? null
        })
      } catch {
        tableInfos.push({ name, col_count: null, row_count: null })
      }
    }
    tables.value = tableInfos
  } catch (e) {
    ElMessage.error('获取表列表失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loadingTables.value = false
  }
}

// 在模块中使用远程表 — 弹出模块选择器
function handleUseInModule(row) {
  pendingTable.value = {
    connection_id: browsingConn.value.id,
    connection_name: browsingConn.value.name,
    table_name: row.name,
    row_count: row.row_count,
    col_count: row.col_count
  }
  moduleDialogVisible.value = true
}

// 导航到目标模块
function navigateToModule(module) {
  if (!pendingTable.value) return
  // 保存远程表信息到 sessionStorage，供目标模块读取
  sessionStorage.setItem('pending_remote_source', JSON.stringify({
    ...pendingTable.value,
    timestamp: Date.now()
  }))
  moduleDialogVisible.value = false
  // 关闭数据源弹窗
  visible.value = false
  emit('update:modelValue', false)
  // 跳转到目标模块
  router.push(module.path)
}

// 初始化：通过 watch(visible) 在弹窗打开时加载，无需在此处调用
</script>

<style scoped>
.ds-container { min-height: 200px; }
.ds-toolbar { margin-bottom: 12px; display: flex; gap: 8px; }
.ds-form { padding: 0 20px; }
.ds-form-title { font-size: 16px; font-weight: 600; margin-bottom: 16px; color: var(--text-primary); }
.ds-form-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--border-color); }
.ds-browse-header { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.ds-browse-title { font-size: 14px; font-weight: 500; color: var(--text-primary); }
.test-ok { color: var(--success-color); font-size: 13px; margin-left: 8px; }
.test-fail { color: var(--danger-color); font-size: 13px; margin-left: 8px; }

/* 模块选择列表 */
.module-list { display: flex; flex-direction: column; gap: 6px; }
.module-item {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 16px; border-radius: 8px; cursor: pointer;
  border: 1px solid var(--border-color, #e4e7ed);
  transition: all 0.2s;
}
.module-item:hover { border-color: var(--primary-color, #409eff); background: #f0f7ff; }
.module-name { font-size: 14px; font-weight: 600; min-width: 80px; }
.module-desc { font-size: 12px; color: var(--text-secondary, #909399); }
</style>
