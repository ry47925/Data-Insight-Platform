import { ref, onMounted, onUnmounted, onActivated, onDeactivated } from 'vue'

/**
 * 自动刷新组合式函数
 * 为管理后台页面提供统一的轮询刷新能力
 * @param {Function} refreshFn - 刷新数据的异步函数
 * @param {Object} options - 配置选项
 * @param {number} options.interval - 刷新间隔（毫秒），默认 30000
 * @param {boolean} options.autoStart - 是否自动启动，默认 true
 * @returns {Object} 自动刷新控制对象
 */
export function useAutoRefresh(refreshFn, options = {}) {
  const {
    interval = 30000,
    autoStart = true
  } = options

  // 响应式状态
  const autoRefresh = ref(true)
  const isRefreshing = ref(false)
  const lastRefreshTime = ref(null)

  let timer = null

  /**
   * 执行一次刷新
   */
  async function immediateRefresh() {
    if (isRefreshing.value) return
    isRefreshing.value = true
    try {
      await refreshFn()
      lastRefreshTime.value = new Date()
    } catch (error) {
      console.error('自动刷新失败:', error)
    } finally {
      isRefreshing.value = false
    }
  }

  /**
   * 启动自动刷新定时器
   */
  function startAutoRefresh() {
    stopAutoRefresh()
    if (autoRefresh.value) {
      timer = setInterval(immediateRefresh, interval)
    }
  }

  /**
   * 停止自动刷新定时器
   */
  function stopAutoRefresh() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  /**
   * 切换自动刷新开关
   */
  function toggleAutoRefresh() {
    autoRefresh.value = !autoRefresh.value
    if (autoRefresh.value) {
      startAutoRefresh()
    } else {
      stopAutoRefresh()
    }
  }

  // 组件挂载时自动启动
  onMounted(() => {
    if (autoStart) {
      startAutoRefresh()
    }
  })

  // keep-alive 下切换到其他页面时停止轮询，避免定时器泄漏（onUnmounted 不触发）
  onDeactivated(() => {
    stopAutoRefresh()
  })

  // keep-alive 切回时按开关状态恢复轮询
  onActivated(() => {
    if (autoStart && autoRefresh.value) {
      startAutoRefresh()
    }
  })

  // 组件卸载时清理定时器
  onUnmounted(() => {
    stopAutoRefresh()
  })

  return {
    autoRefresh,
    isRefreshing,
    lastRefreshTime,
    immediateRefresh,
    startAutoRefresh,
    stopAutoRefresh,
    toggleAutoRefresh
  }
}
