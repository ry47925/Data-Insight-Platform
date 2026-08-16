<template>
  <!-- 全局浮动任务面板：固定在右上角，不遮挡内容 -->
  <div v-if="visibleTasks.length > 0" class="global-task-panel" :class="{ collapsed: panelCollapsed }">
    <!-- 标题栏 -->
    <div class="panel-header" @click="toggleCollapse">
      <div class="panel-title">
        <el-icon :size="16"><List /></el-icon>
        <span>任务进度</span>
        <el-badge :value="runningCount" :max="99" class="task-badge" v-if="runningCount > 0">
          <span class="task-count">{{ visibleTasks.length }}</span>
        </el-badge>
        <span v-else class="task-count">{{ visibleTasks.length }}</span>
      </div>
      <el-icon class="refresh-icon" :class="{ spinning: refreshing }" @click.stop="handleRefresh" title="刷新任务状态">
        <Refresh />
      </el-icon>
      <el-icon class="collapse-icon" :class="{ rotated: panelCollapsed }">
        <ArrowUp />
      </el-icon>
    </div>

    <!-- 任务列表（折叠时隐藏） -->
    <div v-show="!panelCollapsed" class="panel-body">
      <div
        v-for="task in visibleTasks"
        :key="task.id"
        class="task-card"
        :class="`task-${task.status}`"
      >
        <!-- 任务标题行 -->
        <div class="task-header">
          <div class="task-info">
            <span class="task-module-tag">{{ task.moduleLabel }}</span>
            <span v-if="task.isRemote" class="task-remote-tag">远程</span>
            <span class="task-operation">{{ task.operation }}</span>
          </div>
          <span class="task-dataset" v-if="task.datasetName">· {{ task.datasetName }}</span>
        </div>

        <!-- 进度条（仅 running 状态显示） -->
        <div v-if="task.status === 'running' || task.status === 'pending'" class="task-progress">
          <el-progress
            :percentage="task.progress"
            :status="progressStatus(task.status)"
            :stroke-width="6"
            :show-text="true"
          />
          <div class="task-stage" v-if="task.stage || task.message">
            <span v-if="task.stage" class="stage-label">{{ task.stage }}</span>
            <span v-if="task.message" class="stage-message">{{ task.message }}</span>
          </div>
        </div>

        <!-- 状态行 -->
        <div class="task-status-row">
          <div class="task-status-info">
            <span class="status-indicator" :class="`status-${task.status}`"></span>
            <span class="status-text">{{ statusLabel(task.status) }}</span>
            <span v-if="task.status === 'pending'" class="status-hint">等待中</span>
          </div>

          <!-- 操作按钮（按状态显示） -->
          <div class="task-actions">
            <!-- running/pending 状态：取消 + 隐藏 -->
            <template v-if="task.status === 'running' || task.status === 'pending'">
              <el-button
                size="small"
                type="danger"
                text
                :loading="task._cancelling"
                @click.stop="handleCancel(task)"
              >取消</el-button>
              <el-button
                size="small"
                type="info"
                text
                @click.stop="handleHide(task)"
              >隐藏</el-button>
            </template>

            <!-- failed 状态：重试（需 canRetry）+ 关闭 -->
            <template v-else-if="task.status === 'failed'">
              <el-button
                v-if="task.canRetry"
                size="small"
                type="warning"
                text
                :loading="task._retrying"
                @click.stop="handleRetry(task)"
              >重试</el-button>
              <el-button
                size="small"
                type="info"
                text
                @click.stop="handleClose(task)"
              >关闭</el-button>
            </template>

            <!-- success/cancelled 状态：查看结果（仅 success + 有 onViewResult）+ 关闭 -->
            <template v-else>
              <el-button
                v-if="task.status === 'success' && task.onViewResult"
                size="small"
                type="primary"
                text
                @click.stop="handleViewResult(task)"
              >查看结果</el-button>
              <el-button
                size="small"
                type="info"
                text
                @click.stop="handleClose(task)"
              >关闭</el-button>
            </template>
          </div>
        </div>

        <!-- 错误信息（仅 failed 状态显示） -->
        <div v-if="task.status === 'failed' && task.error" class="task-error">
          <el-tooltip :content="task.error" placement="bottom" :show-after="300">
            <span class="error-text">{{ task.error }}</span>
          </el-tooltip>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { List, ArrowUp, Refresh } from '@element-plus/icons-vue'
import {
  visibleTasks,
  cancelTaskInPanel,
  retryTaskInPanel,
  removeTask,
  hideTask,
  restoreRunningTasks,
  viewResult
} from '../stores/taskPanel.js'

// 面板折叠状态（本地 ref，不放入 store）
const panelCollapsed = ref(false)
const refreshing = ref(false)

// 手动刷新任务状态
async function handleRefresh() {
  refreshing.value = true
  try {
    await restoreRunningTasks()
    ElMessage.success('已同步任务状态')
  } catch {
    ElMessage.error('同步失败')
  } finally {
    refreshing.value = false
  }
}

// 运行中任务数（running + pending）
const runningCount = computed(() => {
  return visibleTasks.value.filter(t => t.status === 'running' || t.status === 'pending').length
})

// 切换折叠状态
function toggleCollapse() {
  panelCollapsed.value = !panelCollapsed.value
}

// 进度条状态（Element Plus el-progress 的 status 属性）
function progressStatus(status) {
  if (status === 'pending') return 'warning'
  return ''  // running 时为默认蓝色
}

