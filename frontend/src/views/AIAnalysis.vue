<template>
  <div class="ai-analysis">
    <el-alert
      v-if="!configStatus"
      title="AI 服务不可用"
      type="error"
      description="系统未配置 API Key，AI 分析功能暂时不可用"
      show-icon
      :closable="false"
      style="margin-bottom: 16px;"
    />

    <div class="ai-main">
      <!-- 上端：上下文注入区（可折叠，展开时显示分类列表） -->
      <div class="context-panel card" :class="{ collapsed: !contextPanelExpanded }">
        <div class="card-header">
          <span class="card-title">{{ qaMode ? '数据仓库选择' : '上下文注入' }}</span>
          <div class="flex-center gap-sm">
            <el-tooltip content="使用统计" placement="bottom" effect="dark">
              <el-button text size="small" circle @click="showStatsDialog = true" aria-label="使用统计">
                <el-icon :size="16"><DataLine /></el-icon>
              </el-button>
            </el-tooltip>
            <el-tooltip content="刷新可选项列表" placement="top" effect="dark">
              <el-button text size="small" @click="loadContextOptions" :loading="loadingOptions">
                <el-icon><Refresh /></el-icon>
              </el-button>
            </el-tooltip>
            <el-button text size="small" @click="contextPanelExpanded = !contextPanelExpanded">
              {{ contextPanelExpanded ? '收起' : '展开' }}
              <el-icon style="margin-left:4px;">
                <ArrowUp v-if="contextPanelExpanded" />
                <ArrowDown v-else />
              </el-icon>
            </el-button>
          </div>
        </div>

        <!-- 折叠态：单行汇总条（已选项 chips 横排，可点 × 移除） -->
        <div v-if="!contextPanelExpanded" class="context-summary-bar">
          <span v-if="selectedContextItems.length === 0" class="summary-empty">
            未选择上下文项，点击"展开"选择数据产物或操作记录
          </span>
          <template v-else>
            <span class="summary-prefix">已选 {{ selectedContextItems.length }} 项：</span>
            <div class="summary-chips">
              <el-tag
                v-for="item in selectedContextItems"
                :key="`${item.type}-${item.ref_id}`"
                size="small"
                effect="plain"
                :type="getItemTagType(item)"
                closable
                @close="removeSelectedItem(item)"
              >
                {{ item.label }}
              </el-tag>
            </div>
            <el-button text size="small" class="summary-clear" @click="clearSelection">清空</el-button>
          </template>
        </div>

        <!-- 展开态：搜索栏 + 筛选 + 分类列表 -->
        <div v-else class="context-body">
          <!-- 搜索栏 + 类型筛选 + 状态筛选（固定不动） -->
          <div class="context-toolbar">
            <el-input
              v-model="contextSearch"
              placeholder="搜索名称/数据集ID/任务#ID"
              size="small"
              clearable
              class="search-input"
            >
              <template #prefix>
                <el-icon><Search /></el-icon>
              </template>
            </el-input>
            <el-select v-model="contextTypeFilter" size="small" class="filter-select" v-if="!qaMode">
              <el-option label="全部类型" value="all" />
              <el-option label="数据产物" value="datasets" />
              <el-option label="操作记录" value="tasks" />
            </el-select>
            <el-select v-model="contextStatusFilter" size="small" class="filter-select" v-if="!qaMode">
              <el-option label="全部状态" value="all" />
              <el-option label="成功" value="success" />
              <el-option label="失败" value="failed" />
            </el-select>
            <el-select v-model="contextTaskTypeFilter" size="small" class="filter-select" v-if="!qaMode" @change="onContextTaskFilterChange">
              <el-option label="全部模块" value="" />
              <el-option label="数据清洗" value="cleaning" />
              <el-option label="数据分析" value="data_analysis" />
              <el-option label="数据挖掘" value="data_mining" />
              <el-option label="特征工程" value="feature_engineering" />
              <el-option label="机器学习" value="ml" />
            </el-select>
            <el-select v-model="contextTaskSourceFilter" size="small" class="filter-select" v-if="!qaMode" @change="onContextTaskFilterChange">
              <el-option label="全部来源" value="" />
              <el-option label="本地数据" value="local" />
              <el-option label="远程数据库" value="remote" />
            </el-select>
            <el-button
              v-if="selectedContextItems.length > 0"
              text
              size="small"
              @click="clearSelection"
            >
              清空选择
            </el-button>
          </div>

          <!-- 问答模式：常驻目录 + 一键全选工具条 -->
          <div v-if="qaMode" class="qa-catalog-bar">
            <el-select
              v-model="qaSelectedCatalogId"
              placeholder="选择常驻目录（可选）"
              size="small"
              clearable
              filterable
              class="qa-catalog-select"
              :loading="loadingQaCatalogs"
              @change="applyQaCatalog"
            >
              <el-option
                v-for="cat in qaCatalogs"
                :key="cat.id"
                :label="cat.name"
                :value="cat.id"
              >
                <div class="qa-catalog-option">
                  <span class="qa-catalog-name">{{ cat.name }}</span>
                  <span class="qa-catalog-count">{{ cat.dataset_ids.length }} 个数据集</span>
                </div>
              </el-option>
            </el-select>
            <el-tooltip content="将当前选择的数据产物保存为常驻目录，下次一键复用" placement="top" effect="dark">
              <el-button
                size="small"
                @click="openSaveCatalogDialog"
                :disabled="selectedDatasetsCount === 0"
              >
                <el-icon style="margin-right:4px;"><Files /></el-icon>
                保存为目录
              </el-button>
            </el-tooltip>
            <el-button
              size="small"
              type="danger"
              plain
              @click="deleteCatalogHandler"
              :disabled="!qaSelectedCatalogId"
            >
              删除目录
            </el-button>
            <span class="qa-bar-divider"></span>
            <el-tooltip content="将全部数据产物选入数据仓库（合成小型数据仓库供 AI 查询）" placement="top" effect="dark">
              <el-button
                size="small"
                type="primary"
                plain
                @click="selectAllDatasets"
                :disabled="allDatasets.length === 0"
              >
                <el-icon style="margin-right:4px;"><Select /></el-icon>
                一键全选
              </el-button>
            </el-tooltip>
          </div>

          <!-- 列表区（可上下滚动，搜索栏固定不动） -->
          <div class="context-list">
            <div v-if="loadingOptions" class="loading-mini">
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>加载中...</span>
            </div>
            <template v-else>
              <!-- 数据产物区（类型筛选非 tasks 时显示） -->
              <div v-if="contextTypeFilter !== 'tasks'" class="context-section">
                <div class="section-header">
                  <span class="section-title">数据产物</span>
                  <el-tag size="small" type="info" effect="plain">{{ filteredDatasets.length }}</el-tag>
                  <el-tooltip
                    content="选择需要让 AI 分析的数据产物（清洗结果、模型、报告等），AI 将基于真实数据回答"
                    placement="top"
                    effect="dark"
                  >
                    <el-icon class="section-help"><InfoFilled /></el-icon>
                  </el-tooltip>
                </div>
                <div v-if="contextGroups.length === 0" class="empty-mini">
                  暂无数据产物，请先在其它模块上传或生成数据
                </div>
                <div v-else class="group-list">
                  <!-- 数据产物：按 category(大类) > sub_type(小类) 两级嵌套 -->
                  <div v-for="catGroup in contextGroups" :key="`cat-${catGroup.category}`" class="context-group">
                    <div class="group-header" @click="toggleCategory(catGroup.category)">
                      <el-icon class="group-arrow" :class="{ expanded: expandedCategories[catGroup.category] }">
                        <ArrowRight />
                      </el-icon>
                      <span class="group-name">{{ catGroup.category_label }}</span>
                      <el-tag size="small" effect="light" type="info">{{ countDatasetItems(catGroup) }}</el-tag>
                    </div>
                    <div v-show="expandedCategories[catGroup.category]" class="group-items">
                      <div
                        v-for="subGroup in catGroup.subTypes"
                        :key="`sub-${catGroup.category}-${subGroup.sub_type}`"
                        class="sub-group"
                      >
                        <div class="sub-group-header" @click="toggleSubType(catGroup.category, subGroup.sub_type)">
                          <el-icon class="group-arrow sub-arrow" :class="{ expanded: isSubTypeExpanded(catGroup.category, subGroup.sub_type) }">
                            <ArrowRight />
                          </el-icon>
                          <span class="sub-group-name">{{ subGroup.sub_type_label }}</span>
                          <el-tag size="small" effect="plain">{{ subGroup.items.length }}</el-tag>
                        </div>
                        <div v-show="isSubTypeExpanded(catGroup.category, subGroup.sub_type)" class="group-items">
                          <div
                            v-for="ds in subGroup.items"
                            :key="`dataset-${ds.id}`"
                            class="context-item"
                            :class="{ selected: isItemSelected('dataset', ds.id) }"
                            @click="toggleSelect('dataset', ds.id, `${ds.name} (ID:${ds.id})`, ds.artifact_type, ds.artifact_label)"
                          >
                            <el-checkbox
                              :model-value="isItemSelected('dataset', ds.id)"
                              @click.stop
                              @change="toggleSelect('dataset', ds.id, `${ds.name} (ID:${ds.id})`, ds.artifact_type, ds.artifact_label)"
                            />
                            <div class="item-info">
                              <div class="item-name" :title="`${ds.name} | ID:${ds.id}`">
                                <span class="item-name-text">{{ ds.name }} | ID:{{ ds.id }}</span>
                              </div>
                              <div class="item-meta">
                                <el-tag size="small" effect="plain" :type="getArtifactTagType(ds.artifact_type)">
                                  {{ ds.artifact_label || ds.artifact_type }}
                                </el-tag>
                                <span v-if="ds.row_count" class="meta-text">{{ ds.row_count }} 行</span>
                              </div>
                            </div>
                            <el-tooltip content="预览摘要" placement="top" effect="dark">
                              <el-button
                                text
                                size="small"
                                class="preview-btn"
                                @click.stop="previewItem('dataset', ds.id, ds.name)"
                              >
                                <el-icon><View /></el-icon>
                              </el-button>
                            </el-tooltip>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 操作记录区（类型筛选非 datasets 时显示；问答模式不显示操作） -->
              <div v-if="!qaMode && contextTypeFilter !== 'datasets'" class="context-section">
                <div class="section-header">
                  <span class="section-title">操作记录</span>
                  <el-tag size="small" type="info" effect="plain">{{ filteredTasks.length }}</el-tag>
                  <el-tooltip
                    content="选择需要让 AI 分析的操作记录（训练参数、清洗配置等），帮助 AI 诊断问题原因"
                    placement="top"
                    effect="dark"
                  >
                    <el-icon class="section-help"><InfoFilled /></el-icon>
                  </el-tooltip>
                </div>
                <div v-if="filteredTasks.length === 0" class="empty-mini">
                  暂无操作记录
                </div>
                <div v-else class="group-list">
                  <!-- 操作记录：按 task_type(大类) > operation(小类) 两级嵌套 -->
                  <div v-for="taskGroup in groupedTasks" :key="`task-group-${taskGroup.task_type}`" class="context-group">
                    <div class="group-header" @click="toggleTaskType(taskGroup.task_type)">
                      <el-icon class="group-arrow" :class="{ expanded: expandedTaskTypes[taskGroup.task_type] }">
                        <ArrowRight />
                      </el-icon>
                      <span class="group-name">{{ taskGroup.task_type_label }}</span>
                      <el-tag size="small" effect="light" type="info">{{ countTaskItems(taskGroup) }}</el-tag>
                    </div>
                    <div v-show="expandedTaskTypes[taskGroup.task_type]" class="group-items">
                      <div
                        v-for="opGroup in taskGroup.operations"
                        :key="`op-${taskGroup.task_type}-${opGroup.operation}`"
                        class="sub-group"
                      >
                        <div class="sub-group-header" @click="toggleOperation(taskGroup.task_type, opGroup.operation)">
                          <el-icon class="group-arrow sub-arrow" :class="{ expanded: isOperationExpanded(taskGroup.task_type, opGroup.operation) }">
                            <ArrowRight />
                          </el-icon>
                          <span class="sub-group-name">{{ opGroup.operation_label }}</span>
                          <el-tag size="small" effect="plain">{{ opGroup.items.length }}</el-tag>
                        </div>
                        <div v-show="isOperationExpanded(taskGroup.task_type, opGroup.operation)" class="group-items">
                          <div
                            v-for="task in opGroup.items"
                            :key="`task-${task.id}`"
                            class="context-item"
                            :class="{ selected: isItemSelected('operation', task.id) }"
                            @click="toggleSelect('operation', task.id, `任务#${task.id}(${task.task_type_label || task.task_type})`, task.task_type)"
                          >
                            <el-checkbox
                              :model-value="isItemSelected('operation', task.id)"
                              @click.stop
                              @change="toggleSelect('operation', task.id, `任务#${task.id}(${task.task_type_label || task.task_type})`, task.task_type)"
                            />
                            <div class="item-info">
                              <div class="item-name" :title="`任务#${task.id} | ${task.dataset_name || '-'}`">
                                <span class="item-name-text">任务#{{ task.id }} | {{ task.dataset_name || '-' }}</span>
                                <el-tag v-if="task.is_remote" size="small" type="warning" effect="plain">远程</el-tag>
                                <el-tag v-if="task.dataset_status === 'deleted'" size="small" type="warning">回收站</el-tag>
                                <el-tag v-else-if="task.dataset_status === 'purged'" size="small" type="info">已删除</el-tag>
                              </div>
                              <div class="item-meta">
                                <span v-if="task.is_remote && task.remote_connection_name" class="meta-text">
                                  {{ task.remote_connection_name }}{{ task.remote_table_name ? ' / ' + task.remote_table_name : '' }}
                                </span>
                                <span class="meta-text">{{ formatDateTime(task.created_at) }}</span>
                                <el-tag
                                  v-if="task.status"
                                  size="small"
                                  :type="task.status === 'success' ? 'success' : 'danger'"
                                >
                                  {{ task.status === 'success' ? '成功' : '失败' }}
                                </el-tag>
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                  <!-- 加载更多操作记录 -->
                  <div v-if="taskPage < taskTotalPages" class="load-more-tasks">
                    <el-button
                      text
                      size="small"
                      :loading="loadingMoreTasks"
                      @click="loadMoreTasks"
                    >
                      <el-icon style="margin-right:4px;"><ArrowDown /></el-icon>
                      加载更多
                    </el-button>
                  </div>
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- 下端：对话区（撑满剩余高度） -->
      <div class="chat-panel card">
        <div class="card-header">
          <!-- 模式切换 Tab -->
          <div class="mode-tabs">
            <el-tooltip content="结合上下文注入，进行流程推荐、问题诊断等开放性分析" placement="bottom" effect="dark">
              <button class="mode-tab" :class="{ active: !qaMode }" @click="switchMode('chat')">
                <ChatDotRound />分析对话
              </button>
            </el-tooltip>
            <el-tooltip content="基于数据仓库精确问答与预测，例如：去年平均月薪是多少、预测下一年产量" placement="bottom" effect="dark">
              <button class="mode-tab" :class="{ active: qaMode }" @click="switchMode('qa')">
                <DataAnalysis />产品问答
              </button>
            </el-tooltip>
          </div>
          <div class="flex-center gap-sm">
            <el-button
              v-if="currentConversationId && messages.length > 0"
              text
              size="small"
              @click="startNewTopic"
            >
              <el-icon style="margin-right:4px;"><ChatLineRound /></el-icon>
              开始新话题
            </el-button>
            <el-button v-if="conversations.length > 0" text size="small" @click="showHistoryDialog = true">
              历史记录 ({{ conversations.length }})
            </el-button>
            <el-button text size="small" @click="clearChat" :disabled="messages.length === 0">
              新建会话
            </el-button>
          </div>
        </div>

        <div class="chat-messages" ref="chatMessages">
          <div v-if="messages.length === 0" class="chat-empty">
            <div class="empty-icon"><el-icon :size="48"><QuestionFilled /></el-icon></div>
            <div class="empty-text">{{ qaMode ? '开始产品精确问答' : '开始与 AI 对话' }}</div>
            <div class="empty-hint">
              <template v-if="qaMode">
                在"数据仓库选择"区勾选产物、一键全选或选择常驻目录，即可提问统计、筛选、趋势或预测，AI 将基于真实数据给出精确结果
              </template>
              <template v-else>
                从上方上下文注入区选择数据产物或操作记录作为上下文，AI 将基于真实数据进行分析诊断
              </template>
            </div>
          </div>

          <div v-for="(msg, idx) in messages" :key="idx" class="chat-msg" :class="msg.role">
            <div class="msg-avatar">
              <el-icon><component :is="msg.role === 'user' ? 'User' : 'ChatDotRound'" /></el-icon>
            </div>
            <div class="msg-content">
              <div class="msg-header">
                <span class="msg-role">{{ msg.role === 'user' ? '您' : 'AI 助手' }}</span>
                <span class="msg-time">{{ msg.time }}</span>
              </div>
              <div class="msg-body" v-html="renderMarkdown(msg.content)"></div>

              <!-- 问答精确结果卡片（本地计算，非 LLM 生成，可核验） -->
              <div v-if="msg.role === 'assistant' && hasExecResult(msg.execResult)" class="qa-result-card">
                <div class="qa-result-head">
                  <span class="qa-result-title">
                    <el-icon><DataAnalysis /></el-icon>
                    精确计算结果
                  </span>
                  <el-tag size="small" effect="plain" type="success">{{ execTypeLabel(msg.execResult) }}</el-tag>
                  <el-tag v-if="msg.execResult.computed_by" size="small" effect="plain" type="info">
                    {{ msg.execResult.computed_by === 'pandas' ? '本地精确计算' : '远程SQL下推' }}
                  </el-tag>
                </div>

                <!-- 单值汇总（计数/均值等） -->
                <div v-if="!isGroupedResult(msg.execResult) && !isPredictionResult(msg.execResult)" class="qa-result-single">
                  <span class="qa-result-value">{{ execValue(msg.execResult) }}</span>
                  <span v-if="msg.execResult.result.count !== undefined" class="qa-result-unit">条</span>
                </div>

                <!-- 分组聚合表格 -->
                <el-table
                  v-if="isGroupedResult(msg.execResult)"
                  :data="msg.execResult.result.grouped"
                  size="small"
                  border
                  max-height="220"
                  class="qa-result-table"
                >
                  <el-table-column
                    v-for="col in Object.keys(msg.execResult.result.grouped[0] || {})"
                    :key="col"
                    :prop="col"
                    :label="col"
                  />
                </el-table>

                <!-- 预测结果：总览 + 分布 + TOP 明细 -->
                <div v-if="isPredictionResult(msg.execResult)" class="qa-result-prediction">
                  <div class="qa-pred-overview">
                    <div class="qa-pred-stat">
                      <span class="qa-pred-label">预测总量</span>
                      <span class="qa-pred-num">{{ msg.execResult.result.total }}</span>
                    </div>
                    <div v-if="predictionDistribution(msg.execResult)" class="qa-pred-bars">
                      <div v-for="(val, key) in predictionDistribution(msg.execResult)" :key="key" class="qa-pred-bar-row">
                        <span class="qa-pred-bar-label">{{ key }}</span>
                        <div class="qa-pred-bar-track">
                          <div class="qa-pred-bar-fill" :style="{ width: predBarPercent(val, msg.execResult) + '%' }"></div>
                        </div>
                        <span class="qa-pred-bar-val">{{ val }}</span>
                      </div>
                    </div>
                  </div>
                  <div v-if="msg.execResult.result.sample_rows && msg.execResult.result.sample_rows.length" class="qa-pred-samples-label">预测明细（前 {{ msg.execResult.result.sample_rows.length }} 条）</div>
                  <el-table
                    v-if="msg.execResult.result.sample_rows && msg.execResult.result.sample_rows.length"
                    :data="msg.execResult.result.sample_rows"
                    size="small"
                    border
                    max-height="220"
                    class="qa-result-table"
                  >
                    <el-table-column
                      v-for="col in Object.keys(msg.execResult.result.sample_rows[0] || {})"
                      :key="col"
                      :prop="col"
                      :label="col"
                    />
                  </el-table>
                </div>
              </div>

              <!-- 上下文标记展示 -->
              <div v-if="msg.role === 'assistant' && msg.contextItems && msg.contextItems.length > 0" class="msg-context-tags">
                <span class="context-tag-label">注入上下文:</span>
                <el-tag
                  v-for="ci in msg.contextItems"
                  :key="`${ci.type}-${ci.ref_id}`"
                  size="small"
                  effect="plain"
                  type="info"
                >
                  {{ ci.label || `${ci.type}#${ci.ref_id}` }}
                </el-tag>
              </div>

              <!-- 需要补充上下文提示 -->
              <div v-if="msg.role === 'assistant' && msg.needsContext && msg.needsContext.length > 0" class="needs-context-hint">
                <el-alert
                  type="warning"
                  :closable="false"
                  show-icon
                >
                  <template #title>
                    AI 需要更多上下文才能给出准确分析，请从上方上下文注入区选择以下类型的产物：
                  </template>
                  <div class="needs-context-list">
                    <el-tag
                      v-for="nt in msg.needsContext"
                      :key="nt"
                      size="small"
                      effect="light"
                      type="warning"
                    >
                      {{ nt }}
                    </el-tag>
                  </div>
                </el-alert>
              </div>

              <div v-if="msg.role === 'assistant'" class="msg-footer">
                <span v-if="msg.usage && formatUsage(msg.usage)" class="token-usage">消耗：{{ formatUsage(msg.usage) }}</span>
              </div>
            </div>
          </div>

          <div v-if="aiThinking" class="chat-msg assistant thinking-msg">
            <div class="msg-avatar"><el-icon :size="24"><ChatDotRound /></el-icon></div>
            <div class="msg-content">
              <div class="msg-header">
                <span class="msg-role">AI 助手</span>
                <span class="msg-status">
                  <el-icon class="is-loading"><Loading /></el-icon>
                  <span>{{ thinkingStatus }}</span>
                </span>
              </div>
              <div class="thinking-content">
                <div class="thinking-text">{{ thinkingHint }}</div>
                <div class="thinking-dots">
                  <span></span><span></span><span></span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 快捷命令栏（双 Tab：快捷模板 + 追问） -->
        <div class="quick-commands">
          <div class="followup-tabs">
            <button
              class="followup-tab"
              :class="{ active: activeFollowupTab === 'templates' }"
              @click="activeFollowupTab = 'templates'"
            >
              快捷模板
            </button>
            <button
              class="followup-tab"
              :class="{ active: activeFollowupTab === 'suggestions' }"
              @click="activeFollowupTab = 'suggestions'"
            >
              追问
              <span v-if="suggestedQuestions.length > 0" class="followup-badge">{{ suggestedQuestions.length }}</span>
            </button>
          </div>

          <!-- Tab 1: 快捷模板（始终可用） -->
          <div v-if="activeFollowupTab === 'templates'" class="followup-list">
            <el-button
              v-for="cmd in quickCommands"
              :key="cmd"
              size="small"
              round
              @click="useQuickCommand(cmd)"
            >
              {{ cmd }}
            </el-button>
          </div>

          <!-- Tab 2: 追问建议 -->
          <div v-else class="followup-list">
            <template v-if="suggestedQuestions.length > 0">
              <el-button
                v-for="(q, idx) in suggestedQuestions"
                :key="idx"
                size="small"
                round
                @click="useQuickCommand(q)"
              >
                {{ q }}
              </el-button>
            </template>
            <span v-else class="followup-empty">
              {{ messages.length === 0 ? 'AI 回答后将显示追问建议' : '本次回答未生成追问建议，可使用快捷模板继续' }}
            </span>
          </div>
        </div>

        <div class="chat-input-area">
          <div v-if="selectedContextItems.length > 0" class="context-badge">
            <div class="context-badge-head">
              <el-icon><Link /></el-icon>
              <span>本次对话将注入 {{ selectedContextItems.length }} 个上下文项</span>
              <el-button text size="small" class="badge-clear-btn" @click="clearSelection">
                清空选择
              </el-button>
            </div>
            <!-- 已选上下文项 chips：直接在此可逐个取消，不用到上方面板查找 -->
            <div class="context-badge-chips">
              <el-tag
                v-for="item in selectedContextItems"
                :key="`badge-${item.type}-${item.ref_id}`"
                size="small"
                effect="plain"
                :type="getItemTagType(item)"
                closable
                @close="removeSelectedItem(item)"
              >
                {{ item.label }}
                <span v-if="item.auto_source_dataset_id" class="badge-auto-mark">· 血缘</span>
              </el-tag>
            </div>
          </div>
          <el-input
            ref="questionInput"
            v-model="question"
            type="textarea"
            :rows="2"
            :placeholder="inputPlaceholder"
            @keydown.enter.ctrl="sendMessage"
            :disabled="aiThinking"
            aria-label="输入分析问题"
          />
          <div class="chat-input-actions">
            <span class="input-hint">Ctrl + Enter 发送</span>
            <el-button
              type="primary"
              @click="sendMessage"
              :loading="aiThinking"
              :disabled="!question.trim()"
            >
              <el-icon style="margin-right:4px;"><Promotion /></el-icon>
              发送
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 上下文预览弹窗 -->
    <el-dialog
      v-model="showPreviewDialog"
      :title="`上下文预览 - ${previewTitle}`"
      width="700px"
      aria-label="上下文预览弹窗"
    >
      <div v-if="loadingPreview" class="loading-container">
        <el-icon class="is-loading" :size="24"><Loading /></el-icon>
        <div class="loading-text">加载摘要中...</div>
      </div>
      <div v-else class="preview-content">
        <pre class="preview-text">{{ previewContent }}</pre>
      </div>
    </el-dialog>

    <!-- 历史会话弹窗 -->
    <el-dialog v-model="showHistoryDialog" title="历史会话" width="680px" aria-label="历史会话弹窗">
      <div v-if="conversations.length > 0" class="history-filter">
        <el-input v-model="conversationSearch" placeholder="搜索会话标题" size="default" clearable style="width: 200px;">
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <span class="history-count">共 {{ filteredConversations.length }} 个会话</span>
      </div>
      <div v-if="loadingConversations" class="loading-container">
        <el-icon class="is-loading" :size="24"><Loading /></el-icon>
        <div class="loading-text">加载中...</div>
      </div>
      <div v-else-if="filteredConversations.length === 0" class="empty-state">
        <el-icon :size="48"><Document /></el-icon>
        <div class="empty-text">暂无历史会话</div>
        <div class="empty-hint">开始新的对话后，会话将自动保存</div>
      </div>
      <div v-else class="conversation-list">
        <div
          v-for="conv in filteredConversations"
          :key="conv.id"
          class="conversation-card"
          @click="loadConversation(conv)"
        >
          <div class="conv-header">
            <div class="conv-icon" :class="`icon-${conv.module_type}`">
              <el-icon :size="18">
                <component :is="getModuleIcon(conv.module_type)" />
              </el-icon>
            </div>
            <div class="conv-title-wrap">
              <div class="conv-title">{{ conv.title || '未命名会话' }}</div>
              <div class="conv-sub">
                <span class="conv-msg-count">
                  <el-icon><ChatDotRound /></el-icon>
                  {{ conv.message_count || 0 }} 条消息
                </span>
              </div>
            </div>
            <span class="conv-time">{{ formatTime(conv.updated_at || conv.created_at) }}</span>
          </div>
          <div class="conv-footer">
            <el-button size="small" type="primary" text @click.stop="loadConversation(conv)">
              <el-icon><View /></el-icon> 打开会话
            </el-button>
            <el-button text size="small" @click.stop="startRenameConversation(conv)" aria-label="重命名">
              <el-icon><Edit /></el-icon> 重命名
            </el-button>
            <el-button size="small" type="danger" text @click.stop="deleteConv(conv.id)">
              <el-icon><Delete /></el-icon> 删除
            </el-button>
          </div>
        </div>
      </div>
    </el-dialog>

    <!-- 重命名会话弹窗 -->
    <el-dialog v-model="renameDialogVisible" title="重命名会话" width="400px">
      <el-input v-model="renameTitle" placeholder="请输入新的会话名称" maxlength="100" show-word-limit @keydown.enter="confirmRenameConversation" />
      <template #footer>
        <el-button @click="renameDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmRenameConversation">确认</el-button>
      </template>
    </el-dialog>

    <!-- 保存问答常驻目录弹窗 -->
    <el-dialog v-model="showSaveCatalogDialog" title="保存为常驻目录" width="460px" aria-label="保存常驻目录弹窗">
      <el-form label-width="80px">
        <el-form-item label="目录名称" required>
          <el-input v-model="qaCatalogName" placeholder="为这批数据产物集合命名" maxlength="60" show-word-limit />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="qaCatalogDesc" type="textarea" :rows="2" placeholder="可选，说明该目录用途" maxlength="200" show-word-limit />
        </el-form-item>
        <el-form-item label="数据集">
          <span class="catalog-count-tip">已含 {{ selectedDatasetsCount }} 个数据产物{{ qaSelectedCatalogId ? '（将更新当前所选目录）' : '' }}</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showSaveCatalogDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmSaveCatalog" :disabled="selectedDatasetsCount === 0">保存</el-button>
      </template>
    </el-dialog>

    <!-- 使用统计弹窗 -->
    <el-dialog v-model="showStatsDialog" title="使用统计" width="480px" aria-label="使用统计弹窗">
      <div v-if="loadingStats" class="loading-container">
        <el-icon class="is-loading" :size="24"><Loading /></el-icon>
        <div class="loading-text">加载中...</div>
      </div>
      <div v-else class="stats-grid">
        <div class="stat-card">
          <div class="stat-value">{{ usageStats.today_tokens || 0 }}</div>
          <div class="stat-label">今日 Tokens</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ usageStats.week_tokens || 0 }}</div>
          <div class="stat-label">本周 Tokens</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ usageStats.total_tokens || 0 }}</div>
          <div class="stat-label">累计 Tokens</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ usageStats.today_calls || 0 }}</div>
          <div class="stat-label">今日调用次数</div>
        </div>
      </div>
    </el-dialog>

  </div>
