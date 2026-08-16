<template>
  <div class="data-source-selector">
    <!-- 模式切换按钮组：与下拉框上下排列、等宽，切换模式时容器宽度恒定不变 -->
    <el-radio-group v-model="sourceMode" size="small" @change="onModeChange" class="mode-switch">
      <el-radio-button value="local">本地数据集</el-radio-button>
      <el-radio-button value="remote">远程数据库</el-radio-button>
    </el-radio-group>

    <!-- 本地数据集模式 -->
    <div v-if="sourceMode === 'local'" class="source-panel">
      <el-select
        :model-value="selectedDatasetId"
        placeholder="请选择数据集"
        class="selector-select"
        @change="onDatasetSelect"
        clearable
        :loading="datasetsLoading"
      >
        <!-- :label 用于折叠态显示名称；展开列表用自定义 slot 展示色点/名称/#id/时间/行数 -->
        <el-option v-for="ds in datasets" :key="ds.id" :value="ds.id" :label="ds.name">
          <!-- 命名方案：名称不加后缀，靠色点 + #id + 时间 + 行数区分同名数据集 -->
          <div class="ds-option">
            <span class="ds-dot" :style="{ background: getDatasetColor(ds) }"></span>
            <span class="ds-name">{{ ds.name }}</span>
            <span class="ds-meta">{{ ds.id != null ? `#${ds.id}` : '' }} · {{ formatDsTime(ds.created_at) }} · {{ ds.row_count ? ds.row_count.toLocaleString() : '?' }} 行</span>
          </div>
        </el-option>
      </el-select>
      <div v-if="datasets.length === 0 && !datasetsLoading" class="empty-hint">
        暂无数据，请先上传文件
      </div>
    </div>

    <!-- 远程数据库模式 -->
    <div v-else class="source-panel remote-panel">
      <div class="remote-row">
        <span class="remote-label">数据源连接</span>
        <el-select
          v-model="selectedConnectionId"
          placeholder="请选择数据源连接"
          class="selector-select"
          @change="onConnectionChange"
          clearable
          :loading="connectionsLoading"
        >
          <el-option
            v-for="conn in connections"
            :key="conn.id"
            :label="`${conn.name} (${conn.db_type})`"
            :value="conn.id"
          />
        </el-select>
      </div>
      <div v-if="selectedConnectionId" class="remote-row">
        <span class="remote-label">选择表</span>
        <el-select
          v-model="selectedTableName"
          placeholder="请选择表"
          class="selector-select"
          @change="onTableSelect"
          clearable
          :loading="tablesLoading"
        >
          <el-option
            v-for="tbl in tables"
            :key="tbl.name"
            :label="`${tbl.name} (${tbl.row_count != null ? tbl.row_count.toLocaleString() : '?'}行 × ${tbl.col_count != null ? tbl.col_count : '?'}列)`"
            :value="tbl.name"
          />
        </el-select>
        <el-button
          v-if="selectedConnectionId"
          size="small"
          @click="refreshTables"
          :loading="tablesLoading"
        >刷新</el-button>
      </div>
      <div v-if="selectedTableName && tableInfo" class="table-info">
        <el-tag size="small" type="info">{{ tableInfo.row_count != null ? tableInfo.row_count.toLocaleString() : '?' }} 行</el-tag>
        <el-tag size="small" type="info">{{ tableInfo.col_count != null ? tableInfo.col_count : '?' }} 列</el-tag>
        <el-tag v-if="tableInfo.row_count != null && tableInfo.row_count > 50000" size="small" type="warning">大表·随机采样</el-tag>
        <el-tag size="small" type="success">已选择：{{ selectedTableName }}</el-tag>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onActivated } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchDatasetsByModule,
  fetchDataSources,
  fetchDataSourceTables,
  fetchTableSchema,
  fetchTableCount,
  isLoggedIn
} from '../api/index.js'
import { getDatasetColor } from '../utils/labels.js'

const props = defineProps({
  modelValue: { type: Object, default: () => ({ mode: 'local', datasetId: null }) },
  moduleSource: { type: String, default: '' }  // 用于过滤数据集的模块来源
})

const emit = defineEmits(['update:modelValue', 'select'])