// 状态标签
function statusLabel(status) {
  const labels = {
    'pending': '等待执行',
    'running': '执行中',
    'success': '已完成',
    'failed': '已失败',
    'cancelled': '已取消'
  }
  return labels[status] || status
}

// 取消任务
async function handleCancel(task) {
  try {
    task._cancelling = true
    await cancelTaskInPanel(task.id)
    ElMessage.success(`任务「${task.operation}」已取消`)
  } catch (error) {
    ElMessage.error('取消任务失败：' + (error.response?.data?.detail || error.message))
  } finally {
    task._cancelling = false
  }
}

// 隐藏任务（不从面板移除，继续轮询）
function handleHide(task) {
  hideTask(task.id)
  ElMessage.info(`任务「${task.operation}」已隐藏，完成后可在操作历史查看结果`)
}

// 关闭任务（从面板移除）
function handleClose(task) {
  removeTask(task.id)
}

// 查看任务结果（批量预测等需要重新打开界面的任务）
function handleViewResult(task) {
  viewResult(task.id)
}

// 重试任务
async function handleRetry(task) {
  try {
    task._retrying = true
    await retryTaskInPanel(task.id)
    ElMessage.success(`任务「${task.operation}」已重新提交`)
  } catch (error) {
    ElMessage.error('重试任务失败：' + (error.response?.data?.detail || error.message))
  } finally {
    task._retrying = false
  }
}
</script>

<style scoped>
/* 面板容器：固定定位在右上角 */
.global-task-panel {
  position: fixed;
  right: 20px;
  top: 80px;
  width: 380px;
  max-height: calc(100vh - 120px);
  background: rgba(255, 255, 255, 0.98);
  border-radius: 8px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
  z-index: 2000;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #e4e7ed;
}

/* 折叠状态：只显示标题栏 */
.global-task-panel.collapsed {
  width: 200px;
}

/* 标题栏 */
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  background: #f5f7fa;
  border-bottom: 1px solid #e4e7ed;
  cursor: pointer;
  user-select: none;
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}

.task-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  background: #409eff;
  color: #fff;
  border-radius: 10px;
  font-size: 12px;
  font-weight: normal;
}

.task-badge :deep(.el-badge__content) {
  display: none;
}

.collapse-icon {
  transition: transform 0.3s;
  color: #909399;
}

.collapse-icon.rotated {
  transform: rotate(180deg);
}

.refresh-icon {
  color: #909399;
  transition: color 0.2s;
  margin-right: 4px;
}

.refresh-icon:hover {
  color: #409eff;
}

.refresh-icon.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 任务列表容器 */
.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

/* 单个任务卡片 */
.task-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 8px;
  transition: box-shadow 0.2s;
}

.task-card:last-child {
  margin-bottom: 0;
}

.task-card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

/* 根据状态设置左边框颜色 */
.task-card.task-running {
  border-left: 3px solid #409eff;
}
.task-card.task-pending {
  border-left: 3px solid #e6a23c;
}
.task-card.task-success {
  border-left: 3px solid #67c23a;
}
.task-card.task-failed {
  border-left: 3px solid #f56c6c;
}
.task-card.task-cancelled {
  border-left: 3px solid #909399;
}

/* 任务标题行 */
.task-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.task-info {
  display: flex;
  align-items: center;
  gap: 6px;
}

.task-module-tag {
  display: inline-block;
  padding: 1px 6px;
  background: #ecf5ff;
  color: #409eff;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 500;
}

/* 远程数据库任务标识：橙色小标签，与模块标签并列 */
.task-remote-tag {
  display: inline-block;
  padding: 1px 6px;
  background: #fdf6ec;
  color: #e6a23c;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 500;
  margin-left: 4px;
}

.task-operation {
  font-size: 13px;
  font-weight: 500;
  color: #303133;
}

.task-dataset {
  font-size: 12px;
  color: #909399;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 进度条区域 */
.task-progress {
  margin: 8px 0 6px;
}

.task-stage {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  font-size: 12px;
  color: #606266;
}

.stage-label {
  color: #409eff;
  font-weight: 500;
}

.stage-message {
  color: #909399;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 状态行 */
.task-status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 4px;
}

.task-status-info {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
}

.status-indicator {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.status-running .status-indicator,
.status-indicator.status-running {
  background: #409eff;
  animation: pulse 1.5s infinite;
}

.status-pending .status-indicator,
.status-indicator.status-pending {
  background: #e6a23c;
}

.status-success .status-indicator,
.status-indicator.status-success {
  background: #67c23a;
}

.status-failed .status-indicator,
.status-indicator.status-failed {
  background: #f56c6c;
}

.status-cancelled .status-indicator,
.status-indicator.status-cancelled {
  background: #909399;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.status-text {
  color: #606266;
}

.status-hint {
  color: #e6a23c;
  font-size: 11px;
}

/* 操作按钮 */
.task-actions {
  display: flex;
  gap: 4px;
}

/* 错误信息 */
.task-error {
  margin-top: 6px;
  padding: 4px 8px;
  background: #fef0f0;
  border-radius: 4px;
  font-size: 12px;
}

.error-text {
  color: #f56c6c;
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 300px;
}

/* 滚动条样式 */
.panel-body::-webkit-scrollbar {
  width: 6px;
}

.panel-body::-webkit-scrollbar-track {
  background: #f5f7fa;
}

.panel-body::-webkit-scrollbar-thumb {
  background: #c0c4cc;
  border-radius: 3px;
}

.panel-body::-webkit-scrollbar-thumb:hover {
  background: #909399;
}
</style>