</template>

<script>
export default { name: 'AIAnalysis' }
</script>

<script setup>
import { ref, reactive, computed, inject, nextTick, watch, onMounted, onActivated, onDeactivated, onUnmounted } from 'vue'
import {
  Promotion, Document, Loading,
  ChatDotRound, ChatLineRound,
  DataLine, QuestionFilled, User, Delete,
  View, InfoFilled,
  Refresh, ArrowRight, ArrowDown, ArrowUp, Close, Link,
  Brush, DataAnalysis, Cpu, MagicStick, Files,
  Search, Edit, Select
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  aiChat,
  fetchContextOptions, previewContextItem, fetchBloodlineOps,
  qaChat, listQaCatalogs, saveQaCatalog, deleteQaCatalog,
  getAIConfig,
  fetchConversations, fetchConversation, deleteConversation, renameConversation,
  fetchUsageStats,
  authStore
} from '../api/index.js'
import { getModuleLabel, getArtifactLabel, getArtifactTagType } from '../utils/labels.js'

const datasetStore = inject('datasetStore')

// ========== 对话状态 ==========
const question = ref('')
const messages = ref([])
const aiThinking = ref(false)
const thinkingStatus = ref('AI 正在思考中')
const thinkingHint = ref('正在分析您的问题，请稍候...')
let thinkingTimer = null
let thinkingPhase = 0
const chatMessages = ref(null)

