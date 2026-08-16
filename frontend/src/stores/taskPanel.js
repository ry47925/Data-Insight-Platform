/**
 * 全局任务面板状态管理（单例模式）
 *
 * 使用 reactive 创建全局单例，各模块直接 import 使用，无需 provide/inject。
 *
 * 核心功能：
 * 1. addTask: 模块提交异步任务后调用，将任务添加到面板
 * 2. 轮询逻辑内聚在 store 中，各模块无需自己管理 pollTimer
 * 3. hidden 字段实现"隐藏但继续轮询"：用户看不到卡片，但任务完成后可在操作历史查看结果
 * 4. 任务达到终态（success/failed/cancelled）后自动停止轮询
 */
import { reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { getTaskProgress, cancelTask, retryTask, fetchTaskRecords } from '../api/index.js'

// 全局任务面板状态（单例）
const taskPanelStore = reactive({
  tasks: [],           // 所有任务列表
  collapsed: false,    // 面板是否折叠
  visible: true,       // 面板是否可见
})

// 轮询间隔（毫秒），2秒平衡实时性和服务器负载
const POLL_INTERVAL = 2000

// 成功任务自动关闭延迟（毫秒），30秒后自动从面板移除
// 仅 success 状态自动关闭；failed/cancelled/warning 需用户手动关闭或重试
const AUTO_CLOSE_DELAY = 30000

// 终态集合：任务达到这些状态后自动停止轮询
// warning 不是真正终态（用户可 force 重试），但轮询必须停止，否则会无限请求
const TERMINAL_STATUSES = ['success', 'failed', 'cancelled', 'warning']

/**
 * 添加任务到面板
 * @param {Object} task - 任务信息
 * @param {number} task.recordId - task_records 表主键 ID
 * @param {string} task.celeryTaskId - Celery 任务 ID（pending 状态为 null）
 * @param {string} task.taskType - 任务类型（ml_training / cleaning / feature_engineering_* 等）
 * @param {string} task.operation - 子操作标签（如"模型训练"、"特征选择"）
 * @param {string} task.moduleLabel - 所属模块（如"机器学习"）
 * @param {string} task.datasetName - 数据集名称
 * @param {string} task.initialStatus - 初始状态（running / pending）
 * @param {Function} onComplete - 任务完成时的回调（status, resultSummary）
 * @param {Function} onViewResult - 用户点击"查看结果"时的回调（resultSummary），
 *   用于批量预测等需要重新打开界面查看结果的场景。不传则任务面板不显示"查看结果"按钮
 */
export function addTask(task, onComplete = null, onViewResult = null) {
  // 避免重复添加同一任务（通过 recordId 去重）
  const existing = taskPanelStore.tasks.find(t => t.recordId === task.recordId)
  if (existing) {
    // 任务已存在，更新状态即可
    if (task.initialStatus && existing.status !== task.initialStatus) {
      existing.status = task.initialStatus
    }
    return existing
  }

  const newTask = reactive({
    id: task.recordId,
    recordId: task.recordId,
    celeryTaskId: task.celeryTaskId || null,
    taskType: task.taskType || '',
    operation: task.operation || '',
    moduleLabel: task.moduleLabel || '',
    datasetName: task.datasetName || '',
    isRemote: task.isRemote || false,  // 远程数据库任务标识，用于面板显示远程标签
    status: task.initialStatus || 'running',  // running / pending / success / failed / cancelled
    progress: 0,
    stage: '',
    message: '',
    error: '',
    resultSummary: null,
    pollTimer: null,        // 轮询定时器（内部管理）
    hidden: false,          // 用户主动隐藏后设为 true，不再展示但继续轮询
    createdAt: Date.now(),
    onComplete: onComplete, // 任务完成回调
    autoCloseTimer: null,   // success 状态自动关闭定时器
    onViewResult: onViewResult, // 查看结果回调（存在时面板显示"查看结果"按钮）
  })

  taskPanelStore.tasks.push(newTask)

  // pending 状态的任务也需要轮询，以便感知被调度器激活后状态变化
  // running 状态立即启动轮询
  if (newTask.status === 'running' || newTask.status === 'pending') {
    startPolling(newTask.id)
  }

  return newTask
}

/**
 * 从面板移除任务（仅从前端移除，不影响后端任务）
 * @param {number} taskId - 任务记录 ID
 */
export function removeTask(taskId) {
  const idx = taskPanelStore.tasks.findIndex(t => t.id === taskId)
  if (idx !== -1) {
    const task = taskPanelStore.tasks[idx]
    // 先停止轮询和自动关闭定时器，再移除
    stopPolling(taskId)
    if (task.autoCloseTimer) {
      clearTimeout(task.autoCloseTimer)
      task.autoCloseTimer = null
    }
    // 清理回调引用，避免闭包持有的组件实例无法被 GC
    task.onComplete = null
    task.onViewResult = null
    taskPanelStore.tasks.splice(idx, 1)
  }
}

/**
 * 查看任务结果（用户点击"查看结果"按钮时调用）
 * 调用任务创建时传入的 onViewResult 回调，由各模块自行决定如何展示结果
 * （如批量预测重新打开对话框并回填 resultSummary）
 * @param {number} taskId - 任务记录 ID
 */
export function viewResult(taskId) {
  const task = taskPanelStore.tasks.find(t => t.id === taskId)
  if (task && task.onViewResult) {
    try {
      task.onViewResult(task.resultSummary)
    } catch (e) {
      console.error('查看结果回调执行异常:', e)
    }
  }
}

/**
 * 隐藏任务（不从列表移除，继续轮询直到完成）
 * @param {number} taskId - 任务记录 ID
 */
export function hideTask(taskId) {
  const task = taskPanelStore.tasks.find(t => t.id === taskId)
  if (task) {
    task.hidden = true
  }
}

/**
 * 更新任务数据（轮询回调中调用）
 * @param {number} taskId - 任务记录 ID
 * @param {Object} data - 任务进度数据
 */
export function updateTaskData(taskId, data) {
  const task = taskPanelStore.tasks.find(t => t.id === taskId)
  if (!task) return

  // 更新状态
  if (data.status) {
    task.status = data.status
  }

  // 从 result_summary 提取进度信息
  const summary = data.result_summary || {}
  if (summary.current_progress !== undefined) {
    task.progress = summary.current_progress || 0
  }
  if (summary.current_stage !== undefined) {
    task.stage = summary.current_stage || ''
  }
  if (summary.current_message !== undefined) {
    task.message = summary.current_message || ''
  }

  // 保存完整的 result_summary 供回调使用
  task.resultSummary = summary

  // 错误信息
  if (data.error_message) {
    task.error = data.error_message
  }

  // 同步 can_retry 字段（后端综合判断 status + task_type + failure_category）
  // 前端 GlobalTaskPanel / TaskHistory 统一使用此字段控制重试按钮显示
  if (data.can_retry !== undefined) {
    task.canRetry = data.can_retry
  }

  // 检查是否达到终态
  if (TERMINAL_STATUSES.includes(task.status)) {
    stopPolling(taskId)
    // 调用完成回调
    if (task.onComplete) {
      try {
        task.onComplete(task.status, task.resultSummary)
      } catch (e) {
        console.error('任务完成回调执行异常:', e)
      }
      // 回调执行后清除，避免重复调用
      task.onComplete = null
    }
    // success 状态启动自动关闭定时器（30秒后自动移除）
    // 有 onViewResult 的成功任务（如批量预测）不自动关闭，给用户足够时间查看结果
    // failed/cancelled/warning 不自动关闭，需用户手动关闭或重试
    if (task.status === 'success' && !task.autoCloseTimer && !task.onViewResult) {
      task.autoCloseTimer = setTimeout(() => {
        // 二次校验：任务仍在列表中且状态仍为 success 才移除
        // 避免用户在 30 秒内重试导致状态变化后误删
        const current = taskPanelStore.tasks.find(t => t.id === taskId)
        if (current && current.status === 'success') {
          removeTask(taskId)
        }
      }, AUTO_CLOSE_DELAY)
    }
  }
}

/**
 * 启动单个任务的轮询
 * @param {number} taskId - 任务记录 ID
 */
export function startPolling(taskId) {
  const task = taskPanelStore.tasks.find(t => t.id === taskId)
  if (!task) return

  // 已有轮询在运行，不重复启动
  if (task.pollTimer) return

  // 立即查询一次，然后定时轮询
  _pollOnce(taskId)

  task.pollTimer = setInterval(() => {
    _pollOnce(taskId)
  }, POLL_INTERVAL)
}

/**
 * 停止单个任务的轮询
 * @param {number} taskId - 任务记录 ID
 */
export function stopPolling(taskId) {
  const task = taskPanelStore.tasks.find(t => t.id === taskId)
  if (task && task.pollTimer) {
    clearInterval(task.pollTimer)
    task.pollTimer = null
  }
}

/**
 * 停止所有任务的轮询
 * 用于用户登出或页面卸载时清理
 */
export function stopAllPolling() {
  taskPanelStore.tasks.forEach(task => {
    if (task.pollTimer) {
      clearInterval(task.pollTimer)
      task.pollTimer = null
    }
  })
}

/**
 * 单次轮询：查询任务进度并更新
 * @param {number} taskId - 任务记录 ID
 * @private
 */
async function _pollOnce(taskId) {
  const task = taskPanelStore.tasks.find(t => t.id === taskId)
  if (!task) return

  try {
    const data = await getTaskProgress(taskId)
    updateTaskData(taskId, data)
  } catch (error) {
    // 401 错误由全局拦截器处理，这里只记录其他错误
    if (error.response && error.response.status !== 401) {
      console.error(`轮询任务 ${taskId} 失败:`, error.message)
    }
    // 连续失败时不停止轮询，下次重试
  }
}

/**
 * 取消任务（调用后端取消 API + 乐观更新）
 * @param {number} taskId - 任务记录 ID
 */
export async function cancelTaskInPanel(taskId) {
  const task = taskPanelStore.tasks.find(t => t.id === taskId)
  if (!task) return

  try {
    await cancelTask(taskId)
    // 乐观更新状态为 cancelled
    task.status = 'cancelled'
    stopPolling(taskId)
    // 清理自动关闭定时器（cancelled 状态不自动关闭，但需避免残留定时器误触发）
    if (task.autoCloseTimer) {
      clearTimeout(task.autoCloseTimer)
      task.autoCloseTimer = null
    }
    if (task.onComplete) {
      try {
        task.onComplete('cancelled', task.resultSummary)
      } catch (e) {
        console.error('任务取消回调执行异常:', e)
      }
      task.onComplete = null
    }
  } catch (error) {
    console.error('取消任务失败:', error)
    throw error
  }
}

/**
 * 重试任务（调用后端重试 API + 重置状态）
 * @param {number} taskId - 任务记录 ID
 */
export async function retryTaskInPanel(taskId) {
  const task = taskPanelStore.tasks.find(t => t.id === taskId)
  if (!task) return

  try {
    const res = await retryTask(taskId)
    // 后端返回 queued（已提交Celery执行）或 pending（进入等待队列）
    // 前端状态体系为 running/pending/success/failed/cancelled，需将 queued 映射为 running
    const backendStatus = res.data?.status || 'pending'
    task.status = backendStatus === 'queued' ? 'running' : backendStatus
    task.error = ''
    task.progress = 0
    task.stage = ''
    task.message = backendStatus === 'pending' ? '等待执行（排队中）' : ''
    task.celeryTaskId = res.data?.task_id || null
    // 清理自动关闭定时器（重试后状态变为 running/pending，定时器不应再触发）
    if (task.autoCloseTimer) {
      clearTimeout(task.autoCloseTimer)
      task.autoCloseTimer = null
    }
    // 重新启动轮询（pending 状态也需轮询，以便感知被调度器激活）
    startPolling(taskId)
  } catch (error) {
    console.error('重试任务失败:', error)
    throw error
  }
}

/**
 * 清空所有任务（用户登出时调用）
 */
export function clearAllTasks() {
  stopAllPolling()
  // 清理所有自动关闭定时器和回调引用，避免登出后定时器回调操作已清空的数组
  taskPanelStore.tasks.forEach(task => {
    if (task.autoCloseTimer) {
      clearTimeout(task.autoCloseTimer)
      task.autoCloseTimer = null
    }
    task.onComplete = null
    task.onViewResult = null
  })
  taskPanelStore.tasks.splice(0, taskPanelStore.tasks.length)
}

// 计算属性：可见任务列表（过滤 hidden=true 的任务）
export const visibleTasks = computed(() => {
  return taskPanelStore.tasks.filter(t => !t.hidden)
})

// 计算属性：运行中任务数
export const runningTaskCount = computed(() => {
  return taskPanelStore.tasks.filter(t => t.status === 'running' || t.status === 'pending').length
})

/**
 * 恢复运行中和等待中的任务（页面刷新后调用）
 * 从后端查询 running/pending 状态的 task_record，重新加入面板
 * 恢复的任务无 onComplete 回调，完成时仅显示提示
 */
export async function restoreRunningTasks() {
  try {
    const [runningRes, pendingRes] = await Promise.all([
      fetchTaskRecords({ status: 'running', per_page: 50 }),
      fetchTaskRecords({ status: 'pending', per_page: 50 })
    ])
    const records = [
      ...(runningRes.data?.records || []),
      ...(pendingRes.data?.records || [])
    ]
    for (const record of records) {
      // 跳过已在面板中的任务（避免重复添加）
      const exists = taskPanelStore.tasks.some(t => t.recordId === record.id)
      if (exists) continue

      addTask({
        recordId: record.id,
        celeryTaskId: record.celery_task_id,
        taskType: record.task_type,
        operation: record.operation_label || record.operation || '',
        moduleLabel: record.task_type_label || '',
        datasetName: record.dataset_name || '',
        isRemote: record.is_remote || false,  // 从后端返回提取远程标识
        initialStatus: record.status === 'queued' ? 'running' : record.status
      }, (status) => {
        // 恢复的任务无模块级回调，用通用提示补上完成反馈
        const label = record.task_type_label || '任务'
        if (status === 'success') {
          ElMessage.success(`${label}已完成`)
        } else if (status === 'failed') {
          ElMessage.error(`${label}执行失败，请在任务历史中查看详情`)
        }
      })
    }
  } catch (e) {
    console.error('恢复任务进度失败:', e)
  }
}

// 导出 store 供组件直接使用
export { taskPanelStore }
