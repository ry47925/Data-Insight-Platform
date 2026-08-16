<template>
  <div class="task-history">
    <!-- 任务记录表格 -->
    <div class="card">
      <div class="card-header">
        <span class="card-title" style="margin-bottom:0">我的操作历史</span>
      </div>

      <!-- 筛选栏：两级联动（操作大类+具体操作）+ 状态 + 时间范围 + 关键字 -->
      <div class="filter-bar">
        <el-select v-model="filterCategory" placeholder="操作大类" clearable size="small" @change="onCategoryChange" style="width: 130px">
          <el-option label="文件上传" value="upload" />
          <el-option label="数据治理" value="dataset" />
          <el-option label="数据清洗" value="cleaning" />
          <el-option label="数据分析" value="data_analysis" />
          <el-option label="数据挖掘" value="data_mining" />
          <el-option label="特征工程" value="feature_engineering" />
          <el-option label="机器学习" value="ml_all" />
          <el-option label="AI分析" value="ai" />
          <el-option label="账号管理" value="user_admin" />
        </el-select>

        <el-select v-model="filterOperation" placeholder="具体操作" clearable size="small"
                   @change="onFilterChange" :disabled="!filterCategory || operationOptions.length === 0" style="width: 140px">
          <el-option v-for="op in operationOptions" :key="op.value" :label="op.label" :value="op.value" />
        </el-select>

        <el-select v-model="filterStatus" placeholder="状态" clearable size="small" @change="onFilterChange" style="width: 100px">
          <el-option label="成功" value="success" />
          <el-option label="失败" value="failed" />
          <el-option label="运行中" value="running" />
          <el-option label="等待中" value="pending" />
          <el-option label="已取消" value="cancelled" />
        </el-select>

        <el-select v-model="filterSource" placeholder="数据来源" clearable size="small" @change="onFilterChange" style="width: 120px">
          <el-option label="本地数据" :value="false" />
          <el-option label="远程数据库" :value="true" />
        </el-select>

        <el-select v-model="filterDateRange" placeholder="时间范围" clearable size="small" @change="onDateRangeChange" style="width: 120px">
          <el-option label="今天" value="today" />
          <el-option label="近 7 天" value="7d" />
          <el-option label="近 30 天" value="30d" />
          <el-option label="自定义" value="custom" />
        </el-select>
        <el-date-picker v-if="filterDateRange === 'custom'" v-model="customDateRange"
                        type="datetimerange" size="small" @change="onFilterChange"
                        start-placeholder="开始时间" end-placeholder="结束时间"
                        value-format="YYYY-MM-DDTHH:mm:ss" style="width: 340px" />

        <el-input v-model="filterKeyword" placeholder="搜索数据集名称" clearable size="small"
                  style="width: 180px" @keyup.enter="onFilterChange" @clear="onFilterChange" />

        <el-button size="small" type="primary" @click="onFilterChange">搜索</el-button>
        <el-button size="small" @click="loadTaskRecords" :loading="taskRecordsLoading">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>

        <el-tag v-if="filterDatasetId" closable size="small" type="info" @close="clearDatasetFilter">
          数据集 #{{ filterDatasetId }}
        </el-tag>
      </div>

      <div v-if="taskRecordsLoading && taskRecords.length === 0" class="loading-container">
        <el-icon class="is-loading" :size="32"><Loading /></el-icon>
        <div class="loading-text">正在加载操作历史…</div>
      </div>

      <div v-else-if="!taskRecordsLoading && taskRecords.length === 0" class="empty-state">
        <el-icon class="empty-icon" :size="48"><FolderDelete /></el-icon>
        <div class="empty-text">暂无操作记录</div>
        <div class="empty-hint">在各功能模块中操作后，记录将自动汇总到此处</div>
      </div>

      <el-table
        v-else
        :data="taskRecords"
        border stripe
        style="width: 100%;"
        :default-sort="{ prop: 'created_at', order: 'descending' }"
      >
        <el-table-column label="#" prop="id" width="80" align="center" />
        <el-table-column label="操作类型" width="130" align="center">
          <template #default="{ row }">
            <el-tag :type="row.task_type_tag_type || 'info'" size="small" effect="plain">
              {{ row.task_type_label || row.task_type }}
            </el-tag>
            <el-tag v-if="row.is_remote" type="warning" size="small" effect="plain" style="margin-left:4px;">远程</el-tag>
            <div v-if="row.operation_label" class="operation-sub">{{ row.operation_label }}</div>
          </template>
        </el-table-column>
        <el-table-column label="操作对象" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span>{{ formatOperationObject(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="getStatusTagType(row.status)" size="small">
              {{ row.status_label || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作简述" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.action_description">{{ row.action_description }}</span>
            <span v-else-if="row.error_message" style="color: var(--danger);">{{ row.error_message }}</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="执行时间" width="110" align="center">
          <template #default="{ row }">
            <span v-if="row.execution_time && row.execution_time > 0">
              {{ formatDuration(row.execution_time) }}
            </span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170" align="center">
          <template #default="{ row }">
            {{ formatTime(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="完成时间" width="170" align="center">
          <template #default="{ row }">
            {{ formatTime(row.completed_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openDetailDrawer(row)">详情</el-button>
            <el-button v-if="row.status === 'failed' && canRetry(row)" link type="warning" size="small" @click="handleRetry(row)">重试</el-button>
            <el-button v-if="(row.status === 'running' || row.status === 'pending') && row.celery_task_id"
                       link type="danger" size="small" @click="handleCancel(row)">取消</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 详情抽屉：展示完整操作参数、执行结果、进度时间线、错误信息 -->
      <el-drawer v-model="detailDrawerVisible" title="操作详情" size="45%" direction="rtl">
        <div v-if="detailRecord" class="detail-content">
          <!-- 基本信息 -->
          <div class="detail-section">
            <div class="detail-section-title">基本信息</div>
            <div class="detail-grid">
              <div class="detail-item"><span class="detail-label">操作类型：</span><el-tag :type="detailRecord.task_type_tag_type || 'info'" size="small">{{ detailRecord.task_type_label || detailRecord.task_type }}</el-tag></div>
              <div class="detail-item" v-if="detailRecord.operation_label"><span class="detail-label">具体操作：</span>{{ detailRecord.operation_label }}</div>
              <div class="detail-item"><span class="detail-label">操作对象：</span>{{ formatOperationObject(detailRecord) }}</div>
              <div class="detail-item"><span class="detail-label">状态：</span><el-tag :type="getStatusTagType(detailRecord.status)" size="small">{{ detailRecord.status_label || detailRecord.status }}</el-tag></div>
              <div class="detail-item"><span class="detail-label">执行耗时：</span>{{ detailRecord.execution_time ? formatDuration(detailRecord.execution_time) : '-' }}</div>
              <div class="detail-item"><span class="detail-label">创建时间：</span>{{ formatTime(detailRecord.created_at) }}</div>
              <div class="detail-item"><span class="detail-label">完成时间：</span>{{ formatTime(detailRecord.completed_at) }}</div>
            </div>
          </div>

          <!-- 操作参数 -->
          <div class="detail-section" v-if="detailRecord.params_labeled && detailFilterLabeledSummary(detailRecord.params_labeled) && Object.keys(detailFilterLabeledSummary(detailRecord.params_labeled)).length > 0">
            <div class="detail-section-title">操作参数</div>
            <div class="detail-params">
              <div v-for="(value, key) in detailFilterLabeledSummary(detailRecord.params_labeled)" :key="key" class="detail-param-item">
                <span class="detail-label">{{ key }}：</span>
                <template v-if="isLargeReportField(key, value)">
                  <span class="detail-value">{{ isExpandedKey(key) ? formatResultValue(key, value) : truncatedReportPreview(key, value) }}</span>
                  <el-button link type="primary" size="small" @click="toggleExpandedKey(key)" style="margin-left:4px;">
                    {{ isExpandedKey(key) ? '收起' : '展开' }}
                  </el-button>
                </template>
                <span v-else class="detail-value">{{ formatResultValue(key, value) }}</span>
              </div>
            </div>
          </div>

          <!-- 执行结果 -->
          <div class="detail-section" v-if="detailRecord.result_summary_labeled && detailFilterLabeledSummary(detailRecord.result_summary_labeled) && Object.keys(detailFilterLabeledSummary(detailRecord.result_summary_labeled)).length > 0">
            <div class="detail-section-title">执行结果</div>
            <div class="detail-params">
              <div v-for="(value, key) in detailFilterLabeledSummary(detailRecord.result_summary_labeled)" :key="key" class="detail-param-item">
                <span class="detail-label">{{ key }}：</span>
                <template v-if="isLargeReportField(key, value)">
                  <span class="detail-value">{{ isExpandedKey(key) ? formatResultValue(key, value) : truncatedReportPreview(key, value) }}</span>
                  <el-button link type="primary" size="small" @click="toggleExpandedKey(key)" style="margin-left:4px;">
                    {{ isExpandedKey(key) ? '收起' : '展开' }}
                  </el-button>
                </template>
                <span v-else class="detail-value">{{ formatResultValue(key, value) }}</span>
              </div>
            </div>
          </div>

          <!-- 进度时间线（仅异步任务） -->
          <div class="detail-section" v-if="detailRecord.result_summary?.progress_history && detailRecord.result_summary.progress_history.length > 0">
            <div class="detail-section-title">进度时间线</div>
            <el-timeline>
              <el-timeline-item v-for="(item, idx) in detailRecord.result_summary.progress_history" :key="idx"
                                :timestamp="formatProgressTime(item.timestamp)" placement="top">
                <div class="progress-item">
                  <span class="progress-stage">{{ item.stage }}</span>
                  <el-progress :percentage="item.progress" :status="item.progress === 100 ? 'success' : ''" :stroke-width="10" style="margin-top: 4px" />
                  <div v-if="item.message" class="progress-message">{{ item.message }}</div>
                </div>
              </el-timeline-item>
            </el-timeline>
          </div>

          <!-- 错误信息 -->
          <div class="detail-section" v-if="detailRecord.status === 'failed' && detailRecord.error_message">
            <div class="detail-section-title">错误信息</div>
            <!-- 失败原因分类标签：仅当后端返回 failure_category 时显示 -->
            <el-tag v-if="detailRecord.failure_category"
                    :type="getFailureCategoryTagType(detailRecord.failure_category)"
                    size="small" style="margin-bottom:8px;">
              {{ getFailureCategoryLabel(detailRecord.failure_category) }}
            </el-tag>
            <div class="detail-error">{{ detailRecord.error_message }}</div>
            <!-- 不可重试提示：仅 param_error / data_error 显示，引导用户修改参数或处理数据后重新执行 -->
            <div v-if="detailRecord.failure_category && !isRetryableFailure(detailRecord.failure_category)"
                 class="detail-non-retryable-hint">
              该操作不支持重试，请修改参数或处理数据后重新执行
            </div>
          </div>

          <!-- 底部操作按钮 -->
          <div class="detail-footer">
            <el-button v-if="detailRecord.status === 'failed' && canRetry(detailRecord)" type="warning" size="small" @click="handleRetry(detailRecord)">重试任务</el-button>
            <!-- 取消按钮：仅 pending/running + 有 celery_task_id 显示 -->
            <el-button v-if="(detailRecord.status === 'running' || detailRecord.status === 'pending') && detailRecord.celery_task_id"
                       type="danger" size="small" @click="handleCancel(detailRecord)">取消任务</el-button>
          </div>
        </div>
      </el-drawer>

      <div v-if="taskRecords.length > 0" class="flex-between mt-md">
        <div class="batch-actions">
          <span class="text-sm">共 {{ taskRecordsTotal }} 条记录</span>
        </div>
        <el-pagination
          v-model:current-page="taskRecordsPage"
          v-model:page-size="taskRecordsPageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="taskRecordsTotal"
          layout="sizes, prev, pager, next, jumper"
          small
          background
          @current-change="loadTaskRecords"
          @size-change="() => { taskRecordsPage = 1; loadTaskRecords() }"
        />
      </div>
    </div>
  </div>
</template>

<script>
export default { name: 'TaskHistory' }
</script>

<script setup>
import { ref, computed, watch, onMounted, onActivated, onDeactivated, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { Refresh, Loading, FolderDelete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fetchTaskRecords, retryTask, cancelTask } from '../api/index.js'
import {
  getFailureCategoryLabel,
  getFailureCategoryTagType,
  isRetryableFailure,
} from '../utils/labels.js'

const route = useRoute()
const taskRecords = ref([])
const taskRecordsLoading = ref(false)
const taskRecordsTotal = ref(0)
const taskRecordsPage = ref(1)
const taskRecordsPageSize = ref(20)

// 筛选参数：操作大类、具体操作、状态、时间范围、关键字、数据集ID（从数据管理跳转时携带）
const filterCategory = ref('')
const filterOperation = ref('')
const filterStatus = ref('')
const filterDateRange = ref('')
const filterKeyword = ref('')
// 数据来源筛选：null=全部，true=远程数据库，false=本地数据
const filterSource = ref(null)
const customDateRange = ref(null)
const filterDatasetId = ref(route.query.dataset_id ? Number(route.query.dataset_id) : null)

// 操作大类与具体操作的映射表（与后端 task_labels.py OPERATION_LABELS 保持一致）
// 特征工程的二级操作值为 task_type（feature_engineering_select 等），其他大类为 operation
const CATEGORY_OPERATION_MAP = {
  // 文件上传：6 个二级分类，按 module_source + artifact_type 筛选
  // filterType='module_source' 时 value 格式为 "module_source|artifact_type"
  upload: [
    { value: 'cleaning|raw_data', label: '数据清洗', filterType: 'module_source' },
    { value: 'data_analysis|analysis_data', label: '数据分析', filterType: 'module_source' },
    { value: 'data_mining|raw_data', label: '数据挖掘', filterType: 'module_source' },
    { value: 'feature_engineering|raw_data', label: '特征工程', filterType: 'module_source' },
    { value: 'ml|raw_data', label: '机器学习（上传数据集）', filterType: 'module_source' },
    { value: 'ml|predict_data', label: '机器学习（预测数据集）', filterType: 'module_source' },
  ],
  dataset: [
    { value: 'soft_delete', label: '软删除' },
    { value: 'batch_delete', label: '批量删除' },
    { value: 'permanent_delete', label: '永久删除' },
    { value: 'restore', label: '恢复数据' },
    { value: 'clear_trash', label: '清空回收站' },
    { value: 'edit_meta', label: '编辑元数据' },
    { value: 'import_to_module', label: '跨模块导入' },
  ],
  // 数据清洗 4 个真实 operation（后端 contract_config/problem_strategy/execute_clean/save_clean_result）
  // 原"综合清洗"（comprehensive_clean）后端从不写入，已移除
  cleaning: [
    { value: 'contract_config', label: '契约配置' },
    { value: 'problem_strategy', label: '问题清单配置' },
    { value: 'execute_clean', label: '执行清洗' },
    { value: 'save_clean_result', label: '保存清洗结果' },
  ],
  data_analysis: [
    { value: 'generate_report', label: '生成报告' },
    { value: 'save_report', label: '保存报告' },
  ],
  data_mining: [
    { value: 'cluster', label: '聚类分析' },
    { value: 'association', label: '关联规则' },
    { value: 'sequence', label: '序列模式' },
    { value: 'save_cluster', label: '保存聚类结果' },
    { value: 'save_association', label: '保存关联规则' },
    { value: 'save_sequence', label: '保存序列模式' },
  ],
  // 特殊：特征工程的二级操作值是 task_type，用于 task_type 精确匹配
  // 5 个主操作按 task_type 精确匹配；2 个导出操作按 task_type + operation 组合匹配
  feature_engineering: [
    { value: 'feature_engineering_select', label: '特征选择', filterType: 'task_type' },
    { value: 'feature_engineering_construct', label: '特征构造', filterType: 'task_type' },
    { value: 'feature_engineering_encode', label: '特征编码', filterType: 'task_type' },
    { value: 'feature_engineering_scale', label: '特征缩放', filterType: 'task_type' },
    { value: 'feature_engineering_reduce', label: '特征降维', filterType: 'task_type' },
    { value: 'export_selected', label: '导出特征选择产物', filterType: 'operation', taskType: 'feature_engineering_select' },
    { value: 'export_pool', label: '导出列池产物', filterType: 'operation', taskType: 'feature_engineering_construct' },
  ],
  // 特殊：机器学习包含 ml + ml_training 两个 task_type，二级操作用 operation 区分
  // train 对应 task_type=ml_training，其他对应 task_type=ml + operation
  // 注：机器学习模块无报告导出功能，已移除 export_report 选项
  ml_all: [
    { value: 'train', label: '模型训练' },
    { value: 'batch_predict', label: '批量预测' },
    { value: 'test_evaluate', label: '测试集评估' },
  ],
  ai: [
    { value: 'ai_chat', label: 'AI对话' },
  ],
  // 账号管理：管理员账号操作记录（task_type=user_admin + operation 二级筛选）
  user_admin: [
    { value: 'admin_user_status', label: '管理员变更账号状态' },
    { value: 'admin_reset_password', label: '管理员重置密码' },
    { value: 'admin_unlock', label: '管理员解锁账号' },
  ],
}

// 根据操作大类联动返回具体操作选项
const operationOptions = computed(() => {
  if (!filterCategory.value) return []
  return CATEGORY_OPERATION_MAP[filterCategory.value] || []
})

async function loadTaskRecords() {
  taskRecordsLoading.value = true
  try {
    const params = {
      page: taskRecordsPage.value,
      per_page: taskRecordsPageSize.value
    }

    // 操作大类 + 具体操作筛选（按大类分策略传参）
    if (filterCategory.value) {
      if (filterCategory.value === 'feature_engineering') {
        // 特征工程：5 个主操作按 task_type 精确匹配；2 个导出操作按 task_type + operation 组合匹配
        if (filterOperation.value) {
          const op = operationOptions.value.find(o => o.value === filterOperation.value)
          if (op?.filterType === 'operation') {
            // 导出操作：同时传 task_type 和 operation 精确匹配
            params.task_type = op.taskType
            params.operation = filterOperation.value
          } else {
            // 主操作：按 task_type 精确匹配（值为 feature_engineering_select 等）
            params.task_type = filterOperation.value
            // 导出记录与主操作共用 task_type（export_selected 也用 feature_engineering_select），
            // 必须在主操作筛选时排除导出记录，避免"特征选择"混入"导出特征选择产物"
            if (filterOperation.value === 'feature_engineering_select') {
              params.exclude_operation = 'export_selected'
            } else if (filterOperation.value === 'feature_engineering_construct') {
              params.exclude_operation = 'export_pool'
            }
          }
        } else {
          // 未选具体操作：用前缀匹配 5 类主操作 + 2 类导出操作
          params.task_type_prefix = 'feature_engineering'
        }
      } else if (filterCategory.value === 'ml_all') {
        // 机器学习：train 对应 ml_training，其他对应 ml + operation
        if (filterOperation.value === 'train') {
          params.task_type = 'ml_training'
        } else if (filterOperation.value) {
          params.task_type = 'ml'
          params.operation = filterOperation.value
        } else {
          // 未选具体操作：用 task_type_in 一次查出 ml + ml_training 两类记录
          params.task_type_in = ['ml', 'ml_training']
        }
      } else if (filterCategory.value === 'upload') {
        // 文件上传：按 task_type 筛选，二级操作按 module_source + artifact_type 筛选
        params.task_type = 'upload'
        if (filterOperation.value) {
          // filterOperation 值格式为 "module_source|artifact_type"
          const op = operationOptions.value.find(o => o.value === filterOperation.value)
          if (op?.filterType === 'module_source') {
            const [ms, at] = filterOperation.value.split('|')
            params.module_source = ms
            params.artifact_type = at
          }
        }
      } else if (filterCategory.value === 'data_mining' && filterOperation.value?.startsWith('save_')) {
        // 数据挖掘保存操作：task_type=data_mining + operation=save_xxx
        params.task_type = 'data_mining'
        params.operation = filterOperation.value
      } else {
        // 数据治理/清洗/分析/挖掘：task_type 精确 + operation 二级筛选
        params.task_type = filterCategory.value
        if (filterOperation.value) {
          params.operation = filterOperation.value
        }
      }
    }

    if (filterStatus.value) params.status = filterStatus.value
    if (filterDatasetId.value) params.dataset_id = filterDatasetId.value
    // 数据来源筛选：true=远程数据库操作，false=本地操作
    if (filterSource.value !== null) params.is_remote = filterSource.value

    // 时间范围筛选
    if (filterDateRange.value === 'custom' && customDateRange.value) {
      if (customDateRange.value[0]) params.date_from = customDateRange.value[0]
      if (customDateRange.value[1]) params.date_to = customDateRange.value[1]
    } else if (filterDateRange.value === 'today') {
      const today = new Date()
      today.setHours(0, 0, 0, 0)
      params.date_from = today.toISOString()
    } else if (filterDateRange.value === '7d') {
      const weekAgo = new Date()
      weekAgo.setDate(weekAgo.getDate() - 7)
      params.date_from = weekAgo.toISOString()
    } else if (filterDateRange.value === '30d') {
      const monthAgo = new Date()
      monthAgo.setDate(monthAgo.getDate() - 30)
      params.date_from = monthAgo.toISOString()
    }

    // 关键字搜索
    if (filterKeyword.value) params.keyword = filterKeyword.value

    const res = await fetchTaskRecords(params)
    const data = res.data || {}
    taskRecords.value = data.records || []
    taskRecordsTotal.value = data.total || 0
  } catch (e) {
    console.error(e)
    ElMessage.error('加载操作历史失败')
    taskRecords.value = []
  } finally {
    taskRecordsLoading.value = false
  }
}

// 切换操作大类时清空具体操作，并触发筛选
function onCategoryChange() {
  filterOperation.value = ''
  taskRecordsPage.value = 1
  loadTaskRecords()
}

// 筛选条件变化时重置到第一页并重新加载
function onFilterChange() {
  taskRecordsPage.value = 1
  loadTaskRecords()
}

// 时间范围变化：非自定义时直接触发筛选
function onDateRangeChange() {
  if (filterDateRange.value !== 'custom') {
    onFilterChange()
  }
}

// 清除数据集筛选（从数据管理跳转后用户可手动关闭）
function clearDatasetFilter() {
  filterDatasetId.value = null
  taskRecordsPage.value = 1
  loadTaskRecords()
}

// ========== 详情抽屉 ==========
const detailDrawerVisible = ref(false)
const detailRecord = ref(null)
// 详情抽屉大字段（报告HTML/报告对象）的展开状态集合（key 为中文标签）
const expandedDetailKeys = ref(new Set())

// 操作对象展示：本地=数据集名/文件名；远程=连接名/表名；批量/清空=名称列表
function formatOperationObject(row) {
  if (!row) return '-'
  if (row.dataset_name) {
    return (row.is_remote && row.remote_connection_name)
      ? `${row.remote_connection_name} / ${row.dataset_name}`
      : row.dataset_name
  }
  if (row.params?.filename) return row.params.filename
  const names = row.params?.dataset_names
  if (Array.isArray(names) && names.length > 0) {
    const shown = names.slice(0, 3).join('，')
    const suffix = names.length > 3 ? ` 等 ${names.length} 项` : ''
    return row.params?.names_truncated ? `${shown}${suffix}（仅显示前部分）` : shown
  }
  return '-'
}

// 是否属于需要折叠的大字段：超长报告HTML / 聚类关联序列报告对象
function isLargeReportField(key, value) {
  if (!key) return false
  if (key.includes('报告HTML预览') && typeof value === 'string' && value.length > 200) return true
  if ((key.includes('聚类报告') || key.includes('关联规则报告') || key.includes('序列模式报告'))
      && typeof value === 'object' && value !== null) return true
  return false
}

function isExpandedKey(key) {
  return expandedDetailKeys.value.has(key)
}

function toggleExpandedKey(key) {
  const set = new Set(expandedDetailKeys.value)
  if (set.has(key)) set.delete(key)
  else set.add(key)
  expandedDetailKeys.value = set
}

// 折叠态摘要：HTML 截断前200字符；报告对象显示字段清单
function truncatedReportPreview(key, value) {
  if (key.includes('报告HTML预览') && typeof value === 'string') {
    return value.slice(0, 200) + ' …（点击展开查看完整内容）'
  }
  if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
    const keys = Object.keys(value)
    return `含 ${keys.length} 个字段：${keys.slice(0, 6).join('、')}${keys.length > 6 ? '…' : ''}（点击展开）`
  }
  return formatResultValue(key, value)
}

// 判断任务是否可重试：直接使用后端返回的 can_retry 综合字段
// 后端已综合判断 status + task_type 是否注册 handler + failure_category 是否可重试
// 前端无需硬编码 RETRYABLE_TASK_TYPES，避免与后端 _task_registry 不同步
function canRetry(row) {
  return row.can_retry === true
}

function openDetailDrawer(row) {
  detailRecord.value = row
  detailDrawerVisible.value = true
}

// 重试失败任务
async function handleRetry(row) {
  try {
    const res = await retryTask(row.id)
    if (res.data.status === 'queued' || res.data.status === 'success') {
      ElMessage.success('任务已重新提交')
      detailDrawerVisible.value = false
      loadTaskRecords()
    } else {
      ElMessage.error(res.data.message || '重试失败')
    }
  } catch (e) {
    ElMessage.error('重试失败：' + (e.response?.data?.detail || e.message))
  }
}

// 取消异步任务（仅 pending/running + 有 celery_task_id 可取消）
// 乐观更新：先关闭确认框，后端 revoke 成功后刷新列表
// 注意：revoke(terminate=True) 对 running 任务发送终止信号，但任务可能处于不可中断代码段
async function handleCancel(row) {
  try {
    await ElMessageBox.confirm('确认取消该任务？取消后不可恢复。', '提示', { type: 'warning' })
  } catch (action) {
    // 用户点击取消按钮（action === 'cancel'），不做任何操作
    return
  }
  try {
    const res = await cancelTask(row.id)
    if (res.data.status === 'success') {
      ElMessage.success('任务已取消')
      // 若详情抽屉打开则关闭
      detailDrawerVisible.value = false
      // 刷新列表以显示 cancelled 状态
      loadTaskRecords()
    } else {
      ElMessage.warning(res.data.message || '取消失败')
    }
  } catch (e) {
    ElMessage.error('取消失败：' + (e.response?.data?.detail || e.message))
  }
}

// 格式化进度时间线的 ISO 时间戳为上海时区
function formatProgressTime(timestamp) {
  if (!timestamp) return ''
  return formatTime(timestamp)
}

// 是否存在运行中任务，存在时自动轮询刷新状态
const hasRunning = computed(() =>
  taskRecords.value.some(r => r.status === 'running' || r.status === 'pending')
)
let pollingTimer = null
watch(hasRunning, (val) => {
  if (val && !pollingTimer) {
    pollingTimer = setInterval(loadTaskRecords, 10000)
  } else if (!val && pollingTimer) {
    clearInterval(pollingTimer)
    pollingTimer = null
  }
})
// keep-alive 失活时清理轮询定时器，避免切换到其他模块后仍持续请求 task-records
onDeactivated(() => {
  if (pollingTimer) {
    clearInterval(pollingTimer)
    pollingTimer = null
  }
})

onUnmounted(() => {
  if (pollingTimer) {
    clearInterval(pollingTimer)
    pollingTimer = null
  }
})

onMounted(() => {
  loadTaskRecords()
})

// keep-alive 重新激活时，检查路由参数变化（从数据管理跳转过来时携带 dataset_id）
onActivated(() => {
  const queryDatasetId = route.query.dataset_id ? Number(route.query.dataset_id) : null
  // 路由参数中的数据集ID与当前筛选不一致时，说明是从数据管理跳转过来
  // 此时必须重置所有筛选条件，避免之前的筛选导致数据历史为空
  if (queryDatasetId !== filterDatasetId.value) {
    filterDatasetId.value = queryDatasetId
    filterCategory.value = ''
    filterOperation.value = ''
    filterStatus.value = ''
    filterDateRange.value = ''
    filterKeyword.value = ''
    customDateRange.value = null
    taskRecordsPage.value = 1
    loadTaskRecords()
  }
  // keep-alive 重新激活时，如果有运行中任务且无定时器（被 onDeactivated 清理过），恢复轮询
  if (hasRunning.value && !pollingTimer) {
    pollingTimer = setInterval(loadTaskRecords, 10000)
  }
})

// task_type / status 的中文标签已由后端 task_labels.py 统一返回，
// 前端只需渲染 row.task_type_label / row.status_label 等字段。
// status 的 el-tag 颜色是纯前端展示逻辑，保留本地映射。

function getStatusTagType(status) {
  const map = {
    pending: '',
    running: 'warning',
    success: 'success',
    failed: 'danger',
    cancelled: 'info'
  }
  return map[status] || ''
}

function formatDuration(ms) {
  if (!ms || ms <= 0) return '-'
  const seconds = Math.floor(ms / 1000)
  const msRemain = ms % 1000
  if (seconds < 1) {
    return `${msRemain}ms`
  }
  if (seconds < 60) {
    return `${seconds}.${Math.floor(msRemain / 100)}s`
  }
  const minutes = Math.floor(seconds / 60)
  const secRemain = seconds % 60
  if (minutes < 60) {
    return `${minutes}分${secRemain}秒`
  }
  const hours = Math.floor(minutes / 60)
  const minRemain = minutes % 60
  return `${hours}小时${minRemain}分`
}

// 详情抽屉只排除进度相关字段（进度有独立的进度时间线区域），保留 ID/名称等全部字段
const DETAIL_EXCLUDE_KEYS = [
  '进度历史', '当前阶段', '当前进度', '当前消息',
  '时间戳'
]
function detailFilterLabeledSummary(labeledSummary) {
  if (!labeledSummary || typeof labeledSummary !== 'object') return null
  const filtered = {}
  for (const [key, value] of Object.entries(labeledSummary)) {
    if (!DETAIL_EXCLUDE_KEYS.includes(key)) {
      filtered[key] = value
    }
  }
  return Object.keys(filtered).length > 0 ? filtered : null
}

// 值格式化：用 key 包含匹配（兼容双语格式"中文（english）"）
function formatResultValue(key, value) {
  // 空值统一处理，避免 typeof null === 'object' 导致 Object.entries(null) 报错
  if (value === null || value === undefined) return '-'
  if (key && key.includes('文件大小')) return formatSize(value)
  // 预测文件路径截断：只显示文件名，隐藏服务器存储路径
  // 例如 "ml/user_21/xxx/predicted.csv" → "predicted.csv"
  if (key && key.includes('预测文件') && typeof value === 'string') {
    const parts = value.split('/')
    return parts[parts.length - 1] || value
  }
  // 变动详情（编辑元数据）：将 dict 展开为"字段：旧值 → 新值"多行格式
  if (key && key.includes('变动详情') && typeof value === 'object' && value !== null && !Array.isArray(value)) {
    const parts = []
    for (const [k, v] of Object.entries(value)) {
      parts.push(`${k}：${v}`)
    }
    return parts.join('；') || '-'
  }
  if (key && key.includes('完整指标') && typeof value === 'object' && value !== null) {
    // 完整指标对象展开为可读字符串
    const parts = []
    for (const [k, v] of Object.entries(value)) {
      if (typeof v === 'number') parts.push(`${k}: ${v.toFixed(4)}`)
    }
    return parts.join('，') || JSON.stringify(value)
  }
  if (Array.isArray(value)) {
    // 数组类型（如新增列、特征重要性）展示前 3 项
    if (value.length === 0) return '无'
    const preview = value.slice(0, 3).map(item => {
      if (typeof item === 'object' && item !== null) {
        return item['名称'] || item['name'] || JSON.stringify(item)
      }
      return String(item)
    })
    return value.length > 3 ? `${preview.join('，')} 等 ${value.length} 项` : preview.join('，')
  }
  if (typeof value === 'object' && value !== null) return JSON.stringify(value)
  return value
}

function formatSize(bytes) {
  if (bytes == null || bytes === 0) return '-'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i++
  }
  return size.toFixed(i === 0 ? 0 : 1) + ' ' + units[i]
}

// 解析后端时间字符串为 Date 对象
// 后端返回的 naive datetime 实际为 UTC 时间数值（与 DataManagement.vue 保持一致），
// 无时区后缀时按 UTC（'Z'）解析，再用 Intl 转为上海时区显示。
function _parseShanghaiDate(dateStr) {
  if (!dateStr) return null
  const hasTimezone = /([Zz]$)|([+-]\d{2}:\d{2}$)/.test(dateStr)
  const d = hasTimezone ? new Date(dateStr) : new Date(dateStr + 'Z')
  return isNaN(d.getTime()) ? null : d
}

// 上海时区格式化：返回 yyyy-MM-dd HH:mm:ss
function formatTime(dateStr) {
  if (!dateStr) return '-'
  const d = _parseShanghaiDate(dateStr)
  if (!d) return '-'
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false
  }).formatToParts(d)
  const get = type => parts.find(p => p.type === type)?.value || ''
  return `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}:${get('second')}`
}
</script>

<style scoped>
.filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.operation-sub {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}
.result-item {
  display: flex;
  gap: 4px;
  font-size: 13px;
  line-height: 1.6;
}
.result-key {
  color: var(--text-muted);
  font-weight: 500;
}
.result-value {
  color: var(--text-primary);
}

/* 详情抽屉样式 */
.detail-content {
  padding: 0 4px;
}
.detail-section {
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-color, #ebeef5);
}
.detail-section:last-child {
  border-bottom: none;
}
.detail-section-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
  padding-left: 8px;
  border-left: 3px solid var(--primary-color, #409eff);
}
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 16px;
  font-size: 13px;
}
.detail-item {
  display: flex;
  align-items: center;
  gap: 4px;
}
.detail-label {
  color: var(--text-muted, #909399);
  font-weight: 500;
  white-space: nowrap;
}
.detail-value {
  color: var(--text-primary, #303133);
  word-break: break-all;
}
.detail-params {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}
.detail-param-item {
  display: flex;
  gap: 4px;
  line-height: 1.6;
}
.detail-error {
  background: var(--danger-bg, #fef0f0);
  color: var(--danger, #f56c6c);
  padding: 10px 12px;
  border-radius: 4px;
  font-size: 13px;
  line-height: 1.6;
  word-break: break-all;
}
/* 不可重试提示：仅 param_error/data_error 失败显示，引导用户修改参数或处理数据 */
.detail-non-retryable-hint {
  margin-top: 8px;
  color: var(--text-muted, #909399);
  font-size: 12px;
  line-height: 1.5;
}
.detail-footer {
  display: flex;
  gap: 8px;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--border-color, #ebeef5);
}
.progress-item {
  font-size: 13px;
}
.progress-stage {
  font-weight: 500;
  color: var(--text-primary, #303133);
}
.progress-message {
  color: var(--text-muted, #909399);
  margin-top: 2px;
  font-size: 12px;
}
</style>