// ========== 上下文面板状态 ==========
const allDatasets = ref([])        // 数据产物扁平数组（后端返回，每项含 category/sub_type 等字段）
const recentTasks = ref([])        // 最近任务记录
const loadingOptions = ref(false)
const selectedContextItems = ref([]) // 已选上下文项 [{type, ref_id, label, artifact_type, artifact_label}]

// 上下文面板展开/折叠状态（默认折叠为单行汇总条，用户手动展开）
const contextPanelExpanded = ref(false)

// 数据产物两级展开状态：大类(category) + 小类(sub_type)
const expandedCategories = reactive({})       // { [category]: bool }
const expandedSubTypes = reactive({})         // { [`${category}__${sub_type}`]: bool }

// 操作记录两级展开状态：大类(task_type) + 小类(operation)
const expandedTaskTypes = reactive({})        // { [task_type]: bool }
const expandedOperations = reactive({})      // { [`${task_type}__${operation}`]: bool }

// 上下文搜索与筛选（搜索栏固定，列表区滚动）
const contextSearch = ref('')                 // 搜索关键词（名称/数据集ID/任务#ID）
const contextTypeFilter = ref('all')          // 'all' | 'datasets' | 'tasks'
const contextStatusFilter = ref('all')        // 'all' | 'success' | 'failed'（仅过滤操作记录）
const contextTaskTypeFilter = ref('')         // 模块筛选（''=全部 | cleaning | data_analysis | data_mining | feature_engineering | ml）
const contextTaskSourceFilter = ref('')       // 数据来源筛选（''=全部 | 'local' | 'remote'）

// 操作记录分页状态
const taskPage = ref(1)
const taskTotalPages = ref(1)
const loadingMoreTasks = ref(false)

// 开始新话题标记（true 时下次发送消息会通知后端开启新话题）
const startNewTopicFlag = ref(false)
const questionInput = ref(null)    // 输入框引用，用于聚焦

// 预览弹窗
const showPreviewDialog = ref(false)
const loadingPreview = ref(false)
const previewContent = ref('')
const previewTitle = ref('')

// ========== 会话管理状态 ==========
const conversations = ref([])
const showHistoryDialog = ref(false)
const loadingConversations = ref(false)
const currentConversationId = ref(null)
const conversationSearch = ref('')
// 重命名会话相关状态
const renameDialogVisible = ref(false)
const renameConversationId = ref(null)
const renameTitle = ref('')

// ========== 配置与统计 ==========
const configStatus = ref(false)
const showStatsDialog = ref(false)
const loadingStats = ref(false)
const usageStats = ref({})

// ========== 产品问答模式状态 ==========
// 模式：'chat' 分析对话（原有智能对话）| 'qa' 产品问答（数据仓库精确问答/预测）
const activeMode = ref('chat')
const qaMode = computed(() => activeMode.value === 'qa')
const qaCatalogs = ref([])               // 常驻目录列表 [{id, name, description, dataset_ids, is_default}]
const qaSelectedCatalogId = ref(null)    // 当前选中的常驻目录ID
const loadingQaCatalogs = ref(false)
const showSaveCatalogDialog = ref(false) // 保存常驻目录弹窗
const qaCatalogName = ref('')            // 保存目录名称
const qaCatalogDesc = ref('')            // 保存目录描述

