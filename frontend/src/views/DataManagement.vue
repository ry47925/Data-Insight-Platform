<template>
  <div class="data-management">
    <!-- 产物类型 Tab 筛选 -->
    <div class="card">
      <el-tabs v-model="activeTab" @tab-change="onTabChange" aria-label="产物类型筛选">
        <el-tab-pane label="原始数据" name="raw_data" />
        <el-tab-pane label="数据分析报告" name="analysis_report" />
        <el-tab-pane label="数据清洗产物" name="cleaning_result" />
        <el-tab-pane label="数据挖掘产物" name="mining_result" />
        <el-tab-pane label="特征工程产物" name="feature_result" />
        <el-tab-pane label="机器学习产物" name="ml_report" />
        <el-tab-pane label="机器学习预测数据" name="predict_data" />
        <el-tab-pane label="回收站" name="trash" />
      </el-tabs>
    </div>

    <!-- 来源模块筛选（仅原始数据显示） -->
    <div v-if="activeTab === 'raw_data'" class="card">
      <div class="card-header">
        <span class="card-title" style="margin-bottom:0"> 来源模块筛选</span>
      </div>
      <el-radio-group v-model="sourceFilter" @change="onSourceFilterChange" size="small">
        <el-radio-button value="">全部来源</el-radio-button>
        <el-radio-button value="data_analysis">数据分析原始数据</el-radio-button>
        <el-radio-button value="cleaning">数据清洗原始数据</el-radio-button>
        <el-radio-button value="data_mining">数据挖掘原始数据</el-radio-button>
        <el-radio-button value="feature_engineering">特征工程原始数据</el-radio-button>
        <el-radio-button value="ml">机器学习原始数据</el-radio-button>
      </el-radio-group>
    </div>

    <!-- 数据挖掘产物分类筛选（仅数据挖掘Tab显示） -->
    <div v-if="activeTab === 'mining_result'" class="card">
      <div class="card-header">
        <span class="card-title" style="margin-bottom:0">产物类型筛选</span>
      </div>
      <el-radio-group v-model="miningTypeFilter" @change="() => loadDatasets()" size="small">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button value="cluster_result">聚类结果</el-radio-button>
        <el-radio-button value="association_rules">关联规则</el-radio-button>
        <el-radio-button value="sequential_patterns">序列模式</el-radio-button>
      </el-radio-group>
    </div>

    <!-- 预测数据分类筛选（仅预测数据显示） -->
    <div v-if="activeTab === 'predict_data'" class="card">
      <div class="card-header">
        <span class="card-title" style="margin-bottom:0"> 产物类型筛选</span>
      </div>
      <el-radio-group v-model="predictTypeFilter" @change="() => loadDatasets()" size="small">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button value="predict_data">用户上传的预测文件</el-radio-button>
        <el-radio-button value="ml_prediction">批量预测结果</el-radio-button>
      </el-radio-group>
    </div>

    <!-- 数据导入模块（原始数据、数据挖掘、清洗结果、特征工程产物显示） -->
    <div v-if="activeTab === 'raw_data' || activeTab === 'mining_result' || activeTab === 'cleaning_result' || activeTab === 'feature_result'" class="card">
      <div class="card-header">
        <span class="card-title" style="margin-bottom:0"> 数据导入</span>
      </div>
      <div class="flex-center gap-sm">
        <el-select v-model="importSourceId" placeholder="选择要导入的数据" style="width: 300px;" aria-label="选择要导入的数据">
          <!-- :label 用于折叠态显示名称；展开列表用自定义 slot 展示色点/名称/#id/时间/行数 -->
          <el-option v-for="ds in importSourceOptions" :key="ds.id" :value="ds.id" :label="ds.name">
            <div class="ds-option">
              <span class="ds-dot" :style="{ background: getDatasetColor(ds) }"></span>
              <span class="ds-name">{{ ds.name }}</span>
              <span class="ds-meta">{{ ds.id != null ? `#${ds.id}` : '' }} · {{ formatDsTime(ds.created_at) }} · {{ ds.row_count ? ds.row_count.toLocaleString() : '?' }} 行</span>
            </div>
          </el-option>
        </el-select>
        <el-select v-model="importTargetModule" placeholder="选择目标模块" style="width: 200px;" aria-label="选择目标模块">
          <el-option value="data_analysis" label="数据分析" />
          <el-option value="cleaning" label="数据清洗" />
          <el-option value="data_mining" label="数据挖掘" />
          <el-option value="feature_engineering" label="特征工程" />
          <el-option value="ml" label="机器学习" />
          <el-option value="ai" label="AI分析" />
        </el-select>
        <el-button type="primary" @click="doImport" :disabled="!importSourceId || !importTargetModule" :loading="importLoading">
          <el-icon><Share /></el-icon>
          导入
        </el-button>
      </div>
      <div v-if="importSourceOptions.length === 0" class="empty-hint" style="margin-top:10px;color:var(--text-muted);">
        <span>暂无可导入的数据，请先上传或筛选数据</span>
      </div>
    </div>

    <!-- 数据集表格 -->
    <div class="card">
      <div class="card-header">
        <span class="card-title" style="margin-bottom:0">产物列表</span>
        <div style="display: flex; align-items: center; gap: 8px;">
          <el-input
            v-model="searchKeyword"
            :placeholder="getSearchPlaceholder()"
            size="small"
            style="width: 200px;"
            clearable
            @keyup.enter="onSearch"
          />
          <el-button size="small" @click="() => loadDatasets(true)" :loading="loading">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </div>

      <!-- 加载中 -->
      <div v-if="loading && datasets.length === 0" class="loading-container">
        <el-icon class="is-loading" :size="32"><Loading /></el-icon>
        <div class="loading-text">正在加载数据集…</div>
      </div>

      <!-- 空状态 -->
      <div v-else-if="!loading && datasets.length === 0" class="empty-state">
        <el-icon class="empty-icon" :size="48"><FolderDelete /></el-icon>
        <div class="empty-text">暂无产物</div>
        <div class="empty-hint">请在各功能模块中上传数据，产物将自动汇总到此处</div>
      </div>

      <!-- 数据表格 -->
      <el-table
        v-else
        :data="pagedDatasets"
        border stripe
        style="width: 100%;"
        :default-sort="{ prop: 'created_at', order: 'descending' }"
        @sort-change="onSortChange"
        @selection-change="handleSelectionChange"
      >
        <!-- 多选列 -->
        <el-table-column type="selection" width="55" align="center" />
        <!-- 数据集ID列，便于与操作历史交叉引用 -->
        <el-table-column label="#" prop="id" width="70" align="center" />

        <!-- 名称（含模块来源图标） -->
        <el-table-column label="名称" min-width="220" show-overflow-tooltip sortable="custom" prop="name">
          <template #default="{ row }">
            <div class="name-cell">
              <div style="display: flex; align-items: center;">
                <!-- 数据集色点：同名数据集靠颜色区分（按 id 派生，任何页面同色） -->
                <span class="ds-dot" :style="{ background: getDatasetColor(row) }"></span>
                <el-icon class="module-icon"><component :is="getArtifactIconName(row.artifact_type)" /></el-icon>
                <span>{{ getDisplayName(row) }}</span>
                <el-tag v-if="row.status === 'corrupted'" type="danger" size="small" effect="dark" style="margin-left: 8px;">
                  已损坏
                </el-tag>
              </div>
            </div>
          </template>
        </el-table-column>

        <!-- 产物类型（标签） -->
        <el-table-column label="产物类型" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="getArtifactTagType(row.artifact_type)" size="small" effect="plain">
              {{ getArtifactLabel(row.artifact_type) }}
            </el-tag>
          </template>
        </el-table-column>

        <!-- 来源模块 -->
        <el-table-column label="来源模块" width="110" align="center">
          <template #default="{ row }">
            <span class="module-source">
              <el-icon v-if="getModuleIconName(row.module_source)"><component :is="getModuleIconName(row.module_source)" /></el-icon>
              {{ getModuleLabel(row.module_source) }}
            </span>
          </template>
        </el-table-column>

        <!-- 方法/算法 -->
        <el-table-column label="方法/算法" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <div v-if="row.artifact_type === 'ml_prediction'">
              <el-tooltip
                :content="row.algorithm || '-'"
                placement="top"
                effect="dark"
                :show-after="200"
              >
                <div class="algo-cell">
                  <el-tag type="info" size="small" effect="plain" class="algo-tag">
                    {{ extractAlgorithmName(row.algorithm) }}
                  </el-tag>
                  <el-tag type="warning" size="small" effect="plain" class="algo-tag">
                    预测原始数据: {{ extractPredictSource(row.algorithm) }}
                  </el-tag>
                </div>
              </el-tooltip>
            </div>
            <span v-else>{{ getAlgorithmLabel(row.algorithm) }}</span>
          </template>
        </el-table-column>

        <!-- 标签（独立列，过滤内部元数据 JSON） -->
        <el-table-column label="标签" width="150" show-overflow-tooltip>
          <template #default="{ row }">
            <div v-if="parseDisplayTags(row.tags).length" class="tags-cell">
              <el-tag
                v-for="(tag, idx) in parseDisplayTags(row.tags)"
                :key="idx"
                size="small"
                effect="plain"
                style="margin-right: 4px; margin-bottom: 2px;"
              >
                {{ tag }}
              </el-tag>
            </div>
            <span v-else style="color: var(--text-muted);">-</span>
          </template>
        </el-table-column>

        <!-- 备注（独立列） -->
        <el-table-column label="备注" width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.remarks">{{ row.remarks }}</span>
            <span v-else style="color: var(--text-muted);">-</span>
          </template>
        </el-table-column>

        <!-- 大小 -->
        <el-table-column label="大小" width="100" align="right">
          <template #default="{ row }">
            <el-tooltip content="文件大小" placement="top" effect="dark">
              <span>{{ formatSize(row.file_size) }}</span>
            </el-tooltip>
          </template>
        </el-table-column>

        <!-- 时间 -->
        <el-table-column label="时间" width="170" align="center" sortable="custom">
          <template #default="{ row }">
            {{ formatTime(activeTab === 'trash' ? (row.deleted_at || row.created_at) : row.created_at) }}
          </template>
        </el-table-column>

        <!-- 操作（回收站模式） -->
        <el-table-column v-if="activeTab === 'trash'" label="操作" width="200" align="center" fixed="right">
          <template #default="{ row }">
            <el-button type="success" size="small" link @click="confirmRestore(row)" aria-label="恢复">
              <el-icon><Refresh /></el-icon>恢复
            </el-button>
            <el-button type="danger" size="small" link @click="confirmPermanentDelete(row)" aria-label="永久删除">
              <el-icon><Delete /></el-icon>永久删除
            </el-button>
          </template>
        </el-table-column>

        <!-- 操作（正常模式，根据 artifact_type 不同） -->
        <el-table-column v-else label="操作" min-width="340" align="center" fixed="right">
          <template #default="{ row }">
            <!-- corrupted: 仅显示删除记录（文件已损坏，直接物理删除） -->
            <template v-if="row.status === 'corrupted'">
              <el-button type="danger" size="small" link @click="confirmDelete(row)" aria-label="删除记录">
                <el-icon><Delete /></el-icon>删除记录
              </el-button>
            </template>
            <!-- 正常文件：根据 artifact_type 显示不同操作 -->
            <template v-else>
              <!-- raw_data / analysis_data: 预览 | 下载 | 血缘 | 编辑 | 删除 -->
              <template v-if="row.artifact_type === 'raw_data' || row.artifact_type === 'analysis_data'">
                <el-button type="primary" size="small" link @click="openPreview(row)" aria-label="预览数据">
                  <el-icon><View /></el-icon>预览
                </el-button>
                <el-button type="success" size="small" link @click="handleExport(row, 'csv')" aria-label="下载数据">
                  <el-icon><Download /></el-icon>下载
                </el-button>
                <el-button type="info" size="small" link @click="openLineage(row)" aria-label="查看数据血缘">
                  <el-icon><Share /></el-icon>血缘
                </el-button>
                <el-button type="warning" size="small" link @click="openEditMeta(row)" aria-label="编辑名称">
                  <el-icon><Edit /></el-icon>编辑
                </el-button>
                <el-button type="danger" size="small" link @click="confirmDelete(row)" aria-label="删除">
                  <el-icon><Delete /></el-icon>删除
                </el-button>
              </template>

              <!-- cleaning_result: 预览 | 下载 | 血缘 | 编辑 | 删除 -->
              <template v-else-if="row.artifact_type === 'cleaning_result'">
                <el-button type="primary" size="small" link @click="openPreview(row)" aria-label="预览清洗结果">
                  <el-icon><View /></el-icon>预览
                </el-button>
                <el-button type="success" size="small" link @click="handleExport(row, 'csv')" aria-label="下载清洗结果">
                  <el-icon><Download /></el-icon>下载
                </el-button>
                <el-button type="info" size="small" link @click="openLineage(row)" aria-label="查看数据血缘">
                  <el-icon><Share /></el-icon>血缘
                </el-button>
                <el-button type="warning" size="small" link @click="openEditMeta(row)" aria-label="编辑名称">
                  <el-icon><Edit /></el-icon>编辑
                </el-button>
                <el-button type="danger" size="small" link @click="confirmDelete(row)" aria-label="删除">
                  <el-icon><Delete /></el-icon>删除
                </el-button>
              </template>

              <!-- ml_report: 查看报告 | 导出PDF | 血缘 | 编辑 | 删除 -->
              <template v-else-if="row.artifact_type === 'ml_report'">
                <el-button type="primary" size="small" link @click="openReportView(row)" aria-label="查看模型报告">
                  <el-icon><Document /></el-icon>查看报告
                </el-button>
                <el-button type="success" size="small" link @click="handleExport(row, 'pdf')" aria-label="导出PDF">
                  <el-icon><Download /></el-icon>导出PDF
                </el-button>
                <el-button type="info" size="small" link @click="openLineage(row)" aria-label="查看数据血缘">
                  <el-icon><Share /></el-icon>血缘
                </el-button>
                <el-button type="warning" size="small" link @click="openEditMeta(row)" aria-label="编辑名称">
                  <el-icon><Edit /></el-icon>编辑
                </el-button>
                <el-button type="danger" size="small" link @click="confirmDelete(row)" aria-label="删除">
                  <el-icon><Delete /></el-icon>删除
                </el-button>
              </template>

              <!-- ml_model: 查看报告 | 导出模型 | 导出报告PDF | 血缘 | 编辑 | 删除 -->
              <template v-else-if="row.artifact_type === 'ml_model'">
                <el-button type="primary" size="small" link @click="openReportView(row)" aria-label="查看模型报告">
                  <el-icon><Document /></el-icon>查看报告
                </el-button>
                <el-button type="success" size="small" link @click="handleMLModelExport(row, 'model')" aria-label="导出模型">
                  <el-icon><Download /></el-icon>导出模型
                </el-button>
                <el-button type="info" size="small" link @click="handleExport(row, 'pdf')" aria-label="导出报告PDF">
                  <el-icon><Download /></el-icon>导出报告
                </el-button>
                <el-button type="warning" size="small" link @click="openLineage(row)" aria-label="查看数据血缘">
                  <el-icon><Share /></el-icon>血缘
                </el-button>
                <el-button type="warning" size="small" link @click="openEditMeta(row)" aria-label="编辑名称">
                  <el-icon><Edit /></el-icon>编辑
                </el-button>
                <el-button type="danger" size="small" link @click="confirmDelete(row)" aria-label="删除">
                  <el-icon><Delete /></el-icon>删除
                </el-button>
              </template>

              <!-- 数据分析报告操作 -->
              <template v-else-if="row.artifact_type === 'analysis_report'">
                <el-button type="primary" size="small" link @click="openPreview(row)" aria-label="预览报告">
                  <el-icon><View /></el-icon>预览报告
                </el-button>
                <el-button type="success" size="small" link @click="handleReportExport(row)" aria-label="下载报告">
                  <el-icon><Download /></el-icon>下载
                </el-button>
                <el-button type="info" size="small" link @click="openLineage(row)" aria-label="查看数据血缘">
                  <el-icon><Share /></el-icon>血缘
                </el-button>
                <el-button type="warning" size="small" link @click="openEditMeta(row)" aria-label="编辑名称">
                  <el-icon><Edit /></el-icon>编辑
                </el-button>
                <el-button type="danger" size="small" link @click="confirmDelete(row)" aria-label="删除">
                  <el-icon><Delete /></el-icon>删除
                </el-button>
              </template>

              <!-- 数据挖掘产物：聚类/关联规则/序列模式 -->
              <template v-else-if="row.artifact_type === 'cluster_result' || row.artifact_type === 'association_rules' || row.artifact_type === 'sequential_patterns'">
                <el-button type="primary" size="small" link @click="openPreview(row)" aria-label="预览结果">
                  <el-icon><View /></el-icon>预览
                </el-button>
                <el-button type="success" size="small" link @click="handleExport(row, 'csv')" aria-label="下载结果">
                  <el-icon><Download /></el-icon>下载
                </el-button>
                <el-button type="info" size="small" link @click="openLineage(row)" aria-label="查看数据血缘">
                  <el-icon><Share /></el-icon>血缘
                </el-button>
                <el-button type="warning" size="small" link @click="openEditMeta(row)" aria-label="编辑名称">
                  <el-icon><Edit /></el-icon>编辑
                </el-button>
                <el-button type="danger" size="small" link @click="confirmDelete(row)" aria-label="删除">
                  <el-icon><Delete /></el-icon>删除
                </el-button>
              </template>

              <!-- 特征工程产物 -->
              <template v-else-if="row.artifact_type === 'feature_result'">
                <el-button type="primary" size="small" link @click="openPreview(row)" aria-label="预览结果">
                  <el-icon><View /></el-icon>预览
                </el-button>
                <el-button type="success" size="small" link @click="handleExport(row, 'csv')" aria-label="下载结果">
                  <el-icon><Download /></el-icon>下载
                </el-button>
                <el-button type="info" size="small" link @click="openLineage(row)" aria-label="查看数据血缘">
                  <el-icon><Share /></el-icon>血缘
                </el-button>
                <el-button type="warning" size="small" link @click="openEditMeta(row)" aria-label="编辑名称">
                  <el-icon><Edit /></el-icon>编辑
                </el-button>
                <el-button type="danger" size="small" link @click="confirmDelete(row)" aria-label="删除">
                  <el-icon><Delete /></el-icon>删除
                </el-button>
              </template>

              <!-- 机器学习预测数据 -->
              <template v-else-if="row.artifact_type === 'ml_prediction'">
                <el-button type="primary" size="small" link @click="openPreview(row)" aria-label="预览预测结果">
                  <el-icon><View /></el-icon>预览
                </el-button>
                <el-button type="success" size="small" link @click="handleExport(row, 'csv')" aria-label="下载预测结果">
                  <el-icon><Download /></el-icon>下载
                </el-button>
                <el-button type="info" size="small" link @click="openLineage(row)" aria-label="查看数据血缘">
                  <el-icon><Share /></el-icon>血缘
                </el-button>
                <el-button type="warning" size="small" link @click="openEditMeta(row)" aria-label="编辑名称">
                  <el-icon><Edit /></el-icon>编辑
                </el-button>
                <el-button type="danger" size="small" link @click="confirmDelete(row)" aria-label="删除">
                  <el-icon><Delete /></el-icon>删除
                </el-button>
              </template>

              <!-- 默认操作 -->
              <template v-else>
                <el-button type="primary" size="small" link @click="openPreview(row)" aria-label="预览">
                  <el-icon><View /></el-icon>预览
                </el-button>
                <el-button type="success" size="small" link @click="handleExport(row, 'csv')" aria-label="下载">
                  <el-icon><Download /></el-icon>下载
                </el-button>
                <el-button type="info" size="small" link @click="openLineage(row)" aria-label="查看数据血缘">
                  <el-icon><Share /></el-icon>血缘
                </el-button>
                <el-button type="warning" size="small" link @click="openEditMeta(row)" aria-label="编辑名称">
                  <el-icon><Edit /></el-icon>编辑
                </el-button>
                <el-button type="danger" size="small" link @click="confirmDelete(row)" aria-label="删除">
                  <el-icon><Delete /></el-icon>删除
                </el-button>
              </template>
            </template>
            <!-- 历史：跳转到操作历史并按数据集筛选 -->
            <el-button size="small" link @click="goToTaskHistory(row.id)" aria-label="查看操作历史">
              <el-icon><Clock /></el-icon>历史
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页与批量操作 -->
      <div v-if="datasets.length > 0" class="flex-between mt-md">
        <div class="batch-actions">
          <span class="text-sm">共 {{ datasets.length }} 条记录</span>
          <span v-if="selectedRows.length > 0" class="selected-hint">已选 {{ selectedRows.length }} 项</span>
          <template v-if="activeTab === 'trash'">
            <el-button
              v-if="selectedRows.length > 0"
              type="success" size="small"
              @click="batchRestore"
              :loading="restoreLoading"
            >
              <el-icon><Refresh /></el-icon> 批量恢复 ({{ selectedRows.length }})
            </el-button>
            <el-button
              type="danger" size="small"
              @click="confirmClearTrash"
            >
              <el-icon><Delete /></el-icon> 清空回收站
            </el-button>
          </template>
          <el-button
            v-else-if="selectedRows.length > 0"
            type="danger" size="small"
            @click="batchDelete"
            :loading="deleteLoading"
          >
            <el-icon><Delete /></el-icon> 批量删除 ({{ selectedRows.length }})
          </el-button>
        </div>
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="datasets.length"
          layout="sizes, prev, pager, next, jumper"
          small
          background
          aria-label="产物分页"
        />
      </div>
    </div>

    <!-- 数据预览弹窗 -->
    <el-dialog
      v-model="previewVisible"
      :title="`数据预览 — ${previewDataset?.name || ''}`"
      width="80%"
      top="5vh"
      destroy-on-close
      aria-label="数据预览弹窗"
    >
      <div v-if="previewLoading" class="loading-container">
        <el-icon class="is-loading" :size="32"><Loading /></el-icon>
        <div class="loading-text">正在加载数据…</div>
      </div>
      <!-- 数据分析报告预览 - 使用 iframe 隔离避免样式污染 -->
      <iframe v-else-if="previewDataset?.artifact_type === 'analysis_report'" :src="reportPreviewUrl" class="report-preview-iframe"></iframe>
      <!-- 关联规则预览 -->
      <div v-else-if="previewDataset?.artifact_type === 'association_rules'" class="data-table-wrapper">
        <div class="association-stats mb-md">
          <el-tag type="info" effect="plain">规则总数: {{ previewTotal }}</el-tag>
          <el-tag type="success" effect="plain" style="margin-left: 8px;">最小支持度: {{ associationParams?.min_support ?? '-' }}</el-tag>
          <el-tag type="warning" effect="plain" style="margin-left: 8px;">最小置信度: {{ associationParams?.min_confidence ?? '-' }}</el-tag>
        </div>
        <div v-if="associationRules.length > 0">
          <el-table :data="associationRules" border stripe height="400" style="width: 100%;">
            <el-table-column type="index" label="序号" width="60" align="center" />
            <el-table-column prop="antecedent" label="前项 (Antecedent)" min-width="150" show-overflow-tooltip>
              <template #default="{ row }">
                <el-tag v-for="(item, idx) in (Array.isArray(row.antecedent) ? row.antecedent : [row.antecedent])" :key="idx" size="small" type="primary" effect="plain" style="margin: 2px;">
                  {{ item }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="consequent" label="后项 (Consequent)" min-width="150" show-overflow-tooltip>
              <template #default="{ row }">
                <el-tag v-for="(item, idx) in (Array.isArray(row.consequent) ? row.consequent : [row.consequent])" :key="idx" size="small" type="success" effect="plain" style="margin: 2px;">
                  {{ item }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="support" label="支持度 (Support)" width="120" align="center" sortable>
              <template #default="{ row }">
                {{ row.support !== undefined ? (row.support * 100).toFixed(2) + '%' : '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="confidence" label="置信度 (Confidence)" width="120" align="center" sortable>
              <template #default="{ row }">
                {{ row.confidence !== undefined ? (row.confidence * 100).toFixed(2) + '%' : '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="lift" label="提升度 (Lift)" width="120" align="center" sortable>
              <template #default="{ row }">
                {{ row.lift !== undefined ? row.lift.toFixed(4) : '-' }}
              </template>
            </el-table-column>
          </el-table>
          <div style="margin-top: 12px; display: flex; justify-content: flex-end;">
            <el-pagination
              v-model:current-page="previewPage"
              v-model:page-size="previewPageSize"
              :page-sizes="[10, 20, 50, 100]"
              :total="previewTotal"
              layout="sizes, prev, pager, next, jumper"
              small
              background
              @current-change="handleAssociationPageChange"
              @size-change="handleAssociationSizeChange"
            />
          </div>
        </div>
        <div v-else class="empty-state" style="padding: 60px 0;">
          <el-icon class="empty-icon" :size="48"><InfoFilled /></el-icon>
          <div class="empty-text">未找到满足条件的关联规则</div>
          <div class="empty-hint" style="margin-top: 8px;">建议降低最小支持度或最小置信度后重新分析</div>
        </div>
      </div>
      <!-- 序列模式预览 -->
      <div v-else-if="previewDataset?.artifact_type === 'sequential_patterns'" class="data-table-wrapper">
        <div class="association-stats mb-md">
          <el-tag type="info" effect="plain">模式总数: {{ previewTotal }}</el-tag>
          <el-tag type="success" effect="plain" style="margin-left: 8px;">最小支持度: {{ sequenceParams?.min_support ?? '-' }}</el-tag>
          <el-tag type="warning" effect="plain" style="margin-left: 8px;">算法: {{ sequenceParams?.algorithm ?? '-' }}</el-tag>
        </div>
        <div v-if="sequencePatterns.length > 0">
          <el-table :data="sequencePatterns" border stripe height="400" style="width: 100%;">
            <el-table-column type="index" label="序号" width="60" align="center" />
            <el-table-column prop="sequence" label="序列" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <el-tag v-for="(item, idx) in (Array.isArray(row.sequence) ? row.sequence : [row.sequence])" :key="idx" size="small" type="info" effect="plain" style="margin: 2px;">
                  {{ item }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="support" label="支持度 (Support)" width="140" align="center" sortable>
              <template #default="{ row }">
                {{ row.support !== undefined ? (row.support * 100).toFixed(2) + '%' : '-' }}
              </template>
            </el-table-column>
            <el-table-column prop="length" label="序列长度" width="100" align="center" sortable>
              <template #default="{ row }">
                {{ row.sequence !== undefined ? (Array.isArray(row.sequence) ? row.sequence.length : 1) : '-' }}
              </template>
            </el-table-column>
          </el-table>
          <div style="margin-top: 12px; display: flex; justify-content: flex-end;">
            <el-pagination
              v-model:current-page="previewPage"
              v-model:page-size="previewPageSize"
              :page-sizes="[10, 20, 50, 100]"
              :total="previewTotal"
              layout="sizes, prev, pager, next, jumper"
              small
              background
              @current-change="handlePreviewPageChange"
              @size-change="handlePreviewSizeChange"
            />
          </div>
        </div>
        <div v-else class="empty-state" style="padding: 60px 0;">
          <el-icon class="empty-icon" :size="48"><InfoFilled /></el-icon>
          <div class="empty-text">未找到满足条件的序列模式</div>
          <div class="empty-hint" style="margin-top: 8px;">建议降低最小支持度后重新分析</div>
        </div>
      </div>
      <!-- 普通数据预览 -->
      <div v-else-if="previewColumns.length > 0" class="data-table-wrapper">
        <el-table :data="previewData" border stripe height="400" style="width: 100%;">
          <el-table-column
            v-for="col in previewColumns"
            :key="col"
            :prop="col"
            :label="col"
            :min-width="120"
            show-overflow-tooltip
          />
        </el-table>
        <div style="margin-top: 12px; display: flex; justify-content: flex-end;">
          <el-pagination
            v-model:current-page="previewPage"
            v-model:page-size="previewPageSize"
            :page-sizes="[10, 20, 50, 100]"
            :total="previewTotal"
            layout="sizes, prev, pager, next, jumper"
            small
            background
            @current-change="handlePreviewPageChange"
            @size-change="handlePreviewSizeChange"
          />
        </div>
      </div>
      <div v-else class="empty-state">
        <el-icon class="empty-icon" :size="48"><Warning /></el-icon>
        <div class="empty-text">无法加载数据预览</div>
      </div>
    </el-dialog>

    <!-- 报告查看弹窗（ml_report / ai_report） -->
    <el-dialog
      v-model="reportVisible"
      :title="`报告详情 — ${reportTarget?.name || ''}`"
      width="70%"
      top="5vh"
      destroy-on-close
      aria-label="报告查看弹窗"
    >
      <div v-if="reportLoading" class="loading-container">
        <el-icon class="is-loading" :size="32"><Loading /></el-icon>
        <div class="loading-text">正在加载报告…</div>
      </div>
      <div v-else-if="reportContent" class="report-content" v-html="renderMarkdown(reportContent)"></div>
      <div v-else class="empty-state">
        <el-icon class="empty-icon" :size="48"><Warning /></el-icon>
        <div class="empty-text">无法加载报告内容</div>
      </div>
    </el-dialog>

    <!-- 编辑元数据弹窗 -->
    <el-dialog
      v-model="editVisible"
      title="编辑元数据"
      width="500px"
      destroy-on-close
      aria-label="编辑元数据弹窗"
    >
      <el-form :model="editForm" label-width="80px" aria-label="元数据编辑表单">
        <el-form-item label="数据集名称">
          <el-input v-model="editForm.name" placeholder="请输入名称（不含扩展名）" aria-label="名称" />
        </el-form-item>
        <div v-if="editExtension" style="font-size: 12px; color: var(--text-muted); margin-top: -8px; padding-left: 80px;">
          扩展名 .{{ editExtension }} 不可修改，仅修改名称部分
        </div>
        <el-form-item label="标签">
          <el-input v-model="editForm.tags" placeholder="多个标签用英文逗号分隔，例：销售,2025Q3,核心" aria-label="标签" />
          <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
            提示：多个标签用英文逗号分隔，标签允许重名。
          </div>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editForm.remarks" type="textarea" :rows="3" placeholder="例：用于Q3季度汇报的销售数据" maxlength="200" show-word-limit aria-label="备注" />
          <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
            最多 200 字
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false" aria-label="取消编辑">取消</el-button>
        <el-button type="primary" @click="saveEditMeta" :loading="editLoading" aria-label="保存">
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- 删除确认弹窗 -->
    <el-dialog
      v-model="deleteVisible"
      title="删除确认"
      width="460px"
      aria-label="删除确认弹窗"
    >
      <div style="text-align:center; padding: 20px 0;">
        <el-icon :size="64" style="color: var(--warning); margin-bottom: 16px;"><Warning /></el-icon>
        <p style="font-size: 16px; color: var(--text-primary); margin-bottom: 8px;">
          确定要删除 <strong>{{ deleteTarget?.name }}</strong>（{{ deleteTarget?.id != null ? `#${deleteTarget.id}` : '' }}）吗？
        </p>
        <p v-if="deleteTarget?.id != null" style="font-size: 13px; color: var(--text-secondary); margin-top: 4px;">
          数据集 #{{ deleteTarget.id }} · 创建于 {{ formatDsTime(deleteTarget.created_at) }}
        </p>
        <p v-if="deleteTarget?.status === 'corrupted'" style="font-size: 13px; color: var(--text-secondary);">
          文件已损坏，此操作将直接删除数据库记录，不可恢复
        </p>
        <p v-else style="font-size: 13px; color: var(--text-secondary);">
          文件将移到回收站，可在回收站中恢复
        </p>
      </div>
      <template #footer>
        <el-button @click="deleteVisible = false" aria-label="取消删除">取消</el-button>
        <el-button type="danger" @click="executeDelete" :loading="deleteLoading" aria-label="确认删除">
          {{ deleteTarget?.status === 'corrupted' ? '删除记录' : '移到回收站' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 数据血缘弹窗 -->
    <el-dialog
      v-model="lineageVisible"
      :title="`数据血缘 — ${lineageTarget?.name || ''}`"
      width="70%"
      top="5vh"
      destroy-on-close
      aria-label="数据血缘弹窗"
    >
      <div v-if="lineageLoading" class="loading-container">
        <el-icon class="is-loading" :size="32"><Loading /></el-icon>
        <div class="loading-text">正在加载数据血缘…</div>
      </div>
      <div v-else-if="lineageData.self" class="lineage-content">
        <div class="lineage-current">
          <el-icon :size="24" style="color: #f59e0b;"><Folder /></el-icon>
          <span class="lineage-current-name">{{ lineageData.self.name }}</span>
          <el-tag v-if="lineageData.self.id != null" size="small" type="info" effect="plain" style="margin-left: 4px;">#{{ lineageData.self.id }}</el-tag>
          <el-tag size="small" effect="plain">{{ getModuleLabel(lineageData.self.module_source) }}</el-tag>
        </div>
        
        <!-- 远程数据库虚拟根节点：当数据来源于远程数据库时显示在最顶部 -->
        <div v-if="lineageData.root_source" class="lineage-section">
          <div class="lineage-section-title">远程数据源</div>
          <div class="lineage-tree">
            <div class="lineage-node">
              <div class="lineage-line lineage-dashed"></div>
              <div class="lineage-node-content lineage-virtual-node">
                <el-icon :size="16" style="color:#e6a23c;"><Coin /></el-icon>
                <span>{{ lineageData.root_source.name }}</span>
                <el-tag size="small" type="warning" effect="plain" style="margin-left: 4px;">远程数据库</el-tag>
                <el-tooltip placement="top" effect="dark">
                  <template #content>
                    <div style="max-width:280px;line-height:1.6;">
                      主机:{{ lineageData.root_source.host }}:{{ lineageData.root_source.port }}<br/>
                      数据库:{{ lineageData.root_source.database }}<br/>
                      表:{{ lineageData.root_source.table_name || '-' }}
                    </div>
                  </template>
                  <el-icon style="margin-left:4px;cursor:help;color:#909399;font-size:14px;"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
            </div>
          </div>
        </div>

        <div v-if="lineageData.ancestors.length > 0" class="lineage-section">
          <div class="lineage-section-title">上游（{{ lineageData.ancestors.length }} 个产物）</div>
          <div class="lineage-tree">
            <div v-for="(ancestor, idx) in lineageData.ancestors" :key="ancestor.id" class="lineage-node">
              <div :class="['lineage-line', { 'lineage-dashed': ancestor.is_import }]"></div>
              <div class="lineage-node-content">
                <el-icon :size="16"><Folder /></el-icon>
                <span>{{ ancestor.name }}</span>
                <el-tag v-if="ancestor.id != null" size="small" type="info" effect="plain" style="margin-left: 4px;">#{{ ancestor.id }}</el-tag>
                <el-tag size="small" effect="plain" style="margin-left: 4px;">{{ getModuleLabel(ancestor.module_source) }}</el-tag>
                <span v-if="ancestor.is_import" class="import-badge">导入</span>
              </div>
            </div>
          </div>
        </div>

        <div v-if="lineageData.descendants.length > 0" class="lineage-section">
          <div class="lineage-section-title">下游（{{ lineageData.descendants.length }} 个产物）</div>
          <div class="lineage-tree">
            <div v-for="(descendant, idx) in lineageData.descendants" :key="descendant.id" class="lineage-node">
              <div :class="['lineage-line', { 'lineage-dashed': descendant.is_import }]"></div>
              <div class="lineage-node-content">
                <el-icon :size="16"><component :is="getArtifactIconName(descendant.artifact_type)" /></el-icon>
                <span>{{ descendant.name }}</span>
                <el-tag v-if="descendant.id != null" size="small" type="info" effect="plain" style="margin-left: 4px;">#{{ descendant.id }}</el-tag>
                <el-tag size="small" effect="plain" style="margin-left: 4px;">{{ getModuleLabel(descendant.module_source) }}</el-tag>
                <span v-if="descendant.is_import" class="import-badge">导入</span>
              </div>
            </div>
          </div>
        </div>

        <div v-if="lineageData.ancestors.length === 0 && lineageData.descendants.length === 0" class="empty-state" style="padding: 40px 0;">
          <el-icon class="empty-icon" :size="48"><InfoFilled /></el-icon>
          <div class="empty-text">暂无数据血缘关系</div>
          <div class="empty-hint">该数据集没有上游来源或下游产物</div>
        </div>

        <div class="lineage-legend">
          <div class="legend-item">
            <div class="legend-line"></div>
            <span>实线：同模块内部产物生成关系</span>
          </div>
          <div class="legend-item">
            <div class="legend-line legend-dashed"></div>
            <span>虚线：跨模块生成的副本关系</span>
          </div>
        </div>
      </div>
      <div v-else class="empty-state">
        <el-icon class="empty-icon" :size="48"><Warning /></el-icon>
        <div class="empty-text">无法加载数据血缘</div>
      </div>
    </el-dialog>

    <!-- 恢复确认弹窗 -->
    <el-dialog
      v-model="restoreVisible"
      title="恢复确认"
      width="460px"
      aria-label="恢复确认弹窗"
    >
      <div style="text-align:center; padding: 20px 0;">
        <el-icon :size="64" style="color: var(--success); margin-bottom: 16px;"><Refresh /></el-icon>
        <p style="font-size: 16px; color: var(--text-primary); margin-bottom: 8px;">
          确定要恢复 <strong>{{ restoreTarget?.name }}</strong>（{{ restoreTarget?.id != null ? `#${restoreTarget.id}` : '' }}）吗？
        </p>
        <p v-if="restoreTarget?.id != null" style="font-size: 13px; color: var(--text-secondary); margin-top: 4px;">
          数据集 #{{ restoreTarget.id }} · 创建于 {{ formatDsTime(restoreTarget.created_at) }}
        </p>
        <p style="font-size: 13px; color: var(--text-secondary);">
          恢复后将出现在对应的数据分类中
        </p>
      </div>
      <template #footer>
        <el-button @click="restoreVisible = false" aria-label="取消恢复">取消</el-button>
        <el-button type="success" @click="executeRestore" :loading="restoreLoading" aria-label="确认恢复">
          确认恢复
        </el-button>
      </template>
    </el-dialog>

    <!-- 永久删除确认弹窗 -->
    <el-dialog
      v-model="permanentDeleteVisible"
      title="永久删除确认"
      width="460px"
      aria-label="永久删除确认弹窗"
    >
      <div style="text-align:center; padding: 20px 0;">
        <el-icon :size="64" style="color: var(--danger); margin-bottom: 16px;"><Warning /></el-icon>
        <p style="font-size: 16px; color: var(--text-primary); margin-bottom: 8px;">
          确定要永久删除 <strong>{{ permanentDeleteTarget?.name }}</strong>（{{ permanentDeleteTarget?.id != null ? `#${permanentDeleteTarget.id}` : '' }}）吗？
        </p>
        <p v-if="permanentDeleteTarget?.id != null" style="font-size: 13px; color: var(--text-secondary); margin-top: 4px;">
          数据集 #{{ permanentDeleteTarget.id }} · 创建于 {{ formatDsTime(permanentDeleteTarget.created_at) }}
        </p>
        <p style="font-size: 13px; color: var(--danger);">
          将从用户端移除，可联系管理员恢复
        </p>
      </div>
      <template #footer>
        <el-button @click="permanentDeleteVisible = false" aria-label="取消永久删除">取消</el-button>
        <el-button type="danger" @click="executePermanentDelete" :loading="permanentDeleteLoading" aria-label="确认永久删除">
          永久删除
        </el-button>
      </template>
    </el-dialog>

    <!-- 远程数据库导入弹窗 -->
  </div>
</template>

<script>
export default { name: 'DataManagement' }
</script>

<script setup>
import { ref, computed, inject, onMounted, onActivated } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, Loading, View, Edit, Download, Delete, Document, InfoFilled, Share, Folder, MagicStick, TrendCharts, Histogram, FolderDelete, Warning, Cpu, Upload, Setting, ChatDotRound, Search, Clock, Coin, QuestionFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  updateDataset, deleteDataset, exportDataset,
  fetchTrashList, restoreDataset, permanentDeleteDataset, clearTrash, batchDeleteDatasets,
  getDatasetLineage
} from '../api/index.js'
import api from '../api/index.js'
import { getModuleLabel, getArtifactLabel, getArtifactTagType, getModuleIconName, getDatasetColor } from '../utils/labels.js'

const datasetStore = inject('datasetStore')

// 产物类型 Tab
const activeTab = ref('raw_data')
const sourceFilter = ref('')
const predictTypeFilter = ref('')  // 预测数据产物类型筛选
const miningTypeFilter = ref('')  // 数据挖掘产物类型筛选

// 数据导入
const importSourceId = ref(null)
const importTargetModule = ref('')
const importLoading = ref(false)

// 数据集列表
const datasets = ref([])
const loading = ref(false)

// 导入数据源选项（原始数据、数据分析、清洗结果、数据挖掘产物、特征工程产物）
const importSourceOptions = computed(() => {
  const allowedTypes = ['raw_data', 'analysis_data', 'cleaning_result', 'cluster_result', 'association_rules', 'sequential_patterns', 'feature_result']
  return datasets.value.filter(d => allowedTypes.includes(d.artifact_type))
})

// 搜索关键词
const searchKeyword = ref('')

// 排序与分页
const currentPage = ref(1)
const pageSize = ref(20)
const sortProp = ref('created_at')
const sortOrder = ref('descending')

// 排序后的数据集（含搜索过滤）
const sortedDatasets = computed(() => {
  let list = [...datasets.value]
  
  // 搜索过滤
  if (searchKeyword.value) {
    const keyword = searchKeyword.value.toLowerCase()
    list = list.filter(d => {
      const name = (d.name || d.title || '').toLowerCase()
      const source = (d.root_dataset_name || d.module_source || '').toLowerCase()
      const type = (d.artifact_type || d.module_type || '').toLowerCase()
      return name.includes(keyword) || source.includes(keyword) || type.includes(keyword)
    })
  }
  
  // 排序
  if (!sortProp.value) return list
  return list.sort((a, b) => {
    let va = a[sortProp.value]
    let vb = b[sortProp.value]
    if (va == null) va = ''
    if (vb == null) vb = ''
    if (typeof va === 'number' && typeof vb === 'number') {
      return sortOrder.value === 'ascending' ? va - vb : vb - va
    }
    va = String(va)
    vb = String(vb)
    return sortOrder.value === 'ascending' ? va.localeCompare(vb) : vb.localeCompare(va)
  })
})

// 分页后的数据集
const pagedDatasets = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return sortedDatasets.value.slice(start, start + pageSize.value)
})

// 数据预览
const previewVisible = ref(false)
const previewDataset = ref(null)
const previewDatasetId = ref(null)  // 保存当前预览的数据集ID，用于翻页
const previewLoading = ref(false)
const previewColumns = ref([])
const previewData = ref([])
const reportPreviewHtml = ref('')  // 数据分析报告预览内容（HTML 或 Markdown 渲染结果）
const reportPreviewUrl = ref('')   // iframe blob URL，用于隔离报告样式
const previewTotal = ref(0)
const previewPage = ref(1)
const previewPageSize = ref(50)

// 关联规则预览
const associationRules = ref([])
const associationParams = ref(null)

// 序列模式预览
const sequencePatterns = ref([])
const sequenceParams = ref(null)

// 报告查看
const reportVisible = ref(false)
const reportTarget = ref(null)
const reportLoading = ref(false)
const reportContent = ref('')

// 编辑元数据
const editVisible = ref(false)
const editTarget = ref(null)
const editLoading = ref(false)
const editForm = ref({ name: '', tags: '', remarks: '' })

// 数据血缘
const lineageVisible = ref(false)
const lineageTarget = ref(null)
const lineageLoading = ref(false)
// root_source 为远程数据库虚拟根节点（is_virtual=true），本地数据集时为 null
const lineageData = ref({ self: null, ancestors: [], descendants: [], root_source: null })

// 扩展名（不可修改），优先从名称提取，其次从 file_path 提取
const editExtension = computed(() => {
  if (!editTarget.value) return ''
  const name = editTarget.value.name || ''
  const parts = name.split('.')
  if (parts.length > 1) return parts[parts.length - 1]
  // 名称无扩展名时，从 file_path 提取
  const fp = editTarget.value.file_path || ''
  const fpParts = fp.split('.')
  return fpParts.length > 1 ? fpParts[fpParts.length - 1].toLowerCase() : ''
})

// 删除
const deleteVisible = ref(false)
const deleteTarget = ref(null)
const deleteLoading = ref(false)

// 恢复
const restoreVisible = ref(false)
const restoreTarget = ref(null)
const restoreLoading = ref(false)

// 永久删除
const permanentDeleteVisible = ref(false)
const permanentDeleteTarget = ref(null)
const permanentDeleteLoading = ref(false)

// 批量选择
const selectedRows = ref([])

function handleSelectionChange(rows) {
  selectedRows.value = rows
}

async function batchDelete() {
  if (selectedRows.value.length === 0) return
  const names = selectedRows.value.map(r => r.name).join('、')
  try {
    await ElMessageBox.confirm(
      `确定要将以下 ${selectedRows.value.length} 项移到回收站吗？\n${names}`,
      '批量删除确认',
      { type: 'warning', confirmButtonText: '移到回收站', cancelButtonText: '取消' }
    )
    deleteLoading.value = true
    const ids = selectedRows.value.map(r => r.id)
    await batchDeleteDatasets(ids)
    datasets.value = datasets.value.filter(d => !ids.includes(d.id))
    datasetStore.datasets = datasetStore.datasets.filter(d => !ids.includes(d.id))
    selectedRows.value = []
    ElMessage.success(`已将 ${ids.length} 项移到回收站`)
  } catch {
    // 用户取消
  } finally {
    deleteLoading.value = false
  }
}

// ====== 产物类型映射 ======
// 产物图标与所属模块图标保持一致：
// - 数据挖掘产物（cluster_result/association_rules/sequential_patterns）使用数据挖掘模块图标 Search
// - 机器学习产物（ml_model）使用机器学习模块图标 Cpu
// - 特征工程产物（feature_result/feature_selected）使用特征工程模块图标 Setting
function getArtifactIconName(type) {
  const map = {
    raw_data: 'Folder',
    analysis_data: 'Folder',
    cleaning_result: 'MagicStick',
    cluster_result: 'Search',
    anomaly_result: 'Warning',
    association_rules: 'Search',
    sequential_patterns: 'Search',
    ml_model: 'Cpu',
    ml_report: 'TrendCharts',
    ml_prediction: 'MagicStick',
    predict_data: 'Upload',
    feature_result: 'Setting',
    analysis_report: 'Document'
  }
  return map[type] || 'Document'
}

// ====== 显示名称（自动补全扩展名） ======
function getDisplayName(row) {
  if (!row) return ''
  const name = row.name || ''
  // 如果已有扩展名则直接返回
  if (name.includes('.')) return name
  // 从 file_path 提取扩展名
  const ext = getExtension(row)
  return ext ? `${name}.${ext}` : name
}

// 格式化创建时间为 `MM-DD HH:mm`（本地时区显示）
function formatDsTime(iso) {
  if (!iso) return '--'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '--'
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function getExtension(row) {
  if (!row?.file_path) return ''
  const parts = row.file_path.split('.')
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : ''
}

// ====== 解析 tags 字段：区分用户标签（逗号分隔字符串）和内部元数据（JSON格式，不显示）
function parseDisplayTags(tags) {
  if (!tags) return []
  // 尝试解析为JSON，如果成功且包含original_columns/generated_columns等内部字段，则不是用户标签
  try {
    const parsed = JSON.parse(tags)
    if (parsed && typeof parsed === 'object' && (parsed.original_columns || parsed.generated_columns)) {
      // 内部元数据，不作为标签显示
      return []
    }
  } catch (e) {
    // 不是JSON，作为普通逗号分隔标签处理
  }
  // 普通用户标签，按逗号分隔
  return tags.split(',').map(t => t.trim()).filter(t => t)
}

const router = useRouter()

// 跳转到操作历史页面，并按数据集ID筛选
function goToTaskHistory(datasetId) {
  router.push({ path: '/task-history', query: { dataset_id: datasetId } })
}

// 首次挂载时加载数据集列表并同步全局 store（侧边栏计数）
onMounted(() => {
  loadDatasets(true)
})

// 再次激活时刷新数据集列表（keep-alive 缓存后切换回来）
// store 已有数据时不重复全量查询，避免每次切回都双倍请求
onActivated(() => {
  const needSync = !datasetStore.datasets || datasetStore.datasets.length === 0
  loadDatasets(needSync)
})

// 加载数据集（按 artifact_type 和 module_source）
// 注意：此函数在 onActivated 中调用，不重置 currentPage 以保留用户分页位置
// 参数 syncStore：是否同步全局 store（侧边栏计数）。仅首次加载、刷新、导入后传 true，
// 切 Tab/筛选/搜索等纯查看操作不传，避免每次都额外发一个全量查询请求
async function loadDatasets(syncStore = false) {
  loading.value = true
  try {
    // 回收站Tab：调用回收站列表接口
    if (activeTab.value === 'trash') {
      const res = await fetchTrashList()
      datasets.value = res.data || []
    } else {
      let type = activeTab.value
      const source = (activeTab.value === 'raw_data' && sourceFilter.value) ? sourceFilter.value : null

      // 原始数据Tab：同时查询 raw_data（各模块原始数据）和 analysis_data（数据分析模块数据）
      if (activeTab.value === 'raw_data') {
        const params = {}
        if (source) params.module_source = source
        const res1 = await api.get('/datasets/', { params: { artifact_type: 'raw_data', ...params } })
        const res2 = await api.get('/datasets/', { params: { artifact_type: 'analysis_data', ...params } })
        datasets.value = [...(res1.data || []), ...(res2.data || [])]
      }
      // 机器学习产物Tab：同时查询 ml_model 和 ml_report
      else if (activeTab.value === 'ml_report') {
        const res1 = await api.get('/datasets/', { params: { artifact_type: 'ml_model' } })
        const res2 = await api.get('/datasets/', { params: { artifact_type: 'ml_report' } })
        datasets.value = [...(res1.data || []), ...(res2.data || [])]
      }
      // 数据挖掘Tab：同时查询 cluster_result、association_rules、sequential_patterns，按筛选条件过滤
      else if (activeTab.value === 'mining_result') {
        const filterType = miningTypeFilter.value
        if (!filterType) {
          // 全部
          const res1 = await api.get('/datasets/', { params: { artifact_type: 'cluster_result' } })
          const res2 = await api.get('/datasets/', { params: { artifact_type: 'association_rules' } })
          const res3 = await api.get('/datasets/', { params: { artifact_type: 'sequential_patterns' } })
          datasets.value = [...(res1.data || []), ...(res2.data || []), ...(res3.data || [])]
        } else {
          // 单类型筛选
          const res = await api.get('/datasets/', { params: { artifact_type: filterType } })
          datasets.value = res.data || []
        }
      }
      // 预测数据Tab：查询 predict_data（上传文件）和 ml_prediction（预测结果），按筛选条件过滤
      else if (activeTab.value === 'predict_data') {
        const filterType = predictTypeFilter.value
        if (!filterType) {
          // 全部
          const res1 = await api.get('/datasets/', { params: { artifact_type: 'predict_data' } })
          const res2 = await api.get('/datasets/', { params: { artifact_type: 'ml_prediction' } })
          datasets.value = [...(res1.data || []), ...(res2.data || [])]
        } else {
          // 单类型筛选
          const res = await api.get('/datasets/', { params: { artifact_type: filterType } })
          datasets.value = res.data || []
        }
      }
      // 特征工程产物Tab：查询 feature_result（已统一，不再有 feature_selected 类型）
      else if (activeTab.value === 'feature_result') {
        const res = await api.get('/datasets/', { params: { artifact_type: 'feature_result' } })
        datasets.value = res.data || []
      }
      else {
        const params = {}
        if (type) params.artifact_type = type
        if (source) params.module_source = source
        const res = await api.get('/datasets/', { params })
        datasets.value = res.data || []
      }
      
      // 同步到全局 store：侧边栏计数需要全部数据集列表
      // 各 Tab 查询的是特定 artifact_type 的子集，不能直接用于计数
      // 仅在 syncStore=true 时查询全量数据集更新 store，避免每次切 Tab/筛选都双倍请求
      if (syncStore) {
        try {
          const allRes = await api.get('/datasets/', {})
          datasetStore.datasets = allRes.data || []
        } catch {
          // 同步失败不影响当前 Tab 数据展示
        }
      }
    }
    // 注意：不在这里重置 currentPage，保留用户的分页位置
    // currentPage 只在 onTabChange 和 onSourceFilterChange 中重置
    // 校正页码：删除数据后切回模块，当前页可能越界导致表格空白
    const maxPage = Math.ceil(datasets.value.length / pageSize.value) || 1
    if (currentPage.value > maxPage) {
      currentPage.value = maxPage
    }
  } catch {
    datasets.value = []
  } finally {
    loading.value = false
  }
}

// Tab 切换
function onTabChange() {
  currentPage.value = 1
  sourceFilter.value = ''
  predictTypeFilter.value = ''
  miningTypeFilter.value = ''
  searchKeyword.value = ''
  
  loadDatasets()
}

// 获取搜索框占位符
function getSearchPlaceholder() {
  const placeholderMap = {
    raw_data: '搜索原始数据名称',
    analysis_report: '搜索报告名称',
    cleaning_result: '搜索清洗结果名称',
    mining_result: '搜索挖掘结果名称',
    feature_result: '搜索特征工程产物名称',
    ml_report: '搜索机器学习产物名称',
    predict_data: '搜索预测数据名称',
    trash: '搜索回收站中产物名称'
  }
  return placeholderMap[activeTab.value] || '搜索产物名称'
}

// 搜索
function onSearch() {
  currentPage.value = 1
}

// 来源模块筛选变化
function onSourceFilterChange() {
  currentPage.value = 1
  loadDatasets()
}

// 排序变化
function onSortChange({ prop, order }) {
  sortProp.value = prop
  sortOrder.value = order
  currentPage.value = 1
}

// 打开数据预览
async function openPreview(row) {
  // 释放之前可能存在的 blob URL
  if (reportPreviewUrl.value) {
    URL.revokeObjectURL(reportPreviewUrl.value)
    reportPreviewUrl.value = ''
  }
  previewDataset.value = row
  previewDatasetId.value = row.id
  previewVisible.value = true
  previewColumns.value = []
  previewData.value = []
  reportPreviewHtml.value = ''
  previewTotal.value = 0
  previewPage.value = 1
  associationRules.value = []
  associationParams.value = null
  previewLoading.value = true
  // 数据分析报告类型会在 loadPreviewData 中直接读取 report_content，不调用通用数据接口
  await loadPreviewData()
}

// 加载预览数据（支持翻页）
async function loadPreviewData() {
  if (!previewDatasetId.value) return
  previewLoading.value = true
  try {
    // 关联规则类型：使用专门的接口
    if (previewDataset.value?.artifact_type === 'association_rules') {
      const { fetchAssociationRules } = await import('../api/index.js')
      const res = await fetchAssociationRules(previewDatasetId.value, previewPage.value, previewPageSize.value)
      const d = res.data || {}
      associationRules.value = d.rules || []
      associationParams.value = d.parameters || {}
      previewTotal.value = d.total || 0
      if (associationRules.value.length > 0 && previewPage.value === 1) {
        ElMessage.success('关联规则加载成功')
      }
    } else if (previewDataset.value?.artifact_type === 'sequential_patterns') {
      // 序列模式：使用专门的接口
      const { fetchSequencePatterns } = await import('../api/index.js')
      const res = await fetchSequencePatterns(previewDatasetId.value, previewPage.value, previewPageSize.value)
      const d = res.data || {}
      sequencePatterns.value = d.patterns || []
      sequenceParams.value = d.parameters || {}
      previewTotal.value = d.total || 0
      if (sequencePatterns.value.length > 0 && previewPage.value === 1) {
        ElMessage.success('序列模式加载成功')
      }
    } else if (previewDataset.value?.artifact_type === 'analysis_report') {
      // 数据分析报告：report_content 是 JSON 字符串，需要解析后取出 html 字段
      const rawContent = previewDataset.value?.report_content
      if (!rawContent) {
        reportPreviewHtml.value = '<div style="text-align:center;padding:60px 0;color:var(--text-secondary);">报告内容为空</div>'
      } else {
        let htmlContent = rawContent
        // 后端存的是 {type, html, dynamic_data} JSON，先尝试解析取 html
        try {
          const parsed = typeof rawContent === 'string' ? JSON.parse(rawContent) : rawContent
          if (parsed && typeof parsed.html === 'string') {
            htmlContent = parsed.html
          }
        } catch (e) {
          // 解析失败则按原内容处理
        }
        if (isHtmlContent(htmlContent)) {
          // 后端生成的 HTML 可信，用 blob URL 在 iframe 中隔离渲染
          reportPreviewHtml.value = htmlContent
          const blob = new Blob([htmlContent], { type: 'text/html' })
          reportPreviewUrl.value = URL.createObjectURL(blob)
        } else {
          // Markdown 或纯文本使用简单方式渲染
          reportPreviewHtml.value = renderMarkdown(String(htmlContent))
        }
      }
    } else {
      // 普通数据类型
      const { fetchDatasetData } = await import('../api/index.js')
      const res = await fetchDatasetData(previewDatasetId.value, previewPage.value, previewPageSize.value)
      const d = res.data || {}
      if (d.columns && d.data) {
        previewColumns.value = d.columns
        previewData.value = d.data
        previewTotal.value = d.total_rows || previewDataset.value?.row_count || d.data.length
      } else if (d.columns && d.rows) {
        previewColumns.value = d.columns
        previewData.value = d.rows.map(r => {
          const rowData = {}
          d.columns.forEach((col, i) => { rowData[col] = r[i] || '' })
          return rowData
        })
        previewTotal.value = d.row_count || d.total || d.rows.length
      }
      if (previewColumns.value.length > 0 && previewPage.value === 1) {
        ElMessage.success('数据预览加载成功')
      }
    }
  } catch {
    ElMessage.error('数据加载失败')
  } finally {
    previewLoading.value = false
  }
}

// 预览翻页
function handlePreviewPageChange() {
  loadPreviewData()
}

function handlePreviewSizeChange() {
  previewPage.value = 1
  loadPreviewData()
}

// 关联规则翻页
function handleAssociationPageChange() {
  loadPreviewData()
}

function handleAssociationSizeChange() {
  previewPage.value = 1
  loadPreviewData()
}

// 打开报告查看
async function openReportView(row) {
  reportTarget.value = row
  reportVisible.value = true
  reportContent.value = ''
  reportLoading.value = true

  try {
    // ml_report 类型：使用专门的报告内容查询API
    // ml_model 类型：也用同一个API（后端 ml/reports/{id} 会复用模型报告逻辑）
    if (row.artifact_type === 'ml_report' || row.artifact_type === 'ml_model') {
      const { fetchModelReport } = await import('../api/index.js')
      const res = await fetchModelReport(row.id)
      if (res.data?.report) {
        // 渲染为中文报告
        reportContent.value = renderModelReport(res.data.report)
      } else {
        reportContent.value = `## ${row.name || '模型报告'}\n\n> 报告内容为空。`
      }
    } else {
      // 其他类型：尝试通用数据接口
      const { fetchDatasetData } = await import('../api/index.js')
      const res = await fetchDatasetData(row.id, 1, 1)
      if (res.data?.content) {
        reportContent.value = res.data.content
      } else if (res.data?.report) {
        reportContent.value = res.data.report
      } else {
        reportContent.value = `## ${row.name || '报告'}\n\n- **算法**: ${row.algorithm || '-'}\n- **创建时间**: ${formatTime(row.created_at)}\n- **行数**: ${formatNumber(row.row_count)}\n- **大小**: ${formatSize(row.file_size)}\n\n> 报告内容暂不可用，请尝试导出查看。`
      }
    }
  } catch (e) {
    console.error('报告加载失败', e)
    reportContent.value = `## ${row.name || '报告'}\n\n> 报告内容加载失败：${e?.message || '请重试'}`
  } finally {
    reportLoading.value = false
  }
}

// 将ML模型报告JSON渲染为中文Markdown
function renderModelReport(report) {
  if (!report) return ''

  // 超参数翻译映射
  const algoNameMap = {
    'logistic_regression': '逻辑回归',
    'random_forest': '随机森林',
    'svm': '支持向量机',
    'linear_regression': '线性回归',
    'ridge_regression': '岭回归'
  }
  const solverMap = {
    'lbfgs': 'L-BFGS优化器',
    'liblinear': 'LIBLINEAR优化器',
    'saga': 'SAGA优化器'
  }
  const kernelMap = {
    'linear': '线性核',
    'rbf': '高斯核(RBF)',
    'poly': '多项式核',
    'sigmoid': 'Sigmoid核'
  }

  let md = ''

  // === 模型信息 ===
  const mi = report.model_info || {}
  md += `## 模型信息\n\n`
  md += `| 项目 | 内容 |\n|------|------|\n`
  md += `| 模型名称 | ${mi.model_name || '-'} |\n`
  md += `| 算法 | ${algoNameMap[mi.algorithm] || mi.algorithm || '-'} |\n`
  md += `| 任务类型 | ${mi.task_type === 'classification' ? '分类任务' : mi.task_type === 'regression' ? '回归任务' : (mi.task_type || '-')} |\n`
  md += `| 目标列 | ${mi.target_column || '-'} |\n`
  md += `| 特征数量 | ${mi.feature_count || 0} |\n`
  md += `| 特征列 | ${(mi.feature_columns || []).join('、') || '-'} |\n`
  md += `| 创建时间 | ${formatTime(mi.created_at) || '-'} |\n`
  md += `\n`

  // === 训练参数 ===
  const tp = report.training_params || {}
  md += `## 训练参数\n\n`
  md += `| 参数 | 取值 |\n|------|------|\n`
  md += `| 测试集比例 | ${tp.test_size !== undefined ? (tp.test_size * 100).toFixed(0) + '%' : '-'} |\n`
  md += `| 交叉验证折数 | ${tp.cv_folds || '-'} 折 |\n`
  md += `| 是否自动调优 | ${tp.auto_tune ? '是' : '否'} |\n`
  md += `| 调优方法 | ${tp.tune_method === 'grid' ? '网格搜索(穷尽)' : tp.tune_method === 'random' ? '随机搜索(快速)' : (tp.tune_method || '-')} |\n`
  md += `\n`

  // === 最优超参数 ===
  const bp = report.best_params || {}
  if (Object.keys(bp).length > 0) {
    md += `## 最优超参数\n\n`
    md += `| 参数 | 取值 |\n|------|------|\n`
    for (const [k, v] of Object.entries(bp)) {
      let cn = k
      if (k === 'C') cn = '正则化强度C'
      else if (k === 'solver') cn = '求解器'
      else if (k === 'n_estimators') cn = '树的数量'
      else if (k === 'max_depth') cn = '最大深度'
      else if (k === 'min_samples_split') cn = '最小分割样本数'
      else if (k === 'kernel') cn = '核函数'
      else if (k === 'gamma') cn = '核系数'
      else if (k === 'alpha') cn = '正则化系数'
      let val = v
      if (k === 'solver' && solverMap[v]) val = solverMap[v]
      else if (k === 'kernel' && kernelMap[v]) val = kernelMap[v]
      md += `| ${cn} | ${val} |\n`
    }
    md += `\n`
  }

  // === 性能指标 ===
  const pm = report.performance_metrics || {}
  if (Object.keys(pm).length > 0) {
    md += `## 性能评估指标\n\n`
    md += `| 指标 | 数值 | 说明 |\n|------|------|------|\n`
    if (pm.accuracy !== undefined) md += `| 准确率(Accuracy) | ${(pm.accuracy * 100).toFixed(2)}% | 正确预测样本占比 |\n`
    if (pm.precision !== undefined) md += `| 精确率(Precision) | ${(pm.precision * 100).toFixed(2)}% | 预测为正例中实际为正例的比例 |\n`
    if (pm.recall !== undefined) md += `| 召回率(Recall) | ${(pm.recall * 100).toFixed(2)}% | 实际正例中被正确预测的比例 |\n`
    if (pm.f1 !== undefined) md += `| F1分数 | ${(pm.f1 * 100).toFixed(2)}% | 精确率和召回率的调和平均 |\n`
    if (pm.roc_auc !== undefined) md += `| ROC AUC | ${pm.roc_auc.toFixed(4)} | 受试者工作特征曲线下面积 |\n`
    if (pm.r2 !== undefined) md += `| R² 决定系数 | ${pm.r2.toFixed(4)} | 模型解释因变量方差的比例 |\n`
    if (pm.mse !== undefined) md += `| MSE 均方误差 | ${pm.mse.toFixed(4)} | 预测值与真实值之差的平方和 |\n`
    if (pm.rmse !== undefined) md += `| RMSE 均方根误差 | ${pm.rmse.toFixed(4)} | MSE的平方根，与目标同量纲 |\n`
    if (pm.mae !== undefined) md += `| MAE 平均绝对误差 | ${pm.mae.toFixed(4)} | 预测值与真实值之差的绝对值平均 |\n`
    if (pm.cv_mean !== undefined) md += `| 交叉验证均值 | ${pm.cv_mean.toFixed(4)} | K折交叉验证平均分数 |\n`
    if (pm.cv_std !== undefined) md += `| 交叉验证标准差 | ${pm.cv_std.toFixed(4)} | K折交叉验证分数波动 |\n`
    md += `\n`
  }

  // === 数据集划分 ===
  if (report.dataset_split && Object.keys(report.dataset_split).length > 0) {
    md += `## 📂 数据集划分\n\n`
    const ds = report.dataset_split
    md += `| 项目 | 数值 |\n|------|------|\n`
    md += `| 总样本数 | ${ds.total || '-'} |\n`
    md += `| 训练+验证集 | ${ds.trainval || '-'} (${(ds.trainval_ratio * 100).toFixed(1)}%) |\n`
    md += `| 测试集 | ${ds.test || '-'} (${(ds.test_ratio * 100).toFixed(1)}%) |\n`
    md += `| 说明 | ${ds.description || '-'} |\n`
    md += `\n`
  }

  // === 特征重要性 ===
  if (report.feature_importance && Object.keys(report.feature_importance).length > 0) {
    md += `## 特征重要性\n\n`
    const fi = report.feature_importance
    const sorted = Object.entries(fi).sort((a, b) => b[1] - a[1])
    md += `| 特征 | 重要性 |\n|------|------|\n`
    for (const [feat, imp] of sorted.slice(0, 10)) {
      const bar = '█'.repeat(Math.round(imp * 20))
      md += `| ${feat} | ${imp.toFixed(4)} ${bar} |\n`
    }
    md += `\n`
  }

  // === 调优结果 ===
  if (report.tune_results) {
    md += `## 调优结果\n\n`
    const tr = report.tune_results
    md += `- **最佳分数**: ${tr.best_score?.toFixed(4) || '-'}\n`
    md += `- **方法**: ${tr.method === 'grid' ? '网格搜索' : '随机搜索'}\n`
    md += `- **候选参数组合数**: ${tr.n_candidates || '-'}\n\n`
  }

  return md
}

// 简单的 Markdown 渲染
function renderMarkdown(text) {
  if (!text) return ''
  // 先转义 HTML 实体，防止 XSS 攻击（如 <img onerror=...> 注入）
  // Markdown 标记符（# * > - `）不含 HTML 特殊字符，转义不影响标记识别
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
  // 再进行 Markdown 标记替换
  html = html
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="code-block"><code>$2</code></pre>')
    .replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/\n/g, '<br>')
  html = html.replace(/((?:<li>.*?<\/li><br>)+)/g, '<ul>$1</ul>')
  html = html.replace(/<ul>([\s\S]*?)<\/ul>/g, (_, inner) => '<ul>' + inner.replace(/<br>/g, '') + '</ul>')
  return html
}

// 判断内容是否为 HTML 格式（简单启发式检测）
function isHtmlContent(content) {
  const trimmed = String(content).trim()
  return /^</.test(trimmed) && />$/.test(trimmed)
}

function openLineage(row) {
  lineageTarget.value = row
  lineageLoading.value = true
  getDatasetLineage(row.id).then(res => {
    lineageData.value = res.data || { self: null, ancestors: [], descendants: [], root_source: null }
    lineageLoading.value = false
    lineageVisible.value = true
  }).catch(e => {
    console.error(e)
    ElMessage.error('加载数据血缘失败')
    lineageLoading.value = false
  })
}

// 打开编辑名称
function openEditMeta(row) {
  editTarget.value = row
  // 普通数据集（含机器学习产物）：提取不含扩展名的名称部分
  const name = row.name || ''
  const nameParts = name.split('.')
  let nameWithoutExt = name
  if (nameParts.length > 1) {
    nameWithoutExt = nameParts.slice(0, -1).join('.')
  }
  // 过滤内部元数据 JSON：跨模块导入时 tags 字段会存入 original_columns/generated_columns 等内部元数据
  // 这些不属于用户标签，编辑弹窗中应显示为空，避免用户误操作破坏内部元数据
  let editTags = row.tags || ''
  try {
    const parsed = JSON.parse(editTags)
    if (parsed && typeof parsed === 'object' && (parsed.original_columns || parsed.generated_columns)) {
      editTags = ''
    }
  } catch (e) {
    // 非 JSON，作为普通逗号分隔标签保留原值
  }
  editForm.value = { name: nameWithoutExt, tags: editTags, remarks: row.remarks || '' }
  editVisible.value = true
}

// 判断 tags 字段是否为内部元数据 JSON（含 original_columns/generated_columns 等）
// 跨模块导入时这些字段由系统写入，不属于用户标签，编辑弹窗中应过滤显示且不应被覆盖
function isInternalMetaTags(tags) {
  if (!tags) return false
  try {
    const parsed = JSON.parse(tags)
    return !!(parsed && typeof parsed === 'object' && (parsed.original_columns || parsed.generated_columns))
  } catch (e) {
    return false
  }
}

// 保存编辑名称
async function saveEditMeta() {
  if (!editTarget.value) return
  if (!editForm.value.name.trim()) {
    ElMessage.warning('名称不能为空')
    return
  }
  editLoading.value = true
  try {
    // 普通数据集（含机器学习产物）：拼接扩展名
    const ext = editExtension.value
    const fullName = ext ? `${editForm.value.name.trim()}.${ext}` : editForm.value.name.trim()

    // 构造更新载荷：仅传发生变化的字段，避免触发后端不必要的名称唯一性校验
    // 若名称未修改，不传 name 字段；若原始 tags 为内部元数据 JSON，不传 tags 字段以保留后端原值
    const originalTagsIsMeta = isInternalMetaTags(editTarget.value?.tags)
    const originalName = editTarget.value?.name || ''
    const nameChanged = fullName !== originalName
    const payload = { remarks: editForm.value.remarks.trim() }
    if (nameChanged) {
      payload.name = fullName
    }
    if (!originalTagsIsMeta) {
      payload.tags = editForm.value.tags.trim()
    }
    await updateDataset(editTarget.value.id, payload)

    // 更新本地数据
    const idx = datasets.value.findIndex(d => d.id === editTarget.value.id)
    if (idx >= 0) {
      if (nameChanged) {
        datasets.value[idx].name = fullName
      }
      // 内部元数据 tags 保留原值，不覆盖
      if (!originalTagsIsMeta) {
        datasets.value[idx].tags = editForm.value.tags.trim()
      }
      datasets.value[idx].remarks = editForm.value.remarks.trim()
    }
    // 同步到全局 store
    if (datasetStore.datasets && nameChanged) {
      const storeIdx = datasetStore.datasets.findIndex(d => d.id === editTarget.value.id)
      if (storeIdx >= 0) {
        datasetStore.datasets[storeIdx].name = fullName
      }
    }
    // 触发机器学习模块同步更新（仅名称变化时才需要）
    if (nameChanged && window.dispatchEvent) {
      window.dispatchEvent(new CustomEvent('ml-model-name-updated', {
        detail: { id: editTarget.value.id, name: fullName }
      }))
    }
    editVisible.value = false
    ElMessage.success('名称更新成功')
  } catch (e) {
    const msg = e?.response?.data?.detail || '名称更新失败'
    ElMessage.error(msg)
  } finally {
    editLoading.value = false
  }
}

// 导出（下载名与展示名一致，不加时间戳；同名由浏览器自动加 (1)）
async function handleExport(row, format) {
  try {
    // 普通数据集使用通用导出接口
    const res = await exportDataset(row.id, format)
    // 去源名扩展名后追加导出格式后缀，避免双后缀（如 销售数据.csv_时间戳.csv）
    const ext = format === 'excel' ? 'xlsx' : format
    const base = (row.name || 'dataset').replace(/\.(csv|xlsx|xls|json|txt|html)$/i, '')

    const url = window.URL.createObjectURL(new Blob([res.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `${base}.${ext}`)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
    ElMessage.success(`导出 ${format === 'markdown' ? 'Markdown' : format.toUpperCase()} 成功`)
  } catch {
    ElMessage.error(`导出 ${format === 'markdown' ? 'Markdown' : format.toUpperCase()} 失败`)
  }
}

// 分析报告导出（仅动态HTML，保留完整交互）
async function handleReportExport(row) {
  try {
    const res = await exportDataset(row.id, 'html', 'dynamic')
    const url = window.URL.createObjectURL(new Blob([res.data]))
    const link = document.createElement('a')
    link.href = url
    // 下载名与展示名一致（去原扩展名 + .html），不加时间戳
    const base = (row.name || 'analysis_report').replace(/\.(csv|xlsx|xls|json|txt|html)$/i, '')
    link.setAttribute('download', `${base}.html`)
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
    ElMessage.success('导出动态HTML报告成功')
  } catch (e) {
    ElMessage.error('导出报告失败')
  }
}

// 机器学习模型操作：导出模型文件
async function handleMLModelExport(row, action) {
  try {
    if (action === 'model') {
      // 导出 .pkl 模型文件 — 使用 API 调用下载
      const res = await api.get(`/ml/models/${row.id}/export`, {
        responseType: 'blob'
      })
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const link = document.createElement('a')
      link.href = url
      // 下载名与展示名一致（去原扩展名 + 真实 .pkl 后缀），避免双后缀
      const base = (row.name || 'model').replace(/\.(csv|xlsx|xls|json|txt|pkl|model)$/i, '')
      link.setAttribute('download', `${base}.pkl`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
      ElMessage.success('模型文件导出成功')
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '操作失败')
  }
}

// 统一导入模块：执行导入
async function doImport() {
  if (!importSourceId.value || !importTargetModule.value) return
  
  const sourceDataset = datasets.value.find(d => d.id === importSourceId.value)
  if (!sourceDataset) return
  
  const moduleNames = {
    cleaning: '数据清洗',
    ml: '机器学习',
    ai: 'AI分析',
    feature_engineering: '特征工程',
    data_analysis: '数据分析',
    data_mining: '数据挖掘'
  }
  
  try {
    await ElMessageBox.confirm(
      `确定要将 "${sourceDataset.name}" 导入到${moduleNames[importTargetModule.value]}模块吗？\n导入后将创建一份副本，可在目标模块中使用。`,
      '导入确认',
      { type: 'info', confirmButtonText: '确定导入', cancelButtonText: '取消' }
    )
    
    importLoading.value = true
    await api.post(`/datasets/${importSourceId.value}/import`, null, {
      params: { target_module: importTargetModule.value }
    })
    
    ElMessage.success(`已导入到${moduleNames[importTargetModule.value]}模块`)
    importSourceId.value = null
    importTargetModule.value = ''
    loadDatasets(true) // 数据变更，刷新列表并同步 store
  } catch {
    // 用户取消或导入失败
  } finally {
    importLoading.value = false
  }
}

// 删除确认
function confirmDelete(row) {
  deleteTarget.value = row
  deleteVisible.value = true
}

// 执行删除
async function executeDelete() {
  if (!deleteTarget.value) return
  deleteLoading.value = true
  try {
    await deleteDataset(deleteTarget.value.id)
    datasets.value = datasets.value.filter(d => d.id !== deleteTarget.value.id)
    // 同步全局 store
    datasetStore.datasets = datasetStore.datasets.filter(d => d.id !== deleteTarget.value.id)
    deleteVisible.value = false
    // corrupted 文件直接物理删除，其他文件移到回收站
    if (deleteTarget.value.status === 'corrupted') {
      ElMessage.success('已删除损坏的记录')
    } else {
      ElMessage.success('已移到回收站')
    }
  } catch {
    ElMessage.error('删除失败')
  } finally {
    deleteLoading.value = false
  }
}

// 恢复确认
function confirmRestore(row) {
  restoreTarget.value = row
  restoreVisible.value = true
}

// 执行恢复
async function executeRestore() {
  if (!restoreTarget.value) return
  restoreLoading.value = true
  try {
    await restoreDataset(restoreTarget.value.id)
    datasets.value = datasets.value.filter(d => d.id !== restoreTarget.value.id)
    restoreVisible.value = false
    ElMessage.success('恢复成功')
  } catch {
    ElMessage.error('恢复失败')
  } finally {
    restoreLoading.value = false
  }
}

// 永久删除确认
function confirmPermanentDelete(row) {
  permanentDeleteTarget.value = row
  permanentDeleteVisible.value = true
}

// 执行永久删除
async function executePermanentDelete() {
  if (!permanentDeleteTarget.value) return
  permanentDeleteLoading.value = true
  try {
    await permanentDeleteDataset(permanentDeleteTarget.value.id)
    datasets.value = datasets.value.filter(d => d.id !== permanentDeleteTarget.value.id)
    permanentDeleteVisible.value = false
    ElMessage.success('已永久删除')
  } catch {
    ElMessage.error('永久删除失败')
  } finally {
    permanentDeleteLoading.value = false
  }
}

// 批量恢复
async function batchRestore() {
  if (selectedRows.value.length === 0) return
  try {
    await ElMessageBox.confirm(
      `确定要恢复选中的 ${selectedRows.value.length} 项吗？`,
      '批量恢复确认',
      { type: 'success', confirmButtonText: '确定恢复', cancelButtonText: '取消' }
    )
    restoreLoading.value = true
    const ids = selectedRows.value.map(r => r.id)
    const promises = ids.map(id => restoreDataset(id))
    await Promise.all(promises)

    datasets.value = datasets.value.filter(d => !ids.includes(d.id))
    selectedRows.value = []
    ElMessage.success(`已恢复 ${ids.length} 项`)
  } catch {
    // 用户取消
  } finally {
    restoreLoading.value = false
  }
}

// 清空回收站确认
async function confirmClearTrash() {
  try {
    await ElMessageBox.confirm(
      '确定要清空回收站吗？将从用户端移除，可联系管理员恢复',
      '清空回收站确认',
      { type: 'warning', confirmButtonText: '确定清空', cancelButtonText: '取消' }
    )
    // 清空数据集回收站
    await clearTrash()
    datasets.value = []
    selectedRows.value = []
    ElMessage.success('回收站已清空')
  } catch {
    // 用户取消
  }
}

// 格式化数字
function formatNumber(n) {
  return n != null ? n.toLocaleString() : '-'
}

// 格式化文件大小
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

// 算法中文名映射
const algorithmLabelMap = {
  logistic_regression: '逻辑回归',
  svm: '支持向量机',
  decision_tree: '决策树',
  naive_bayes: '朴素贝叶斯',
  knn: 'K近邻',
  random_forest: '随机森林',
  adaboost: 'AdaBoost',
  gbdt: '梯度提升树',
  xgboost: 'XGBoost',
  lightgbm: 'LightGBM',
  mlp: '多层感知机',
  linear_regression: '线性回归',
  ridge_regression: '岭回归',
  lasso_regression: 'Lasso回归'
}

// 获取算法中文名称（兼容后端返回的 "xxx (classification)" / "xxx（分类）" 格式）
// 同时支持半角和全角括号
function getAlgorithmLabel(algorithm) {
  if (!algorithm) return '-'
  // 提取纯算法名(去掉括号中的任务类型),同时匹配半角()和全角（）
  const pureName = algorithm.replace(/\s*[(（].*?[)）]\s*$/, '')
  return algorithmLabelMap[pureName] || pureName
}

// 解析 ml_prediction 的算法名（"xxx（模型: model_xxx）→ 预测原始数据: data.csv" 中前半段），返回中文名称
function extractAlgorithmName(algo) {
  if (!algo) return '-'
  // 截取 "（模型:" 或 "(模型:" 之前的内容作为算法名
  const match = algo.match(/^(.+?)\s*[（(]模型[：:]/)
  if (match) {
    // 提取到的可能是 "linear_regression (regression)" 这种格式，进一步转为中文
    return getAlgorithmLabel(match[1].trim())
  }
  // 兜底：直接尝试转为中文
  return getAlgorithmLabel(algo)
}

// 解析 ml_prediction 中"预测原始数据: XXX"部分
function extractPredictSource(algo) {
  if (!algo) return '-'
  const match = algo.match(/预测原始数据[:：]\s*([^,，)）]+)/)
  return match ? match[1].trim() : '-'
}

// 格式化时间（处理UTC时间，统一显示为上海时区）
function formatTime(dateStr) {
  if (!dateStr) return '-'
  let d
  const hasTimezone = dateStr.includes('Z') || /[+-]\d{2}:\d{2}$/.test(dateStr)
  if (!hasTimezone) {
    d = new Date(dateStr + 'Z')
  } else {
    d = new Date(dateStr)
  }
  if (isNaN(d.getTime())) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false
  }).format(d).replace(/\//g, '-')
}
</script>

<style scoped>
/* 名称单元格 */
.name-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.name-cell .module-icon {
  font-size: 16px;
  flex-shrink: 0;
}

/* 数据集色点：同名数据集靠颜色区分（按 id 派生，任何页面同色） */
.ds-dot {
  flex: none;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  display: inline-block;
}

/* 数据集下拉选项：色点 + 名称 + 元信息 */
.ds-option {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  overflow: hidden;
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

/* 标签单元格：允许多个标签换行显示 */
.tags-cell {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px;
}

/* 模块来源样式 */
.module-source {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
}

/* 报告内容样式 */
.report-content {
  padding: 16px;
  font-size: 14px;
  line-height: 1.8;
  color: var(--text-primary);
  max-height: 500px;
  overflow-y: auto;
}
.report-content :deep(h2) { font-size: 18px; margin: 16px 0 10px; color: var(--primary); }
.report-content :deep(h3) { font-size: 15px; margin: 12px 0 8px; }
.report-content :deep(h4) { font-size: 14px; margin: 10px 0 6px; }
.report-content :deep(ul) { padding-left: 20px; margin: 8px 0; }
.report-content :deep(li) { margin-bottom: 4px; }
.report-content :deep(strong) { color: var(--primary); }
.report-content :deep(blockquote) {
  border-left: 3px solid var(--primary);
  padding-left: 12px; margin: 8px 0;
  color: var(--text-secondary); font-style: italic;
}
.report-content :deep(.code-block) {
  background: #1e293b; color: #e2e8f0;
  padding: 12px 16px; border-radius: var(--radius-sm);
  margin: 8px 0; overflow-x: auto; font-size: 12px;
}
.report-content :deep(.inline-code) {
  background: #f1f5f9; color: #e11d48;
  padding: 2px 6px; border-radius: 4px; font-size: 12px;
}

.algo-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}
.algo-cell .algo-tag {
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* iframe 隔离报告预览，避免样式污染主页面 */
.report-preview-iframe {
  width: 100%;
  height: 70vh;
  border: none;
  background: #f5f7fa;
}

/* 关联规则统计 */
.association-stats {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  padding: 12px 16px;
  background: var(--bg-light);
  border-radius: var(--radius-sm);
  margin-bottom: 12px;
}
.association-stats .el-tag {
  font-size: 13px;
}

/* 分页栏 */
.pagination-bar {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

/* 数据血缘样式 */
.lineage-content {
  padding: 16px;
}
.lineage-current {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
  border-radius: 8px;
  margin-bottom: 24px;
  font-size: 15px;
  font-weight: 600;
}
.lineage-current-name {
  color: #92400e;
}
.lineage-section {
  margin-bottom: 20px;
}
.lineage-section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
  padding-left: 8px;
  border-left: 3px solid var(--primary);
}
.lineage-tree {
  padding-left: 24px;
}
.lineage-node {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 12px;
}
.lineage-line {
  width: 2px;
  min-height: 24px;
  background: var(--primary);
  flex-shrink: 0;
  margin-top: 6px;
}
.lineage-line.lineage-dashed {
  background: none;
  border-left: 2px dashed var(--text-muted);
}
.lineage-node-content {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
}
.lineage-node-content span {
  color: var(--text-primary);
}
/* 远程数据源虚拟根节点：橙色边框高亮，区别于普通产物节点 */
.lineage-virtual-node {
  padding: 4px 8px;
  border: 1px dashed #e6a23c;
  border-radius: 4px;
  background: #fdf6ec;
}
.import-badge {
  font-size: 11px;
  color: #f59e0b;
  background: #fef3c7;
  padding: 2px 6px;
  border-radius: 4px;
}
.lineage-legend {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--border-light);
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  font-size: 12px;
  color: var(--text-secondary);
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.legend-line {
  width: 24px;
  height: 2px;
  background: var(--primary);
}
.legend-line.legend-dashed {
  background: none;
  border-bottom: 2px dashed var(--text-muted);
}
</style>