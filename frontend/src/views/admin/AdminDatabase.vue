<template>
  <div>
    <el-tabs v-model="activeTab" type="border-card">
      <el-tab-pane label="表结构" name="tables">
        <div class="card">
          <div class="card-header">
            <div class="card-title">数据库表管理</div>
            <div class="flex-center" style="gap:10px;">
              <el-select v-model="selectedTable" placeholder="选择数据表" clearable style="width:200px;" @change="onTableSelect">
                <el-option
                  v-for="table in tables"
                  :key="table.name"
                  :label="`${table.name} (${table.row_count}行)`"
                  :value="table.name"
                />
              </el-select>
              <el-button size="small" @click="viewStructure" :disabled="!selectedTable">
                <el-icon><View /></el-icon> 查看结构
              </el-button>
              <el-button size="small" type="primary" @click="backupDb">
                <el-icon><Download /></el-icon> 备份数据库
              </el-button>
            </div>
          </div>

          <div v-if="selectedTable" class="mt-md">
            <el-descriptions :column="2" border>
              <el-descriptions-item label="表名">{{ selectedTable }}</el-descriptions-item>
              <el-descriptions-item label="作用说明">{{ tableDescriptions[selectedTable]?.description || '-' }}</el-descriptions-item>
              <el-descriptions-item label="实际使用">{{ tableDescriptions[selectedTable]?.usage || '-' }}</el-descriptions-item>
              <el-descriptions-item label="如何增加数据">{{ tableDescriptions[selectedTable]?.howToAdd || '-' }}</el-descriptions-item>
            </el-descriptions>
          </div>

          <div v-if="selectedTable" class="mt-md">
            <div class="flex-center" style="justify-content: space-between; margin-bottom: 12px;">
              <div>
                <span style="font-weight: 600;">{{ selectedTable }} - 数据预览</span>
                <span style="margin-left: 12px; font-size: 12px; color: #9ca3af;">
                  {{ currentTableInfo?.row_count || 0 }} 行 | {{ formatSize(currentTableInfo?.table_size) }} | {{ currentTableInfo?.index_count || 0 }} 个索引
                </span>
              </div>
              <div class="flex-center" style="gap:10px;">
                <el-input v-model="searchQuery" placeholder="搜索..." clearable style="width:200px;" @keyup.enter="loadTableData" />
                <el-button size="small" @click="loadTableData">
                  <el-icon><Search /></el-icon> 查询
                </el-button>
                <el-button size="small" type="primary" @click="exportData">
                  <el-icon><Download /></el-icon> 导出
                </el-button>
              </div>
            </div>
            <div class="data-table-wrapper">
              <el-table :data="tableData" border>
                <el-table-column
                  v-for="col in tableColumns"
                  :key="col"
                  :prop="col"
                  :label="col"
                  :formatter="formatCell"
                  min-width="100"
                />
              </el-table>
            </div>
            <div class="flex-center" style="justify-content: flex-end; margin-top: 16px;">
              <el-pagination
                v-model:current-page="page"
                :page-size="pageSize"
                :total="total"
                layout="total, prev, pager, next"
                @current-change="loadTableData"
              />
            </div>
          </div>

          <div v-else class="mt-md" style="text-align: center; padding: 40px; color: #9ca3af;">
            <div style="font-size: 48px; margin-bottom: 12px; color: #409eff;">
              <svg viewBox="0 0 1024 1024" width="48" height="48" fill="currentColor">
                <path d="M512 128C264.6 128 64 195.5 64 279.4v465.2c0 83.9 200.6 151.4 448 151.4s448-67.5 448-151.4V279.4C960 195.5 759.4 128 512 128zM832 744.6c0 27.6-143.3 87.4-320 87.4s-320-59.8-320-87.4V538.8c70.4 32.1 192.7 53.2 320 53.2s249.6-21.1 320-53.2v205.8z m0-326.4c0 27.6-143.3 87.4-320 87.4s-320-59.8-320-87.4V327.4c70.4 32.1 192.7 53.2 320 53.2s249.6-21.1 320-53.2v90.8z"/>
              </svg>
            </div>
            <div>请从上方下拉框选择数据表进行查看</div>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="SQL 查询" name="sql">
        <div class="card">
          <div class="card-header">
            <div class="card-title">SQL 查询（只读）</div>
          </div>
          <div style="max-width: 800px;">
            <div style="margin-bottom: 12px;">
              <span style="font-size: 13px; color: #6b7280;">💡 查询示例（按表分组，覆盖全部表）：</span>
              <el-select v-model="selectedExample" placeholder="选择示例" clearable filterable style="width: 440px; margin-left: 8px;" @change="loadExample">
                <el-option-group v-for="group in sqlExampleGroups" :key="group.table" :label="group.label">
                  <el-option v-for="q in group.queries" :key="q.sql" :label="q.label" :value="q.sql" />
                </el-option-group>
              </el-select>
            </div>
            <el-input
              v-model="sqlQuery"
              type="textarea"
              :rows="4"
              placeholder="输入 SELECT 查询语句，例如：SELECT * FROM users LIMIT 10"
            />
            <div class="flex-center" style="justify-content: space-between; margin-top: 12px;">
              <div class="flex-center" style="gap: 8px;">
                <el-select v-model="selectedHistory" placeholder="历史记录" clearable style="width: 300px;" @change="loadFromHistory">
                  <el-option
                    v-for="(item, index) in sqlHistory"
                    :key="index"
                    :label="item.substring(0, 50) + (item.length > 50 ? '...' : '')"
                    :value="item"
                  />
                </el-select>
                <el-button size="small" @click="clearHistory" :disabled="sqlHistory.length === 0">
                  清空历史
                </el-button>
              </div>
              <el-button size="small" type="primary" @click="executeSql">
                <el-icon><VideoPlay /></el-icon> 执行查询
              </el-button>
            </div>
            <div v-if="queryResult" class="mt-md">
              <div style="margin-bottom: 12px;">
                <span style="font-weight: 600;">查询结果：</span>{{ queryResult.row_count }} 行
              </div>
              <div class="data-table-wrapper">
                <el-table :data="queryResult.data" border>
                  <el-table-column
                    v-for="col in queryResult.columns"
                    :key="col"
                    :prop="col"
                    :label="col"
                    min-width="100"
                  />
                </el-table>
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="ClickHouse" name="clickhouse">
        <!-- 同步状态概览（批次D：同步管理接口已接入） -->
        <div class="card" style="margin-bottom: 16px;">
          <div class="card-header">
            <div class="card-title">数据集同步状态</div>
            <div style="display: flex; gap: 8px;">
              <el-button size="small" :loading="chSyncLoading" @click="loadClickHouseSyncStatus">
                刷新
              </el-button>
              <el-button size="small" type="danger" plain :loading="chSyncLoading" @click="handleCleanupAllClickHouse">
                全部清理
              </el-button>
            </div>
          </div>
          <div style="display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 16px;">
            <div style="background: #f5f7fa; border-radius: 6px; padding: 12px; text-align: center;">
              <div style="font-size: 20px; font-weight: 600;">{{ chStatus.enabled ? '已启用' : '未启用' }}</div>
              <div style="font-size: 12px; color: #909399; margin-top: 4px;">功能开关</div>
            </div>
            <div style="background: #f5f7fa; border-radius: 6px; padding: 12px; text-align: center;">
              <div style="font-size: 20px; font-weight: 600;" :style="{ color: chStatus.available ? '#67c23a' : '#f56c6c' }">
                {{ chStatus.available ? '可用' : '不可用' }}
              </div>
              <div style="font-size: 12px; color: #909399; margin-top: 4px;">连接状态</div>
            </div>
            <div style="background: #f5f7fa; border-radius: 6px; padding: 12px; text-align: center;">
              <div style="font-size: 20px; font-weight: 600;">{{ chStatus.min_rows ?? '-' }}</div>
              <div style="font-size: 12px; color: #909399; margin-top: 4px;">同步阈值(行)</div>
            </div>
            <div style="background: #f5f7fa; border-radius: 6px; padding: 12px; text-align: center;">
              <div style="font-size: 20px; font-weight: 600; color: #67c23a;">{{ chStatus.synced ?? 0 }}</div>
              <div style="font-size: 12px; color: #909399; margin-top: 4px;">已同步</div>
            </div>
            <div style="background: #f5f7fa; border-radius: 6px; padding: 12px; text-align: center;">
              <div style="font-size: 20px; font-weight: 600;" :style="{ color: (chStatus.failed || 0) > 0 ? '#f56c6c' : '#67c23a' }">
                {{ chStatus.failed ?? 0 }}
              </div>
              <div style="font-size: 12px; color: #909399; margin-top: 4px;">同步失败</div>
            </div>
            <div style="background: #f5f7fa; border-radius: 6px; padding: 12px; text-align: center;">
              <div style="font-size: 20px; font-weight: 600;">{{ chStorage.total_readable || '0 B' }}</div>
              <div style="font-size: 12px; color: #909399; margin-top: 4px;">副本占用</div>
            </div>
          </div>
          <div class="data-table-wrapper">
            <el-table :data="chSyncItems" border v-loading="chSyncLoading" empty-text="暂无数据集副本（≥1万行的原始数据上传后自动同步）" max-height="420">
              <el-table-column prop="dataset_id" label="ID" width="70" />
              <el-table-column prop="dataset_name" label="数据集名称" min-width="180" show-overflow-tooltip />
              <el-table-column prop="row_count" label="行数" width="90" />
              <el-table-column prop="column_count" label="列数" width="60" />
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag :type="row.status === 'synced' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'" size="small">
                    {{ row.status_label }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="达阈值" width="70">
                <template #default="{ row }">
                  <el-tag :type="row.meets_threshold ? 'success' : 'info'" size="small">
                    {{ row.meets_threshold ? '是' : '否' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="synced_at" label="同步时间" width="170" />
              <el-table-column prop="last_error" label="最近错误" min-width="140" show-overflow-tooltip />
              <el-table-column label="操作" width="160" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" @click="handleSyncClickHouse(row)">重建同步</el-button>
                  <el-button size="small" type="danger" plain @click="handleCleanupClickHouse(row)">清理</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div style="font-size: 12px; color: #909399; margin-top: 8px; line-height: 1.6;">
            说明：仅原始数据（raw_data/analysis_data）且行数 ≥ {{ chStatus.min_rows ?? 10000 }} 会自动同步副本；数据分析模块的统计/质量/图表/推荐在副本可用时走 ClickHouse 加速，失败自动降级 pandas；"清理"仅删除副本不影响源数据文件。
          </div>
        </div>

        <!-- 查询工具（原有） -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">ClickHouse 查询工具</div>
            <el-tag type="success" style="font-size: 12px;">参与业务：大表分析加速</el-tag>
          </div>
          <div style="font-size: 12px; color: #909399; margin-bottom: 12px; line-height: 1.8; background: #f8f8f9; padding: 10px 12px; border-radius: 6px;">
            <b>库与表说明：</b><br />
            1. 业务库 <code style="color:#409eff;">analysis</code>：本项目数据副本。其中 <code style="color:#409eff;">ds_{数据集id}</code> 表 = 某个数据集的同步副本（仅 ≥1万行的原始数据自动同步）；<code style="color:#409eff;">dataset_registry</code> 表 = 同步注册表（记录每个副本的状态/行数/同步时间）。<br />
            2. 系统库 <code style="color:#909399;">system / default / information_schema / INFORMATION_SCHEMA</code>：ClickHouse 自带，可忽略（大小写不同是官方同时提供两个兼容视图，属正常现象）。下拉已隐藏系统库，仅显示业务库。
          </div>
          <div style="margin-bottom: 16px;">
            <el-select v-model="chDatabase" placeholder="选择业务库" @change="loadClickHouseTables">
              <el-option-group v-for="g in chDatabaseGroups" :key="g.label" :label="g.label">
                <el-option
                  v-for="db in g.options"
                  :key="db"
                  :label="db"
                  :value="db"
                />
              </el-option-group>
            </el-select>
            <el-button size="small" @click="loadClickHouseDatabases" style="margin-left: 8px;">
              刷新
            </el-button>
          </div>
          <div v-if="chTables.length > 0" class="data-table-wrapper" style="margin-bottom: 16px;">
            <el-table :data="chTables" border>
              <el-table-column prop="name" label="表名" />
              <el-table-column prop="database" label="数据库" width="150" />
            </el-table>
          </div>
          <div style="max-width: 800px;">
            <div style="margin-bottom: 12px;">
              <span style="font-size: 13px; color: #6b7280;">💡 查询示例（按表/用途分组，点选自动填入）：</span>
              <el-select v-model="chSelectedExample" placeholder="选择示例" clearable filterable style="width: 440px; margin-left: 8px;" @change="loadChExample">
                <el-option-group v-for="group in chExampleGroups" :key="group.key" :label="group.label">
                  <el-option v-for="q in group.queries" :key="q.sql" :label="q.label" :value="q.sql" />
                </el-option-group>
              </el-select>
            </div>
            <el-input
              v-model="chQuery"
              type="textarea"
              :rows="3"
              placeholder="输入 ClickHouse 查询语句，例如：SELECT * FROM analysis.dataset_registry LIMIT 10"
            />
            <div class="flex-center" style="justify-content: flex-end; margin-top: 12px;">
              <el-button size="small" type="primary" @click="executeClickHouseSql">
                <el-icon><VideoPlay /></el-icon> 执行查询
              </el-button>
            </div>
            <div v-if="chQueryResult" class="mt-md">
              <div style="margin-bottom: 12px;">
                <span style="font-weight: 600;">查询结果：</span>{{ chQueryResult.row_count }} 行
              </div>
              <div class="data-table-wrapper">
                <el-table :data="chQueryResult.data" border>
                  <el-table-column
                    v-for="col in chQueryResult.columns"
                    :key="col"
                    :prop="col"
                    :label="col"
                    :formatter="formatCell"
                    min-width="100"
                  />
                </el-table>
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="索引说明" name="indexes">
        <div class="card">
          <div class="card-header">
            <div class="card-title">索引说明</div>
          </div>
          <div style="line-height: 1.8;">
            <h4 style="margin-bottom: 12px;">什么是索引？</h4>
            <p>索引是数据库中用于加速数据查询的一种数据结构，类似于书籍的目录。当查询条件包含索引列时，数据库可以直接通过索引快速定位到数据，而不需要扫描整张表。</p>
            
            <h4 style="margin-top: 20px; margin-bottom: 12px;">索引数为什么不是从1开始？</h4>
            <p>默认情况下，PostgreSQL 会为每张表的主键自动创建一个名为 <code>table_name_pkey</code> 的索引。因此：</p>
            <ul style="margin-left: 20px;">
              <li><strong>索引数为 0</strong>：表没有主键或其他索引（非常少见）</li>
              <li><strong>索引数为 1</strong>：表只有主键索引（默认情况）</li>
              <li><strong>索引数 &gt; 1</strong>：表除了主键外还有额外创建的索引</li>
            </ul>

            <h4 style="margin-top: 20px; margin-bottom: 12px;">当前数据库各表索引情况</h4>
            <div class="data-table-wrapper" style="margin-top: 12px;">
              <el-table :data="tables" border>
                <el-table-column prop="name" label="表名" width="180" />
                <el-table-column prop="index_count" label="索引数" width="100" />
                <el-table-column label="索引详情" min-width="300">
                  <template #default="scope">
                    <div v-for="(idx, i) in scope.row.indexes || []" :key="i" style="font-size: 12px;">
                      {{ idx.name }} ({{ idx.column_names?.join(', ') }})
                      <el-tag v-if="idx.unique" size="small" type="success" style="margin-left: 8px;">唯一</el-tag>
                    </div>
                    <span v-if="!scope.row.indexes || scope.row.indexes.length === 0" style="color: #9ca3af;">暂无索引</span>
                  </template>
                </el-table-column>
              </el-table>
            </div>

            <h4 style="margin-top: 20px; margin-bottom: 12px;">本项目索引说明</h4>
            <div class="data-table-wrapper" style="margin-top: 12px;">
              <el-table :data="indexDescriptions" border>
                <el-table-column prop="table" label="表名" width="180" />
                <el-table-column prop="index" label="索引名" width="180" />
                <el-table-column prop="columns" label="索引列" width="200" />
                <el-table-column prop="purpose" label="用途" />
              </el-table>
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="structureVisible" title="表结构" width="700px">
      <el-tabs v-if="currentStructure" type="border-card">
        <el-tab-pane label="字段">
          <div class="data-table-wrapper">
            <el-table :data="currentStructure.columns" border>
              <el-table-column prop="name" label="字段名" width="150" />
              <el-table-column prop="type" label="类型" width="150" />
              <el-table-column prop="nullable" label="可空" width="80">
                <template #default="scope">
                  <el-tag :type="scope.row.nullable ? 'info' : 'success'">
                    {{ scope.row.nullable ? '是' : '否' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="default" label="默认值" />
            </el-table>
          </div>
        </el-tab-pane>
        <el-tab-pane label="索引">
          <div class="data-table-wrapper">
            <el-table :data="currentStructure.indexes" border>
              <el-table-column prop="name" label="索引名" width="200" />
              <el-table-column prop="column_names" label="列" width="200">
                <template #default="scope">
                  {{ (scope.row.column_names || []).join(', ') }}
                </template>
              </el-table-column>
              <el-table-column prop="unique" label="唯一" width="80">
                <template #default="scope">
                  <el-tag :type="scope.row.unique ? 'success' : 'info'">
                    {{ scope.row.unique ? '是' : '否' }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="structureVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { Search, VideoPlay, Download, View } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { listDatabaseTables, getTableData, executeQuery, exportTableData, listClickHouseDatabases, listClickHouseTables, executeClickHouseQuery, backupDatabase, getClickHouseSyncStatus, syncClickHouseDataset, cleanupClickHouseDataset, cleanupAllClickHouse, getClickHouseStorageStats } from '../../api/admin.js'

const activeTab = ref('tables')
const tables = ref([])
const selectedTable = ref(null)
const tableData = ref([])
const tableColumns = ref([])
const searchQuery = ref('')
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const structureVisible = ref(false)
const currentStructure = ref(null)
const currentTableInfo = ref(null)

// 表格单元格格式化：对象/数组以 JSON 呈现，避免显示 [object Object]
function formatCell(row, column, cellValue) {
  if (cellValue === null || cellValue === undefined) return ''
  if (typeof cellValue === 'object') {
    try {
      return JSON.stringify(cellValue, null, 2)
    } catch (e) {
      return String(cellValue)
    }
  }
  return cellValue
}

const sqlQuery = ref('')
const queryResult = ref(null)
const sqlHistory = ref([])
const selectedHistory = ref(null)
const selectedExample = ref(null)

const chDatabase = ref('analysis')
const chDatabases = ref([])
const chTables = ref([])
const chQuery = ref('')
const chQueryResult = ref(null)
const chSelectedExample = ref(null)

// ClickHouse 系统库（官方自带；下拉不展示，避免误导——业务库才是本项目数据副本）
const CH_SYSTEM_DATABASES = ['system', 'default', 'information_schema', 'INFORMATION_SCHEMA']
// 下拉仅展示业务库（本项目数据副本）；系统库在下方说明中解释，无需操作
const chDatabaseGroups = computed(() => {
  const biz = chDatabases.value.filter(d => !CH_SYSTEM_DATABASES.includes(d))
  const groups = []
  if (biz.length) groups.push({ label: '业务库（本项目数据副本）', options: biz })
  return groups
})

// ============ ClickHouse 查询示例（按分组，参照 SQL 查询 tab）============
// 静态示例覆盖注册表/存储结构；副本表 ds_{id} 为动态表名，基于同步状态实时生成
const chExampleGroups = computed(() => {
  const groups = []
  groups.push({
    key: 'registry', label: '同步注册表 dataset_registry',
    queries: [
      { label: '全部同步副本', sql: "SELECT dataset_id, dataset_name, status, row_count, synced_at, last_error FROM analysis.dataset_registry ORDER BY dataset_id DESC" },
      { label: '同步失败列表', sql: "SELECT dataset_id, dataset_name, last_error FROM analysis.dataset_registry WHERE status = 'failed'" },
      { label: '同步状态统计', sql: "SELECT status, COUNT(*) AS `数量` FROM analysis.dataset_registry GROUP BY status" },
      { label: '副本存储概况', sql: "SELECT dataset_id, dataset_name, row_count FROM analysis.dataset_registry WHERE status = 'synced' ORDER BY row_count DESC" },
    ]
  })
  const synced = chSyncItems.value.filter(i => i.status === 'synced')
  if (synced.length) {
    groups.push({
      key: 'copies', label: '数据集副本 ds_{数据集id}',
      queries: synced.map(i => ({
        label: `ds_${i.dataset_id} · ${i.dataset_name}（前 10 行）`,
        sql: `SELECT * FROM analysis.ds_${i.dataset_id} LIMIT 10`
      }))
    })
  }
  groups.push({
    key: 'storage', label: '副本存储与结构（system 系统表只读）',
    queries: [
      { label: '业务库所有表及占用', sql: "SELECT name AS `表名`, total_rows AS `行数`, formatReadableSize(total_bytes) AS `占用` FROM system.tables WHERE database = 'analysis' ORDER BY total_rows DESC" },
      { label: '注册表表结构', sql: "SELECT name AS `列名`, type AS `类型` FROM system.columns WHERE database = 'analysis' AND table = 'dataset_registry'" },
    ]
  })
  return groups
})

function loadChExample(sql) {
  if (sql) {
    chQuery.value = sql
  }
}

// ClickHouse 同步管理（批次D）
const chSyncLoading = ref(false)
const chSyncItems = ref([])
const chStatus = ref({})
const chStorage = ref({})

const tableDescriptions = reactive({
  users: {
    description: '存储平台用户信息',
    usage: '✓ 已使用 - 用于用户注册、登录认证',
    howToAdd: '通过前端注册页面或管理端创建用户'
  },
  datasets: {
    description: '存储所有上传的数据集信息（文件元数据）',
    usage: '✓ 已使用 - 所有模块的核心数据存储',
    howToAdd: '在各功能模块（清洗/分析/挖掘/特征工程/机器学习）上传文件'
  },
  ai_conversations: {
    description: '存储用户与AI的对话历史记录',
    usage: '✓ 已使用 - AI模块对话功能',
    howToAdd: '在AI分析模块与AI进行对话交互'
  },
  ai_usage_log: {
    description: '存储AI API调用的token使用量',
    usage: '✓ 已使用 - 记录每次AI调用的token消耗',
    howToAdd: '使用AI分析功能时自动记录'
  },
  ai_config: {
    description: '存储AI配置信息（API密钥、模型等）',
    usage: '✓ 已使用 - 管理端AI配置页面管理',
    howToAdd: '在管理端AI配置页面添加配置'
  },
  task_records: {
    description: '存储异步任务执行记录（数据清洗、机器学习训练等）',
    usage: '✓ 已使用 - 异步任务系统自动记录',
    howToAdd: '执行大数据量的数据清洗、机器学习训练等操作'
  },
  ai_messages: {
    description: 'AI 对话单条消息存储（用户/助手/系统消息）',
    usage: '✓ 已使用 - AI 模块对话消息逐条落库，替代旧的 conversation JSON 数组',
    howToAdd: '在 AI 分析模块与 AI 对话时自动写入'
  },
  ai_conversation_contexts: {
    description: 'AI 会话上下文项关联（持久化用户选过的数据集/操作上下文）',
    usage: '✓ 已使用 - 会话恢复时重建上下文注入',
    howToAdd: '在 AI 分析模块勾选上下文项（数据集/操作记录）时自动记录'
  },
  datasource_connections: {
    description: '远程数据库连接配置（用户添加的 MySQL/PostgreSQL 数据源）',
    usage: '✓ 已使用 - 各模块远程数据源功能（清洗/分析/挖掘/特征工程/机器学习可连远程表）',
    howToAdd: '用户在数据源管理模块添加远程数据库连接；密码经加密后存储'
  },
  support_messages: {
    description: '用户"联系管理员"提交的申请（恢复数据集/解锁账户/错误上报）',
    usage: '✓ 已使用 - 管理端用户管理→用户申请 Tab',
    howToAdd: '用户在登录页/联系管理员页提交申请时自动写入'
  },
  cache_stats_hourly: {
    description: '缓存命中统计按小时归档（缓存管理→历史统计 Tab 数据源）',
    usage: '✓ 已使用 - TaskScheduler 后台每 60 秒 upsert 小时累计值',
    howToAdd: '系统后台定时写入，无需手动操作'
  },
  log_records: {
    description: 'WARNING/ERROR 级别日志异步入库记录（运行日志模块数据源）',
    usage: '✓ 已使用 - logger.py DbLogHandler 自动写库；服务总览"今日错误"、运行日志趋势/汇总均基于此表',
    howToAdd: '后端任意模块产生 WARNING/ERROR 日志时自动异步批量写入'
  },
  data_catalogs: {
    description: 'AI 产品问答的常驻数据目录（一组数据集保存为小型数据仓库，用户可快速复用）',
    usage: '✓ 已使用 - AI 分析模块"产品问答"Tab 中保存/选择常驻目录；按 user_id 隔离',
    howToAdd: '在 AI 分析模块切换到"产品问答"，勾选数据产物后点击"保存为目录"'
  },
  app_config: {
    description: '应用全局配置键值对（不依赖环境变量，服务重启不丢失）',
    usage: '✓ 已使用 - 如远程数据源密码加密密钥等全局配置',
    howToAdd: '由系统初始化或管理端配置写入'
  }
})

const indexDescriptions = ref([
  { table: 'users', index: 'users_pkey', columns: 'id', purpose: '主键索引，加速用户ID查询' },
  { table: 'users', index: 'ix_users_username', columns: 'username', purpose: '加速用户名查询和唯一性验证' },
  { table: 'users', index: 'ix_users_email', columns: 'email', purpose: '加速邮箱查询和唯一性验证' },
  { table: 'datasets', index: 'datasets_pkey', columns: 'id', purpose: '主键索引' },
  { table: 'datasets', index: 'ix_datasets_user_id', columns: 'user_id', purpose: '加速按用户查询数据集' },
  { table: 'datasets', index: 'ix_datasets_status', columns: 'status', purpose: '加速按状态筛选' },
  { table: 'datasets', index: 'ix_datasets_module_source', columns: 'module_source', purpose: '加速按模块筛选' },
  { table: 'datasets', index: 'ix_datasets_artifact_type', columns: 'artifact_type', purpose: '加速按产物类型筛选' },
  { table: 'datasets', index: 'ix_datasets_name', columns: 'name', purpose: '加速按名称搜索/排序' },
  { table: 'datasets', index: 'ix_datasets_root_dataset_id', columns: 'root_dataset_id', purpose: '加速血缘关系查询' },
  { table: 'datasets', index: 'ix_datasets_created_at', columns: 'created_at', purpose: '加速按时间排序' },
  { table: 'ai_conversations', index: 'ai_conversations_pkey', columns: 'id', purpose: '主键索引' },
  { table: 'ai_conversations', index: 'ix_ai_conversations_user_id', columns: 'user_id', purpose: '加速按用户查询对话' },
  { table: 'ai_conversations', index: 'ix_ai_conversations_dataset_id', columns: 'dataset_id', purpose: '加速按数据集查询对话' },
  { table: 'ai_usage_log', index: 'ai_usage_log_pkey', columns: 'id', purpose: '主键索引' },
  { table: 'ai_usage_log', index: 'ix_ai_usage_log_conversation_id', columns: 'conversation_id', purpose: '加速按对话查询使用量' },
  { table: 'ai_config', index: 'ai_config_pkey', columns: 'id', purpose: '主键索引' },
  { table: 'task_records', index: 'task_records_pkey', columns: 'id', purpose: '主键索引' },
  { table: 'task_records', index: 'ix_task_records_user_id', columns: 'user_id', purpose: '加速按用户查询任务' },
  { table: 'task_records', index: 'ix_task_records_task_type', columns: 'task_type', purpose: '加速按任务类型筛选' },
  { table: 'task_records', index: 'ix_task_records_status', columns: 'status', purpose: '加速按状态筛选' },
  { table: 'ai_messages', index: 'ai_messages_pkey', columns: 'id', purpose: '主键索引' },
  { table: 'ai_messages', index: 'ix_ai_messages_conversation_id', columns: 'conversation_id', purpose: '加速按会话查询消息' },
  { table: 'ai_conversation_contexts', index: 'ai_conversation_contexts_pkey', columns: 'id', purpose: '主键索引' },
  { table: 'ai_conversation_contexts', index: 'ix_ai_conversation_contexts_conversation_id', columns: 'conversation_id', purpose: '加速按会话查询上下文项' },
  { table: 'datasource_connections', index: 'datasource_connections_pkey', columns: 'id', purpose: '主键索引' },
  { table: 'datasource_connections', index: 'ix_datasource_connections_user_id', columns: 'user_id', purpose: '加速按用户查询数据源连接' },
  { table: 'app_config', index: 'app_config_pkey', columns: 'key', purpose: '主键索引（配置键唯一标识）' },
  { table: 'support_messages', index: 'support_messages_pkey', columns: 'id', purpose: '主键索引' },
  { table: 'support_messages', index: 'ix_support_messages_status', columns: 'status', purpose: '加速按状态筛选待处理申请' },
  { table: 'cache_stats_hourly', index: 'cache_stats_hourly_pkey', columns: 'id', purpose: '主键索引' },
  { table: 'cache_stats_hourly', index: 'ix_cache_stats_hourly_hour', columns: 'hour', purpose: '加速按小时查询（唯一）' },
  { table: 'log_records', index: 'log_records_pkey', columns: 'id', purpose: '主键索引' },
  { table: 'log_records', index: 'ix_log_records_created_at', columns: 'created_at', purpose: '加速按时间范围查询' },
  { table: 'log_records', index: 'ix_log_records_level', columns: 'level', purpose: '加速按级别筛选' },
  { table: 'log_records', index: 'ix_log_records_module', columns: 'module', purpose: '加速按模块筛选' }
])

// SQL 查询示例（按表分组，覆盖全部表）
const sqlExampleGroups = [
  {
    table: 'users', label: 'users · 用户',
    queries: [
      { label: '查看所有用户', sql: "SELECT id, username, email, role, is_active, created_at FROM users ORDER BY created_at DESC LIMIT 20" },
      { label: '今日新增用户', sql: "SELECT COUNT(*) AS 今日新增 FROM users WHERE created_at >= NOW() - INTERVAL '1 day'" },
      { label: '锁定/禁用账号', sql: "SELECT id, username, is_active, failed_login_count, locked_until FROM users WHERE NOT is_active OR locked_until > NOW()" },
    ]
  },
  {
    table: 'datasets', label: 'datasets · 数据集',
    queries: [
      { label: '各模块数据集数', sql: "SELECT module_source, COUNT(*) AS 数量, SUM(file_size) AS 总大小 FROM datasets WHERE status = 'active' GROUP BY module_source ORDER BY 数量 DESC" },
      { label: '各产物类型统计', sql: "SELECT artifact_type, COUNT(*) AS 数量 FROM datasets WHERE status = 'active' GROUP BY artifact_type" },
      { label: '最近上传的数据集', sql: "SELECT id, user_id, name, module_source, row_count, created_at FROM datasets ORDER BY created_at DESC LIMIT 20" },
    ]
  },
  {
    table: 'task_records', label: 'task_records · 任务记录',
    queries: [
      { label: '任务状态分布', sql: "SELECT status, COUNT(*) AS 数量 FROM task_records GROUP BY status" },
      { label: '今日任务情况', sql: "SELECT status, COUNT(*) AS 数量 FROM task_records WHERE created_at >= NOW() - INTERVAL '1 day' GROUP BY status" },
      { label: '失败任务 TOP 模块', sql: "SELECT task_type, COUNT(*) AS 失败数 FROM task_records WHERE status = 'failed' GROUP BY task_type ORDER BY 失败数 DESC LIMIT 10" },
      { label: '平均执行耗时', sql: "SELECT ROUND(AVG(execution_time)) AS 平均耗时_ms FROM task_records WHERE execution_time IS NOT NULL" },
    ]
  },
  {
    table: 'ai_conversations', label: 'ai_conversations · AI 对话',
    queries: [
      { label: '最近对话', sql: "SELECT id, user_id, module_type, title, message_count, created_at FROM ai_conversations ORDER BY created_at DESC LIMIT 20" },
      { label: '各模块对话数', sql: "SELECT module_type, COUNT(*) AS 数量 FROM ai_conversations GROUP BY module_type" },
    ]
  },
  {
    table: 'ai_messages', label: 'ai_messages · AI 消息',
    queries: [
      { label: '最近消息', sql: "SELECT id, conversation_id, role, LEFT(content, 50) AS 内容摘要, created_at FROM ai_messages ORDER BY created_at DESC LIMIT 20" },
      { label: '会话消息数 TOP', sql: "SELECT conversation_id, COUNT(*) AS 消息数, SUM(tokens_used) AS 总token FROM ai_messages GROUP BY conversation_id ORDER BY 消息数 DESC LIMIT 10" },
    ]
  },
  {
    table: 'ai_usage_log', label: 'ai_usage_log · AI 用量',
    queries: [
      { label: 'AI 调用量统计', sql: "SELECT module_type, COUNT(*) AS 调用次数, SUM(prompt_tokens) AS 输入token, SUM(completion_tokens) AS 输出token FROM ai_usage_log GROUP BY module_type" },
      { label: '近 30 天每日用量', sql: "SELECT DATE(created_at) AS 日期, SUM(total_tokens) AS 总token FROM ai_usage_log GROUP BY DATE(created_at) ORDER BY 日期 DESC LIMIT 30" },
    ]
  },
  {
    table: 'ai_config', label: 'ai_config · AI 配置',
    queries: [
      { label: '查看 AI 配置', sql: "SELECT id, provider, base_url, model, is_active, created_at FROM ai_config" },
    ]
  },
  {
    table: 'ai_conversation_contexts', label: 'ai_conversation_contexts · 会话上下文',
    queries: [
      { label: '上下文项统计', sql: "SELECT item_type, COUNT(*) AS 数量 FROM ai_conversation_contexts GROUP BY item_type" },
    ]
  },
  {
    table: 'datasource_connections', label: 'datasource_connections · 数据源连接',
    queries: [
      { label: '数据源连接列表', sql: "SELECT id, user_id, name, db_type, host, port, database, username FROM datasource_connections ORDER BY created_at DESC" },
      { label: '各类型数据源数', sql: "SELECT db_type, COUNT(*) AS 数量 FROM datasource_connections GROUP BY db_type" },
    ]
  },
  {
    table: 'app_config', label: 'app_config · 全局配置',
    queries: [
      { label: '全局配置列表', sql: "SELECT key, value, updated_at FROM app_config ORDER BY key" },
    ]
  },
  {
    table: 'support_messages', label: 'support_messages · 用户申请',
    queries: [
      { label: '申请列表', sql: "SELECT id, category, username, contact, status, created_at FROM support_messages ORDER BY created_at DESC LIMIT 20" },
      { label: '待处理申请', sql: "SELECT category, COUNT(*) AS 待处理 FROM support_messages WHERE status = 'pending' GROUP BY category" },
      { label: '申请分类/状态统计', sql: "SELECT category, status, COUNT(*) AS 数量 FROM support_messages GROUP BY category, status" },
    ]
  },
  {
    table: 'cache_stats_hourly', label: 'cache_stats_hourly · 缓存统计',
    queries: [
      { label: '最近 24 小时命中率', sql: "SELECT hour, hits, misses, hit_rate, total_keys FROM cache_stats_hourly ORDER BY hour DESC LIMIT 24" },
      { label: '累计命中率', sql: "SELECT SUM(hits) AS 总命中, SUM(misses) AS 总未命中, ROUND(SUM(hits) * 100.0 / NULLIF(SUM(hits) + SUM(misses), 0), 2) AS 平均命中率 FROM cache_stats_hourly" },
      { label: '键数/内存峰值', sql: "SELECT MAX(total_keys) AS 键数峰值, MAX(memory_bytes) AS 内存峰值字节 FROM cache_stats_hourly" },
    ]
  },
  {
    table: 'log_records', label: 'log_records · 日志记录',
    queries: [
      { label: '今日错误数', sql: "SELECT COUNT(*) AS 今日错误 FROM log_records WHERE level = 'ERROR' AND created_at >= NOW() - INTERVAL '1 day'" },
      { label: '错误/警告按模块统计', sql: "SELECT module, level, COUNT(*) AS 数量 FROM log_records GROUP BY module, level ORDER BY 数量 DESC" },
      { label: '最近错误', sql: "SELECT id, module, LEFT(message, 80) AS 消息摘要, created_at FROM log_records WHERE level = 'ERROR' ORDER BY created_at DESC LIMIT 20" },
      { label: '错误/警告按天趋势', sql: "SELECT DATE(created_at) AS 日期, COUNT(*) FILTER (WHERE level = 'ERROR') AS 错误, COUNT(*) FILTER (WHERE level = 'WARNING') AS 警告 FROM log_records GROUP BY DATE(created_at) ORDER BY 日期 DESC LIMIT 15" },
    ]
  },
]

function formatSize(bytes) {
  if (!bytes) return '-'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(2) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(2) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB'
}

async function loadTables() {
  try {
    const res = await listDatabaseTables()
    tables.value = res.data.tables || []
  } catch (e) {
    console.error('获取表列表失败:', e)
  }
}

function onTableSelect(tableName) {
  if (!tableName) {
    tableData.value = []
    tableColumns.value = []
    total.value = 0
    currentTableInfo.value = null
    return
  }
  const table = tables.value.find(t => t.name === tableName)
  if (table) {
    currentTableInfo.value = table
    tableColumns.value = table.columns.map(c => c.name)
    page.value = 1
    loadTableData()
  }
}

async function loadTableData() {
  if (!selectedTable.value) return
  try {
    const res = await getTableData(selectedTable.value, pageSize.value, (page.value - 1) * pageSize.value, searchQuery.value)
    tableData.value = res.data.data || []
    tableColumns.value = res.data.columns || []
    total.value = res.data.total || 0
  } catch (e) {
    console.error('获取表数据失败:', e)
  }
}

function viewStructure() {
  const table = tables.value.find(t => t.name === selectedTable.value)
  if (table) {
    currentStructure.value = {
      columns: table.columns || [],
      indexes: table.indexes || []
    }
    structureVisible.value = true
  }
}

async function exportData() {
  if (!selectedTable.value) return
  try {
    const res = await exportTableData(selectedTable.value, searchQuery.value)
    const blob = new Blob([res.data], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    const filename = res.headers['content-disposition']?.match(/filename="(.+)"/)?.[1] || `${selectedTable.value}.csv`
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (e) {
    console.error('导出失败:', e)
    ElMessage.error('导出失败')
  }
}

async function backupDb() {
  try {
    ElMessage.info('正在备份，请稍候...')
    const res = await backupDatabase()
    const blob = new Blob([res.data], { type: 'application/sql' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    const filename = res.headers['content-disposition']?.match(/filename="(.+)"/)?.[1] || 'database_backup.sql'
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
    ElMessage.success('备份成功')
  } catch (e) {
    console.error('备份失败:', e)
    const errMsg = e.response?.data?.detail || '备份失败'
    ElMessage.error(errMsg)
  }
}

function loadExample(query) {
  if (query) {
    sqlQuery.value = query
  }
}

async function executeSql() {
  if (!sqlQuery.value.trim()) {
    ElMessage.warning('请输入查询语句')
    return
  }
  try {
    const res = await executeQuery(sqlQuery.value)
    queryResult.value = res.data
    addToHistory(sqlQuery.value.trim())
  } catch (e) {
    const errMsg = e.response?.data?.detail || '查询失败'
    ElMessage.error(errMsg)
  }
}

function addToHistory(query) {
  const MAX_HISTORY = 10
  const newHistory = [query, ...sqlHistory.value.filter(h => h !== query)].slice(0, MAX_HISTORY)
  sqlHistory.value = newHistory
  localStorage.setItem('admin_sql_history', JSON.stringify(newHistory))
}

function loadFromHistory(query) {
  if (query) {
    sqlQuery.value = query
  }
}

function clearHistory() {
  sqlHistory.value = []
  selectedHistory.value = null
  localStorage.removeItem('admin_sql_history')
}

function loadHistoryFromStorage() {
  try {
    const saved = localStorage.getItem('admin_sql_history')
    if (saved) {
      sqlHistory.value = JSON.parse(saved)
    }
  } catch (e) {
    console.error('加载历史记录失败:', e)
  }
}

async function loadClickHouseDatabases() {
  try {
    const res = await listClickHouseDatabases()
    chDatabases.value = res.data.databases || []
    // 优先选择业务库（非系统库），避免默认落在 default/system 等系统库
    const biz = chDatabases.value.filter(d => !CH_SYSTEM_DATABASES.includes(d))
    const target = biz.length ? biz[0] : (chDatabases.value[0] || '')
    if (target && target !== chDatabase.value) {
      chDatabase.value = target
    }
    await loadClickHouseTables()
  } catch (e) {
    console.error('获取 ClickHouse 数据库失败:', e)
    ElMessage.error('ClickHouse 连接失败或未启用')
  }
}

async function loadClickHouseTables() {
  try {
    const res = await listClickHouseTables(chDatabase.value)
    chTables.value = (res.data.tables || []).map(t => ({ name: t, database: res.data.database }))
  } catch (e) {
    console.error('获取 ClickHouse 表失败:', e)
  }
}

async function executeClickHouseSql() {
  if (!chQuery.value.trim()) {
    ElMessage.warning('请输入查询语句')
    return
  }
  try {
    const res = await executeClickHouseQuery(chQuery.value)
    chQueryResult.value = res.data
  } catch (e) {
    const errMsg = e.response?.data?.detail || '查询失败'
    ElMessage.error(errMsg)
  }
}

// ============ ClickHouse 同步管理（批次D）============
async function loadClickHouseSyncStatus() {
  chSyncLoading.value = true
  try {
    const [resStatus, resStorage] = await Promise.all([
      getClickHouseSyncStatus(),
      getClickHouseStorageStats(),
    ])
    chStatus.value = resStatus.data || {}
    chSyncItems.value = resStatus.data?.items || []
    chStorage.value = resStorage.data || {}
  } catch (e) {
    console.error('获取 ClickHouse 同步状态失败:', e)
    ElMessage.error('获取 ClickHouse 同步状态失败')
  } finally {
    chSyncLoading.value = false
  }
}

async function handleSyncClickHouse(row) {
  try {
    const res = await syncClickHouseDataset(row.dataset_id)
    ElMessage.success(res.data?.message || '同步任务已触发')
    await loadClickHouseSyncStatus()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '触发同步失败')
  }
}

async function handleCleanupClickHouse(row) {
  try {
    const res = await cleanupClickHouseDataset(row.dataset_id)
    ElMessage.success(res.data?.message || '副本已清理')
    await loadClickHouseSyncStatus()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '清理副本失败')
  }
}

async function handleCleanupAllClickHouse() {
  try {
    const res = await cleanupAllClickHouse()
    ElMessage.success(res.data?.message || '已清理全部副本')
    await loadClickHouseSyncStatus()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '清理失败')
  }
}

onMounted(() => {
  loadTables()
  loadHistoryFromStorage()
  loadClickHouseSyncStatus()
})
</script>