// 问答模式下已选数据产物数量（常驻目录保存/全选按钮禁用判断用）
const selectedDatasetsCount = computed(() =>
  selectedContextItems.value.filter(i => i.type === 'dataset').length
)

// ========== 标签映射 ==========
// 模块名、产物类型名、任务类型名优先使用后端返回的 *_label 字段
// 标签映射函数统一复用 utils/labels.js，避免本地维护重复映射

// 快捷命令（空会话时展示的模板）
const quickCommands = [
  '分析这份数据的核心特征',
  '数据质量是否存在问题？',
  '模型准确率为什么偏低？',
  '给出改进建议'
]

// ========== 追问建议状态 ==========
// AI 回答后生成的追问建议列表（来自后端 suggested_questions 字段）
const suggestedQuestions = ref([])
// 当前激活的追问 Tab：'templates' 展示快捷模板，'suggestions' 展示追问建议
const activeFollowupTab = ref('templates')

// ========== 计算属性 ==========
// 按会话标题搜索，并按更新时间倒序排列
const filteredConversations = computed(() => {
  const keyword = conversationSearch.value.trim().toLowerCase()
  const filtered = keyword
    ? conversations.value.filter(c => (c.title || '').toLowerCase().includes(keyword))
    : conversations.value
  return filtered.sort((a, b) => {
    // 用统一的上海时区解析，避免无时区字符串按本地时区解析导致排序错误
    const timeA = (_parseShanghaiDate(a.updated_at || a.created_at) || new Date(0)).getTime()
    const timeB = (_parseShanghaiDate(b.updated_at || b.created_at) || new Date(0)).getTime()
    return timeB - timeA
  })
})

const inputPlaceholder = computed(() => {
  if (qaMode.value) {
    return selectedDatasetsCount.value > 0
      ? `基于 ${selectedDatasetsCount.value} 个数据产物，询问统计、筛选、趋势或预测（如：去年平均月薪是多少？预测下一年产量）...`
      : '请先选择数据产物（可一键全选或选择常驻目录），再输入问题...'
  }
  if (selectedContextItems.value.length > 0) {
    return `基于 ${selectedContextItems.value.length} 个上下文项，输入您的问题...`
  }
  return "输入您的问题，或先从上方上下文注入区选择上下文项以获得更准确的分析..."
})

// ========== 上下文分组 computed ==========

// 数据产物大类展示顺序（按业务流程排序，用 category_label 匹配，更稳健）
const DATASET_CATEGORY_ORDER = [
  '原始数据',
  '数据清洗产物',
  '数据分析报告',
  '数据挖掘产物',
  '特征工程产物',
  '机器学习产物'
]

// 操作记录大类展示顺序（按业务流程排序，用 task_type_label 匹配）
const TASK_TYPE_ORDER = [
  '数据清洗',
  '数据分析',
  '数据挖掘',
  '特征工程',
  '机器学习'
]

// 数据产物搜索过滤：按 name 模糊匹配、按 id 精确匹配
// 类型筛选为 'tasks' 时直接返回空数组；#15 形式仅匹配操作记录
const filteredDatasets = computed(() => {
  if (contextTypeFilter.value === 'tasks') return []
  const keyword = contextSearch.value.trim()
  if (!keyword) return allDatasets.value
  if (keyword.startsWith('#')) return []

  const kw = keyword.toLowerCase()
  return allDatasets.value.filter(ds => {
    // 按 name 模糊匹配
    if ((ds.name || '').toLowerCase().includes(kw)) return true
    // 按 id 精确匹配
    const numId = parseInt(keyword)
    if (!isNaN(numId) && ds.id === numId) return true
    return false
  })
})