// 格式化创建时间为 `MM-DD HH:mm`（本地时区显示）
function formatDsTime(iso) {
  if (!iso) return '--'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '--'
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// 模式：local / remote
const sourceMode = ref('local')

// 本地数据集
const datasets = ref([])
const datasetsLoading = ref(false)
const selectedDatasetId = ref(null)

// 远程数据库
const connections = ref([])
const connectionsLoading = ref(false)
const selectedConnectionId = ref(null)
const tables = ref([])
const tablesLoading = ref(false)
const selectedTableName = ref(null)

// 表信息缓存
const tableInfo = computed(() => {
  if (!selectedTableName.value) return null
  return tables.value.find(t => t.name === selectedTableName.value) || null
})

// 表列表请求序号：快速切换连接时丢弃过期请求结果，防止表列表串显
let tableLoadSeq = 0

// 加载本地数据集
async function loadDatasets() {
  if (!isLoggedIn()) { datasets.value = []; return }
  datasetsLoading.value = true
  try {
    // 只显示原始数据（artifact_type=raw_data），过滤掉各模块生成的产物
    // 产物应通过数据管理模块查看，不应出现在模块下拉框中
    const res = await fetchDatasetsByModule(props.moduleSource, 'raw_data')
    datasets.value = res.data || []
  } catch {
    datasets.value = []
  } finally {
    datasetsLoading.value = false
  }
}

// 暴露reload方法供父组件在上传成功后调用，避免下拉框需要刷新页面才显示新数据集
// selectDataset用于上传后自动选中新数据集，避免用户在带时间戳的重名文件中难以辨认
defineExpose({
  reload: loadDatasets,
  selectDataset: (id) => {
    selectedDatasetId.value = id
    emitSelect()
  }
})

// 加载数据源连接
async function loadConnections() {
  if (!isLoggedIn()) { connections.value = []; return }
  connectionsLoading.value = true
  try {
    const res = await fetchDataSources()
    connections.value = res.data || []
  } catch {
    connections.value = []
  } finally {
    connectionsLoading.value = false
  }
}

// 加载连接下的表列表
async function loadTables(connId) {
  if (!isLoggedIn()) { tables.value = []; return }
  const seq = ++tableLoadSeq
  tablesLoading.value = true
  tables.value = []
  selectedTableName.value = null
  emitSelect()
  try {
    const tableNames = (await fetchDataSourceTables(connId)).data || []
    // 并发加载 schema/行数：每批 8 张表，避免连接下几十张表时串行请求导致长时间 loading
    const tableInfos = []
    const BATCH = 8
    for (let i = 0; i < tableNames.length; i += BATCH) {
      // 连接已切换，丢弃过期结果（loading 由最新请求管理）
      if (seq !== tableLoadSeq) return
      const batch = tableNames.slice(i, i + BATCH)
      const results = await Promise.all(batch.map(async (name) => {
        try {
          const [schemaRes, countRes] = await Promise.all([
            fetchTableSchema(connId, name),
            fetchTableCount(connId, name)
          ])
          return {
            name,
            // 保留完整 schema 信息（含列类型），供各模块 onSourceSelect 使用
            schema: schemaRes.data || [],
            col_count: (schemaRes.data || []).length,
            row_count: countRes.data?.row_count ?? null
          }
        } catch {
          return { name, schema: [], col_count: null, row_count: null }
        }
      }))
      tableInfos.push(...results)
    }
    // 最后一次写回前再次校验序号，避免过期请求覆盖新连接的表列表
    if (seq !== tableLoadSeq) return
    tables.value = tableInfos
  } catch {
    if (seq === tableLoadSeq) tables.value = []
  } finally {
    if (seq === tableLoadSeq) tablesLoading.value = false
  }
}

function refreshTables() {
  if (selectedConnectionId.value) {
    loadTables(selectedConnectionId.value)
  }
}

// 触发选择事件
function emitSelect() {
  if (sourceMode.value === 'local') {
    emit('select', {
      mode: 'local',
      datasetId: selectedDatasetId.value
    })
  } else {
    const remoteConfig = selectedConnectionId.value && selectedTableName.value
      ? {
          use_remote: true,
          connection_id: selectedConnectionId.value,
          table_name: selectedTableName.value
        }
      : null
    emit('select', {
      mode: 'remote',
      remote: remoteConfig
    })
  }
}

// 模式切换
function onModeChange() {
  selectedDatasetId.value = null
  selectedConnectionId.value = null
  selectedTableName.value = null
  tables.value = []
  emitSelect()
}

// 本地数据集选择
function onDatasetSelect(val) {
  selectedDatasetId.value = val
  emitSelect()
}

// 连接变更
function onConnectionChange(val) {
  selectedConnectionId.value = val
  if (val) {
    loadTables(val)
  } else {
    tables.value = []
    selectedTableName.value = null
    emitSelect()
  }
}

// 表选择
// 远程大表采样阈值（与后端 REMOTE_SAMPLE_THRESHOLD 一致），超过此值后端将自动采样
const REMOTE_SAMPLE_THRESHOLD = 50000

function onTableSelect() {
  // 大表预警：选择超阈值远程表时提示用户数据将被随机采样
  if (tableInfo.value && tableInfo.value.row_count != null && tableInfo.value.row_count > REMOTE_SAMPLE_THRESHOLD) {
    ElMessage.warning(
      `该表共 ${tableInfo.value.row_count.toLocaleString()} 行，超过 ${REMOTE_SAMPLE_THRESHOLD.toLocaleString()} 行阈值，` +
      `模块加载时将随机采样 ${REMOTE_SAMPLE_THRESHOLD.toLocaleString()} 行（随机起点连续片段）。如需全量分析，请先导入为本地数据集。`
    )
  } else if (tableInfo.value && tableInfo.value.row_count != null) {
    // 小表确认提示，避免用户误判（对应问题12：85行表误提示大表）
    ElMessage.success(`已选择表 ${selectedTableName.value}，共 ${tableInfo.value.row_count.toLocaleString()} 行`)
  }
  emitSelect()
}

// 加载 sessionStorage 中暂存的远程数据源（从 DataSourceDialog "在模块中使用" 传入）
function checkPendingRemoteSource() {
  try {
    const raw = sessionStorage.getItem('pending_remote_source')
    if (!raw) return
    const data = JSON.parse(raw)
    // 5分钟内有效
    if (Date.now() - data.timestamp > 5 * 60 * 1000) {
      sessionStorage.removeItem('pending_remote_source')
      return
    }
    // 切换到远程模式
    sourceMode.value = 'remote'
    selectedConnectionId.value = data.connection_id
    // 先加载连接列表，然后选中对应连接
    loadConnections().then(() => {
      selectedConnectionId.value = data.connection_id
      loadTables(data.connection_id).then(() => {
        selectedTableName.value = data.table_name
        emitSelect()
      })
    })
    sessionStorage.removeItem('pending_remote_source')
  } catch {
    sessionStorage.removeItem('pending_remote_source')
  }
}

onMounted(() => {
  loadDatasets()
  loadConnections()
  checkPendingRemoteSource()
})

// keep-alive 激活时刷新数据集和连接列表
// 修复：App.vue 使用 keep-alive，切换模块不会重新触发 onMounted，
// 导致在数据管理上传新文件或在数据源弹窗新建连接后，切回模块看不到最新数据
onActivated(() => {
  loadDatasets()
  loadConnections()
  // 重新检查是否有待使用的远程数据源（从 DataSourceDialog 跳转过来）
  checkPendingRemoteSource()
})
</script>

<style scoped>
.data-source-selector {
  /* 宽度自适应撑满卡片：消除右侧空白；按钮组与下拉框均 100%，切换模式时容器尺寸恒定 */
  width: 100%;
  max-width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}

/* 模式切换按钮组：占满容器宽度，两个按钮均分 */
.mode-switch {
  width: 100%;
  display: flex;
}
.mode-switch :deep(.el-radio-button) {
  flex: 1;
}
.mode-switch :deep(.el-radio-button .el-radio-button__inner) {
  width: 100%;
}

.source-panel {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}

/* 下拉框撑满容器宽度（与模式切换按钮组等宽对齐） */
.selector-select {
  width: 100%;
}

.remote-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
.remote-row .selector-select {
  /* 行内下拉框占满剩余宽度，保证整行总宽恒为 360px */
  flex: 1;
  width: auto;
}

.remote-label {
  flex: none;
  font-size: 13px;
  color: var(--text-secondary, #909399);
}

.table-info {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.empty-hint {
  font-size: 12px;
  color: var(--text-muted, #c0c4cc);
}

/* 数据集下拉选项：色点 + 名称 + 元信息 */
.ds-option {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  overflow: hidden;
}

.ds-dot {
  flex: none;
  width: 9px;
  height: 9px;
  border-radius: 50%;
}

.ds-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ds-meta {
  flex: none;
  margin-left: auto;
  font-size: 12px;
  color: var(--text-muted, #909399);
  white-space: nowrap;
}
</style>
