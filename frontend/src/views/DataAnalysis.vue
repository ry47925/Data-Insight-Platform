<template>
  <div class="data-analysis">
    <!-- 1. 数据上传区域 -->
    <div class="card">
      <div class="card-title">
        <el-icon><UploadFilled /></el-icon>
        <span>数据上传</span>
      </div>
      <el-upload
        class="upload-area"
        drag
        :auto-upload="false"
        :show-file-list="false"
        :on-change="onFileChange"
        accept=".csv,.xlsx,.xls,.json"
        :disabled="uploadLoading"
        aria-label="上传数据文件进行分析"
      >
        <el-icon class="upload-icon" :size="48"><UploadFilled /></el-icon>
        <div class="upload-text">拖拽文件到此处，或 <em>点击上传</em></div>
        <div class="upload-hint">支持 CSV、Excel (.xlsx/.xls)、JSON 格式，最大 100MB</div>
      </el-upload>
      <div v-if="uploadFile" class="flex-center gap-sm mt-sm">
        <el-tag type="info" effect="plain">{{ uploadFile.name }}</el-tag>
        <el-button type="primary" size="small" @click="doUpload" :loading="uploadLoading">
          <el-icon><Upload /></el-icon>
          开始上传
        </el-button>
        <el-button size="small" @click="cancelUpload">取消</el-button>
      </div>
    </div>

    <!-- 2. 数据集选择区域 -->
    <div class="card">
      <div class="card-title">
        <el-icon><Folder /></el-icon>
        <span>选择数据集</span>
        <!-- 模块操作按钮统一放置在标题栏右侧 -->
        <div class="card-title-actions">
          <el-button type="warning" size="small" @click="generateReport" :loading="reportLoading" :disabled="!hasDataSource">
            <el-icon><Document /></el-icon>
            生成分析报告
          </el-button>
        </div>
      </div>
      <DataSourceSelector ref="dataSourceSelectorRef" module-source="data_analysis" @select="onSourceSelect" />
    </div>

    <!-- 3. 数据预览区域 -->
    <div class="card" v-if="hasDataSource">
      <div class="card-title">
        <el-icon><View /></el-icon>
        数据预览
      </div>
      <!-- Task 8: 全局搜索 + Task 14: 列管理 -->
      <div class="flex-center gap-sm" style="flex-wrap: wrap; margin-bottom: 10px;">
        <el-input v-model="searchKeyword" placeholder="搜索任意内容..." clearable style="width: 300px;">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-popover trigger="click" width="260" placement="bottom-start">
          <template #reference>
            <el-button>
              <el-icon><Setting /></el-icon>
              列管理
            </el-button>
          </template>
          <div style="max-height: 300px; overflow-y: auto;">
            <div style="margin-bottom: 8px; display: flex; justify-content: space-between;">
              <el-button size="small" text @click="showAllColumns">全选</el-button>
              <el-button size="small" text @click="hideAllColumns">全不选</el-button>
            </div>
            <el-checkbox
              v-for="col in tableColumns"
              :key="col"
              :model-value="!hiddenColumns.includes(col)"
              @change="(val) => toggleColumnVisibility(col, val)"
              style="display: block; margin-bottom: 4px;"
            >
              {{ columnDisplayNames[col] || col }}
            </el-checkbox>
          </div>
        </el-popover>
      </div>
      <div class="data-table-wrapper">
        <el-table
          :data="filteredTableData"
          border
          stripe
          style="width: 100%;"
          v-loading="tableLoading"
          empty-text="暂无数据"
          :row-class-name="tableRowClassName"
        >
          <el-table-column type="index" width="50" fixed />
          <el-table-column
            v-for="col in visibleTableColumns"
            :key="col"
            :prop="col"
            :label="columnDisplayNames[col] || col"
            min-width="120"
            show-overflow-tooltip
          />
        </el-table>
      </div>
      <div class="flex-center mt-sm" style="justify-content: flex-end;">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="totalRows"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="loadTableData"
          @size-change="loadTableData"
          small
          background
        />
      </div>
    </div>

    <!-- 4. 统计摘要区域 -->
    <div class="card" v-if="hasDataSource && stats">
      <div class="card-title">
        <el-icon><DataLine /></el-icon>
        统计摘要
      </div>

      <!-- Task 6: 数据质量概览卡片 -->
      <div v-if="quality" class="quality-overview mb-md">
        <h4 class="section-subtitle">数据质量概览</h4>
        <div class="stats-grid">
          <div class="stat-card">
            <div class="stat-value">{{ formatPercent(quality.overall_missing_rate) }}</div>
            <div class="stat-label">总体缺失率</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ quality.missing_columns_count ?? 0 }}</div>
            <div class="stat-label">含缺失值列数</div>
          </div>
          <div class="stat-card" :class="{'stat-card--danger': (quality.infinite_columns || []).length > 0}">
            <div class="stat-value">{{ (quality.infinite_columns || []).length }}</div>
            <div class="stat-label">含无穷大列数</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ quality.duplicate_rows ?? 0 }}</div>
            <div class="stat-label">重复行数</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">{{ (quality.constant_columns || []).length }}</div>
            <div class="stat-label">常量列数</div>
          </div>
        </div>
        <!-- 无穷大值红色警告 -->
        <el-alert
          v-if="quality.infinite_columns && quality.infinite_columns.length > 0"
          type="error"
          :closable="false"
          style="margin-top: 10px;"
        >
          <span>以下列包含无穷大值：{{ quality.infinite_columns.join('、') }}</span>
        </el-alert>
        <!-- 数据质量良好绿色提示 -->
        <el-alert
          v-if="isQualityGood"
          type="success"
          :closable="false"
          style="margin-top: 10px;"
        >
          <span>数据质量良好，未发现缺失、无穷大值或重复行问题</span>
        </el-alert>
      </div>

      <!-- 基本信息 -->
      <div class="stats-grid mb-md">
        <div class="stat-card">
          <div class="stat-value">{{ stats.row_count ?? '-' }}</div>
          <div class="stat-label">总行数</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ stats.column_count ?? '-' }}</div>
          <div class="stat-label">总列数</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ stats.numeric_count ?? '-' }}</div>
          <div class="stat-label">数值列</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ stats.categorical_count ?? '-' }}</div>
          <div class="stat-label">分类列</div>
        </div>
      </div>

      <!-- Task 14: 列信息表（含类型切换、重命名、排序） -->
      <div v-if="stats.columns && stats.columns.length > 0" class="mb-md">
        <div class="flex-center" style="justify-content: space-between; margin-bottom: 10px;">
          <h4 class="section-subtitle" style="margin-bottom: 0;">列信息</h4>
          <el-select v-model="columnSortBy" placeholder="排序方式" style="width: 160px;" clearable>
            <el-option label="按列名" value="name" />
            <el-option label="按类型" value="type" />
            <el-option label="按缺失率" value="missing_rate" />
          </el-select>
        </div>
        <el-table :data="sortedColumns" border size="small" style="width: 100%;" max-height="400">
          <el-table-column prop="name" label="列名" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">
              <span>{{ columnDisplayNames[row.name] || row.name }}</span>
              <el-icon class="rename-icon" @click="renameColumn(row.name)" title="重命名"><Edit /></el-icon>
            </template>
          </el-table-column>
          <!-- Task 13: 类型列（可点击切换） -->
          <el-table-column label="类型" width="100" align="center">
            <template #default="{ row }">
              <el-tag
                :type="getColumnType(row) === 'numeric' ? 'success' : 'warning'"
                style="cursor: pointer;"
                @click="toggleColumnType(row)"
              >
                {{ getColumnType(row) === 'numeric' ? '数值' : '分类' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="missing_count" label="缺失数" width="90" align="center" />
          <el-table-column label="缺失率" width="90" align="center">
            <template #default="{ row }">
              {{ formatPercent(row.missing_rate) }}
            </template>
          </el-table-column>
          <el-table-column label="完整性" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="getCompletenessLevel(row).type" size="small">
                {{ getCompletenessLevel(row).label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="唯一性" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="getUniquenessLevel(row).type" size="small">
                {{ getUniquenessLevel(row).label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="质量评分" width="100" align="center">
            <template #default="{ row }">
              <span :style="{ color: getQualityScoreColor(row), fontWeight: 600 }">
                {{ getQualityScore(row) }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- Task 7: 数值列统计（表格展示，风格与列信息表一致） -->
      <div v-if="stats.numeric_stats && Object.keys(stats.numeric_stats).length > 0" class="mb-md">
        <h4 class="section-subtitle">数值列统计</h4>
        <el-table :data="numericStatsTableData" border size="small" style="width: 100%;" max-height="400">
          <el-table-column prop="colName" label="列名" min-width="120" show-overflow-tooltip fixed />
          <el-table-column label="均值" min-width="90" align="center">
            <template #default="{ row }">{{ formatNum(row.mean) }}</template>
          </el-table-column>
          <el-table-column label="中位数" min-width="90" align="center">
            <template #default="{ row }">{{ formatNum(row.median) }}</template>
          </el-table-column>
          <el-table-column label="标准差" min-width="90" align="center">
            <template #default="{ row }">{{ formatNum(row.std) }}</template>
          </el-table-column>
          <el-table-column label="最小值" min-width="90" align="center">
            <template #default="{ row }">{{ formatNum(row.min) }}</template>
          </el-table-column>
          <el-table-column label="最大值" min-width="90" align="center">
            <template #default="{ row }">{{ formatNum(row.max) }}</template>
          </el-table-column>
          <el-table-column prop="missing_count" label="缺失数" min-width="80" align="center" />
          <el-table-column label="缺失率" min-width="80" align="center">
            <template #default="{ row }">{{ formatPercent(row.missing_rate) }}</template>
          </el-table-column>
          <el-table-column label="偏度" min-width="80" align="center">
            <template #default="{ row }">{{ formatNum(row.skewness) }}</template>
          </el-table-column>
          <el-table-column label="峰度" min-width="80" align="center">
            <template #default="{ row }">{{ formatNum(row.kurtosis) }}</template>
          </el-table-column>
          <el-table-column label="P90" min-width="80" align="center">
            <template #default="{ row }">{{ formatNum(row.p90) }}</template>
          </el-table-column>
          <el-table-column label="P95" min-width="80" align="center">
            <template #default="{ row }">{{ formatNum(row.p95) }}</template>
          </el-table-column>
          <el-table-column label="P99" min-width="80" align="center">
            <template #default="{ row }">{{ formatNum(row.p99) }}</template>
          </el-table-column>
          <el-table-column label="变异系数(CV)" min-width="110" align="center">
            <template #default="{ row }">{{ formatCV(row.cv) }}</template>
          </el-table-column>
          <el-table-column label="众数" min-width="80" align="center">
            <template #default="{ row }">{{ formatMode(row.mode) }}</template>
          </el-table-column>
          <el-table-column prop="zero_count" label="零值数" min-width="80" align="center" />
          <el-table-column label="零值率" min-width="80" align="center">
            <template #default="{ row }">{{ formatPercent(row.zero_rate) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 分类列统计（表格展示，风格与列信息表一致） -->
      <div v-if="stats.categorical_stats && Object.keys(stats.categorical_stats).length > 0">
        <h4 class="section-subtitle">分类列统计</h4>
        <el-table :data="categoricalStatsTableData" border size="small" style="width: 100%;" max-height="400">
          <el-table-column prop="colName" label="列名" min-width="140" show-overflow-tooltip fixed />
          <el-table-column prop="unique_count" label="唯一值数" min-width="90" align="center" />
          <el-table-column prop="missing_count" label="缺失数" min-width="80" align="center" />
          <el-table-column label="缺失率" min-width="80" align="center">
            <template #default="{ row }">{{ formatPercent(row.missing_rate) }}</template>
          </el-table-column>
          <el-table-column label="TOP 值" min-width="240">
            <template #default="{ row }">
              <div v-if="row.top_values && row.top_values.length > 0" class="top-values-inline">
                <span v-for="(item, idx) in row.top_values" :key="idx" class="top-value-inline-item">
                  <el-tag size="small" type="info">{{ item.value }}</el-tag>
                  <span class="top-value-count">{{ item.count }}</span>
                </span>
              </div>
              <span v-else style="color: var(--text-muted);">-</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- 5. 图表可视化区域 -->
    <div class="card" v-if="hasDataSource">
      <div class="card-title">
        <el-icon><Picture /></el-icon>
        图表可视化
      </div>

      <!-- 智能推荐区域 -->
      <div v-if="recommendations.length > 0" class="recommendation-wrapper mt-md">
        <!-- 折叠时的显示按钮 -->
        <el-button v-if="!showRecommendations" size="small" type="primary" plain @click="showRecommendations = true">
          <el-icon><MagicStick /></el-icon>
          显示智能推荐 ({{ recommendations.length }})
        </el-button>
        <!-- 展开时的推荐列表 -->
        <div v-if="showRecommendations" class="recommendation-section">
          <div class="flex-center gap-sm" style="margin-bottom: 10px;">
            <el-icon><MagicStick /></el-icon>
            <span style="font-weight: bold;">智能推荐</span>
            <el-button size="small" text @click="showRecommendations = false">隐藏</el-button>
          </div>
          <div v-if="recommendationLoading" class="empty-hint">加载推荐中...</div>
          <div v-else class="recommendation-list">
            <el-card
              v-for="(rec, index) in recommendations"
              :key="index"
              shadow="hover"
              class="recommendation-card"
              @click="applyRecommendation(rec)"
            >
              <div class="recommendation-content">
                <div class="flex-center gap-sm">
                  <el-tag :type="['success', 'warning', 'info', 'danger'][index % 4]">
                    {{ getRecommendationTypeLabel(rec.chart_type) }}
                  </el-tag>
                  <span class="recommendation-score">匹配度: {{ (rec.score * 100).toFixed(0) }}%</span>
                </div>
                <div class="recommendation-reason mt-sm">{{ rec.reason }}</div>
                <div class="recommendation-columns mt-sm">
                  <span class="text-muted">搭配:</span>
                  <el-tag size="small" type="info">{{ formatRecommendationColumns(rec.params) }}</el-tag>
                </div>
              </div>
            </el-card>
          </div>
        </div>
      </div>

      <!-- 图表类型选择（按分析目的分组，不支持的类型禁用并提示原因） -->
      <div class="chart-controls flex-center gap-sm" style="flex-wrap: wrap;">
        <el-select
          v-model="chartType"
          placeholder="选择图表类型"
          style="width: 180px;"
          @change="onChartTypeChange"
          aria-label="选择图表类型"
        >
          <el-option-group
            v-for="group in chartTypeGroups"
            :key="group.label"
            :label="group.label"
          >
            <el-option
              v-for="ctValue in group.options"
              :key="ctValue"
              :label="allChartTypeOptions.find(ct => ct.value === ctValue)?.label || ctValue"
              :value="ctValue"
              :disabled="!isChartTypeSupported(ctValue)"
            >
              <span :title="getChartTypeDisabledReason(ctValue)">
                {{ allChartTypeOptions.find(ct => ct.value === ctValue)?.label || ctValue }}
                <span v-if="!isChartTypeSupported(ctValue)" style="color: #999; margin-left: 4px;">（不支持）</span>
              </span>
            </el-option>
          </el-option-group>
        </el-select>

        <el-button
          v-if="hasDataSource"
          size="small"
          type="primary"
          plain
          :loading="recommendationLoading"
          @click="fetchRecommendations"
        >
          <el-icon><MagicStick /></el-icon>
          智能推荐
        </el-button>

        <!-- 图表参数面板 -->
        <div v-if="chartType" class="chart-param-panel">
          <div class="param-group">
            <div class="param-group-title">公共参数</div>
            <div v-for="param in currentChartParams.filter(p => ['showDataLabels', 'showLegend'].includes(p.key))" :key="param.key" class="param-item">
              <el-checkbox :model-value="chartParams[param.key] !== false" @change="val => chartParams[param.key] = val">
                {{ param.label }}
              </el-checkbox>
            </div>
          </div>
          
          <div class="param-group">
            <div class="param-group-title">图表参数</div>
            <div v-for="param in currentChartParams.filter(p => !['showDataLabels', 'showLegend'].includes(p.key))" :key="param.key" class="param-item">
              <el-select
                v-if="param.type === 'select'"
                v-model="chartParams[param.key]"
                :placeholder="param.label"
                :multiple="param.multiple"
                :clearable="param.clearable"
                style="width: 200px;"
                :aria-label="param.label"
              >
                <el-option
                  v-for="col in getParamOptions(param.options)"
                  :key="col"
                  :label="col"
                  :value="col"
                />
              </el-select>
              <el-input-number
                v-else-if="param.type === 'number'"
                v-model="chartParams[param.key]"
                :min="param.min"
                :placeholder="param.label"
                style="width: 150px;"
              />
            </div>
          </div>
        </div>

        <el-button type="primary" @click="generateChart" :loading="chartLoading" :disabled="!canGenerateChart">
          <el-icon><Search /></el-icon>
          生成图表
        </el-button>
        <el-button v-if="chartReady" type="success" @click="doExportChart" :loading="exportLoading">
          <el-icon><Download /></el-icon>
          导出图表
        </el-button>
        <el-button type="info" @click="addChartToReport" :disabled="!chartReady">
          <el-icon><Plus /></el-icon>
          添加到分析报告
        </el-button>
      </div>

      <!-- 图表渲染区 -->
      <div class="chart-container mt-md" ref="chartRef" v-show="chartReady"></div>
      <div v-if="!chartReady && chartError" class="empty-state">
        <div class="empty-text" style="color: var(--danger);">{{ chartError }}</div>
      </div>
      <div v-if="!chartReady && !chartError" class="empty-state">
        <div class="empty-icon"><el-icon :size="48"><TrendCharts /></el-icon></div>
        <div class="empty-text">请选择图表类型和列，然后点击"生成图表"</div>
      </div>

      <!-- 已添加到分析报告的图表列表 -->
      <div v-if="reportCharts.length > 0" class="report-charts mt-md">
        <div class="section-subtitle">已添加到分析报告的图表</div>
        <div class="report-chart-list">
          <el-card v-for="chart in reportCharts" :key="chart.id" shadow="hover" class="report-chart-card">
            <div class="report-chart-header">
              <span class="report-chart-title">{{ chart.title }}</span>
              <el-button type="danger" link size="small" @click="removeReportChart(chart.id)">
                <el-icon><Delete /></el-icon>
                删除
              </el-button>
            </div>
            <el-image :src="chart.image_base64" fit="contain" style="height: 120px; width: 100%;" />
          </el-card>
        </div>
      </div>
    </div>

    <!-- 7. 数据分析报告配置弹窗 -->
    <el-dialog v-model="reportConfigDialogVisible" title="数据分析报告配置" width="600px">
      <div
        class="report-config-section"
        v-for="module in reportModules"
        :key="module.key"
      >
        <!-- 模块总开关 -->
        <div class="report-module-header">
          <el-checkbox
            v-model="reportSections[module.key]"
            :disabled="module.key === 'charts' && reportCharts.length === 0"
          >
            {{ module.label }}
          </el-checkbox>
        </div>
        <!-- 模块子配置（仅在总开关勾选时显示） -->
        <div class="report-module-options" v-if="reportSections[module.key]">
          <!-- 数据预览：样本数据预览行数 -->
          <template v-if="module.key === 'dataPreview'">
            <div class="report-sub-section">
              <span class="sub-label">预览行数：</span>
              <el-input-number v-model="reportOptions.dataPreview.sampleRows" :min="0" :max="50" size="small" />
            </div>
          </template>

          <!-- 数据质量概览：选择显示哪些质量指标 -->
          <template v-if="module.key === 'quality'">
            <div class="report-sub-section">
              <el-checkbox-group v-model="reportOptions.quality.metrics">
                <el-checkbox label="missing_rate">总体缺失率</el-checkbox>
                <el-checkbox label="missing_columns">含缺失值列数</el-checkbox>
                <el-checkbox label="infinite_columns">含无穷大列数</el-checkbox>
                <el-checkbox label="duplicate_rows">重复行数</el-checkbox>
                <el-checkbox label="constant_columns">常量列数</el-checkbox>
                <el-checkbox label="row_count">总行数</el-checkbox>
                <el-checkbox label="column_count">总列数</el-checkbox>
                <el-checkbox label="numeric_count">数值列数</el-checkbox>
                <el-checkbox label="categorical_count">分类列数</el-checkbox>
              </el-checkbox-group>
            </div>
          </template>

          <!-- 列信息：固定展示所有列信息 -->
          <template v-if="module.key === 'columnInfo'">
            <div class="report-sub-section">
              <span class="sub-label">固定展示所有列的详细信息（列名、类型、缺失数、缺失率、完整性、唯一性、质量评分）</span>
            </div>
          </template>

          <!-- 数值列统计 -->
          <template v-if="module.key === 'numericStats'">
            <div class="report-sub-section">
              <el-checkbox-group v-model="reportOptions.numericStats.metrics">
                <el-checkbox label="mean">均值</el-checkbox>
                <el-checkbox label="median">中位数</el-checkbox>
                <el-checkbox label="std">标准差</el-checkbox>
                <el-checkbox label="min">最小值</el-checkbox>
                <el-checkbox label="max">最大值</el-checkbox>
                <el-checkbox label="missing_count">缺失数</el-checkbox>
                <el-checkbox label="missing_rate">缺失率</el-checkbox>
                <el-checkbox label="skewness">偏度</el-checkbox>
                <el-checkbox label="kurtosis">峰度</el-checkbox>
                <el-checkbox label="p90">P90</el-checkbox>
                <el-checkbox label="p95">P95</el-checkbox>
                <el-checkbox label="p99">P99</el-checkbox>
                <el-checkbox label="cv">变异系数(CV)</el-checkbox>
                <el-checkbox label="mode">众数</el-checkbox>
                <el-checkbox label="zero_count">零值数</el-checkbox>
                <el-checkbox label="zero_rate">零值率</el-checkbox>
              </el-checkbox-group>
            </div>
          </template>

          <!-- 分类列统计 -->
          <template v-if="module.key === 'categoricalStats'">
            <div class="report-sub-section">
              <el-checkbox-group v-model="reportOptions.categoricalStats.metrics">
                <el-checkbox label="unique_count">唯一值数</el-checkbox>
                <el-checkbox label="missing_count">缺失数</el-checkbox>
                <el-checkbox label="missing_rate">缺失率</el-checkbox>
                <el-checkbox label="top_values">TOP值</el-checkbox>
              </el-checkbox-group>
            </div>
            <div class="report-sub-section">
              <span class="sub-label">TOP值数量：</span>
              <el-input-number v-model="reportOptions.categoricalStats.topN" :min="1" :max="20" size="small" />
            </div>
          </template>

          <!-- 自定义图表：选择要包含的图表 -->
          <template v-if="module.key === 'charts'">
            <div class="report-sub-section">
              <el-checkbox-group v-model="selectedChartIds">
                <el-checkbox v-for="chart in reportCharts" :key="chart.id" :label="chart.id">
                  {{ chart.title || chart.type }}
                </el-checkbox>
              </el-checkbox-group>
              <div v-if="reportCharts.length === 0" class="empty-hint">暂无已添加的图表</div>
            </div>
          </template>


        </div>
      </div>
      <template #footer>
        <el-button @click="reportConfigDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmGenerateReport" :disabled="!hasSelectedReportSection">
          确认生成
        </el-button>
      </template>
    </el-dialog>

    <!-- 8. 数据分析报告预览弹窗 -->
    <el-dialog v-model="reportDialogVisible" title="数据分析报告预览" width="80%" top="5vh">
      <div v-if="reportLoading" style="text-align: center; padding: 50px;">
        <el-icon class="is-loading" :size="30"><Loading /></el-icon>
        <p>正在生成报告...</p>
      </div>
      <iframe v-else-if="reportHtml" :src="reportIframeUrl" class="report-preview-iframe"></iframe>
      <template #footer>
        <el-button @click="reportDialogVisible = false">关闭</el-button>
        <el-button type="success" @click="exportReport" :disabled="reportSaved">导出到数据管理</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, watch, onMounted, onBeforeUnmount, onDeactivated, onActivated, nextTick, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { UploadFilled, Upload, Refresh, DataLine, View, Download, Search, QuestionFilled, Picture, TrendCharts, Edit, Setting, Document, Loading, Plus, Delete, MagicStick } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import {
  uploadAnalysisFile,
  fetchAnalysisRawData,
  fetchAnalysisData,
  fetchAnalysisStats,
  fetchAnalysisQuality,
  fetchChartData,
  fetchChartRecommendations,
  generateAnalysisReport,
  saveAnalysisReport
} from '../api/index.js'
import { addTask } from '../stores/taskPanel.js'
import DataSourceSelector from '../components/DataSourceSelector.vue'

// DataSourceSelector组件引用，用于上传后调用reload刷新下拉框
const dataSourceSelectorRef = ref(null)

// ====== 上传 ======
const uploadFile = ref(null)
const uploadLoading = ref(false)

function onFileChange(file) {
  uploadFile.value = file.raw
}

function cancelUpload() {
  uploadFile.value = null
}

async function doUpload() {
  if (!uploadFile.value) return
  uploadLoading.value = true
  try {
    const res = await uploadAnalysisFile(uploadFile.value)
    ElMessage.success('文件上传成功')
    uploadFile.value = null
    // 刷新下拉框并自动选中新上传的数据集，避免用户在带时间戳的重名文件中难以辨认
    await dataSourceSelectorRef.value?.reload()
    await loadRawData()
    if (res.data && res.data.id) {
      dataSourceSelectorRef.value?.selectDataset(res.data.id)
      onSourceSelect({ mode: 'local', datasetId: res.data.id })
    } else if (analysisRawData.value.length > 0) {
      onSourceSelect({ mode: 'local', datasetId: analysisRawData.value[0].id })
    }
  } catch (e) {
    ElMessage.error(extractErrorMessage(e, '上传失败：'))
  } finally {
    uploadLoading.value = false
  }
}

// ====== 数据集列表 ======
const analysisRawData = ref([])
const rawDataLoading = ref(false)
const datasetId = ref(null)

// 数据源配置（本地/远程模式）
const sourceConfig = ref({ mode: 'local', datasetId: null, remote: null })

// 是否已有有效数据源选择
const hasDataSource = computed(() => {
  if (sourceConfig.value.mode === 'local') return !!sourceConfig.value.datasetId
  if (sourceConfig.value.mode === 'remote') return !!(sourceConfig.value.remote)
  return false
})

// 获取远程数据源配置（非远程模式返回 null）
function getRemoteConfig() {
  if (sourceConfig.value.mode === 'remote' && sourceConfig.value.remote) {
    return sourceConfig.value.remote
  }
  return null
}

async function loadRawData() {
  rawDataLoading.value = true
  try {
    const res = await fetchAnalysisRawData()
    analysisRawData.value = res.data || []
  } catch (e) {
    ElMessage.error(extractErrorMessage(e, '获取数据集列表失败：'))
  } finally {
    rawDataLoading.value = false
  }
}

function onDatasetChange(val) {
  // 清空之前的状态
  stats.value = null
  tableData.value = []
  tableColumns.value = []
  totalRows.value = 0
  currentPage.value = 1
  chartReady.value = false
  chartError.value = ''
  chartColumn.value = ''
  chartColumnX.value = ''
  chartColumnY.value = ''
  // 清空新增的图表列状态
  chartColumnY2.value = ''
  chartColumnSize.value = ''
  chartColumnsMultiple.value = []
  chartColumnValue.value = ''
  // 清空图表类型与参数
  chartType.value = ''
  Object.keys(chartParams).forEach(key => delete chartParams[key])
  // 清空智能推荐
  recommendations.value = []
  showRecommendations.value = false
  // 清空搜索、高亮、列操作状态
  searchKeyword.value = ''
  highlightedRowIndex.value = -1
  columnTypeOverrides.value = {}
  hiddenColumns.value = []
  columnDisplayNames.value = {}
  columnSortBy.value = ''
  // 清空质量数据
  quality.value = null
  // 清空报告状态
  if (reportIframeUrl.value) {
    URL.revokeObjectURL(reportIframeUrl.value)
    reportIframeUrl.value = ''
  }
  reportHtml.value = ''
  reportSaved.value = false
  reportDialogVisible.value = false
  reportConfigDialogVisible.value = false
  reportCharts.value = []

  if (val) {
    loadTableData()
    loadStats()
    loadQuality()
  }
}

// 数据源选择回调（DataSourceSelector 的 @select 事件）
function onSourceSelect(config) {
  if (config.mode === 'local') {
    datasetId.value = config.datasetId
    sourceConfig.value = { mode: 'local', datasetId: config.datasetId, remote: null }
    // 本地模式：利用现有 onDatasetChange 进行状态清理和数据加载
    if (config.datasetId) {
      onDatasetChange(config.datasetId)
    }
  } else {
    // 远程模式：先清理状态，再设置配置并加载数据
    onDatasetChange(null) // 清理状态，但不触发加载（val 为 null）
    sourceConfig.value = { mode: 'remote', datasetId: null, remote: config.remote }
    if (config.remote) {
      loadTableData()
      loadStats()
      loadQuality()
    }
  }
}

// ====== 数据预览 ======
const tableData = ref([])
const tableColumns = ref([])
const totalRows = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const tableLoading = ref(false)

// Task 8: 全局搜索
const searchKeyword = ref('')

// Task 12: 高亮行索引
const highlightedRowIndex = ref(-1)

// Task 14: 列隐藏/显示
const hiddenColumns = ref([])

// Task 14: 列重命名映射
const columnDisplayNames = ref({})

// 实时过滤表格数据
const filteredTableData = computed(() => {
  if (!searchKeyword.value || !searchKeyword.value.trim()) {
    return tableData.value
  }
  const keyword = searchKeyword.value.trim().toLowerCase()
  return tableData.value.filter(row => {
    return Object.values(row).some(val =>
      String(val).toLowerCase().includes(keyword)
    )
  })
})

// 可见表格列（排除隐藏列）
const visibleTableColumns = computed(() => {
  return tableColumns.value.filter(col => !hiddenColumns.value.includes(col))
})

// 表格行样式（高亮选中行）
function tableRowClassName({ rowIndex }) {
  if (rowIndex === highlightedRowIndex.value) {
    return 'row-highlight'
  }
  return ''
}

// 列显示/隐藏切换
function toggleColumnVisibility(col, visible) {
  if (visible) {
    hiddenColumns.value = hiddenColumns.value.filter(c => c !== col)
  } else {
    hiddenColumns.value = [...hiddenColumns.value, col]
  }
}

function showAllColumns() {
  hiddenColumns.value = []
}

function hideAllColumns() {
  hiddenColumns.value = [...tableColumns.value]
}

async function loadTableData() {
  if (!hasDataSource.value) return
  tableLoading.value = true
  try {
    const res = await fetchAnalysisData(datasetId.value, currentPage.value, pageSize.value, getRemoteConfig())
    const data = res.data
    if (data && data.rows) {
      tableData.value = data.rows
      tableColumns.value = data.columns || []
      totalRows.value = data.total || data.rows.length
    } else if (Array.isArray(data)) {
      tableData.value = data
      if (data.length > 0) {
        tableColumns.value = Object.keys(data[0])
      }
      totalRows.value = data.length
    }
  } catch (e) {
    ElMessage.error('获取数据预览失败')
  } finally {
    tableLoading.value = false
  }
}

// ====== 统计摘要 ======
const stats = ref(null)
const statsLoading = ref(false)

// Task 13: 列类型手动覆盖
const columnTypeOverrides = ref({})

// Task 14: 列排序方式
const columnSortBy = ref('')

// 获取列的当前类型（优先使用覆盖值）
function getColumnType(col) {
  if (columnTypeOverrides.value[col.name]) {
    return columnTypeOverrides.value[col.name]
  }
  return col.is_numeric ? 'numeric' : 'categorical'
}

// 切换列类型
function toggleColumnType(col) {
  const currentType = getColumnType(col)
  columnTypeOverrides.value = {
    ...columnTypeOverrides.value,
    [col.name]: currentType === 'numeric' ? 'categorical' : 'numeric'
  }
}

// 判断是否为常量列
function isConstantColumn(col) {
  if (!quality.value || !quality.value.constant_columns) return false
  return quality.value.constant_columns.includes(col.name)
}

// 获取列的唯一值数量
function getColumnUniqueCount(col) {
  // 优先从 basic_info.columns 取（所有列都有 unique_count，与类型切换/远程模式均兼容）
  const basicCol = stats.value?.columns?.find(c => c.name === col.name)
  if (basicCol && basicCol.unique_count !== null && basicCol.unique_count !== undefined) {
    return basicCol.unique_count
  }
  const colType = getColumnType(col)
  if (colType === 'categorical' && stats.value?.categorical_stats?.[col.name]) {
    return stats.value.categorical_stats[col.name].unique_count
  }
  if (colType === 'numeric' && stats.value?.numeric_stats?.[col.name]) {
    return stats.value.numeric_stats[col.name].unique_count
  }
  return null
}

// 获取完整性等级
function getCompletenessLevel(col) {
  if (isConstantColumn(col)) {
    return { label: '常量列', type: 'info' }
  }
  let missingRate = col.missing_rate ?? 0
  // 后端缺失率以 0-100 的百分比返回，统一换算为 0-1 的小数再分级
  if (missingRate > 1) {
    missingRate = missingRate / 100
  }
  if (missingRate === 0) {
    return { label: '高', type: 'success' }
  } else if (missingRate < 0.1) {
    return { label: '中', type: 'warning' }
  } else {
    return { label: '低', type: 'danger' }
  }
}

// 获取唯一性等级
function getUniquenessLevel(col) {
  if (isConstantColumn(col)) {
    return { label: '常量列', type: 'info' }
  }
  const uniqueCount = getColumnUniqueCount(col)
  if (uniqueCount === null || uniqueCount === undefined) {
    return { label: '-', type: 'info' }
  }
  const nonNullCount = (col.non_null_count ?? (stats.value?.row_count ?? 0) - (col.missing_count ?? 0))
  if (nonNullCount <= 0) {
    return { label: '-', type: 'info' }
  }
  const uniqueRatio = uniqueCount / nonNullCount
  if (uniqueRatio >= 0.9) {
    return { label: '高', type: 'success' }
  } else if (uniqueRatio >= 0.3) {
    return { label: '中', type: 'warning' }
  } else {
    return { label: '低', type: 'danger' }
  }
}

// 获取质量评分（0-100）
function getQualityScore(col) {
  if (isConstantColumn(col)) {
    return 30
  }
  let missingRate = col.missing_rate ?? 0
  if (missingRate > 1) {
    missingRate = missingRate / 100
  }
  missingRate = Math.max(0, Math.min(1, missingRate))
  const completenessScore = (1 - missingRate) * 60
  let uniquenessScore = 20
  const uniqueCount = getColumnUniqueCount(col)
  if (uniqueCount !== null && uniqueCount !== undefined) {
    const nonNullCount = Math.max(0, (col.non_null_count ?? (stats.value?.row_count ?? 0) - (col.missing_count ?? 0)))
    if (nonNullCount > 0) {
      const uniqueRatio = Math.max(0, Math.min(1, uniqueCount / nonNullCount))
      uniquenessScore = uniqueRatio * 20
    }
  }
  const isNumeric = getColumnType(col) === 'numeric'
  const typeScore = isNumeric ? 20 : 15
  const totalScore = completenessScore + uniquenessScore + typeScore
  return Math.max(0, Math.min(100, Math.round(totalScore)))
}

// 获取质量评分颜色
function getQualityScoreColor(col) {
  const score = getQualityScore(col)
  if (score >= 80) return '#10b981'
  if (score >= 60) return '#f59e0b'
  return '#ef4444'
}

// 列重命名
async function renameColumn(colName) {
  try {
    const { value } = await ElMessageBox.prompt(
      '此操作仅修改展示名称，不影响原始数据',
      '重命名列',
      {
        inputValue: columnDisplayNames.value[colName] || colName,
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        inputValidator: (val) => (!!val && val.trim() !== '') || '列名不能为空'
      }
    )
    if (value) {
      columnDisplayNames.value = {
        ...columnDisplayNames.value,
        [colName]: value.trim()
      }
      ElMessage.success('列名已更新')
    }
  } catch (e) {
    // 用户取消
  }
}

// 排序后的列信息
const sortedColumns = computed(() => {
  if (!stats.value || !stats.value.columns) return []
  const cols = [...stats.value.columns]
  if (columnSortBy.value === 'name') {
    cols.sort((a, b) => a.name.localeCompare(b.name))
  } else if (columnSortBy.value === 'type') {
    cols.sort((a, b) => getColumnType(a).localeCompare(getColumnType(b)))
  } else if (columnSortBy.value === 'missing_rate') {
    cols.sort((a, b) => (b.missing_rate || 0) - (a.missing_rate || 0))
  }
  return cols
})

// 数值列统计表格数据：每行一个数值列，风格与列信息表保持一致
const numericStatsTableData = computed(() => {
  if (!stats.value || !stats.value.numeric_stats) return []
  return Object.entries(stats.value.numeric_stats).map(([colName, stat]) => ({
    colName,
    ...stat
  }))
})

// 分类列统计表格数据：每行一个分类列，风格与列信息表保持一致
const categoricalStatsTableData = computed(() => {
  if (!stats.value || !stats.value.categorical_stats) return []
  return Object.entries(stats.value.categorical_stats).map(([colName, stat]) => ({
    colName,
    ...stat
  }))
})

async function loadStats() {
  if (!hasDataSource.value) return
  statsLoading.value = true
  try {
    const res = await fetchAnalysisStats(datasetId.value, getRemoteConfig())
    const data = res.data || res
    // 数据结构转换：将 basic_info 中的字段提升到顶层，方便模板使用
    if (data && data.basic_info) {
      stats.value = {
        ...data,
        row_count: data.basic_info.row_count,
        column_count: data.basic_info.column_count,
        columns: data.basic_info.columns,
        numeric_count: data.basic_info.numeric_count ?? Object.keys(data.numeric_stats || {}).length,
        categorical_count: data.basic_info.categorical_count ?? Object.keys(data.categorical_stats || {}).length
      }
    } else {
      stats.value = data
    }
  } catch (e) {
    ElMessage.error('获取统计摘要失败')
  } finally {
    statsLoading.value = false
  }
}

// ====== Task 6: 数据质量概览 ======
const quality = ref(null)

// 判断数据质量是否良好（无缺失、无无穷大、无重复行）
const isQualityGood = computed(() => {
  if (!quality.value) return false
  return (quality.value.missing_columns_count ?? 0) === 0 &&
         (quality.value.infinite_columns || []).length === 0 &&
         (quality.value.duplicate_rows ?? 0) === 0
})

async function loadQuality() {
  if (!hasDataSource.value) return
  try {
    const res = await fetchAnalysisQuality(datasetId.value, getRemoteConfig())
    quality.value = res.data || res
  } catch (e) {
    // 质量数据获取失败不阻塞主流程
    console.error('获取数据质量信息失败', e)
  }
}

// ====== 图表可视化 ======
const chartRef = ref(null)
const chartType = ref('')
const chartColumn = ref('')
const chartColumnX = ref('')
const chartColumnY = ref('')
const chartColumnY2 = ref('')
const chartColumnSize = ref('')
const chartColumnValue = ref('')
const chartColumnsMultiple = ref([])
const chartLoading = ref(false)
const chartReady = ref(false)
const chartError = ref('')
const exportLoading = ref(false)
let chartInstance = null

// 智能推荐相关
const recommendations = ref([])
const recommendationLoading = ref(false)
const showRecommendations = ref(true)
const supportedChartTypes = ref({})

// 图表参数配置定义
const chartParamConfig = {
  common: [
    // 默认开启数据标签，确保柱状图/折线图/饼图等按规范显示数值；用户可手动关闭
    { key: 'showDataLabels', type: 'boolean', label: '显示数据标签', default: true },
    { key: 'showLegend', type: 'boolean', label: '显示图例', default: true },
  ],
  single_column: [
    { key: 'columns', type: 'select', label: '选择列', multiple: true, clearable: true, options: 'numeric' },
  ],
  pie: [
    { key: 'column', type: 'select', label: '选择列', multiple: false, clearable: false, options: 'categorical' },
    { key: 'topN', type: 'number', label: 'TOP N', default: 10, min: 1 },
  ],
  qq: [
    { key: 'column', type: 'select', label: '选择列', multiple: false, clearable: false, options: 'numeric' },
  ],
  dual_column: [
    { key: 'x_column', type: 'select', label: 'X轴列', multiple: false, clearable: true, options: 'categorical_or_index' },
    { key: 'y_columns', type: 'select', label: 'Y轴列', multiple: true, clearable: true, options: 'numeric' },
    { key: 'topN', type: 'number', label: 'TOP N（柱状图）', default: 10, min: 1, condition: 'bar' },
  ],
  bubble: [
    { key: 'x_column', type: 'select', label: 'X轴列', multiple: false, clearable: false, options: 'numeric' },
    { key: 'y_column', type: 'select', label: 'Y轴列', multiple: false, clearable: false, options: 'numeric' },
    { key: 'size_column', type: 'select', label: '大小列', multiple: false, clearable: false, options: 'numeric' },
  ],
  dual_axis: [
    { key: 'x_column', type: 'select', label: 'X轴列', multiple: false, clearable: false, options: 'categorical' },
    { key: 'y1_column', type: 'select', label: 'Y1轴列', multiple: false, clearable: false, options: 'numeric' },
    { key: 'y2_column', type: 'select', label: 'Y2轴列', multiple: false, clearable: false, options: 'numeric' },
  ],
  multi_column: [
    { key: 'columns', type: 'select', label: '数值列', multiple: true, clearable: false, options: 'numeric' },
    { key: 'x_column', type: 'select', label: 'X轴列', multiple: false, clearable: true, options: 'categorical', condition: 'multi_line' },
  ],
  stacked_bar_group: [
    { key: 'x_column', type: 'select', label: 'X轴列', multiple: false, clearable: true, options: 'categorical' },
    { key: 'y_columns', type: 'select', label: 'Y轴列', multiple: true, clearable: false, options: 'numeric' },
  ],
  table_heatmap: [
    { key: 'x_column', type: 'select', label: '行', multiple: false, clearable: true, options: 'all' },
    { key: 'y_column', type: 'select', label: '列', multiple: false, clearable: true, options: 'all' },
    { key: 'value_column', type: 'select', label: '值列', multiple: false, clearable: true, options: 'numeric' },
  ],
  heatmap: [
    { key: 'columns', type: 'select', label: '数值列', multiple: true, clearable: true, options: 'numeric' },
  ],
}

// 图表类型到参数组的映射
const chartTypeParamGroups = {
  histogram: ['common', 'multi_column'],
  boxplot: ['common', 'multi_column'],
  pie: ['common', 'pie'],
  kde: ['common', 'multi_column'],
  qq: ['common', 'multi_column'],
  scatter: ['common', 'dual_column'],
  bar: ['common', 'dual_column'],
  area: ['common', 'dual_column'],
  bubble: ['common', 'bubble'],
  dual_axis: ['common', 'dual_axis'],
  stacked_bar: ['common', 'stacked_bar_group'],
  multi_line: ['common', 'multi_column'],
  radar: ['common', 'multi_column'],
  heatmap: ['common', 'heatmap'],
  table_heatmap: ['common', 'table_heatmap'],
}

// 图表参数响应式对象
const chartParams = reactive({})

// 获取当前图表类型的所有参数定义
const currentChartParams = computed(() => {
  const groups = chartTypeParamGroups[chartType.value] || []
  const params = []
  for (const group of groups) {
    const groupParams = chartParamConfig[group] || []
    for (const param of groupParams) {
      if (!param.condition || 
          (typeof param.condition === 'string' && param.condition === chartType.value) ||
          (Array.isArray(param.condition) && param.condition.includes(chartType.value))) {
        params.push(param)
      }
    }
  }
  return params
})

// 获取参数选项列表
function getParamOptions(optionsType) {
  switch (optionsType) {
    case 'numeric':
      return numericColumns.value
    case 'categorical':
      return categoricalColumns.value
    case 'categorical_or_index':
      return [...categoricalColumns.value, ...allColumns.value.filter(c => !categoricalColumns.value.includes(c))]
    case 'all':
    default:
      return allColumns.value
  }
}

// Task 10: 图表类型选项（当前共 15 种，line 已合并到 multi_line）
const allChartTypeOptions = [
  { value: 'histogram', label: '频数直方图' },
  { value: 'scatter', label: '散点图' },
  { value: 'boxplot', label: '箱线图' },
  { value: 'pie', label: '饼图' },
  { value: 'heatmap', label: '热力图' },
  { value: 'bar', label: '柱状图' },
  { value: 'stacked_bar', label: '堆叠柱状图' },
  { value: 'area', label: '面积图' },
  { value: 'kde', label: '单变量KDE密度图' },
  { value: 'qq', label: '标准化QQ图' },
  { value: 'bubble', label: '气泡图' },
  { value: 'multi_line', label: '多折线图' },
  { value: 'dual_axis', label: '双Y轴图' },
  { value: 'radar', label: '雷达图' },
  { value: 'table_heatmap', label: '表格热力图' }
]

// 图表类型按分析目的分组，用于下拉选择器分类展示
const chartTypeGroups = [
  {
    label: '数据分布',
    options: ['histogram', 'boxplot', 'kde', 'qq']
  },
  {
    label: '趋势与对比',
    options: ['area', 'multi_line', 'bar', 'stacked_bar', 'dual_axis']
  },
  {
    label: '变量关系',
    options: ['scatter', 'bubble', 'heatmap', 'table_heatmap']
  },
  {
    label: '占比构成',
    options: ['pie']
  },
  {
    label: '特殊图表',
    options: ['radar']
  }
]

// 获取图表类型标签，兼容旧代码对 chartTypeOptions 的查找
const chartTypeOptions = allChartTypeOptions

// 判断图表类型是否被当前数据集支持
function isChartTypeSupported(chartType) {
  const info = supportedChartTypes.value[chartType]
  return info ? info.supported === true : true
}

// 获取图表类型禁用提示
function getChartTypeDisabledReason(chartType) {
  const info = supportedChartTypes.value[chartType]
  if (info && info.reason) {
    return info.reason
  }
  return '当前数据集不支持该图表类型'
}

// 已添加到分析报告的图表列表
const reportCharts = ref([])

function buildChartTitle() {
  const option = chartTypeOptions.find(ct => ct.value === chartType.value)
  const label = option?.label || chartType.value
  const t = chartType.value
  const p = chartParams

  if (['histogram', 'boxplot', 'kde'].includes(t)) {
    const cols = p.columns || []
    return `${label}：${cols.join('、') || '数值列'}`
  }
  if (t === 'pie') {
    return `${label}：${p.column || ''}`
  }
  if (t === 'qq') {
    return `${label}：${p.column || ''}`
  }
  if (['scatter', 'bar', 'area'].includes(t)) {
    const yCols = p.y_columns || []
    const xName = p.x_column === '__index__' || !p.x_column ? '行索引' : p.x_column
    return `${label}：${xName} vs ${yCols.join('、') || ''}`
  }
  if (t === 'bubble') {
    return `${label}：${p.x_column || ''} vs ${p.y_column || ''}（大小：${p.size_column || ''}）`
  }
  if (t === 'dual_axis') {
    const xName = p.x_column === '__index__' || !p.x_column ? '行索引' : p.x_column
    return `${label}：${xName}（${p.y1_column || ''} / ${p.y2_column || ''}）`
  }
  if (t === 'stacked_bar') {
    const cols = p.y_columns || []
    const xName = p.x_column === '__index__' || !p.x_column ? '行索引' : p.x_column
    return `${label}：${xName} / ${cols.join('、')}`
  }
  if (t === 'multi_line') {
    const cols = p.columns || []
    const xName = p.x_column === '__index__' || !p.x_column ? '行索引' : p.x_column
    return `${label}：${xName} / ${cols.join('、')}`
  }
  if (t === 'radar') {
    const cols = p.columns || []
    return `${label}：${cols.join('、')}`
  }
  if (t === 'table_heatmap') {
    const parts = []
    if (p.x_column) parts.push(p.x_column)
    if (p.y_column) parts.push(p.y_column)
    if (p.value_column) parts.push(p.value_column)
    return `${label}：${parts.join(' × ') || '全表'}`
  }
  if (t === 'heatmap') {
    const cols = p.columns || []
    return `${label}：${cols.length > 0 ? cols.join('、') : '数值列相关性'}`
  }
  return label
}

// 校验当前图表参数是否满足数据集特征，不满足时给出具体提示
function validateChartParamsForData(t) {
  const nums = numericColumns.value
  const cats = categoricalColumns.value
  const usable = usableColumns.value

  const setError = (msg) => {
    chartError.value = msg
  }

  switch (t) {
    case 'histogram':
    case 'boxplot':
    case 'kde':
      if (nums.length === 0) setError('当前数据缺少数值列，无法生成此类图表')
      break
    case 'qq':
      if (nums.length === 0) setError('当前数据缺少数值列，无法生成 QQ 图')
      break
    case 'pie':
      if (cats.length === 0) setError('当前数据缺少分类列，无法生成饼图')
      break
    case 'scatter':
      if (nums.length < 2) setError('散点图至少需要 2 个数值列，当前数据不足')
      break
    case 'bubble':
      if (nums.length < 3) setError('气泡图至少需要 3 个数值列，当前数据不足')
      break
    case 'heatmap':
      if (nums.length < 2) setError('热力图至少需要 2 个数值列，当前数据不足')
      break
    case 'radar':
      if (nums.length < 3) setError('雷达图至少需要 3 个数值列，当前数据不足')
      break
    case 'bar':
    case 'stacked_bar':
      if (cats.length === 0 || nums.length === 0) setError('柱状图需要至少 1 个分类列和 1 个数值列')
      break
    case 'area':
      if (nums.length === 0) setError('当前数据缺少数值列，无法生成该图表')
      break
    case 'multi_line':
      if (nums.length < 1) setError('多折线图至少需要 1 个数值列，当前数据不足')
      break
    case 'dual_axis':
      if (nums.length < 2) setError('双 Y 轴图至少需要 2 个数值列，当前数据不足')
      break
    default:
      break
  }
}

// 统一提取后端错误信息，按 message → detail → e.message 优先级读取
function extractErrorMessage(e, defaultPrefix = '') {
  const msg = e?.response?.data?.message || e?.response?.data?.detail || e?.message || '未知错误'
  return defaultPrefix ? defaultPrefix + msg : msg
}

// 将当前已生成的图表添加到分析报告
function addChartToReport() {
  if (!chartReady.value || !chartInstance) return
  const imageBase64 = chartInstance.getDataURL({ type: 'png', pixelRatio: 2 })
  reportCharts.value.push({
    id: Date.now() + Math.random().toString(36).slice(2),
    type: chartType.value,
    params: buildChartParams(),
    title: buildChartTitle(),
    image_base64: imageBase64
  })
  ElMessage.success('已添加到分析报告')
}

// 从分析报告列表中移除单个图表
function removeReportChart(id) {
  reportCharts.value = reportCharts.value.filter(chart => chart.id !== id)
}

// 获取统计信息中的列列表（兼容后端返回的嵌套结构）
function getStatsColumns() {
  if (stats.value && stats.value.columns) {
    return stats.value.columns
  }
  if (stats.value && stats.value.basic_info && stats.value.basic_info.columns) {
    return stats.value.basic_info.columns
  }
  return null
}

// 所有可用列（从 stats 或 tableColumns 中获取）
const allColumns = computed(() => {
  const cols = getStatsColumns()
  if (cols) {
    return cols.map(c => c.name)
  }
  return tableColumns.value
})

// 判断列是否适合用于图表（排除常量列和缺失过多的列）
function isChartUsableColumn(c) {
  if (!c) return false
  // 常量列不适合做图
  if (c.is_constant) return false
  // 缺失值超过 50% 的列不适合做图
  if (c.missing_too_many) return false
  return true
}

// 数值列（优先使用手动覆盖的类型，同时排除常量/缺失过多列）
const numericColumns = computed(() => {
  const cols = getStatsColumns()
  if (cols) {
    return cols.filter(c => getColumnType(c) === 'numeric' && isChartUsableColumn(c)).map(c => c.name)
  }
  return []
})

// 分类列（优先使用手动覆盖的类型，同时排除常量/缺失过多列）
const categoricalColumns = computed(() => {
  const cols = getStatsColumns()
  if (cols) {
    return cols.filter(c => getColumnType(c) === 'categorical' && isChartUsableColumn(c)).map(c => c.name)
  }
  return []
})

// 所有可用于图表的列（排除常量/缺失过多列）
const usableColumns = computed(() => {
  const cols = getStatsColumns()
  if (cols) {
    return cols.filter(c => isChartUsableColumn(c)).map(c => c.name)
  }
  return []
})

const canGenerateChart = computed(() => {
  const t = chartType.value
  if (!t) return false

  if (['histogram', 'boxplot', 'kde', 'qq'].includes(t)) {
    return chartParams.columns === undefined || chartParams.columns.length > 0
  }
  if (t === 'pie') {
    return !!chartParams.column
  }
  if (['scatter', 'bar', 'area'].includes(t)) {
    // X 轴为空时后端自动使用行索引，因此只需校验 Y 轴
    return (chartParams.y_columns === undefined || chartParams.y_columns.length > 0)
  }
  if (t === 'dual_axis') {
    return !!chartParams.y1_column && !!chartParams.y2_column
  }
  if (t === 'bubble') {
    return !!chartParams.x_column && !!chartParams.y_column && !!chartParams.size_column
  }
  if (t === 'stacked_bar') {
    return (chartParams.y_columns === undefined || chartParams.y_columns.length > 0) && !!chartParams.x_column
  }
  if (t === 'multi_line') {
    return chartParams.columns === undefined || chartParams.columns.length > 0
  }
  if (t === 'radar') {
    return chartParams.columns === undefined || chartParams.columns.length > 0
  }
  if (t === 'heatmap') {
    return numericColumns.value.length >= 2
  }
  if (t === 'table_heatmap') {
    return true
  }
  return false
})

function initChartParams() {
  Object.keys(chartParams).forEach(key => delete chartParams[key])
  for (const param of currentChartParams.value) {
    if (param.default !== undefined) {
      chartParams[param.key] = param.default
    }
  }
}

function onChartTypeChange() {
  chartColumn.value = ''
  chartColumnX.value = ''
  chartColumnY.value = ''
  chartColumnY2.value = ''
  chartColumnSize.value = ''
  chartColumnsMultiple.value = []
  chartColumnValue.value = ''
  chartReady.value = false
  chartError.value = ''

  initChartParams()

  const t = chartType.value
  const nums = numericColumns.value
  const cats = categoricalColumns.value
  const usable = usableColumns.value

  if (['histogram', 'boxplot', 'kde', 'qq'].includes(t)) {
    chartParams.columns = nums.slice(0, 3)
  } else if (t === 'pie') {
    if (cats.length > 0) chartParams.column = cats[0]
  } else if (t === 'scatter') {
    chartParams.x_column = nums[0] || ''
    chartParams.y_columns = nums.slice(1, 2)
  } else if (t === 'bar') {
    chartParams.x_column = cats[0] || ''
    chartParams.y_columns = nums.slice(0, 1)
  } else if (t === 'bubble') {
    chartParams.x_column = nums[0] || ''
    chartParams.y_column = nums[1] || nums[0] || ''
    chartParams.size_column = nums[2] || nums[1] || nums[0] || ''
  } else if (t === 'multi_line') {
    // 多折线图兼容单条/多条折线：至少 1 个有效数值列
    if (nums.length >= 1) {
      chartParams.x_column = ''
      chartParams.columns = nums.slice(0, Math.min(nums.length, 3))
    } else {
      chartParams.x_column = ''
      chartParams.columns = []
      chartError.value = '多折线图至少需要 1 个有效数值列，当前数据不足'
    }
  } else if (t === 'dual_axis') {
    if (nums.length >= 2) {
      chartParams.x_column = ''
      chartParams.y1_column = nums[0]
      chartParams.y2_column = nums[1]
    } else {
      chartParams.x_column = ''
      chartParams.y1_column = ''
      chartParams.y2_column = ''
      chartError.value = '双 Y 轴图至少需要 2 个有效数值列，当前数据不足'
    }
  } else if (t === 'radar') {
    chartParams.columns = nums.slice(0, 3)
  } else if (t === 'stacked_bar') {
    chartParams.y_columns = nums.slice(0, 3)
    chartParams.x_column = cats[0] || ''
  } else if (t === 'area') {
    // 没有合适分类列时默认使用行索引作为 X 轴
    chartParams.x_column = ''
    chartParams.y_columns = nums.slice(0, 1)
  }

  // 同步 chartParams 到独立的 ref，供 buildChartOption 使用
  chartColumn.value = chartParams.column || chartParams.columns?.[0] || ''
  chartColumnX.value = chartParams.x_column || ''
  chartColumnY.value = chartParams.y_columns?.[0] || chartParams.y_column || chartParams.y1_column || ''
  chartColumnY2.value = chartParams.y2_column || ''
  chartColumnSize.value = chartParams.size_column || ''
  chartColumnsMultiple.value = chartParams.columns || []
  chartColumnValue.value = chartParams.value_column || ''

  // 自动填充参数后，校验当前数据是否满足该图表类型的最低要求
  validateChartParamsForData(t)
}

function buildChartParams() {
  const params = { ...chartParams }
  return params
}

async function generateChart() {
  if (!canGenerateChart.value) return
  chartLoading.value = true
  chartReady.value = false
  chartError.value = ''

  // 同步 chartParams 到 ref，确保标题和轴名使用用户在参数面板中的最新选择
  chartColumn.value = chartParams.column || chartParams.columns?.[0] || ''
  chartColumnX.value = chartParams.x_column || ''
  chartColumnY.value = chartParams.y_columns?.[0] || chartParams.y_column || chartParams.y1_column || ''
  chartColumnY2.value = chartParams.y2_column || ''
  chartColumnSize.value = chartParams.size_column || ''
  chartColumnsMultiple.value = chartParams.columns || []
  chartColumnValue.value = chartParams.value_column || ''

  // 发送请求前再次校验数据与参数匹配性
  validateChartParamsForData(chartType.value)
  if (chartError.value) {
    chartLoading.value = false
    return
  }

  // 校验 X 轴列不能与 Y 轴列重复
  const xCol = chartParams.x_column || ''
  const yCols = new Set([
    ...(chartParams.y_columns || []),
    ...(chartParams.columns || []),
    chartParams.y_column,
    chartParams.y1_column,
    chartParams.y2_column,
    chartParams.size_column,
    chartParams.value_column
  ].filter(Boolean))
  if (xCol && yCols.has(xCol)) {
    chartError.value = `X 轴列 '${xCol}' 不能同时作为 Y 轴/数值列，请调整参数`
    chartLoading.value = false
    return
  }

  try {
    const params = buildChartParams()
    const config = {
      chart_type: chartType.value,
      params: params
    }

    const res = await fetchChartData(datasetId.value, config, getRemoteConfig())
    const chartData = res.data || res

    chartReady.value = true
    chartError.value = ''
    await nextTick()
    renderChart(chartData)
  } catch (e) {
    chartReady.value = false
    chartError.value = extractErrorMessage(e, '生成图表失败：')
    ElMessage.error(chartError.value)
  } finally {
    chartLoading.value = false
  }
}

// 获取图表智能推荐
async function fetchRecommendations() {
  if (!hasDataSource.value) return
  recommendationLoading.value = true
  try {
    const res = await fetchChartRecommendations(datasetId.value, null, null, getRemoteConfig())
    recommendations.value = res.data?.recommendations || []
    supportedChartTypes.value = res.data?.supported_chart_types || {}
    showRecommendations.value = true
  } catch (e) {
    console.error('获取图表推荐失败', e)
    recommendations.value = []
    supportedChartTypes.value = {}
  } finally {
    recommendationLoading.value = false
  }
}

// 获取推荐卡片的图表类型中文标签，兼容旧版 line 推荐
function getRecommendationTypeLabel(chartType) {
  if (chartType === 'line') return '多折线图'
  return chartTypeOptions.find(ct => ct.value === chartType)?.label || chartType
}

// 格式化推荐卡片的列信息，例如：X轴：部门，Y轴：销售额、利润
function formatRecommendationColumns(params) {
  const xCol = params?.x_column || ''
  const yCols = new Set()
  ;['y_columns', 'columns'].forEach(key => {
    const arr = params?.[key]
    if (Array.isArray(arr)) {
      arr.forEach(c => { if (c && c !== xCol) yCols.add(c) })
    }
  })
  ;['y_column', 'y1_column', 'y2_column', 'size_column', 'value_column', 'column'].forEach(key => {
    const c = params?.[key]
    if (c && c !== xCol) yCols.add(c)
  })
  const yList = [...yCols]
  if (xCol && yList.length > 0) {
    return `X轴：${xCol}，Y轴：${yList.join('、')}`
  }
  if (xCol) {
    return `X轴：${xCol}`
  }
  if (yList.length > 0) {
    return `Y轴：${yList.join('、')}`
  }
  return ''
}

// 应用推荐配置
function applyRecommendation(recommendation) {
  // 折线图已合并到多折线图，旧推荐做兼容转换
  if (recommendation.chart_type === 'line') {
    recommendation = { ...recommendation, chart_type: 'multi_line' }
    const params = recommendation.params || {}
    if (params.y_columns && !params.columns) {
      params.columns = params.y_columns
    }
  }
  const params = recommendation.params || {}
  // 提取推荐参数中涉及的所有列名
  const requiredCols = new Set()
  ;['column', 'x_column', 'y_column', 'y1_column', 'y2_column', 'size_column', 'value_column'].forEach(key => {
    if (params[key]) requiredCols.add(params[key])
  })
  ;['columns', 'y_columns'].forEach(key => {
    if (Array.isArray(params[key])) params[key].forEach(c => requiredCols.add(c))
  })

  const availableCols = new Set(allColumns.value)
  const missing = [...requiredCols].filter(c => !availableCols.has(c))
  if (missing.length > 0) {
    ElMessage.warning(`当前数据集缺少推荐列：${missing.join('、')}，请重新生成推荐`)
    return
  }

  chartType.value = recommendation.chart_type
  Object.keys(params).forEach(key => {
    chartParams[key] = params[key]
  })

  // 兜底清洗：确保应用推荐后 X 轴列不会与 Y 轴列重叠
  const xCol = chartParams.x_column || ''
  if (xCol) {
    let removed = []
    ;['y_columns', 'columns'].forEach(key => {
      const arr = chartParams[key]
      if (Array.isArray(arr)) {
        const beforeLen = arr.length
        chartParams[key] = arr.filter(c => c && c !== xCol)
        if (chartParams[key].length < beforeLen) {
          removed.push(xCol)
        }
      }
    })
    ;['y_column', 'y1_column', 'y2_column', 'size_column', 'value_column'].forEach(key => {
      if (chartParams[key] === xCol) {
        chartParams[key] = ''
        removed.push(xCol)
      }
    })
    removed = [...new Set(removed)]
    if (removed.length > 0) {
      ElMessage.info(`已自动移除与 X 轴重复的列：${removed.join('、')}`)
    }
    // 清洗后检查是否还有有效 Y 轴列
    const hasY = ['y_columns', 'columns'].some(key => Array.isArray(chartParams[key]) && chartParams[key].length > 0) ||
                 ['y_column', 'y1_column', 'y2_column', 'size_column', 'value_column'].some(key => chartParams[key])
    if (!hasY) {
      ElMessage.warning('该推荐参数清洗后没有可用的数值列，请手动调整')
      return
    }
  }

  // 点击推荐后保持推荐区域显示，方便用户切换其他推荐
  nextTick(() => {
    generateChart()
  })
}

function renderChart(data) {
  if (!chartRef.value) return

  // 销毁旧实例
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }

  chartInstance = echarts.init(chartRef.value)
  let option = buildChartOption(chartType.value, data)
  option = applyChartCommonOptions(option, chartType.value)
  chartInstance.setOption(option)
  chartInstance.resize()

  // Task 12: 点击图表数据点高亮表格行
  chartInstance.off('click')
  chartInstance.on('click', (params) => {
    if (params.dataIndex !== undefined && params.dataIndex >= 0) {
      highlightedRowIndex.value = params.dataIndex
    }
  })

  // 响应式调整：先移除旧监听器再添加，防止多次生成图表时监听器堆积
  window.removeEventListener('resize', handleResize)
  window.addEventListener('resize', handleResize)
}

function handleResize() {
  chartInstance?.resize()
}

// Task 12: dataZoom 配置（仅用于有X轴的图表）
function getBaseDataZoom() {
  return [
    { type: 'inside', start: 0, end: 100 },
    { type: 'slider', start: 0, end: 100 }
  ]
}

function buildChartOption(type, data) {
  switch (type) {
    case 'histogram': {
      const hasSeries = data.series && data.series.length > 0
      const seriesColors = ['#4361ee', '#e63946', '#2a9d8f', '#f4a261', '#9b5de5', '#00bbf9', '#ff006e', '#fb5607']
      return {
        title: { text: '频数直方图', left: 'center' },
        tooltip: { trigger: 'axis' },
        dataZoom: getBaseDataZoom(),
        legend: hasSeries ? { icon: 'circle' } : undefined,
        xAxis: { type: 'category', data: data.labels || [], axisLabel: { rotate: 30 } },
        yAxis: { type: 'value', name: '频数' },
        series: hasSeries ? data.series.map((s, i) => ({
          name: s.name,
          type: 'bar',
          data: s.values || [],
          itemStyle: { color: seriesColors[i % seriesColors.length] },
          barGap: 0,
          barCategoryGap: '10%'
        })) : [{ type: 'bar', data: data.values || [], itemStyle: { color: '#4361ee' } }]
      }
    }
    case 'scatter':
      return {
        title: { text: chartColumnX.value + ' vs ' + chartColumnY.value, left: 'center' },
        tooltip: { trigger: 'item', formatter: '{b}: ({c})' },
        xAxis: { type: 'value', name: chartColumnX.value },
        yAxis: { type: 'value', name: chartColumnY.value },
        series: [{
          type: 'scatter',
          data: (data.x || []).map((xi, i) => [xi, (data.y || [])[i]]),
          symbolSize: 8,
          itemStyle: { color: '#4361ee' }
        }]
      }
    case 'boxplot': {
      // 使用单个 boxplot series，避免多 series 导致的图例筛选/越界问题；
      // 图例仅作展示，不支持点击筛选。
      const rawSeries = data.series || []
      const seriesColors = ['#4361ee', '#e63946', '#2a9d8f', '#f4a261', '#9b5de5', '#00bbf9', '#ff006e', '#fb5607']
      const categoryNames = rawSeries.map(s => s.name)
      const boxData = []
      const outlierData = []
      rawSeries.forEach((s, i) => {
        const d = s.data || []
        const color = seriesColors[i % seriesColors.length]
        boxData.push({
          value: [d[0], d[1], d[2], d[3], d[4]],
          name: s.name,
          itemStyle: { color: color + '60', borderColor: color, borderWidth: 2 }
        })
        const outliers = d[5] || []
        outliers.forEach(val => {
          outlierData.push({
            value: [s.name, val],
            itemStyle: { color: color }
          })
        })
      })
      return {
        title: { text: '箱线图', left: 'center' },
        tooltip: {
          trigger: 'item',
          formatter: p => {
            if (p.seriesType === 'scatter') {
              return `<strong>${p.value[0]}</strong><br/>异常值: ${p.value[1]}`
            }
            return `<strong>${p.name}</strong><br/>
              最小值: ${p.value[0]}<br/>
              Q1: ${p.value[1]}<br/>
              中位数: ${p.value[2]}<br/>
              Q3: ${p.value[3]}<br/>
              最大值: ${p.value[4]}`
          }
        },
        legend: {
          data: categoryNames.map((name, i) => ({
            name,
            icon: 'circle',
            itemStyle: { color: seriesColors[i % seriesColors.length] }
          })),
          selectedMode: false
        },
        xAxis: { type: 'category', data: categoryNames },
        yAxis: { type: 'value' },
        series: [
          {
            type: 'boxplot',
            data: boxData,
            boxWidth: [16, 32]
          },
          {
            type: 'scatter',
            data: outlierData,
            symbolSize: 6
          }
        ]
      }
    }
    case 'pie':
      return {
        title: { text: chartColumn.value + ' 饼图', left: 'center', top: 10 },
        tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
        legend: { top: 'bottom', type: 'scroll' },
        series: [{
          type: 'pie',
          radius: ['40%', '70%'],
          center: ['50%', '45%'],
          data: (data.labels || []).map((label, i) => ({
            name: label,
            value: (data.values || [])[i]
          })),
          emphasis: {
            itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0, 0, 0, 0.5)' }
          }
        }]
      }
    case 'heatmap': {
      // 热力图：data.data 应为相关矩阵二维数组
      const heatData = []
      const labels = data.labels || []
      const matrix = data.data || []
      const maxVal = matrix.flat().reduce((m, v) => Math.max(m, Math.abs(v)), 0) || 1

      for (let i = 0; i < matrix.length; i++) {
        for (let j = 0; j < (matrix[i]?.length || 0); j++) {
          heatData.push([j, i, matrix[i][j]])
        }
      }

      return {
        title: { text: '热力图', left: 'center' },
        tooltip: { position: 'top' },
        xAxis: { type: 'category', data: labels, axisLabel: { rotate: 45 } },
        yAxis: { type: 'category', data: labels },
        visualMap: {
          min: -maxVal,
          max: maxVal,
          calculable: true,
          orient: 'horizontal',
          left: 'center',
          bottom: 0
        },
        series: [{
          type: 'heatmap',
          data: heatData,
          label: { show: true, formatter: p => p.value[2].toFixed(2) },
          emphasis: {
            itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.5)' }
          }
        }]
      }
    }
    // ====== Task 10: 新增图表类型渲染 ======
    case 'bar': {
      const hasSeries = data.series && data.series.length > 0
      const seriesColors = ['#4361ee', '#e63946', '#2a9d8f', '#f4a261', '#9b5de5', '#00bbf9', '#ff006e', '#fb5607']
      
      if (hasSeries && data.dual_axis_needed) {
        // 双 Y 轴柱状图：后端返回 labels（X 轴类别）与 series（含 name/values），
        // 首个系列置于左轴，其余系列置于右轴（量纲差异大时避免互相压制）
        return {
          title: { text: '双Y轴柱状图', left: 'center' },
          tooltip: { trigger: 'axis' },
          dataZoom: getBaseDataZoom(),
          legend: { top: 30 },
          xAxis: { type: 'category', data: data.labels || [], axisLabel: { rotate: 30 } },
          yAxis: [
            { type: 'value', name: '左侧', position: 'left' },
            { type: 'value', name: '右侧', position: 'right' }
          ],
          series: data.series.map((s, i) => ({
            name: s.name,
            type: 'bar',
            data: s.values || [],
            yAxisIndex: i === 0 ? 0 : 1,
            itemStyle: { color: seriesColors[i % seriesColors.length] },
            barGap: 0,
            barCategoryGap: '10%'
          }))
        }
      }
      
      const categories = data.categories || data.labels || []
      const values = data.values || []
      let finalCategories = categories
      let finalValues = values
      if (categories.length > 10) {
        finalCategories = [...categories.slice(0, 9), '其他']
        const otherValue = values.slice(9).reduce((sum, v) => sum + (Number(v) || 0), 0)
        finalValues = [...values.slice(0, 9), otherValue]
      }
      return {
        title: { text: chartColumnY.value + ' by ' + chartColumnX.value, left: 'center' },
        tooltip: { trigger: 'axis' },
        dataZoom: getBaseDataZoom(),
        xAxis: { type: 'category', data: finalCategories, axisLabel: { rotate: 30 } },
        yAxis: { type: 'value', name: chartColumnY.value },
        series: hasSeries ? data.series.map((s, i) => ({
          name: s.name,
          type: 'bar',
          data: s.values || [],
          itemStyle: { color: seriesColors[i % seriesColors.length] },
          barGap: 0,
          barCategoryGap: '10%'
        })) : [{ type: 'bar', data: finalValues, itemStyle: { color: '#4361ee' } }]
      }
    }
    case 'stacked_bar':
      return {
        title: { text: '堆叠柱状图', left: 'center' },
        tooltip: { trigger: 'axis' },
        dataZoom: getBaseDataZoom(),
        legend: { top: 30 },
        xAxis: { type: 'category', data: data.categories || [], axisLabel: { rotate: 30 } },
        yAxis: { type: 'value' },
        series: (data.series || []).map(s => ({
          name: s.name,
          type: 'bar',
          stack: 'total',
          data: s.data || [],
          emphasis: { focus: 'series' }
        }))
      }
    case 'area': {
      const hasSeries = data.series && data.series.length > 0
      const seriesColors = ['#4361ee', '#e63946', '#2a9d8f', '#f4a261', '#9b5de5', '#00bbf9', '#ff006e', '#fb5607']

      return {
        title: { text: hasSeries ? '面积图' : chartColumnY.value + ' 趋势', left: 'center' },
        tooltip: { trigger: 'axis' },
        dataZoom: getBaseDataZoom(),
        legend: hasSeries ? { top: 30 } : undefined,
        xAxis: { type: 'category', data: data.x || data.labels || [], axisLabel: { rotate: 30 }, name: chartColumnX.value },
        yAxis: { type: 'value', name: hasSeries ? '' : chartColumnY.value },
        series: hasSeries ? data.series.map((s, i) => ({
          name: s.name,
          type: 'line',
          data: s.values || [],
          smooth: false,
          areaStyle: { color: seriesColors[i % seriesColors.length] + '30' },
          itemStyle: { color: seriesColors[i % seriesColors.length] }
        })) : [{
          type: 'line',
          data: data.y || data.values || [],
          smooth: false,
          areaStyle: { color: 'rgba(67, 97, 238, 0.3)' },
          itemStyle: { color: '#4361ee' }
        }]
      }
    }
    case 'kde': {
      const hasSeries = data.series && data.series.length > 0
      const seriesColors = ['#4361ee', '#e63946', '#2a9d8f', '#f4a261', '#9b5de5', '#00bbf9', '#ff006e', '#fb5607']
      return {
        title: { text: '单变量KDE密度图', left: 'center' },
        tooltip: { trigger: 'axis' },
        dataZoom: getBaseDataZoom(),
        legend: hasSeries ? { icon: 'circle' } : undefined,
        xAxis: { type: 'value', name: chartColumn.value },
        yAxis: { type: 'value', name: '密度' },
        series: hasSeries ? data.series.map((s, i) => ({
          name: s.name,
          type: 'line',
          data: (data.x || []).map((xi, idx) => [xi, (s.values || [])[idx]]),
          smooth: true,
          areaStyle: { color: seriesColors[i % seriesColors.length] + '30' },
          itemStyle: { color: seriesColors[i % seriesColors.length] }
        })) : [{
          type: 'line',
          data: (data.x || []).map((xi, i) => [xi, (data.y || [])[i]]),
          smooth: true,
          areaStyle: { color: 'rgba(67, 97, 238, 0.3)' },
          itemStyle: { color: '#4361ee' }
        }]
      }
    }
    case 'qq': {
      // QQ图：理论分位数 vs 样本分位数的散点 + 参考线（支持多列）
      const hasSeries = data.series && data.series.length > 0
      const seriesColors = ['#4361ee', '#e63946', '#2a9d8f', '#f4a261', '#9b5de5', '#00bbf9', '#ff006e', '#fb5607']
      
      let allVals = []
      if (hasSeries) {
        data.series.forEach(s => {
          allVals = [...allVals, ...(s.theoretical || []), ...(s.sample || [])]
        })
      } else {
        allVals = [...(data.theoretical || []), ...(data.sample || [])]
      }
      const minVal = allVals.length > 0 ? Math.min(...allVals) : 0
      const maxVal = allVals.length > 0 ? Math.max(...allVals) : 1
      
      const series = []
      if (hasSeries) {
        data.series.forEach((s, i) => {
          series.push({
            name: s.name,
            type: 'scatter',
            data: (s.theoretical || []).map((t, idx) => [t, (s.sample || [])[idx]]),
            symbolSize: 6,
            itemStyle: { color: seriesColors[i % seriesColors.length] }
          })
        })
      } else {
        series.push({
          type: 'scatter',
          data: (data.theoretical || []).map((t, i) => [t, (data.sample || [])[i]]),
          symbolSize: 6,
          itemStyle: { color: '#4361ee' }
        })
      }
      // 添加参考线
      series.push({
        type: 'line',
        data: [[minVal, minVal], [maxVal, maxVal]],
        symbol: 'none',
        lineStyle: { type: 'dashed', color: '#999' }
      })
      
      return {
        title: { text: '标准化 QQ 图', left: 'center' },
        tooltip: {
          trigger: 'item',
          formatter: p => {
            if (p.seriesName) {
              return `<strong>${p.seriesName}</strong><br/>理论分位数: ${p.value[0].toFixed(4)}<br/>样本分位数: ${p.value[1].toFixed(4)}`
            }
            return `理论分位数: ${p.value[0].toFixed(4)}<br/>样本分位数: ${p.value[1].toFixed(4)}`
          }
        },
        legend: hasSeries ? { icon: 'circle' } : undefined,
        xAxis: { type: 'value', name: '理论分位数', min: minVal, max: maxVal },
        yAxis: { type: 'value', name: '样本分位数', min: minVal, max: maxVal },
        series: series
      }
    }
    case 'bubble':
      return {
        title: { text: chartColumnY.value + ' vs ' + chartColumnX.value, left: 'center' },
        tooltip: {
          trigger: 'item',
          formatter: p => `${chartColumnX.value}: ${p.value[0]}<br/>${chartColumnY.value}: ${p.value[1]}<br/>${chartColumnSize.value}: ${p.value[2]}`
        },
        xAxis: { type: 'value', name: chartColumnX.value },
        yAxis: { type: 'value', name: chartColumnY.value },
        series: [{
          type: 'scatter',
          data: (data.x || []).map((xi, i) => [xi, (data.y || [])[i], (data.size || [])[i]]),
          symbolSize: val => Math.max(5, val[2] || 10),
          itemStyle: { color: '#4361ee', opacity: 0.7 }
        }]
      }
    case 'multi_line': {
      const seriesColors = ['#4361ee', '#e63946', '#2a9d8f', '#f4a261', '#9b5de5', '#00bbf9', '#ff006e', '#fb5607']

      return {
        title: { text: '多折线图', left: 'center' },
        tooltip: { trigger: 'axis' },
        dataZoom: getBaseDataZoom(),
        legend: { top: 30 },
        xAxis: { type: 'category', data: data.x || data.labels || [], axisLabel: { rotate: 30 }, name: chartColumnX.value },
        yAxis: { type: 'value' },
        series: (data.series || []).map((s, i) => ({
          name: s.name,
          type: 'line',
          data: s.values || s.data || [],
          smooth: false,
          itemStyle: { color: seriesColors[i % seriesColors.length] }
        }))
      }
    }
    case 'dual_axis':
      return {
        title: { text: '双Y轴图', left: 'center' },
        tooltip: { trigger: 'axis' },
        dataZoom: getBaseDataZoom(),
        legend: { top: 30 },
        xAxis: { type: 'category', data: data.x || [], axisLabel: { rotate: 30 } },
        yAxis: [
          { type: 'value', name: data.y1_name || chartColumnY.value, position: 'left' },
          { type: 'value', name: data.y2_name || chartColumnY2.value, position: 'right' }
        ],
        series: [
          { name: data.y1_name || chartColumnY.value, type: 'bar', data: data.y1 || [], itemStyle: { color: '#4361ee' } },
          { name: data.y2_name || chartColumnY2.value, type: 'line', data: data.y2 || [], yAxisIndex: 1, smooth: false, itemStyle: { color: '#e63946' } }
        ]
      }
    case 'radar': {
      // 雷达图：indicators 为维度名，series 为各样本数据
      const indicators = (data.indicators || []).map(name => ({ name: name, max: 100 }))
      return {
        title: { text: '雷达图', left: 'center' },
        tooltip: {},
        legend: { top: 30 },
        radar: { indicator: indicators },
        series: [{
          type: 'radar',
          data: (data.series || []).map(s => ({
            name: s.name,
            value: s.value || s.data || []
          }))
        }]
      }
    }
    case 'table_heatmap': {
      // 表格热力图：rows 为行标签，columns 为列标签，data 为二维值数组
      const rowLabels = data.rows || []
      const colLabels = data.columns || []
      const matrix = data.data || []
      const heatData = []
      let maxVal = 0
      let minVal = 0
      for (let i = 0; i < matrix.length; i++) {
        for (let j = 0; j < (matrix[i]?.length || 0); j++) {
          const val = matrix[i][j]
          if (val !== null && val !== undefined) {
            heatData.push([j, i, val])
            maxVal = Math.max(maxVal, val)
            minVal = Math.min(minVal, val)
          }
        }
      }
      // 单元格过多时隐藏数据标签，避免重叠；保留 tooltip 查看详情
      const cellCount = rowLabels.length * colLabels.length
      const showLabels = cellCount <= 100
      return {
        title: { text: '表格热力图', left: 'center' },
        tooltip: {
          position: 'top',
          formatter: p => `${rowLabels[p.value[1]]} × ${colLabels[p.value[0]]}: ${p.value[2] ?? 'N/A'}`
        },
        grid: { top: 50, right: 30, bottom: 80, left: 100 },
        xAxis: { type: 'category', data: colLabels, axisLabel: { rotate: 45, interval: 0 }, splitArea: { show: true } },
        yAxis: { type: 'category', data: rowLabels, axisLabel: { interval: 0 }, splitArea: { show: true } },
        visualMap: {
          min: minVal,
          max: maxVal,
          calculable: true,
          orient: 'horizontal',
          left: 'center',
          bottom: 20
        },
        series: [{
          type: 'heatmap',
          data: heatData,
          label: { show: showLabels, formatter: p => p.value[2] !== null ? p.value[2].toFixed(2) : 'N/A' },
          emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.5)' } },
          // 将单元格总数透传给统一标签处理函数，便于公共参数控制
          _cellCount: cellCount
        }]
      }
    }
    default:
      return {}
  }
}

// 统一应用图例和数据标签配置
// 公共参数"显示数据标签"需要对全部 15 种图表生效：
// - 线/柱/面积/直方图：柱顶/点顶显示数值
// - 饼图：扇形旁显示百分比
// - 热力图/表格热力图：单元格内显示数值（过多时自动隐藏）
// - 雷达图：顶点显示数值
// - 散点/气泡/QQ 图：数据点过多，默认仅在 emphasis 悬停时显示标签
// - 箱线图/KDE：不适合逐点标签，统一关闭，数据信息通过标题/tooltip 体现
function applyChartCommonOptions(option, type) {
  if (!option) return option

  // 图例配置
  const showLegend = chartParams.showLegend !== false
  if (showLegend) {
    if (!option.legend) option.legend = {}
    option.legend.show = true
    // 如果图表已自定义 legend 位置/图标，则不再强制 top:30；否则默认放在标题下方
    const hasCustomPosition = option.legend.bottom !== undefined || option.legend.top !== undefined
    if (!hasCustomPosition && !['pie', 'heatmap', 'table_heatmap'].includes(type)) {
      option.legend.top = 30
    }
  } else {
    option.legend = { show: false }
  }

  // 数据标签配置：未定义时按默认 true 处理（与参数面板默认值一致）
  const showDataLabels = chartParams.showDataLabels !== false
  const seriesArray = option.series ? (Array.isArray(option.series) ? option.series : [option.series]) : []
  if (!seriesArray.length) return option

  // 为每个 series 初始化 label 对象
  seriesArray.forEach(s => {
    if (!s.label) s.label = {}
  })

  // 支持逐点标签的图表类型
  const pointLabelTypes = ['bar', 'stacked_bar', 'multi_line', 'area', 'dual_axis', 'histogram']
  // 散点类图表：用 emphasis 标签避免数据密集时重叠
  const scatterLikeTypes = ['scatter', 'bubble', 'qq']

  if (showDataLabels) {
    if (pointLabelTypes.includes(type)) {
      seriesArray.forEach(s => {
        s.label.show = true
        s.label.position = 'top'
        s.label.fontSize = 10
        s.label.color = '#666'
        s.label.formatter = '{c}'
        s.label.hideOverlap = true
      })
    } else if (type === 'pie') {
      seriesArray.forEach(s => {
        s.label.show = true
        s.label.formatter = '{b}: {d}%'
        s.label.fontSize = 11
      })
    } else if (type === 'heatmap') {
      seriesArray.forEach(s => {
        s.label.show = true
        s.label.formatter = p => {
          const v = p.value[2]
          return typeof v === 'number' ? v.toFixed(2) : v
        }
      })
    } else if (type === 'table_heatmap') {
      seriesArray.forEach(s => {
        // 单元格超过 100 时强制隐藏，避免重叠
        const cellCount = s._cellCount || 0
        s.label.show = cellCount <= 100
        s.label.formatter = p => {
          const v = p.value[2]
          return v !== null && v !== undefined ? Number(v).toFixed(2) : 'N/A'
        }
      })
    } else if (type === 'radar') {
      // 雷达图标签需设置在每个 data 对象上
      seriesArray.forEach(s => {
        if (s.data) {
          s.data.forEach(d => {
            if (!d.label) d.label = {}
            d.label.show = true
            d.label.formatter = p => p.value
          })
        }
      })
    } else if (scatterLikeTypes.includes(type)) {
      seriesArray.forEach(s => {
        // 不在常态显示，悬停时显示坐标值
        s.label.show = false
        s.emphasis = s.emphasis || {}
        s.emphasis.label = s.emphasis.label || {}
        s.emphasis.label.show = true
        s.emphasis.label.formatter = '{c}'
      })
    } else {
      // 箱线图、KDE 等：逐点标签无意义，统一关闭
      seriesArray.forEach(s => {
        s.label.show = false
      })
    }
  } else {
    // 用户关闭数据标签：统一关闭所有系列标签
    seriesArray.forEach(s => {
      s.label.show = false
    })
    // 雷达图 data 对象上的标签也要关闭
    if (type === 'radar') {
      seriesArray.forEach(s => {
        if (s.data) {
          s.data.forEach(d => {
            if (!d.label) d.label = {}
            d.label.show = false
          })
        }
      })
    }
  }

  return option
}

async function doExportChart() {
  if (!chartReady.value || !chartInstance) return
  exportLoading.value = true
  try {
    // 直接使用前端 ECharts 实例导出，保证与页面看到的效果完全一致
    const dataUrl = chartInstance.getDataURL({
      type: 'png',
      pixelRatio: 2,
      backgroundColor: '#ffffff'
    })
    const a = document.createElement('a')
    a.href = dataUrl
    // 使用数据集名称拼接文件名，并过滤文件系统非法字符
    let dsName = '未命名'
    if (sourceConfig.value.mode === 'remote' && sourceConfig.value.remote) {
      dsName = sourceConfig.value.remote.table_name || '远程数据'
    } else {
      dsName = analysisRawData.value.find(d => d.id === datasetId.value)?.name || '未命名'
    }
    const safeDsName = dsName.replace(/[\\/:*?"<>|]/g, '_')
    const safeChartType = String(chartType.value || 'chart').replace(/[^a-zA-Z0-9_\-]/g, '_')
    a.download = `${safeDsName}_${safeChartType}_${Date.now()}.png`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    ElMessage.success('图表导出成功')
  } catch (e) {
    ElMessage.error(extractErrorMessage(e, '导出失败：'))
  } finally {
    exportLoading.value = false
  }
}

// ====== Task 16: 数据分析报告生成 ======
const reportLoading = ref(false)
const reportDialogVisible = ref(false)
const reportHtml = ref('')
const reportIframeUrl = ref('')
const reportDynamicData = ref({})
const reportSaved = ref(false)
const reportConfigDialogVisible = ref(false)

// 报告导出配置：控制各章节是否包含
const reportSections = reactive({
  dataPreview: true,
  quality: true,
  columnInfo: true,
  numericStats: true,
  categoricalStats: true,
  charts: false
})

// 报告章节键名映射（用于向后端传递 sections 数组）
const REPORT_SECTION_KEY_MAP = {
  dataPreview: 'data_preview',
  quality: 'quality',
  columnInfo: 'column_info',
  numericStats: 'numeric_stats',
  categoricalStats: 'categorical_stats',
  charts: 'charts'
}

// 报告模块定义：控制配置弹窗中各模块的渲染顺序与展示标签
const reportModules = [
  { key: 'dataPreview', label: '数据预览' },
  { key: 'quality', label: '数据质量概览' },
  { key: 'columnInfo', label: '列信息' },
  { key: 'numericStats', label: '数值列统计' },
  { key: 'categoricalStats', label: '分类列统计' },
  { key: 'charts', label: '自定义图表' },
]

// 报告各模块的细粒度配置选项（仅对应模块总开关勾选时生效）
const reportOptions = reactive({
  dataPreview: { sampleRows: 5 },
  quality: {
    metrics: ['missing_rate', 'missing_columns', 'infinite_columns', 'duplicate_rows', 'constant_columns', 'row_count', 'column_count', 'numeric_count', 'categorical_count']
  },
  columnInfo: {},
  numericStats: {
    metrics: ['mean', 'median', 'std', 'min', 'max', 'missing_count', 'missing_rate', 'skewness', 'kurtosis', 'p90', 'p95', 'p99', 'cv', 'mode', 'zero_count', 'zero_rate']
  },
  categoricalStats: {
    metrics: ['unique_count', 'missing_count', 'missing_rate', 'top_values'],
    topN: 10
  }
})

// 报告配置中选中的图表ID
const selectedChartIds = ref([])

// 是否至少选择了一个报告章节
const hasSelectedReportSection = computed(() => {
  return Object.values(reportSections).some(v => v)
})

// 当已添加图表变化时，自动更新"自定义图表"选项的可用状态
watch(reportCharts, (charts) => {
  if (charts.length === 0) {
    reportSections.charts = false
  }
}, { deep: true })

// 生成数据分析报告
function generateReport() {
  if (!hasDataSource.value) return
  // 根据当前是否有已添加图表设置默认选中状态
  reportSections.charts = reportCharts.value.length > 0
  // 默认选中所有已添加的图表
  selectedChartIds.value = reportCharts.value.map(c => c.id)
  reportConfigDialogVisible.value = true
}

// 确认报告配置后调用后端生成报告
async function confirmGenerateReport() {
  if (!hasDataSource.value) return
  if (!hasSelectedReportSection.value) {
    ElMessage.warning('请至少选择一个报告章节')
    return
  }
  reportConfigDialogVisible.value = false
  reportLoading.value = true
  reportSaved.value = false
  try {
    // 按 reportModules 顺序构建 sections，确保报告序号从1开始连续编号
    const sections = reportModules
      .filter(module => reportSections[module.key])
      .map(module => REPORT_SECTION_KEY_MAP[module.key])
    const charts = reportSections.charts ? reportCharts.value.filter(c => selectedChartIds.value.includes(c.id)) : []
    // 同时传递细粒度配置选项，由后端按选项裁剪报告内容
    const res = await generateAnalysisReport(datasetId.value, {
      sections,
      options: reportOptions,
      charts
    }, getRemoteConfig())

    // 判断是否为异步任务：后端异步分发时返回 task_record_id + task_id
    // 后端可能返回 'queued'、'running'、'pending' 三种初始状态，均视为异步任务
    const asyncStatuses = ['queued', 'running', 'pending']
    const submitDatasetId = datasetId.value
    if (res.data && res.data.task_record_id && asyncStatuses.includes(res.data.status)) {
      // 异步任务：关闭报告弹窗，交由全局任务面板管理进度
      reportDialogVisible.value = false
      reportLoading.value = false
      const datasetName = sourceConfig.value.mode === 'remote'
        ? (sourceConfig.value.remote?.table_name || '远程数据')
        : (analysisRawData.value.find(d => d.id === datasetId.value)?.name || '')
      addTask({
        recordId: res.data.task_record_id,
        celeryTaskId: res.data.task_id,
        taskType: 'data_analysis',
        operation: '数据分析报告',
        moduleLabel: '数据分析',
        datasetName: datasetName,
        initialStatus: res.data.status === 'pending' ? 'pending' : 'running',
      }, (status, summary) => {
        // 任务完成回调：成功时从 result_summary 提取 preview_html 渲染到 iframe
        if (status === 'success') {
          // 数据集一致性校验：若用户在任务执行期间切换了数据集，不直接渲染报告以免串显
          if (datasetId.value !== submitDatasetId) {
            ElMessage.success('报告生成完成，请切回原数据集查看结果')
            return
          }
          const previewHtml = summary?.preview_html || ''
          if (!previewHtml) {
            ElMessage.warning('报告已生成，但预览内容获取失败，请重新生成或查看操作历史')
            return
          }
          reportHtml.value = previewHtml
          reportDynamicData.value = summary?.dynamic_data || {}
          if (reportIframeUrl.value) {
            URL.revokeObjectURL(reportIframeUrl.value)
          }
          const blob = new Blob([reportHtml.value], { type: 'text/html' })
          reportIframeUrl.value = URL.createObjectURL(blob)
          reportSaved.value = false
          reportDialogVisible.value = true
        } else if (status === 'failed') {
          ElMessage.error(summary?.error_message || '分析报告生成失败')
        } else if (status === 'cancelled') {
          ElMessage.info('任务已取消')
        }
      })
    } else {
      // 同步任务：校验数据集一致性后展示，避免 await 期间用户切换数据集导致页面污染
      // 修复问题1类：原实现无校验，切换数据集后旧报告会通过 handleReportResult 重新填充并弹出
      if (datasetId.value === submitDatasetId) {
        reportDialogVisible.value = true
        await handleReportResult(res.data)
      } else {
        ElMessage.success('报告生成完成，请切回原数据集查看结果')
      }
      reportLoading.value = false
    }
  } catch (e) {
    reportLoading.value = false
    // 503：Celery 不可用且数据集 ≥1万行，不允许降级到同步
    if (e.response?.status === 503) {
      ElMessage.error(e.response?.data?.detail || '数据量较大，Celery 服务不可用，无法执行。请启动 Celery 服务或使用小数据集')
    } else if (e.response?.status === 429) {
      // 429：单用户并发任务超限
      ElMessage.warning(e.response?.data?.detail || '异步任务数超限，请等待现有任务完成或取消后再试')
    } else {
      ElMessage.error(extractErrorMessage(e, '生成报告失败：'))
    }
  }
}

// 同步任务结果处理：从后端返回值提取 preview_html 渲染到 iframe
async function handleReportResult(data) {
  const previewHtml = data?.preview_html || ''
  if (!previewHtml) {
    ElMessage.warning('报告内容为空')
    return
  }
  reportHtml.value = previewHtml
  reportDynamicData.value = data?.dynamic_data || {}
  // 创建 blob URL 用于 iframe 隔离预览，避免样式污染主页面
  if (reportIframeUrl.value) {
    URL.revokeObjectURL(reportIframeUrl.value)
  }
  const blob = new Blob([reportHtml.value], { type: 'text/html' })
  reportIframeUrl.value = URL.createObjectURL(blob)
  // 报告已生成但未保存到数据管理，需用户手动点击导出
  reportSaved.value = false
  ElMessage.success('报告预览已生成')
}

// 导出报告到数据管理
async function exportReport() {
  if (!hasDataSource.value || !reportHtml.value) return
  try {
    await saveAnalysisReport(datasetId.value, {
      report_html: reportHtml.value,
      report_data: reportDynamicData.value
    }, getRemoteConfig())
    reportSaved.value = true
    ElMessage.success('报告已保存到数据管理模块')
  } catch (e) {
    ElMessage.error(extractErrorMessage(e, '保存报告失败：'))
  }
}

// ====== 工具函数 ======
function formatNum(val) {
  if (val === null || val === undefined) return '-'
  if (typeof val === 'number') {
    return Number.isInteger(val) ? val.toString() : val.toFixed(4)
  }
  return val
}

function formatPercent(val) {
  if (val === null || val === undefined) return '-'
  if (typeof val === 'number') return val.toFixed(2) + '%'
  return val
}

// 格式化变异系数
function formatCV(val) {
  if (val === null || val === undefined) return '-'
  if (typeof val === 'number') return val.toFixed(4)
  return val
}

// 格式化众数（可能为列表）
function formatMode(val) {
  if (val === null || val === undefined) return '-'
  if (Array.isArray(val)) {
    return val.length > 0 ? val.map(v => String(v)).join(', ') : '-'
  }
  return String(val)
}

// ====== 生命周期 ======
// 清理 ECharts resize 监听器，防止 keep-alive 缓存下监听器堆积导致内存泄漏
function cleanupChartListeners() {
  window.removeEventListener('resize', handleResize)
}

onMounted(() => {
  loadRawData()
})

// keep-alive 失活时移除 resize 监听器
// 避免切换模块后仍触发回调
onDeactivated(() => {
  cleanupChartListeners()
})

// keep-alive 重新激活时无需重新渲染图表（实例和 DOM 均被缓存）
// 但如果之前清理过监听器，需要重新绑定以恢复窗口缩放响应
onActivated(() => {
  if (chartInstance && chartReady.value) {
    window.addEventListener('resize', handleResize)
  }
})

// 组件彻底卸载时 dispose ECharts 实例并移除监听器
onBeforeUnmount(() => {
  cleanupChartListeners()
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
})

// 数据集选择和数据加载由 onSourceSelect 统一管理，不再在此 watch 中响应
</script>

<style scoped>
.data-analysis {
  max-width: 1000px;
  margin: 0 auto;
}

.empty-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #c0c4cc;
  font-size: 13px;
  padding: 8px 0;
}

.section-subtitle {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
  padding-left: 8px;
  border-left: 3px solid var(--primary);
}

/* 统计卡片 - 详情模式 */
.stat-card--detail {
  text-align: left;
  padding: 16px;
  box-sizing: border-box;
  overflow: hidden;
}
.stat-card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid #e5e7eb;
}
.stat-detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px 16px;
}
.stat-detail-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.stat-detail-label {
  color: var(--text-secondary);
  font-size: 12px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.stat-detail-value {
  color: var(--text-primary);
  font-weight: 500;
  font-family: 'SF Mono', 'Consolas', monospace;
  font-size: 13px;
  word-break: break-all;
  line-height: 1.4;
  text-align: left;
}

/* TOP 值 */
.top-values {
  padding-top: 8px;
  border-top: 1px solid #e5e7eb;
}
.top-values-title {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}
.top-value-item {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.top-value-count {
  font-size: 12px;
  color: var(--text-muted);
}
.top-values-inline {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.top-value-inline-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

/* 图表控制区 */
.chart-controls {
  padding: 12px;
  background: #f8fafc;
  border-radius: var(--radius-sm);
}

/* 图表容器 */
.chart-container {
  width: 100%;
  height: 480px;
  border: 1px solid #e5e7eb;
  border-radius: var(--radius-sm);
}

/* Task 6: 质量卡片危险样式 */
.stat-card--danger {
  border-color: var(--danger, #ef4444) !important;
}
.stat-card--danger .stat-value {
  color: var(--danger, #ef4444);
}

/* Task 12: 表格高亮行 */
:deep(.el-table .row-highlight td) {
  background-color: #e6f7ff !important;
}

/* Task 14: 重命名图标 */
.rename-icon {
  cursor: pointer;
  margin-left: 6px;
  color: var(--primary, #4361ee);
  vertical-align: middle;
}
.rename-icon:hover {
  opacity: 0.7;
}

/* 已添加到分析报告的图表列表 */
.report-chart-list {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.report-chart-card {
  width: 220px;
}
.report-chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.report-chart-title {
  font-size: 13px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 140px;
}



/* 报告配置弹窗 - 分层结构 */
.report-config-section {
  margin-bottom: 16px;
  padding: 12px;
  border: 1px solid #ebeef5;
  border-radius: 4px;
}
.report-module-header {
  font-weight: 500;
  margin-bottom: 8px;
}
.report-module-options {
  padding-left: 24px;
  margin-top: 8px;
}
.report-sub-section {
  margin-bottom: 8px;
}
.sub-label {
  display: inline-block;
  margin-right: 8px;
  color: #606266;
  font-size: 13px;
}

/* 报告预览样式 - 修复弹窗白边和滚动问题 */
.report-preview {
  margin: 0;
  padding: 0;
  width: 100%;
  max-height: 70vh;
  overflow-y: auto;
  background: #f5f7fa;
}

/* iframe 隔离报告预览，避免样式污染主页面 */
.report-preview-iframe {
  width: 100%;
  height: 70vh;
  border: none;
  background: #f5f7fa;
}

/* 图表参数面板样式 */
.chart-param-panel {
  display: flex;
  flex-wrap: wrap;
  gap: 20px;
  align-items: flex-start;
  padding: 10px 0;
}
.param-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.param-group-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 4px;
}
.param-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 智能推荐样式 */
.recommendation-section {
  padding: 12px;
  background: #fefce8;
  border-radius: 8px;
  border: 1px solid #fde047;
}
.recommendation-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}
.recommendation-card {
  cursor: pointer;
  transition: all 0.2s;
}
.recommendation-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
}
.recommendation-content {
  padding: 4px;
}
.recommendation-score {
  font-size: 12px;
  color: var(--text-secondary);
}
.recommendation-reason {
  font-size: 13px;
  color: var(--text-primary);
  line-height: 1.5;
}
.recommendation-columns {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
</style>