// 操作记录搜索过滤：按 id 精确匹配（#15 或 15）、按 dataset_name 模糊匹配
// 同时应用状态筛选（成功/失败）
const filteredTasks = computed(() => {
  if (contextTypeFilter.value === 'datasets') return []
  const keyword = contextSearch.value.trim()

  return recentTasks.value.filter(task => {
    // 账号管理(user_admin)操作与 AI 分析无关，直接排除
    const taskType = task.group_key || task.task_type
    if (taskType === 'user_admin') return false

    // 状态过滤（仅过滤操作记录）
    if (contextStatusFilter.value === 'success' && task.status !== 'success') return false
    if (contextStatusFilter.value === 'failed' && task.status === 'success') return false

    if (!keyword) return true

    // 按 id 精确匹配（#15 或 15）
    const match = keyword.match(/^#?(\d+)$/)
    if (match) {
      const numId = parseInt(match[1])
      if (task.id === numId) return true
      return false
    }

    // 按 dataset_name 模糊匹配
    const kw = keyword.toLowerCase()
    if ((task.dataset_name || '').toLowerCase().includes(kw)) return true
    return false
  })
})

// 数据产物按 category(大类) > sub_type(小类) 两级分组
// 优先使用后端返回的 *_label，缺失时回退到 labels.js 函数
// 不匹配的大类和小类自动隐藏（只遍历过滤后的数据，无数据的分组不会出现）
const contextGroups = computed(() => {
  const filtered = filteredDatasets.value

  const categoryMap = {}
  filtered.forEach(ds => {
    const cat = ds.category || ds.artifact_type || 'other'
    const catLabel = ds.category_label || getArtifactLabel(ds.artifact_type) || cat
    const sub = ds.sub_type || ds.artifact_type || 'other'
    const subLabel = ds.sub_type_label || ds.artifact_label || getArtifactLabel(ds.artifact_type) || sub

    if (!categoryMap[cat]) {
      categoryMap[cat] = {
        category: cat,
        category_label: catLabel,
        subTypes: {}
      }
    }
    if (!categoryMap[cat].subTypes[sub]) {
      categoryMap[cat].subTypes[sub] = {
        sub_type: sub,
        sub_type_label: subLabel,
        items: []
      }
    }
    categoryMap[cat].subTypes[sub].items.push(ds)
  })

  // 转为数组并按指定大类顺序排序
  const groups = Object.values(categoryMap).map(g => ({
    ...g,
    subTypes: Object.values(g.subTypes)
  }))

  groups.sort((a, b) => {
    const idxA = DATASET_CATEGORY_ORDER.indexOf(a.category_label)
    const idxB = DATASET_CATEGORY_ORDER.indexOf(b.category_label)
    if (idxA === -1 && idxB === -1) return a.category_label.localeCompare(b.category_label)
    if (idxA === -1) return 1
    if (idxB === -1) return -1
    return idxA - idxB
  })

  return groups
})

// 操作记录固定分类结构（与操作历史 TaskHistory.vue CATEGORY_OPERATION_MAP 对齐）
// 分类体系完整展示（大类 + 标准操作子类），记录按 group_key + operation 归入；
// 当前页无记录的组计数为 0，避免"数据分析/数据挖掘子类缺失"的感知问题
const FIXED_TASK_STRUCTURE = [
  {
    task_type: 'cleaning',
    task_type_label: '数据清洗',
    operations: [
      { operation: 'contract_config', operation_label: '契约配置' },
      { operation: 'problem_strategy', operation_label: '问题清单配置' },
      { operation: 'execute_clean', operation_label: '执行清洗' },
      { operation: 'save_clean_result', operation_label: '保存清洗结果' },
    ]
  },
  {
    task_type: 'data_analysis',
    task_type_label: '数据分析',
    operations: [
      { operation: 'generate_report', operation_label: '生成报告' },
      { operation: 'save_report', operation_label: '保存报告' },
    ]
  },
  {
    task_type: 'data_mining',
    task_type_label: '数据挖掘',
    operations: [
      { operation: 'cluster', operation_label: '聚类分析' },
      { operation: 'association', operation_label: '关联规则' },
      { operation: 'sequence', operation_label: '序列模式' },
      { operation: 'save_cluster', operation_label: '保存聚类结果' },
      { operation: 'save_association', operation_label: '保存关联规则' },
      { operation: 'save_sequence', operation_label: '保存序列模式' },
    ]
  },
  {
    task_type: 'feature_engineering',
    task_type_label: '特征工程',
    operations: [
      { operation: 'select_features', operation_label: '特征选择' },
      { operation: 'construct_features', operation_label: '特征构造' },
      { operation: 'encode_features', operation_label: '特征编码' },
      { operation: 'scale_features', operation_label: '特征缩放' },
      { operation: 'reduce_features', operation_label: '特征降维' },
      { operation: 'export_selected', operation_label: '导出特征选择产物' },
      { operation: 'export_pool', operation_label: '导出列池产物' },
    ]
  },
  {
    task_type: 'ml',
    task_type_label: '机器学习',
    operations: [
      { operation: 'train', operation_label: '模型训练' },
      { operation: 'batch_predict', operation_label: '批量预测' },
      { operation: 'test_evaluate', operation_label: '测试集评估' },
    ]
  },
]

// 操作记录按固定模块分类(大类) > 标准操作(小类) 两级分组
// 分组结构完整固定（对齐操作历史），不随当前页记录动态增减；记录按 group_key + operation 归入
const groupedTasks = computed(() => {
  const filtered = filteredTasks.value

  // 记录按 group_key + operation 归入（特征工程 5 子类型、ml/ml_training 已由后端 group_key 归一）
  const taskMap = {}
  filtered.forEach(task => {
    const gk = task.group_key || task.task_type || 'other'
    const op = task.operation || 'other'
    if (!taskMap[gk]) taskMap[gk] = {}
    if (!taskMap[gk][op]) taskMap[gk][op] = []
    taskMap[gk][op].push(task)
  })

  // 按固定结构构建完整分组
  const groups = FIXED_TASK_STRUCTURE.map(grp => {
    const opsMap = taskMap[grp.task_type] || {}
    const operations = grp.operations.map(opDef => ({
      operation: opDef.operation,
      operation_label: opDef.operation_label,
      items: opsMap[opDef.operation] || [],
    }))
    return {
      task_type: grp.task_type,
      task_type_label: grp.task_type_label,
      operations,
    }
  })

  // 固定结构之外的 task_type（兜底）动态追加到末尾
  Object.keys(taskMap).forEach(gk => {
    if (!FIXED_TASK_STRUCTURE.some(g => g.task_type === gk)) {
      const ops = Object.keys(taskMap[gk]).map(op => ({
        operation: op,
        operation_label: taskMap[gk][op][0].operation_label || op,
        items: taskMap[gk][op],
      }))
      const label = filtered.find(t => (t.group_key || t.task_type) === gk)?.task_type_label || gk
      groups.push({ task_type: gk, task_type_label: label, operations: ops })
    }
  })

  return groups
})

// ========== 生命周期 ==========
// 记录当前用户ID，用于keep-alive重新激活时检测用户切换
let lastUserId = authStore.user?.id || null

onMounted(async () => {
  lastUserId = authStore.user?.id || null
  await checkConfigStatus()
  await Promise.all([
    loadConversations(),
    loadContextOptions(),
    loadQaCatalogs()
  ])
})

// keep-alive 重新激活时，检测用户是否切换；切换则重置所有状态避免泄露上一个用户的数据
// 同一用户下也刷新上下文选项，确保操作记录反映最新的数据集状态
onActivated(async () => {
  const currentUserId = authStore.user?.id || null
  if (currentUserId !== lastUserId) {
    // 用户切换：重置所有状态（含思考动画，避免旧请求回复串入新用户会话）
    lastUserId = currentUserId
    aiThinking.value = false
    stopThinkingAnimation()
    currentConversationId.value = null
    messages.value = []
    selectedContextItems.value = []
    await checkConfigStatus()
    await Promise.all([
      loadConversations(),
      loadContextOptions(),
      loadQaCatalogs()
    ])
  } else {
    // 同一用户：仅刷新上下文选项，反映数据集状态变化（如删除/恢复）
    loadContextOptions()
  }
})

// keep-alive 下切换到其他模块时停止思考动画，避免定时器持续空转（onUnmounted 不触发）
onDeactivated(() => {
  stopThinkingAnimation()
})

onUnmounted(() => {
  stopThinkingAnimation()
})

watch(() => messages.value.length, async () => {
  await nextTick()
  if (chatMessages.value) {
    chatMessages.value.scrollTop = chatMessages.value.scrollHeight
  }
})

// ========== 上下文面板方法 ==========

// 加载上下文可选项
// append=false（默认）：刷新模式，重置 taskPage=1 并替换数据
// append=true：加载更多模式，请求下一页并追加到 recentTasks
// 注：后端 datasets 现已改为扁平数组（每项含 category/sub_type 等字段），直接赋值给 allDatasets
async function loadContextOptions(append = false) {
  const requestPage = append ? taskPage.value + 1 : 1
  if (append) {
    loadingMoreTasks.value = true
  } else {
    loadingOptions.value = true
    taskPage.value = 1
  }
  try {
    // 模块筛选（contextTaskTypeFilter）与数据来源筛选（contextTaskSourceFilter）随请求传给后端
    const fetchOptions = {}
    if (contextTaskTypeFilter.value) fetchOptions.taskType = contextTaskTypeFilter.value
    if (contextTaskSourceFilter.value === 'local') fetchOptions.isRemote = false
    else if (contextTaskSourceFilter.value === 'remote') fetchOptions.isRemote = true
    const res = await fetchContextOptions(requestPage, 20, fetchOptions)
    const data = res.data || {}

    // 数据产物扁平数组（仅在刷新模式下重置）
    if (!append) {
      allDatasets.value = data.datasets || []
    }

    // 操作记录：刷新模式替换，加载更多模式追加
    if (append) {
      recentTasks.value = [...recentTasks.value, ...(data.recent_tasks || [])]
    } else {
      recentTasks.value = data.recent_tasks || []
    }

    // 从响应中读取分页信息
    const pagination = data.tasks_pagination || {}
    taskPage.value = pagination.page || requestPage
    taskTotalPages.value = pagination.total_pages || 1

    // 默认展开第一个数据产物大类和小类（仅刷新模式，且未手动操作过）
    if (!append && contextGroups.value.length > 0) {
      const firstCat = contextGroups.value[0].category
      if (expandedCategories[firstCat] === undefined) {
        expandedCategories[firstCat] = true
      }
      const firstSubTypes = contextGroups.value[0].subTypes
      if (firstSubTypes && firstSubTypes.length > 0) {
        const key = `${firstCat}__${firstSubTypes[0].sub_type}`
        if (expandedSubTypes[key] === undefined) {
          expandedSubTypes[key] = true
        }
      }
    }
    // 默认展开第一个操作记录大类和小类
    if (groupedTasks.value.length > 0) {
      const firstTaskType = groupedTasks.value[0].task_type
      if (expandedTaskTypes[firstTaskType] === undefined) {
        expandedTaskTypes[firstTaskType] = true
      }
      const firstOps = groupedTasks.value[0].operations
      if (firstOps && firstOps.length > 0) {
        const key = `${firstTaskType}__${firstOps[0].operation}`
        if (expandedOperations[key] === undefined) {
          expandedOperations[key] = true
        }
      }
    }
  } catch (e) {
    console.error('加载上下文选项失败:', e)
    if (!append) {
      allDatasets.value = []
      recentTasks.value = []
      taskTotalPages.value = 1
    }
  } finally {
    if (append) {
      loadingMoreTasks.value = false
    } else {
      loadingOptions.value = false
    }
  }
}

// 加载更多操作记录
async function loadMoreTasks() {
  await loadContextOptions(true)
}

// 模块/数据来源筛选变化：重置分页并重新加载操作记录
function onContextTaskFilterChange() {
  taskPage.value = 1
  loadContextOptions(false)
}

// 切换数据产物大类展开/收起
function toggleCategory(category) {
  expandedCategories[category] = !expandedCategories[category]
}

// 切换数据产物小类展开/收起
function toggleSubType(category, subType) {
  const key = `${category}__${subType}`
  expandedSubTypes[key] = !expandedSubTypes[key]
}

// 判断数据产物小类是否展开
function isSubTypeExpanded(category, subType) {
  const key = `${category}__${subType}`
  return !!expandedSubTypes[key]
}

// 切换操作记录大类展开/收起
function toggleTaskType(taskType) {
  expandedTaskTypes[taskType] = !expandedTaskTypes[taskType]
}

// 切换操作记录小类展开/收起
function toggleOperation(taskType, operation) {
  const key = `${taskType}__${operation}`
  expandedOperations[key] = !expandedOperations[key]
}

// 判断操作记录小类是否展开
function isOperationExpanded(taskType, operation) {
  const key = `${taskType}__${operation}`
  return !!expandedOperations[key]
}

// 统计某个数据产物大类下的总项数（所有小类项数之和）
function countDatasetItems(catGroup) {
  return (catGroup.subTypes || []).reduce((sum, s) => sum + s.items.length, 0)
}

// 统计某个操作记录大类下的总项数（所有小类项数之和）
function countTaskItems(taskGroup) {
  return (taskGroup.operations || []).reduce((sum, o) => sum + o.items.length, 0)
}

function isItemSelected(type, refId) {
  return selectedContextItems.value.some(
    item => item.type === type && item.ref_id === refId
  )
}

function toggleSelect(type, refId, label, artifactType, artifactLabel) {
  const existing = selectedContextItems.value.some(
    item => item.type === type && item.ref_id === refId
  )
  if (existing) {
    // 取消选中：从已选项中移除该上下文项
    selectedContextItems.value = selectedContextItems.value.filter(
      item => !(item.type === type && item.ref_id === refId)
    )
    // 取消选中数据产物时，一并移除由它自动带出的血缘操作（保留用户手动添加的操作）
    if (type === 'dataset') {
      selectedContextItems.value = selectedContextItems.value.filter(
        item => item.auto_source_dataset_id !== refId
      )
    }
  } else {
    selectedContextItems.value.push({
      type,
      ref_id: refId,
      label,
      artifact_type: artifactType || '',
      artifact_label: artifactLabel || ''
    })
    // 选中数据产物时，自动带出它血缘链上的操作（默认选中、标注所属产物、可在已选项中取消）
    if (type === 'dataset') {
      autoInjectBloodlineOps(refId)
    }
  }
}

// 选中数据产物后，自动带出它血缘链上的最近操作记录（默认选中，可取消）
async function autoInjectBloodlineOps(datasetId) {
  try {
    const res = await fetchBloodlineOps(datasetId)
    const ops = res.data?.operations || []
    let addedCount = 0
    for (const op of ops) {
      const exists = selectedContextItems.value.some(
        item => item.type === 'operation' && item.ref_id === op.id
      )
      if (exists) continue
      // 标注操作所属的产物，便于区分同名产物
      const opTypeLabel = op.task_type_label || op.task_type || 'unknown'
      const belongs = op.belongs_to ? ` · ${op.belongs_to}` : ''
      selectedContextItems.value.push({
        type: 'operation',
        ref_id: op.id,
        label: `任务#${op.id}(${opTypeLabel})${belongs}`,
        artifact_type: op.task_type || 'unknown',
        artifact_label: opTypeLabel,
        auto_source_dataset_id: datasetId
      })
      addedCount++
    }
    if (addedCount > 0) {
      ElMessage.info(`已按数据血缘自动带出 ${addedCount} 条操作，可在已选项中取消`)
    }
  } catch (e) {
    console.error('自动带出血缘操作失败:', e)
  }
}

function removeSelectedItem(item) {
  const idx = selectedContextItems.value.findIndex(
    i => i.type === item.type && i.ref_id === item.ref_id
  )
  if (idx >= 0) {
    selectedContextItems.value.splice(idx, 1)
  }
}

function clearSelection() {
  selectedContextItems.value = []
}

// ========== 产品问答模式方法 ==========

// 切换问答/分析模式：重置跨模式残留的对话与上下文状态，避免串数据
function switchMode(mode) {
  if (activeMode.value === mode) return
  activeMode.value = mode
  // 切换模式时清空当前对话、上下文选择与追问建议
  stopThinkingAnimation()
  aiThinking.value = false
  messages.value = []
  currentConversationId.value = null
  startNewTopicFlag.value = false
  selectedContextItems.value = []
  suggestedQuestions.value = []
  activeFollowupTab.value = 'templates'
  contextPanelExpanded.value = false
}

// 一键全选：将当前加载的全部数据产物选入数据仓库（仅数据产物，不含操作记录）
function selectAllDatasets() {
  const currentDatasets = filteredDatasets.value
  if (currentDatasets.length === 0) return
  // 清空旧选择，再全部加入，避免与已有手动选择重复
  selectedContextItems.value = selectedContextItems.value.filter(i => i.type !== 'dataset')
  for (const ds of currentDatasets) {
    if (!selectedContextItems.value.some(i => i.type === 'dataset' && i.ref_id === ds.id)) {
      selectedContextItems.value.push({
        type: 'dataset',
        ref_id: ds.id,
        label: `${ds.name} (ID:${ds.id})`,
        artifact_type: ds.artifact_type,
        artifact_label: ds.artifact_label
      })
    }
  }
  ElMessage.success(`已将 ${currentDatasets.length} 个数据产物选入数据仓库`)
}

// 加载当前用户的常驻目录列表
async function loadQaCatalogs() {
  loadingQaCatalogs.value = true
  try {
    const res = await listQaCatalogs()
    qaCatalogs.value = res.data || []
  } catch (e) {
    console.error('加载常驻目录失败:', e)
    qaCatalogs.value = []
  } finally {
    loadingQaCatalogs.value = false
  }
}

// 选中常驻目录后，将其中数据集作为数据仓库
function applyQaCatalog(catId) {
  if (!catId) return
  const cat = qaCatalogs.value.find(c => c.id === catId)
  if (!cat) return
  // 清除旧的已选数据产物，装载目录的集合
  selectedContextItems.value = []
  const idSet = new Set(cat.dataset_ids)
  for (const ds of allDatasets.value) {
    if (idSet.has(ds.id)) {
      selectedContextItems.value.push({
        type: 'dataset',
        ref_id: ds.id,
        label: `${ds.name} (ID:${ds.id})`,
        artifact_type: ds.artifact_type,
        artifact_label: ds.artifact_label
      })
    }
  }
  ElMessage.success(`已装载常驻目录"${cat.name}"（${selectedContextItems.value.length} 个数据产物）`)
}

// 打开"保存为目录"弹窗
function openSaveCatalogDialog() {
  qaCatalogName.value = ''
  qaCatalogDesc.value = ''
  showSaveCatalogDialog.value = true
}

// 确认保存常驻目录
async function confirmSaveCatalog() {
  if (!qaCatalogName.value.trim()) {
    ElMessage.warning('请输入目录名称')
    return
  }
  const ids = getSelectedDatasetIds()
  if (ids.length === 0) {
    ElMessage.warning('请先选择数据产物')
    return
  }
  // 若已选中某目录则视为更新该目录
  const catalogId = qaSelectedCatalogId.value || undefined
  try {
    await saveQaCatalog({
      name: qaCatalogName.value.trim(),
      dataset_ids: ids,
      description: qaCatalogDesc.value.trim() || undefined,
      catalog_id: catalogId
    })
    ElMessage.success(catalogId ? '目录已更新' : '目录已保存')
    showSaveCatalogDialog.value = false
    await loadQaCatalogs()
  } catch (e) {
    const msg = e.response?.data?.detail || '保存目录失败'
    ElMessage.error(typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
}

// 删除常驻目录
async function deleteCatalogHandler() {
  const catId = qaSelectedCatalogId.value
  if (!catId) return
  try {
    await ElMessageBox.confirm('确定删除该常驻目录吗？此操作不影响数据本身。', '确认删除', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  try {
    await deleteQaCatalog(catId)
    qaSelectedCatalogId.value = null
    ElMessage.success('目录已删除')
    await loadQaCatalogs()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '删除目录失败')
  }
}

// ========== 问答精确结果渲染辅助 ==========

// 判断 exec_result 是否可渲染成本地结果卡片
function hasExecResult(execResult) {
  if (!execResult || !execResult.success) return false
  const r = execResult.result
  return !!r && (r.count !== undefined || r.grouped !== undefined ||
    r.total !== undefined || r.top_predictions !== undefined ||
    (r[`${execResult.aggregation || 'mean'}_${execResult.target_column || ''}`] !== undefined))
}

// 渲染 exec_result 单值数值：优先取 result 中除 grouped 外的数值键
function execValue(execResult) {
  const r = (execResult && execResult.result) || {}
  return r.count !== undefined ? r.count : Object.values(r)[0]
}

// 执行类型标签（聚合/明细/预测），用于结果卡片角标
function execTypeLabel(execResult) {
  if (!execResult) return ''
  const t = execResult.result_type
  if (execResult.needs_model || t === 'prediction') return '预测结果'
  if (t === 'rows') return '数据明细'
  return '聚合结果'
}

// 判断是否为分组聚合（有 grouped 字段）
function isGroupedResult(execResult) {
  return !!(execResult && execResult.success && execResult.result && execResult.result.grouped)
}

// 判断是否为模型预测结果
function isPredictionResult(execResult) {
  return !!(execResult && execResult.success && execResult.result && execResult.result.top_predictions)
}

// 预测分布对象（k:v），用于缩放条展示
function predictionDistribution(execResult) {
  const stats = execResult?.result?.prediction_stats || {}
  if (stats && typeof stats === 'object' && Object.keys(stats).length > 0) return stats
  return null
}

// 计算预测分布中各分类的占比（用于缩放条宽度，0-100）
function predBarPercent(value, execResult) {
  const dist = predictionDistribution(execResult)
  if (!dist) return 0
  const max = Math.max(...Object.values(dist))
  if (!max) return 0
  return Math.round((Number(value) / max) * 100)
}

async function previewItem(type, refId, name) {
  showPreviewDialog.value = true
  loadingPreview.value = true
  previewTitle.value = name || `${type}#${refId}`
  previewContent.value = ''
  try {
    const res = await previewContextItem(type, refId)
    const data = res.data || {}
    if (type === 'dataset') {
      previewContent.value = data.preview || '(无摘要内容)'
    } else {
      previewContent.value = data.preview || '(无摘要内容)'
    }
  } catch (e) {
    previewContent.value = `预览加载失败: ${e.response?.data?.detail || e.message}`
  } finally {
    loadingPreview.value = false
  }
}

function getItemIcon(item) {
  if (item.type === 'operation') return 'Files'
  const artifactType = item.artifact_type
  if (artifactType === 'ml_model' || artifactType === 'ml_report') return 'Cpu'
  if (artifactType === 'cleaning_result') return 'Brush'
  if (artifactType === 'feature_result') return 'MagicStick'
  if (artifactType === 'analysis_report') return 'DataAnalysis'
  return 'Document'
}

function getItemTypeLabel(item) {
  if (item.type === 'operation') return '操作记录'
  return item.artifact_label || item.artifact_type || '数据产物'
}

function getItemTagType(item) {
  if (item.type === 'operation') return 'warning'
  // 复用 labels.js 的标签颜色映射，避免本地维护重复映射
  return getArtifactTagType(item.artifact_type)
}

// ========== 对话方法 ==========

// 转义 HTML 特殊字符，防止 AI 返回内容中的原始 HTML 标签触发 XSS
function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function renderMarkdown(text) {
  if (!text) return ''
  // 先转义 HTML 特殊字符，再应用 markdown 替换（生成的标签是安全的，原始 HTML 会被转义为文本）
  let html = escapeHtml(text)
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="code-block"><code>$2</code></pre>')
    .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^\|(.+)\|$/gm, (line) => {
      const cells = line.split('|').filter(c => c.trim())
      const isHeader = line.includes('---')
      if (isHeader) return ''
      const tag = line.match(/^\|[-|\s]+\|$/) ? '' : 'td'
      return '<tr>' + cells.map(c => `<${tag}>${c.trim()}</${tag}>`).join('') + '</tr>'
    })
    .replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>')

  // 列表处理：在 \n→<br> 之前，先把连续的列表行（- 或 * 开头）包裹成 <ul><li>
  // 避免后续 <br> 打断连续 <li> 的正则匹配导致裸 <li> 渲染异常
  const lines = html.split('\n')
  const result = []
  let inList = false
  for (const line of lines) {
    // 匹配 - xxx 或 * xxx（但不是 ** 加粗）
    const listMatch = line.match(/^[-*]\s+(.+)$/)
    if (listMatch) {
      if (!inList) {
        result.push('<ul>')
        inList = true
      }
      result.push(`<li>${listMatch[1]}</li>`)
    } else {
      if (inList) {
        result.push('</ul>')
        inList = false
      }
      result.push(line)
    }
  }
  if (inList) result.push('</ul>')
  html = result.join('\n')

  // 换行转 <br>（<ul>/<li> 标签内的换行不影响渲染）
  html = html.replace(/\n/g, '<br>')
  // 清理 <ul>/<li> 标签间多余的 <br>
  html = html.replace(/<br>(<\/?(?:ul|li)>)/g, '$1')
  html = html.replace(/(<\/?(?:ul|li)>)<br>/g, '$1')
  return html
}

function formatUsage(usage) {
  if (!usage) return ''
  if (typeof usage === 'number') {
    return `${usage} tokens`
  }
  if (typeof usage === 'string') {
    try {
      const obj = JSON.parse(usage)
      return formatUsage(obj)
    } catch {
      return usage
    }
  }
  if (typeof usage === 'object') {
    const total = usage.total_tokens || 0
    const prompt = usage.prompt_tokens || 0
    const completion = usage.completion_tokens || 0
    if (total > 0 || prompt > 0 || completion > 0) {
      if (prompt > 0 || completion > 0) {
        return `输入 ${prompt} / 输出 ${completion} = 合计 ${total} tokens`
      }
      return `${total} tokens`
    }
  }
  return ''
}

function startThinkingAnimation() {
  thinkingPhase = 0
  thinkingStatus.value = 'AI 正在思考中'
  thinkingHint.value = '正在理解您的问题，请稍候...'
  if (thinkingTimer) clearInterval(thinkingTimer)
  thinkingTimer = setInterval(() => {
    thinkingPhase = (thinkingPhase + 1) % 4
    const phases = [
      { status: 'AI 正在思考中', hint: '正在分析问题关键点...' },
      { status: '正在检索上下文', hint: '正在加载选中的数据产物...' },
      { status: 'AI 正在组织语言', hint: '正在生成分析回答...' },
      { status: '即将完成', hint: '马上就好，请稍候...' }
    ]
    const p = phases[thinkingPhase]
    thinkingStatus.value = p.status
    thinkingHint.value = p.hint
  }, 2000)
}

function stopThinkingAnimation() {
  if (thinkingTimer) {
    clearInterval(thinkingTimer)
    thinkingTimer = null
  }
  thinkingPhase = 0
}

function useQuickCommand(cmd) {
  question.value = cmd
}

// 问答模式下：仅取已选数据产物ID作为数据仓库
const getSelectedDatasetIds = () =>
  selectedContextItems.value.filter(i => i.type === 'dataset').map(i => i.ref_id)

async function sendMessage() {
  const q = question.value.trim()
  if (!q || aiThinking.value) return

  if (!configStatus.value) {
    ElMessage.warning('AI 服务不可用，请联系管理员配置 API Key')
    return
  }

  // 问答模式下未选数据产物则拦截
  if (qaMode.value && getSelectedDatasetIds().length === 0) {
    ElMessage.warning('请先在"数据仓库选择"区域勾选数据产物、一键全选或选择常驻目录')
    return
  }

  // 记录当前选中的上下文项快照（用于消息展示）
  const contextSnapshot = selectedContextItems.value.map(item => ({ ...item }))

  messages.value.push({
    role: 'user',
    content: q,
    // 统一使用上海时区，与历史消息展示口径一致
    time: _formatShanghai(new Date()),
    contextItems: contextSnapshot
  })
  question.value = ''
  aiThinking.value = true
  startThinkingAnimation()

  try {
    // 构造 context_items 参数（仅传 type 和 ref_id）
    const contextItemsParam = contextSnapshot.map(item => ({
      type: item.type,
      ref_id: item.ref_id
    }))

    // startNewTopicFlag 为 true 时通知后端开启新话题，断开与历史对话的关联
    let res
    if (qaMode.value) {
      // 产品问答：走数据仓库精确问答/预测接口，只传数据产物ID集合
      res = await qaChat(q, getSelectedDatasetIds(), currentConversationId.value, startNewTopicFlag.value)
    } else {
      // 分析对话：构造 context_items 参数（仅传 type 和 ref_id）
      const contextItemsParam = contextSnapshot.map(item => ({
        type: item.type,
        ref_id: item.ref_id
      }))
      res = await aiChat(q, contextItemsParam, currentConversationId.value, null, startNewTopicFlag.value)
    }
    // 发送后无论成功失败都重置新话题标记
    startNewTopicFlag.value = false
    const reply = res.data?.answer
    const usage = res.data?.usage || 0
    const needsContext = res.data?.needs_context || []
    const isFallback = res.data?.usage?.is_fallback || false
    const suggestedQuestionsList = res.data?.suggested_questions || []
    const execResult = res.data?.exec_result || null

    if (res.data?.conversation_id) {
      currentConversationId.value = res.data.conversation_id
    }

    // 更新追问建议：有追问时切到 suggestions Tab，无追问时回到 templates Tab
    if (suggestedQuestionsList.length > 0) {
      suggestedQuestions.value = suggestedQuestionsList
      activeFollowupTab.value = 'suggestions'
    } else {
      suggestedQuestions.value = []
      activeFollowupTab.value = 'templates'
    }

    messages.value.push({
      role: 'assistant',
      content: reply || '抱歉，未能获取到分析结果，请重试。',
      time: _formatShanghai(new Date()),
      usage: usage,
      is_fallback: isFallback,
      needsContext: needsContext,
      // 问答模式附带精确计算结果（前端可选渲染为表格/结构化卡片）
      execResult: qaMode.value ? execResult : null
    })
    await loadConversations()
  } catch (e) {
    // 异常时也重置新话题标记，避免状态残留
    startNewTopicFlag.value = false
    console.error(e)
    // 尽量透出后端的明确错误原因（如"追问次数已用完""会话已过期"），
    // 只有拿不到明确信息时才回退到通用兜底文案，避免误导用户以为服务不可用
    const detail = e?.response?.data?.detail ?? e?.response?.data?.error
    let errText = '抱歉，AI 服务暂时不可用，请检查网络连接或稍后重试。'
    if (detail) {
      errText = Array.isArray(detail)
        ? detail.map(d => d?.msg || d).join('；')
        : String(detail)
    }
    messages.value.push({
      role: 'assistant',
      content: errText,
      time: _formatShanghai(new Date())
    })
  } finally {
    aiThinking.value = false
    stopThinkingAnimation()
  }
}

// 新建会话：清空当前对话消息和会话ID，下次发送消息时创建新会话
// 注意：不会删除后端历史会话数据，只是在前端开始一个新对话
async function clearChat() {
  // 当前有对话时弹出确认，避免误点丢失对话
  if (messages.value.length > 0) {
    try {
      await ElMessageBox.confirm(
        '将清空当前对话并开始新会话，历史会话记录仍可在"历史记录"中查看。确认继续？',
        '新建会话',
        {
          confirmButtonText: '确认',
          cancelButtonText: '取消',
          type: 'warning'
        }
      )
    } catch {
      // 用户取消，不做任何操作
      return
    }
  }
  messages.value = []
  currentConversationId.value = null
  selectedContextItems.value = []
  startNewTopicFlag.value = false
  // 清空追问建议并重置 Tab
  suggestedQuestions.value = []
  activeFollowupTab.value = 'templates'
  ElMessage.success('已开始新会话')
}

// 开始新话题：清空上下文选择并标记下一次发送为新话题
async function startNewTopic() {
  try {
    await ElMessageBox.confirm(
      '开始新话题将清空当前上下文选择，AI将不再关联之前的对话内容。确认继续？',
      '开始新话题',
      {
        confirmButtonText: '确认',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch {
    // 用户取消，不做任何操作
    return
  }
  selectedContextItems.value = []
  startNewTopicFlag.value = true
  ElMessage.success('已开始新话题，请输入您的问题')
  // 聚焦输入框，引导用户输入新问题
  await nextTick()
  questionInput.value?.focus?.()
}

// ========== 配置检查 ==========

async function checkConfigStatus() {
  try {
    const res = await getAIConfig()
    const data = res.data || {}
    configStatus.value = !!data.is_configured
  } catch {
    configStatus.value = false
  }
}

// ========== 会话管理 ==========

async function loadConversations() {
  loadingConversations.value = true
  try {
    const res = await fetchConversations()
    conversations.value = res.data || []
  } catch {
    conversations.value = []
  } finally {
    loadingConversations.value = false
  }
}

async function loadConversation(conv) {
  try {
    const res = await fetchConversation(conv.id)
    const data = res.data || {}
    const msgs = data.conversation || data.messages || []
    messages.value = msgs.map(m => ({
      role: m.role,
      content: m.content,
      time: formatTime(m.created_at || new Date().toISOString()),
      usage: m.usage || 0
    }))
    currentConversationId.value = conv.id
    // 切换会话时清空追问建议、已选上下文项并重置 Tab，避免跨会话串数据
    selectedContextItems.value = []
    suggestedQuestions.value = []
    activeFollowupTab.value = 'templates'
    showHistoryDialog.value = false
    ElMessage.success('已加载历史会话')
  } catch (e) {
    // 加载失败：保留当前消息列表，提示错误且不关闭弹窗，
    // 避免伪造"已加载历史会话"覆盖用户正在查看的内容
    console.error('加载历史会话失败:', e)
    ElMessage.error('加载历史会话失败，请重试')
  }
}

async function deleteConv(id) {
  try {
    await ElMessageBox.confirm('确定要删除这个会话吗？', '确认删除', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    // 用户点击取消（reject 为 'cancel' 字符串），不执行删除
    return
  }
  try {
    await deleteConversation(id)
    conversations.value = conversations.value.filter(c => c.id !== id)
    ElMessage.success('删除成功')
  } catch (e) {
    // 接口失败：提示错误，保留会话列表，避免前端与后端数据不一致
    console.error('删除会话失败:', e)
    ElMessage.error('删除失败，请重试')
  }
}

// 开始重命名会话：打开弹窗并预填充当前标题
function startRenameConversation(conv) {
  renameConversationId.value = conv.id
  renameTitle.value = conv.title || ''
  renameDialogVisible.value = true
}

// 确认重命名：调用后端接口并同步本地列表
async function confirmRenameConversation() {
  if (!renameTitle.value.trim()) {
    ElMessage.warning('标题不能为空')
    return
  }
  try {
    await renameConversation(renameConversationId.value, renameTitle.value.trim())
    // 更新本地列表中的标题
    const conv = conversations.value.find(c => c.id === renameConversationId.value)
    if (conv) conv.title = renameTitle.value.trim()
    // 如果是当前会话，也更新当前会话标题显示
    if (currentConversationId.value === renameConversationId.value) {
      // 可以在这里更新任何需要的地方
    }
    ElMessage.success('重命名成功')
    renameDialogVisible.value = false
  } catch (error) {
    const msg = error.response?.data?.detail || '重命名失败'
    ElMessage.error(msg)
  }
}

// ========== 使用统计 ==========

async function loadUsageStats() {
  loadingStats.value = true
  try {
    const res = await fetchUsageStats()
    usageStats.value = res.data || {}
  } catch {
    usageStats.value = {}
  } finally {
    loadingStats.value = false
  }
}

watch(showStatsDialog, (val) => {
  if (val) {
    loadUsageStats()
  }
})

// ========== 工具函数 ==========

function getModuleIcon(type) {
  const iconMap = {
    data_cleaning: 'Brush',
    data_mining: 'DataAnalysis',
    feature_engineering: 'MagicStick',
    machine_learning: 'Cpu',
    comprehensive: 'DataLine',
    general_chat: 'ChatDotRound',
    ai_qa: 'ChatLineRound' // 产品问答会话
  }
  return iconMap[type] || 'Document'
}

// 解析后端时间字符串为 Date 对象
// 后端返回的 naive datetime 实际为 UTC 时间数值（与 DataManagement.vue 保持一致），
// 无时区后缀时按 UTC（'Z'）解析，再用 Intl 转为上海时区显示。
function _parseShanghaiDate(timeStr) {
  if (!timeStr) return null
  // 检测是否带时区信息：Z / +08:00 / -05:00
  const hasTimezone = /([Zz]$)|([+-]\d{2}:\d{2}$)/.test(timeStr)
  const d = hasTimezone ? new Date(timeStr) : new Date(timeStr + 'Z')
  return isNaN(d.getTime()) ? null : d
}

// 统一用上海时区格式化时间，避免客户端时区差异
// 相对时间精确到秒，绝对时间用上海时区
function formatTime(timeStr) {
  if (!timeStr) return ''
  const d = _parseShanghaiDate(timeStr)
  if (!d) return timeStr

  const now = new Date()
  const diff = now.getTime() - d.getTime()

  // 负数或0表示时间异常，直接显示绝对时间
  if (diff <= 0) return _formatShanghai(d)

  // 相对时间精确到秒
  const seconds = Math.floor(diff / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)

  if (seconds < 60) return `${seconds} 秒前`
  if (minutes < 60) {
    const remSec = seconds % 60
    return remSec > 0 ? `${minutes} 分 ${remSec} 秒前` : `${minutes} 分钟前`
  }
  if (hours < 24) {
    const remMin = minutes % 60
    const remSec = seconds % 60
    const parts = [`${hours} 小时`]
    if (remMin > 0) parts.push(`${remMin} 分`)
    if (remSec > 0) parts.push(`${remSec} 秒`)
    return parts.join(' ') + '前'
  }
  if (days < 7) {
    const remHr = hours % 24
    const remMin = minutes % 60
    const remSec = seconds % 60
    const parts = [`${days} 天`]
    if (remHr > 0) parts.push(`${remHr} 小时`)
    if (remMin > 0) parts.push(`${remMin} 分`)
    if (remSec > 0) parts.push(`${remSec} 秒`)
    return parts.join(' ') + '前'
  }

  // 超过7天显示绝对时间，统一用上海时区
  return _formatShanghai(d)
}

// 上海时区格式化工具：返回 yyyy-MM-dd HH:mm:ss
function _formatShanghai(d) {
  // 用 Intl 获取上海时区的各部分，避免浏览器本地时区影响
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false
  }).formatToParts(d)
  const get = type => parts.find(p => p.type === type)?.value || ''
  return `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}:${get('second')}`
}

// 格式化为绝对时间 yyyy-MM-dd HH:mm:ss（上海时区，操作记录/消息时间戳专用）
function formatDateTime(timeStr) {
  if (!timeStr) return '-'
  const d = _parseShanghaiDate(timeStr)
  if (!d) return timeStr
  return _formatShanghai(d)
}
</script>

<style scoped>
/* 主布局：上下结构（上端上下文注入区 + 下端对话区）
   用 min-height 允许内容撑开页面滚动，避免两个区域被视口高度压缩过小 */
.ai-main {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: calc(100vh - 140px);
}

/* 重置 global.css .card 的 padding/margin，避免吃掉内部空间导致内容溢出 */
.ai-main .card {
  padding: 0;
  margin-bottom: 0;
}

/* 上下文注入区：可折叠，展开时限制最大高度，内部列表区滚动 */
.context-panel {
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  overflow: hidden;
}

/* 展开态：限制最大高度，内部列表区 flex:1 滚动 */
.context-panel:not(.collapsed) {
  max-height: 320px;
}

/* 折叠态：高度自适应内容（单行汇总条） */
.context-panel.collapsed {
  max-height: none;
}

/* 对话区：撑满剩余高度，并保证最小可用空间，内容多时页面整体滚动 */
.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 520px;
  overflow: hidden;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border-light, #f0f0f0);
  flex-shrink: 0;
}

.card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

/* ========== 上下文面板样式 ========== */

/* 展开态：flex 布局，工具栏固定 + 列表区滚动 */
.context-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 12px 16px 0;
}

/* 折叠态汇总条：单行 chips 横排，可点 × 移除 */
.context-summary-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: var(--primary-light, #eff6ff);
  border-top: 1px solid #dbeafe;
}

.summary-empty {
  font-size: 12px;
  color: var(--text-muted);
}

.summary-prefix {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  flex-shrink: 0;
}

.summary-chips {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: nowrap;
  overflow-x: auto;
  padding: 2px 0;
}

.summary-clear {
  flex-shrink: 0;
}

/* 搜索栏 + 筛选（固定不动，列表区滚动） */
.context-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border-light, #f0f0f0);
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  min-width: 160px;
}

.filter-select {
  width: 110px;
  flex-shrink: 0;
}

/* 列表区：占满剩余高度，可上下滚动 */
.context-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px 0;
}

.context-section {
  margin-bottom: 20px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 10px;
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary, #4b5563);
}

.section-help {
  font-size: 14px;
  color: var(--text-muted);
  cursor: help;
}

.loading-mini,
.empty-mini {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 12px;
  font-size: 12px;
  color: var(--text-muted);
}

.group-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.context-group {
  border: 1px solid var(--border-light, #f0f0f0);
  border-radius: 8px;
  overflow: hidden;
}

.group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  background: #f9fafb;
  cursor: pointer;
  user-select: none;
}

.group-arrow {
  transition: transform 0.2s;
  font-size: 12px;
  color: var(--text-muted);
}

.group-arrow.expanded {
  transform: rotate(90deg);
}

.group-name {
  flex: 1;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.group-items {
  display: flex;
  flex-direction: column;
}

/* 小类嵌套样式（二级分组，缩进显示层级关系） */
.sub-group {
  border-left: 2px solid var(--border-light, #f0f0f0);
  margin-left: 12px;
}

.sub-group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  cursor: pointer;
  user-select: none;
  background: #fafbfc;
}

.sub-group-header:hover {
  background: #f3f4f6;
}

.sub-arrow {
  font-size: 11px;
}

.sub-group-name {
  flex: 1;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary, #4b5563);
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* 操作记录加载更多按钮区 */
.load-more-tasks {
  display: flex;
  justify-content: center;
  padding: 8px 0 4px;
}

.context-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
  border: 1px solid transparent;
}

.context-item:hover {
  background: #f9fafb;
}

.context-item.selected {
  background: var(--primary-light, #eff6ff);
  border-color: #dbeafe;
}

.context-item .item-info {
  flex: 1;
  min-width: 0;
}

.item-name {
  font-size: 13px;
  color: var(--text-primary);
  margin-bottom: 2px;
  display: flex;
  align-items: center;
  gap: 4px;
}
.item-name-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.item-name .el-tag {
  flex-shrink: 0;
}

.item-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.meta-text {
  font-size: 11px;
  color: var(--text-muted);
}

.preview-btn {
  flex-shrink: 0;
  color: var(--text-muted);
}

.preview-btn:hover {
  color: var(--primary, #4361ee);
}

/* ========== 对话区样式 ========== */

.chat-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 0;
}

.chat-empty {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-muted);
}
.chat-empty .empty-icon { font-size: 48px; margin-bottom: 12px; opacity: 0.5; }
.chat-empty .empty-text { font-size: 16px; margin-bottom: 6px; }
.chat-empty .empty-hint { font-size: 13px; }

.chat-msg {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
  animation: msgSlideIn 0.3s ease;
}
.chat-msg.user { flex-direction: row-reverse; }
.chat-msg.user .msg-content { align-items: flex-end; }

.msg-avatar {
  width: 36px; height: 36px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 20px;
  background: #f3f4f6;
  flex-shrink: 0;
}

.msg-content {
  flex: 1;
  max-width: 80%;
  display: flex;
  flex-direction: column;
}

.msg-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.msg-role { font-size: 12px; font-weight: 600; color: var(--text-secondary); }
.msg-time { font-size: 11px; color: var(--text-muted); }

.msg-body {
  background: #f9fafb;
  border-radius: var(--radius-sm, 6px);
  padding: 14px 18px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-primary);
  word-break: break-word;
}
/* 列表样式：统一缩进和间距 */
.msg-body ul {
  margin: 6px 0;
  padding-left: 22px;
}
.msg-body li {
  margin: 3px 0;
}
.chat-msg.user .msg-body {
  background: var(--primary-light, #eff6ff);
  border: 1px solid #dbeafe;
}

.msg-context-tags {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 6px;
  font-size: 11px;
}

.context-tag-label {
  color: var(--text-muted);
  font-size: 11px;
}

.needs-context-hint {
  margin-top: 8px;
}

.needs-context-list {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 6px;
}

.msg-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 4px;
}

.token-usage {
  font-size: 11px;
  color: var(--text-muted);
}

.thinking-dots {
  display: flex; gap: 4px; padding: 14px 18px;
  background: #f9fafb; border-radius: var(--radius-sm, 6px);
}
.thinking-dots span {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--primary, #4361ee);
  animation: dotBounce 1.4s infinite ease-in-out both;
}
.thinking-dots span:nth-child(1) { animation-delay: -0.32s; }
.thinking-dots span:nth-child(2) { animation-delay: -0.16s; }

/* 快捷命令栏 */
.quick-commands {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 16px 8px;
  border-top: 1px solid var(--border-light, #f0f0f0);
  flex-shrink: 0;
}

/* 追问建议双 Tab */
.followup-tabs {
  display: flex;
  gap: 4px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-light, #f0f0f0);
}

.followup-tab {
  font-size: 12px;
  padding: 4px 12px;
  border: none;
  background: transparent;
  color: var(--text-muted, #909399);
  cursor: pointer;
  border-radius: 4px 4px 0 0;
  position: relative;
  transition: color 0.2s;
}

.followup-tab:hover {
  color: var(--primary, #4361ee);
}

.followup-tab.active {
  color: var(--primary, #4361ee);
  font-weight: 600;
}

.followup-tab.active::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -1px;
  height: 2px;
  background: var(--primary, #4361ee);
  border-radius: 1px;
}

.followup-badge {
  display: inline-block;
  min-width: 16px;
  height: 16px;
  line-height: 16px;
  padding: 0 4px;
  margin-left: 4px;
  font-size: 10px;
  color: #fff;
  background: var(--primary, #4361ee);
  border-radius: 8px;
}

.followup-list {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding-top: 6px;
  min-height: 32px;
}

.followup-empty {
  font-size: 12px;
  color: var(--text-muted, #909399);
}

.quick-label {
  font-size: 12px;
  color: var(--text-muted);
}

.chat-input-area {
  border-top: 1px solid var(--border-light, #f0f0f0);
  padding: 14px 16px 0;
  flex-shrink: 0;
}

.context-badge {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  color: var(--primary, #4361ee);
  margin-bottom: 8px;
  padding: 6px 8px;
  background: var(--primary-light, #eff6ff);
  border-radius: 4px;
}

.context-badge-head {
  display: flex;
  align-items: center;
  gap: 6px;
}

/* 已选项 chips 横排，可换行；每个可单独点 × 取消，避免到上方面板查找 */
.context-badge-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

/* 血缘自动带出操作的标记 */
.context-badge-chips .badge-auto-mark {
  font-weight: 600;
  opacity: 0.85;
}

/* 提示条内的清空按钮：靠右，减少内边距避免过高 */
.context-badge .badge-clear-btn {
  margin-left: auto;
  padding: 2px 6px;
  height: auto;
  min-height: 0;
  font-size: 12px;
}

.chat-input-actions {
  display: flex; align-items: center; justify-content: flex-end;
  gap: 10px; padding: 8px 0;
}
.input-hint { font-size: 11px; color: var(--text-muted); margin-right: auto; }

/* ========== 预览弹窗样式 ========== */

.preview-content {
  max-height: 60vh;
  overflow-y: auto;
}

.preview-text {
  background: #f9fafb;
  border-radius: 8px;
  padding: 14px 16px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'Courier New', Consolas, monospace;
  margin: 0;
}

/* ========== 统计弹窗样式 ========== */

.stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.stat-card {
  background: #f9fafb;
  border-radius: var(--radius-sm, 6px);
  padding: 16px;
  text-align: center;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.stat-label {
  font-size: 12px;
  color: var(--text-muted);
}

.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: var(--text-muted);
}

.loading-container .loading-text {
  margin-top: 12px;
  font-size: 13px;
}

/* 思考中提示样式 */
.thinking-msg {
  opacity: 0.95;
}

.msg-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--primary-color, #4361ee);
  margin-left: 10px;
  font-weight: 500;
}

.msg-status .el-icon.is-loading {
  animation: rotating 1.4s linear infinite;
}

.thinking-content {
  background: linear-gradient(135deg, #f0f7ff 0%, #faf5ff 100%);
  border-left: 3px solid var(--primary-color, #4361ee);
  border-radius: 6px;
  padding: 10px 14px;
  margin-top: 4px;
}

.thinking-text {
  font-size: 13px;
  color: var(--text-secondary, #4b5563);
  margin-bottom: 6px;
  line-height: 1.5;
}

@keyframes rotating {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes msgSlideIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes dotBounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}

/* 历史会话弹窗样式 */
.history-filter {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.history-count {
  font-size: 13px;
  color: var(--text-muted);
}

.conversation-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 500px;
  overflow-y: auto;
  padding-right: 4px;
}

.conversation-card {
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 12px;
  padding: 16px;
  background: var(--bg-white, white);
  cursor: pointer;
  transition: all 0.2s ease;
}

.conversation-card:hover {
  border-color: var(--primary-light, #dbeafe);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  transform: translateY(-1px);
}

.conv-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
}

.conv-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: white;
}

.conv-icon.icon-general_chat {
  background: linear-gradient(135deg, #60a5fa, #3b82f6);
}
.conv-icon.icon-data_cleaning {
  background: linear-gradient(135deg, #34d399, #10b981);
}
.conv-icon.icon-data_mining {
  background: linear-gradient(135deg, #34d399, #10b981);
}
.conv-icon.icon-feature_engineering {
  background: linear-gradient(135deg, #fbbf24, #f59e0b);
}
.conv-icon.icon-machine_learning {
  background: linear-gradient(135deg, #a78bfa, #8b5cf6);
}
.conv-icon.icon-comprehensive {
  background: linear-gradient(135deg, #f87171, #ef4444);
}

.conv-title-wrap {
  flex: 1;
  min-width: 0;
}

.conv-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-sub {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.conv-msg-count {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-muted);
}

.conv-time {
  font-size: 12px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.conv-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--border-light, #f0f0f0);
}

.empty-state {
  text-align: center;
  padding: 40px 20px;
  color: var(--text-muted);
}

.empty-state .empty-text {
  font-size: 14px;
  margin-top: 8px;
  margin-bottom: 4px;
}

.empty-state .empty-hint {
  font-size: 12px;
}

.flex-center {
  display: flex;
  align-items: center;
}

.gap-sm {
  gap: 8px;
}

/* ========== 产品问答模式样式 ========== */

/* 对话区模式切换 Tab */
.mode-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--bg-secondary, #f5f6f8);
  border-radius: 6px;
  padding: 3px;
}
.mode-tab {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: none;
  background: transparent;
  padding: 6px 14px;
  border-radius: 5px;
  font-size: 13px;
  color: var(--text-secondary, #555);
  cursor: pointer;
  transition: all 0.2s;
}
.mode-tab .el-icon {
  vertical-align: -1px;
}
.mode-tab.active {
  background: #fff;
  color: var(--el-color-primary, #409eff);
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

/* 问答模式：常驻目录 + 一键全选工具条 */
.qa-catalog-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0 12px;
  border-bottom: 1px solid var(--border-light, #f0f0f0);
  flex-wrap: wrap;
}
.qa-catalog-select {
  width: 260px;
}
.qa-catalog-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.qa-catalog-name {
  font-size: 13px;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.qa-catalog-count {
  font-size: 12px;
  color: var(--text-muted, #999);
  flex-shrink: 0;
}
.qa-bar-divider {
  width: 1px;
  height: 20px;
  background: var(--border-light, #f0f0f0);
}

/* 保存目录弹窗提示 */
.catalog-count-tip {
  font-size: 13px;
  color: var(--text-secondary, #666);
}

/* 问答精确结果卡片 */
.qa-result-card {
  margin-top: 12px;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  padding: 12px 14px;
  background: #fafcfd;
}
.qa-result-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.qa-result-title {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.qa-result-single {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 6px 0;
}
.qa-result-value {
  font-size: 30px;
  font-weight: 700;
  color: var(--el-color-primary, #409eff);
}
.qa-result-unit {
  font-size: 13px;
  color: var(--text-muted, #999);
}
.qa-result-table {
  width: 100%;
  border-radius: 6px;
  overflow: hidden;
}

/* 预测结果 */
.qa-pred-overview {
  display: flex;
  gap: 24px;
  padding: 4px 0 8px;
  align-items: center;
  flex-wrap: wrap;
}
.qa-pred-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 90px;
}
.qa-pred-label {
  font-size: 12px;
  color: var(--text-muted, #999);
}
.qa-pred-num {
  font-size: 24px;
  font-weight: 700;
  color: var(--el-color-primary, #409eff);
}
.qa-pred-bars {
  flex: 1;
  min-width: 200px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.qa-pred-bar-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.qa-pred-bar-label {
  min-width: 60px;
  color: var(--text-secondary, #666);
  text-align: right;
}
.qa-pred-bar-track {
  flex: 1;
  height: 8px;
  background: var(--bg-secondary, #f0f2f5);
  border-radius: 4px;
  overflow: hidden;
}
.qa-pred-bar-fill {
  height: 100%;
  background: var(--el-color-primary, #409eff);
  border-radius: 4px;
  transition: width 0.3s;
}
.qa-pred-bar-val {
  min-width: 30px;
  color: var(--text-primary);
}
.qa-pred-samples-label {
  font-size: 12px;
  color: var(--text-muted, #999);
  margin: 6px 0 4px;
}
</style>
