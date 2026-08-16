<template>
  <div>
    <el-tabs v-model="activeTab" type="border-card" @tab-change="onTabChange">
      <!-- 数据列表 Tab -->
      <el-tab-pane label="数据列表" name="list">
        <!-- 数据状态说明 -->
        <el-alert type="info" :closable="false" show-icon style="margin-bottom: 12px;">
          <template #title>数据状态说明</template>
          <div style="font-size: 12px; line-height: 1.8; color: #606266;">
            活跃（active）→ 正常使用中的数据，用户端可见可操作<br/>
            已删除（deleted）→ 用户从数据管理删除的数据，在用户端回收站中，用户可恢复
          </div>
        </el-alert>

        <!-- 分类统计卡片 -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">分类统计</div>
          </div>
          <div class="stats-grid" style="grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));">
            <div
              v-for="(item, key) in categoryStats"
              :key="key"
              class="stat-card"
              :class="{ 'stat-card-active': filter.type === key }"
              style="cursor: pointer;"
              @click="filterByCategory(key)"
            >
              <div class="stat-value">{{ item.label }}</div>
              <div class="stat-count">{{ item.count }}</div>
              <div style="font-size: 12px; color: #9ca3af; margin-top: 2px;">
                {{ formatSize(item.total_size) }}
              </div>
            </div>
          </div>
        </div>

        <!-- 筛选栏 -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">筛选条件</div>
            <div class="flex-center" style="gap: 12px;">
              <el-select v-model="filter.type" placeholder="按类型筛选" clearable style="width: 120px;" @change="loadDatasets">
                <el-option label="全部" value="" />
                <el-option label="数据分析" value="data_analysis" />
                <el-option label="数据清洗" value="cleaning" />
                <el-option label="数据挖掘" value="data_mining" />
                <el-option label="特征工程" value="feature_engineering" />
                <el-option label="机器学习" value="ml" />
                <el-option label="回收站" value="trash" />
                <el-option label="其它" value="other" />
              </el-select>
              <el-select v-model="filter.userId" placeholder="按用户筛选" clearable filterable style="width: 120px;" @change="loadDatasets">
                <el-option v-for="u in userList" :key="u.id" :label="u.username" :value="u.id" />
              </el-select>
              <el-select v-model="filter.status" placeholder="按状态筛选" clearable style="width: 120px;" @change="loadDatasets">
                <el-option label="全部" value="" />
                <el-option label="活跃" value="active" />
                <el-option label="已删除" value="deleted" />
              </el-select>
              <el-input v-model="filter.keyword" placeholder="搜索文件名" clearable style="width: 180px;" @keyup.enter="loadDatasets" @clear="loadDatasets" />
              <el-button size="small" @click="loadDatasets">
                <el-icon><Search /></el-icon> 查询
              </el-button>
              <el-button size="small" @click="resetFilters">
                <el-icon><Refresh /></el-icon> 重置
              </el-button>
            </div>
          </div>
        </div>

        <!-- 数据列表 -->
        <div class="card">
          <div class="card-header">
            <div class="card-title">数据列表</div>
          </div>
          <div class="data-table-wrapper">
            <el-table 
              :data="datasets" 
              border 
              v-loading="datasetsLoading"
            >
              <el-table-column label="文件名" min-width="200" show-overflow-tooltip>
                <template #default="{ row }">
                  <div class="file-cell">
                    <span class="ds-dot" :style="{ background: getDatasetColor(row) }"></span>
                    <span class="file-name">{{ row.name }}</span>
                    <span class="file-id">#{{ row.id }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="所属分类" width="120">
                <template #default="{ row }">
                  <span v-if="row.source_type === 'remote_db'" style="color: #409eff">远程数据库</span>
                  <span v-else :style="{ color: getCategoryColor(row.module_source) }">
                    {{ getCategoryLabel(row.module_source) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="标签" width="120">
                <template #default="{ row }">
                  <el-tag :type="getTagType(row)" size="small">
                    {{ getTagLabel(row) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="大小" width="100">
                <template #default="{ row }">
                  {{ formatSize(row.file_size) }}
                </template>
              </el-table-column>
              <el-table-column label="创建时间" width="160">
                <template #default="{ row }">
                  {{ formatTime(row.created_at) }}
                </template>
              </el-table-column>
              <el-table-column label="所属用户" width="100">
                <template #default="{ row }">
                  {{ row.username || '-' }}
                </template>
              </el-table-column>
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag :type="getStatusType(row.status)" size="small">
                    {{ getStatusLabel(row.status) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="160" align="center">
                <template #default="{ row }">
                  <el-button size="small" @click="handleView(row)">详情</el-button>
                  <el-popconfirm
                    title="确定要永久删除该数据集吗？此操作不可恢复"
                    confirm-button-text="确定删除"
                    cancel-button-text="取消"
                    @confirm="handlePermanentDelete(row)"
                  >
                    <template #reference>
                      <el-button size="small" type="danger">永久删除</el-button>
                    </template>
                  </el-popconfirm>
                </template>
              </el-table-column>
            </el-table>
            <div class="pagination-wrapper">
              <el-pagination
                @size-change="handleSizeChange"
                @current-change="handleCurrentChange"
                :current-page="pagination.current"
                :page-sizes="[20, 50, 100]"
                :page-size="pagination.size"
                layout="total, sizes, prev, pager, next, jumper"
                :total="pagination.total"
              />
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- 已损坏 Tab -->
      <el-tab-pane label="已损坏" name="corrupted">
        <!-- 已损坏数据说明 -->
        <el-alert type="error" :closable="false" show-icon style="margin-bottom: 12px;">
          <template #title>已损坏数据说明</template>
          <div style="font-size: 12px; line-height: 1.8; color: #606266;">
            已损坏（corrupted）→ 物理文件丢失但数据库记录存在，需修复或彻底删除
          </div>
        </el-alert>

        <div class="card">
          <div class="card-header">
            <div class="card-title">筛选条件</div>
            <div class="flex-center" style="gap: 12px;">
              <el-select v-model="corruptedFilter.userId" placeholder="按用户筛选" clearable filterable style="width: 120px;" @change="loadCorruptedDatasets">
                <el-option v-for="u in userList" :key="u.id" :label="u.username" :value="u.id" />
              </el-select>
              <el-input v-model="corruptedKeyword" placeholder="搜索文件名" clearable style="width: 180px;" @keyup.enter="loadCorruptedDatasets" @clear="loadCorruptedDatasets" />
              <el-button size="small" @click="loadCorruptedDatasets">
                <el-icon><Search /></el-icon> 查询
              </el-button>
              <el-button size="small" @click="resetCorruptedFilters">
                <el-icon><Refresh /></el-icon> 重置
              </el-button>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <div class="card-title">已损坏数据（文件在存储中不存在，仅数据库记录）</div>
          </div>
          <div class="data-table-wrapper">
            <el-table 
              :data="corruptedDatasets" 
              border 
              v-loading="corruptedLoading"
            >
              <el-table-column label="文件名" min-width="200" show-overflow-tooltip>
                <template #default="{ row }">
                  <div class="file-cell">
                    <span class="ds-dot" :style="{ background: getDatasetColor(row) }"></span>
                    <span class="file-name">{{ row.name }}</span>
                    <span class="file-id">#{{ row.id }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="所属分类" width="120">
                <template #default="{ row }">
                  <span :style="{ color: getCategoryColor(row.module_source) }">
                    {{ getCategoryLabel(row.module_source) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="标签" width="120">
                <template #default="{ row }">
                  <el-tag :type="getTagType(row)" size="small">
                    {{ getTagLabel(row) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="创建时间" width="160">
                <template #default="{ row }">
                  {{ formatTime(row.created_at) }}
                </template>
              </el-table-column>
              <el-table-column label="所属用户" width="100">
                <template #default="{ row }">
                  {{ row.username || '-' }}
                </template>
              </el-table-column>
              <el-table-column label="操作" width="160" align="center">
                <template #default="{ row }">
                  <el-button size="small" @click="handleView(row)">详情</el-button>
                  <el-button size="small" type="danger" @click="handleDeleteCorrupted(row)">删除记录</el-button>
                </template>
              </el-table-column>
            </el-table>
            <div class="pagination-wrapper">
              <el-pagination
                @size-change="handleCorruptedSizeChange"
                @current-change="handleCorruptedCurrentChange"
                :current-page="corruptedPagination.current"
                :page-sizes="[20, 50, 100]"
                :page-size="corruptedPagination.size"
                layout="total, sizes, prev, pager, next, jumper"
                :total="corruptedPagination.total"
              />
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- 已清空 Tab -->
      <el-tab-pane label="已清空" name="trash">
        <!-- 已清空数据说明 -->
        <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 12px;">
          <template #title>已清空数据说明</template>
          <div style="font-size: 12px; line-height: 1.8; color: #606266;">
            已清空（purged）→ 用户从自己回收站永久清空的数据，用户端不再显示，管理端可恢复
          </div>
        </el-alert>

        <div class="card">
          <div class="card-header">
            <div class="card-title">筛选条件</div>
            <div class="flex-center" style="gap: 12px;">
              <el-select v-model="trashFilter.userId" placeholder="按用户筛选" clearable filterable style="width: 120px;" @change="loadTrashDatasets">
                <el-option v-for="u in userList" :key="u.id" :label="u.username" :value="u.id" />
              </el-select>
              <el-input v-model="trashKeyword" placeholder="搜索文件名" clearable style="width: 180px;" @keyup.enter="loadTrashDatasets" @clear="loadTrashDatasets" />
              <el-button size="small" @click="loadTrashDatasets">
                <el-icon><Search /></el-icon> 查询
              </el-button>
              <el-button size="small" @click="resetTrashFilters">
                <el-icon><Refresh /></el-icon> 重置
              </el-button>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <div class="card-title">回收站数据列表</div>
            <el-button 
              type="success" 
              size="small" 
              :disabled="selectedTrashRows.length === 0"
              @click="handleBatchRestore"
            >
              <el-icon><Refresh /></el-icon> 批量恢复 ({{ selectedTrashRows.length }})
            </el-button>
          </div>
          <div class="data-table-wrapper">
            <el-table 
              :data="trashDatasets" 
              border 
              v-loading="trashLoading"
              @selection-change="handleTrashSelectionChange"
            >
              <el-table-column type="selection" width="50" align="center" />
              <el-table-column label="文件名" min-width="200" show-overflow-tooltip>
                <template #default="{ row }">
                  <div class="file-cell">
                    <span class="ds-dot" :style="{ background: getDatasetColor(row) }"></span>
                    <span class="file-name">{{ row.name }}</span>
                    <span class="file-id">#{{ row.id }}</span>
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="所属分类" width="120">
                <template #default="{ row }">
                  <span :style="{ color: getCategoryColor(row.module_source) }">
                    {{ getCategoryLabel(row.module_source) }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column label="标签" width="120">
                <template #default="{ row }">
                  <el-tag :type="getTagType(row)" size="small">
                    {{ getTagLabel(row) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="大小" width="100">
                <template #default="{ row }">
                  {{ formatSize(row.file_size) }}
                </template>
              </el-table-column>
              <el-table-column label="清空时间" width="160">
                <template #default="{ row }">
                  {{ formatTime(row.deleted_at) }}
                </template>
              </el-table-column>
              <el-table-column label="所属用户" width="100">
                <template #default="{ row }">
                  {{ row.username || '-' }}
                </template>
              </el-table-column>
              <el-table-column label="操作" width="160" align="center">
                <template #default="{ row }">
                  <el-button size="small" @click="handleView(row)">详情</el-button>
                  <el-button size="small" type="success" @click="handleRestore(row)">恢复</el-button>
                </template>
              </el-table-column>
            </el-table>
            <div class="pagination-wrapper">
              <el-pagination
                @size-change="handleTrashSizeChange"
                @current-change="handleTrashCurrentChange"
                :current-page="trashPagination.current"
                :page-sizes="[20, 50, 100]"
                :page-size="trashPagination.size"
                layout="total, sizes, prev, pager, next, jumper"
                :total="trashPagination.total"
              />
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 查看详情弹窗 -->
    <el-dialog v-model="detailVisible" title="数据详情" width="600px">
      <el-descriptions :column="2" border v-if="currentDetail">
        <el-descriptions-item label="文件名">{{ currentDetail.name }}</el-descriptions-item>
        <el-descriptions-item label="所属分类">
          <span :style="{ color: getCategoryColor(currentDetail.module_source) }">
            {{ getCategoryLabel(currentDetail.module_source) }}
          </span>
        </el-descriptions-item>
        <el-descriptions-item label="标签">
          <el-tag :type="getTagType(currentDetail)" size="small">{{ getTagLabel(currentDetail) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="大小">{{ formatSize(currentDetail.file_size) }}</el-descriptions-item>
        <el-descriptions-item label="行数">{{ currentDetail.row_count || '-' }}</el-descriptions-item>
        <el-descriptions-item label="算法">{{ currentDetail.algorithm || '-' }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="getStatusType(currentDetail.status)" size="small">{{ getStatusLabel(currentDetail.status) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="所属用户">{{ currentDetail.username || '-' }}</el-descriptions-item>
        <el-descriptions-item label="创建时间" :span="2">{{ formatTime(currentDetail.created_at) }}</el-descriptions-item>
        <el-descriptions-item label="数据来源" :span="2">{{ getSourceLabel(currentDetail) }}</el-descriptions-item>
        <el-descriptions-item label="文件路径" :span="2">{{ currentDetail.file_path || '-' }}</el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh } from '@element-plus/icons-vue'
import { 
  listBusinessDatasets, 
  getBusinessStats, 
  listUsers,
  restorePurgedDataset,
  adminPermanentDeleteDataset
} from '@/api/admin'
import { getDatasetColor } from '@/utils/labels'

const activeTab = ref('list')

// ===== 数据列表 =====
const datasets = ref([])
const datasetsLoading = ref(false)
const userList = ref([])

const filter = reactive({
  type: '',
  userId: '',
  status: '',
  keyword: ''
})

const pagination = reactive({
  current: 1,
  size: 20,
  total: 0
})

// ===== 已损坏数据 =====
const corruptedDatasets = ref([])
const corruptedLoading = ref(false)
const corruptedFilter = reactive({ userId: '' })
const corruptedKeyword = ref('')

const corruptedPagination = reactive({
  current: 1,
  size: 20,
  total: 0
})

// ===== 业务回收站 =====
const trashDatasets = ref([])
const trashLoading = ref(false)
const trashFilter = reactive({ userId: '' })
const trashKeyword = ref('')
const selectedTrashRows = ref([])

const trashPagination = reactive({
  current: 1,
  size: 20,
  total: 0
})

// ===== 详情弹窗 =====
const detailVisible = ref(false)
const currentDetail = ref(null)

const categoryConfig = {
  data_analysis: { label: '数据分析', color: '#409eff' },
  cleaning: { label: '数据清洗', color: '#67c23a' },
  data_mining: { label: '数据挖掘', color: '#e6a23c' },
  feature_engineering: { label: '特征工程', color: '#909399' },
  ml: { label: '机器学习', color: '#f56c6c' },
  batch_predict: { label: '机器学习', color: '#f56c6c' },
  upload: { label: '数据分析', color: '#409eff' },
  data_source: { label: '远程数据库', color: '#409eff' },
  trash: { label: '回收站', color: '#9ca3af' },
  other: { label: '其它', color: '#9ca3af' }
}

const categoryStats = ref({
  data_analysis: { count: 0, total_size: 0, label: '数据分析' },
  cleaning: { count: 0, total_size: 0, label: '数据清洗' },
  data_mining: { count: 0, total_size: 0, label: '数据挖掘' },
  feature_engineering: { count: 0, total_size: 0, label: '特征工程' },
  ml: { count: 0, total_size: 0, label: '机器学习' },
  trash: { count: 0, total_size: 0, label: '回收站' },
  other: { count: 0, total_size: 0, label: '其它' }
})

function getCategoryColor(moduleSource) {
  return categoryConfig[moduleSource]?.color || '#9ca3af'
}

function getCategoryLabel(moduleSource) {
  return categoryConfig[moduleSource]?.label || '未知'
}

// 数据来源展示：远程数据库显示连接与表名，本地数据返回"本地文件"
function getSourceLabel(row) {
  if (!row) return '-'
  if (row.source_type === 'remote_db') {
    const conn = row.connection_id ? `连接#${row.connection_id}` : ''
    const tbl = row.table_name ? `表 ${row.table_name}` : ''
    return `远程数据库${conn ? '（' + conn + (tbl ? ' · ' + tbl : '') + '）' : ''}`
  }
  return '本地文件'
}

function getTagLabel(row) {
  const { module_source, artifact_type, algorithm } = row
  
  const tagMap = {
    data_analysis: {
      raw_data: '原始数据',
      analysis_data: '原始数据',
      analysis_report: '分析报告'
    },
    cleaning: {
      raw_data: '原始数据',
      cleaning_result: '清洗产物',
      cleaning_raw: '清洗原始数据'
    },
    data_mining: {
      raw_data: '原始数据',
      cluster_result: '聚类结果',
      anomaly_result: '异常检测',
      association_rules: '关联规则',
      sequential_patterns: '序列模式'
    },
    feature_engineering: {
      raw_data: '原始数据',
      feature_select: '特征选择',
      feature_selected: '特征选择',
      column_pool: '列池导出',
      feature_result: '特征工程产物'
    },
    ml: {
      raw_data: '原始数据',
      predict_data: '预测数据',
      prediction_result: '预测结果',
      ml_prediction: '预测结果',
      ml_model: '分类模型',
      ml_report: '学习报告'
    },
    batch_predict: {
      predict_data: '预测数据',
      ml_prediction: '预测结果'
    },
    upload: {
      raw_data: '原始数据',
      analysis_data: '原始数据',
      analysis_report: '分析报告'
    },

  }
  
  if (tagMap[module_source]?.[artifact_type]) {
    return tagMap[module_source][artifact_type]
  }
  
  if (algorithm) {
    if (algorithm.includes('K-Means') || algorithm.includes('聚类')) return '聚类结果'
    if (algorithm.includes('Isolation') || algorithm.includes('异常')) return '异常检测'
    if (algorithm.includes('Apriori') || algorithm.includes('关联')) return '关联规则'
    if (algorithm.includes('分类')) return '分类模型'
    if (algorithm.includes('回归')) return '回归模型'
  }
  
  if (artifact_type) {
    const typeMap = {
      raw_data: '原始数据',
      analysis_data: '原始数据',
      analysis_report: '分析报告',
      cleaning_result: '清洗产物',
      cleaning_raw: '清洗原始数据',
      cluster_result: '聚类结果',
      anomaly_result: '异常检测',
      association_rules: '关联规则',
      sequential_patterns: '序列模式',
      feature_select: '特征选择',
      feature_selected: '特征选择',
      column_pool: '列池导出',
      feature_result: '特征工程产物',
      predict_data: '预测数据',
      prediction_result: '预测结果',
      ml_prediction: '预测结果',
      ml_model: (algorithm) => {
        // 从算法字段中提取括号内的任务类型来判断分类/回归
        // 算法字段格式: "逻辑回归（分类）" / "随机森林（回归）"(全角括号)
        // 不能用 includes('回归') 判断,因为"逻辑回归"也包含"回归"子串
        if (algorithm) {
          if (algorithm.includes('（分类）') || algorithm.includes('(classification)') || algorithm.includes('(分类)')) {
            return '分类模型'
          }
          if (algorithm.includes('（回归）') || algorithm.includes('(regression)') || algorithm.includes('(回归)')) {
            return '回归模型'
          }
        }
        return '分类模型'
      },
      ml_report: '学习报告'
    }
    const result = typeMap[artifact_type]
    if (typeof result === 'function') {
      return result(row.algorithm)
    }
    return result || artifact_type.replace(/_/g, ' ')
  }
  
  return '其他'
}

function getTagType(row) {
  const { artifact_type } = row
  
  if (!artifact_type) return 'info'
  
  if (artifact_type === 'raw_data' || artifact_type === 'analysis_data' || artifact_type === 'cleaning_raw') {
    return 'info'
  }
  if (artifact_type === 'analysis_report' || artifact_type === 'ml_report') {
    return 'success'
  }
  if (artifact_type === 'cleaning_result') {
    return 'warning'
  }
  if (artifact_type === 'cluster_result' || artifact_type === 'anomaly_result' || artifact_type === 'association_rules' || artifact_type === 'sequential_patterns') {
    return 'success'
  }
  if (artifact_type === 'feature_select' || artifact_type === 'feature_selected' || artifact_type === 'column_pool' || artifact_type === 'feature_result') {
    return 'warning'
  }
  if (artifact_type === 'predict_data') {
    return 'info'
  }
  if (artifact_type === 'prediction_result' || artifact_type === 'ml_prediction') {
    return 'success'
  }
  if (artifact_type === 'ml_model') {
    return 'danger'
  }
  
  return 'info'
}

function getStatusType(status) {
  switch (status) {
    case 'active': return 'success'
    case 'deleted': return 'warning'
    case 'purged': return 'danger'
    case 'corrupted': return 'danger'
    default: return 'info'
  }
}

function getStatusLabel(status) {
  switch (status) {
    case 'active': return '活跃'
    case 'deleted': return '已删除'
    case 'purged': return '已清空'
    case 'corrupted': return '已损坏'
    default: return status
  }
}

function formatSize(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
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

function loadStats() {
  getBusinessStats().then(res => {
    const stats = res.data
    const byModuleList = stats.by_module || []
    
    // 将数组转换为对象，方便按 module_source 查找
    const byModule = {}
    byModuleList.forEach(item => {
      byModule[item.module_source] = {
        count: item.count || 0,
        total_size: item.total_size || 0
      }
    })
    
    Object.keys(categoryStats.value).forEach(key => {
      if (key === 'other') {
        categoryStats.value[key].count = 0
        categoryStats.value[key].total_size = 0
      } else if (key === 'data_analysis') {
        // data_analysis 对应 upload 模块
        const moduleStat = byModule[key] || byModule['upload'] || {}
        categoryStats.value[key].count = moduleStat.count || 0
        categoryStats.value[key].total_size = moduleStat.total_size || 0
      } else if (key === 'trash') {
        // 回收站统计：用户软删除的数据（status=deleted），与用户端回收站对应
        categoryStats.value[key].count = stats.trash_count || 0
        categoryStats.value[key].total_size = stats.trash_size || 0
      } else {
        const moduleStat = byModule[key] || {}
        categoryStats.value[key].count = moduleStat.count || 0
        categoryStats.value[key].total_size = moduleStat.total_size || 0
      }
    })
  }).catch(() => {})
}

function loadDatasets() {
  datasetsLoading.value = true
  const params = {
    page: pagination.current,
    page_size: pagination.size
  }

  // 回收站是状态维度（status=deleted），不是来源模块维度，需特殊处理
  if (filter.type === 'trash') {
    params.status = 'deleted'
  } else if (filter.type) {
    params.module_source = filter.type
  }

  if (filter.userId) {
    params.user_id = filter.userId
  }

  // 已通过回收站分类设置 status，避免被状态筛选框覆盖
  if (filter.type !== 'trash' && filter.status) {
    params.status = filter.status
  }

  if (filter.keyword) {
    params.keyword = filter.keyword
  }

  listBusinessDatasets(params).then(res => {
    datasets.value = res.data.datasets || []
    pagination.total = res.data.total || 0
  }).catch(err => {
    ElMessage.error('加载数据失败: ' + (err.response?.data?.detail || err.message))
  }).finally(() => {
    datasetsLoading.value = false
  })
}

function loadTrashDatasets() {
  trashLoading.value = true
  const params = {
    page: trashPagination.current,
    page_size: trashPagination.size,
    status: 'purged'
  }
  
  if (trashFilter.userId) {
    params.user_id = trashFilter.userId
  }
  
  if (trashKeyword.value) {
    params.keyword = trashKeyword.value
  }
  
  listBusinessDatasets(params).then(res => {
    trashDatasets.value = res.data.datasets || []
    trashPagination.total = res.data.total || 0
  }).catch(err => {
    ElMessage.error('加载回收站数据失败: ' + (err.response?.data?.detail || err.message))
  }).finally(() => {
    trashLoading.value = false
  })
}

function loadCorruptedDatasets() {
  corruptedLoading.value = true
  const params = {
    page: corruptedPagination.current,
    page_size: corruptedPagination.size,
    status: 'corrupted'
  }
  
  if (corruptedFilter.userId) {
    params.user_id = corruptedFilter.userId
  }
  
  if (corruptedKeyword.value) {
    params.keyword = corruptedKeyword.value
  }
  
  listBusinessDatasets(params).then(res => {
    corruptedDatasets.value = res.data.datasets || []
    corruptedPagination.total = res.data.total || 0
  }).catch(err => {
    ElMessage.error('加载已损坏数据失败: ' + (err.response?.data?.detail || err.message))
  }).finally(() => {
    corruptedLoading.value = false
  })
}

function loadUsers() {
  listUsers({ page_size: 100 }).then(res => {
    userList.value = res.data.users || []
  }).catch(() => {})
}

function filterByCategory(category) {
  filter.type = category
  pagination.current = 1
  loadDatasets()
}

function resetFilters() {
  filter.type = ''
  filter.userId = ''
  filter.status = ''
  filter.keyword = ''
  pagination.current = 1
  loadDatasets()
}

function resetTrashFilters() {
  trashFilter.userId = ''
  trashKeyword.value = ''
  trashPagination.current = 1
  loadTrashDatasets()
}

function resetCorruptedFilters() {
  corruptedFilter.userId = ''
  corruptedKeyword.value = ''
  corruptedPagination.current = 1
  loadCorruptedDatasets()
}

function handleSizeChange(size) {
  pagination.size = size
  pagination.current = 1
  loadDatasets()
}

function handleCurrentChange(page) {
  pagination.current = page
  loadDatasets()
}

function handleTrashSizeChange(size) {
  trashPagination.size = size
  trashPagination.current = 1
  loadTrashDatasets()
}

function handleTrashCurrentChange(page) {
  trashPagination.current = page
  loadTrashDatasets()
}

function handleCorruptedSizeChange(size) {
  corruptedPagination.size = size
  corruptedPagination.current = 1
  loadCorruptedDatasets()
}

function handleCorruptedCurrentChange(page) {
  corruptedPagination.current = page
  loadCorruptedDatasets()
}

function handleDeleteCorrupted(row) {
  ElMessageBox.confirm(
    `确定要删除 "${row.name}"（#${row.id}）的记录吗？此操作不可恢复。`,
    '删除确认',
    {
      type: 'warning',
      confirmButtonText: '确定删除',
      cancelButtonText: '取消'
    }
  ).then(() => {
    adminPermanentDeleteDataset(row.id).then(() => {
      ElMessage.success('已删除损坏的记录')
      loadCorruptedDatasets()
      loadStats()
    }).catch(err => {
      ElMessage.error('删除失败: ' + (err.response?.data?.detail || err.message))
    })
  }).catch(() => {})
}

// 管理端永久删除数据集（数据列表Tab）
function handlePermanentDelete(row) {
  adminPermanentDeleteDataset(row.id).then(() => {
    ElMessage.success(`已永久删除 "${row.name}"`)
    loadDatasets()
    loadStats()
  }).catch(err => {
    ElMessage.error('删除失败: ' + (err.response?.data?.detail || err.message))
  })
}

function handleView(row) {
  currentDetail.value = row
  detailVisible.value = true
}

function handleRestore(row) {
  ElMessageBox.confirm(
    `确定要恢复 "${row.name}"（#${row.id}）吗？恢复后将在用户端回收站中可见。`,
    '恢复确认',
    {
      type: 'info',
      confirmButtonText: '确定恢复',
      cancelButtonText: '取消'
    }
  ).then(() => {
    restorePurgedDataset(row.id).then(() => {
      ElMessage.success('恢复成功')
      loadTrashDatasets()
      loadStats()
    }).catch(err => {
      ElMessage.error('恢复失败: ' + (err.response?.data?.detail || err.message))
    })
  }).catch(() => {})
}

function handleTrashSelectionChange(rows) {
  selectedTrashRows.value = rows
}

function handleBatchRestore() {
  if (selectedTrashRows.value.length === 0) return
  
  ElMessageBox.confirm(
    `确定要批量恢复选中的 ${selectedTrashRows.value.length} 个数据吗？恢复后将在用户端回收站中可见。`,
    '批量恢复确认',
    {
      type: 'info',
      confirmButtonText: '确定恢复',
      cancelButtonText: '取消'
    }
  ).then(() => {
    const restorePromises = selectedTrashRows.value.map(row => {
      return restorePurgedDataset(row.id).catch(() => {})
    })
    
    Promise.all(restorePromises).then(() => {
      ElMessage.success(`成功恢复 ${selectedTrashRows.value.length} 个数据`)
      selectedTrashRows.value = []
      loadTrashDatasets()
      loadStats()
    }).catch(() => {
      ElMessage.error('批量恢复失败')
    })
  }).catch(() => {})
}

function onTabChange(tabName) {
  if (tabName === 'trash') {
    loadTrashDatasets()
  } else if (tabName === 'corrupted') {
    loadCorruptedDatasets()
  }
}

onMounted(() => {
  loadStats()
  loadUsers()
  loadDatasets()
  loadTrashDatasets()
  loadCorruptedDatasets()
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

.pagination-wrapper {
  display: flex;
  justify-content: flex-end;
  padding: 16px;
}

/* 文件名单元格：色点 + 名称 + #id */
.file-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.file-cell .file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-cell .file-id {
  flex: none;
  font-size: 12px;
  color: var(--text-muted, #909399);
}

/* 数据集色点（按 id 派生，同名数据集靠颜色区分） */
.ds-dot {
  flex: none;
  width: 9px;
  height: 9px;
  border-radius: 50%;
}
</style>