<template>
  <div class="data-cleaning">
    <!-- ========== 数据上传区域 ========== -->
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
        aria-label="上传数据文件进行清洗"
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

    <!-- ========== 数据集选择 ========== -->
    <div class="card">
      <div class="card-title">
        <el-icon><Folder /></el-icon>
        <span>选择数据集</span>
      </div>
      <DataSourceSelector
        ref="dataSourceSelectorRef"
        module-source="cleaning"
        @select="onSourceSelect"
      />
      <!-- 数据预览：选择数据集后自动加载 -->
      <DataPreview
        v-if="hasDataSource"
        :columns="previewColumns"
        :rows="previewRows"
        :loading="previewLoading"
        :total="previewTotal"
        :empty-text="previewEmptyText"
      />
    </div>

    <!-- ========== 五步向导导航 ========== -->
    <div class="card">
      <el-steps :active="currentStep" finish-status="success" align-center>
        <el-step title="预检" description="数据问题检测">
          <template #icon><el-icon><Search /></el-icon></template>
        </el-step>
        <el-step title="契约" description="列类型约束">
          <template #icon><el-icon><Document /></el-icon></template>
        </el-step>
        <el-step title="问题清单" description="问题逐条处理">
          <template #icon><el-icon><WarningFilled /></el-icon></template>
        </el-step>
        <el-step title="管道" description="清洗操作配置">
          <template #icon><el-icon><Setting /></el-icon></template>
        </el-step>
        <el-step title="审计" description="清洗结果报告">
          <template #icon><el-icon><DataAnalysis /></el-icon></template>
        </el-step>
      </el-steps>
    </div>

    <!-- ========== Step 1 预检 ========== -->
    <div v-if="currentStep === 0" class="card">
      <div class="card-title">
        <el-icon><Search /></el-icon>
        <span>Step 1 · 数据预检</span>
      </div>

      <!-- 预检操作区 -->
      <div class="flex-center gap-sm">
        <el-button type="primary" @click="runPrecheck" :disabled="!hasDataSource" :loading="precheckLoading">
          <el-icon style="margin-right:4px;"><Search /></el-icon>
          开始预检
        </el-button>
        <span v-if="!hasDataSource" class="text-muted" style="margin-left: 8px;">请先选择数据源</span>
      </div>
      <div v-if="cleaningRawData.length === 0" class="empty-hint" style="margin-top:10px;color:var(--text-muted);">
        <el-icon><UploadFilled /></el-icon>
        <span>暂无原始数据，请先上传文件</span>
      </div>

      <!-- 预检结果展示 -->
      <div v-if="precheckResult" class="precheck-result">
        <el-alert
          title="预检完成"
          :type="precheckAlertType"
          :description="precheckSummary"
          :closable="false"
          show-icon
          style="margin: 16px 0;"
        />

        <!-- 问题数量统计卡片 -->
        <div class="stats-grid">
          <div class="stat-card" style="--stat-color: var(--warning)">
            <div class="stat-value" style="color: var(--warning)">{{ missingValuesCount }}<span class="stat-unit"> 个</span></div>
            <div class="stat-label">缺失值</div>
          </div>
          <div class="stat-card" style="--stat-color: var(--info)">
            <div class="stat-value" style="color: var(--info)">{{ duplicateRowsCount }}<span class="stat-unit"> 行</span></div>
            <div class="stat-label">重复行</div>
          </div>
          <div class="stat-card" style="--stat-color: var(--danger)">
            <div class="stat-value" style="color: var(--danger)">{{ outliersCount }}<span class="stat-unit"> 个</span></div>
            <div class="stat-label">异常值</div>
          </div>
          <div class="stat-card" style="--stat-color: var(--primary)">
            <div class="stat-value" style="color: var(--primary)">{{ typeErrorsCount }}<span class="stat-unit"> 个</span></div>
            <div class="stat-label">类型错误</div>
          </div>
        </div>

        <!-- 缺失值统计表格：显示列名、缺失数、百分比、行号（索引+1） -->
        <div v-if="missingValueRows.length > 0" class="problem-section">
          <h4 class="problem-title">
            <el-icon style="color: var(--warning);"><WarningFilled /></el-icon>
            缺失值统计
          </h4>
          <el-table :data="missingValueRows" border size="small" style="width: 100%;" max-height="300">
            <el-table-column type="index" label="#" width="60" align="center" />
            <el-table-column prop="column" label="列名" min-width="120" show-overflow-tooltip />
            <el-table-column prop="missing_count" label="缺失数" width="100" align="center" />
            <el-table-column prop="missing_percent" label="百分比" width="110" align="center">
              <template #default="{ row }">
                <el-tag type="warning" size="small">{{ row.missing_percent }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="row_indices_text" label="缺失行号" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="sample-values">{{ row.row_indices_text }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 重复行统计：展开行显示每组重复行的行号和列值 -->
        <div v-if="duplicateRowsCount > 0" class="problem-section">
          <h4 class="problem-title">
            <el-icon style="color: var(--info);"><WarningFilled /></el-icon>
            重复行统计
          </h4>
          <el-descriptions :column="2" border size="small" style="margin-bottom: 12px;">
            <el-descriptions-item label="重复行数">{{ duplicateRowsCount }} 行</el-descriptions-item>
            <el-descriptions-item label="占总行数比例">{{ duplicateRowsPercent }}</el-descriptions-item>
          </el-descriptions>
          <el-table :data="duplicateGroupRows" border size="small" style="width: 100%;" max-height="400" row-key="group_index">
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="dup-expand">
                  <div class="dup-expand-row">
                    <span class="dup-label">重复行号：</span>
                    <span class="sample-values">{{ row.row_indices_text }}</span>
                  </div>
                  <div class="dup-expand-row">
                    <span class="dup-label">列值：</span>
                    <div class="dup-values">
                      <el-tag
                        v-for="(val, key) in row.row_values"
                        :key="key"
                        size="small"
                        type="info"
                        effect="plain"
                        class="dup-value-tag"
                      >
                        {{ key }} = {{ val }}
                      </el-tag>
                    </div>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column type="index" label="#" width="60" align="center" />
            <el-table-column prop="group_index" label="组号" width="100" align="center">
              <template #default="{ row }">
                <el-tag type="info" size="small">第 {{ row.group_index }} 组</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="row_count" label="重复行数" width="120" align="center" />
            <el-table-column prop="row_indices_text" label="重复行号" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="sample-values">{{ row.row_indices_text }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="row_values_preview" label="列值预览" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="sample-values">{{ row.row_values_preview }}</span>
              </template>
            </el-table-column>
          </el-table>
          <div v-if="duplicateGroupsTruncated" class="truncated-hint">
            前 {{ duplicateGroupRows.length }} 组（共 {{ duplicateTotalGroups }} 组）
          </div>
        </div>

        <!-- 类型识别结果表格 -->
        <div v-if="typeDetectionRows.length > 0" class="problem-section">
          <h4 class="problem-title">
            <el-icon style="color: var(--primary);"><DataLine /></el-icon>
            类型识别结果
          </h4>
          <el-table :data="typeDetectionRows" border size="small" style="width: 100%;" max-height="300">
            <el-table-column type="index" label="#" width="60" align="center" />
            <el-table-column prop="column" label="列名" />
            <el-table-column prop="inferred_type" label="推断类型" width="120" align="center">
              <template #default="{ row }">
                <el-tag :type="typeTagColor(row.inferred_type)" size="small">{{ typeLabel(row.inferred_type) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="sample_values" label="样本值" min-width="200">
              <template #default="{ row }">
                <span class="sample-values">{{ row.sample_values }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 异常值检测结果：显示列名、异常值数、行号、异常值样本、IQR边界 -->
        <div v-if="outlierRows.length > 0" class="problem-section">
          <h4 class="problem-title">
            <el-icon style="color: var(--danger);"><WarningFilled /></el-icon>
            异常值检测结果
          </h4>
          <el-table :data="outlierRows" border size="small" style="width: 100%;" max-height="400">
            <el-table-column type="index" label="#" width="60" align="center" />
            <el-table-column prop="column" label="列名" min-width="120" show-overflow-tooltip />
            <el-table-column prop="outlier_count" label="异常值数" width="100" align="center">
              <template #default="{ row }">
                <el-tag type="danger" size="small">{{ row.outlier_count }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="row_indices_text" label="行号" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="sample-values">{{ row.row_indices_text }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="values_text" label="异常值样本" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="sample-values">{{ row.values_text }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="bounds_text" label="IQR边界" width="160" align="center">
              <template #default="{ row }">
                <el-tag type="warning" size="small" effect="plain">{{ row.bounds_text }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 类型错误检测结果：显示列名、错误数、期望类型、错误行号、错误值样本 -->
        <div v-if="typeErrorRows.length > 0" class="problem-section">
          <h4 class="problem-title">
            <el-icon style="color: var(--primary);"><WarningFilled /></el-icon>
            类型错误检测结果
          </h4>
          <el-table :data="typeErrorRows" border size="small" style="width: 100%;" max-height="400">
            <el-table-column type="index" label="#" width="60" align="center" />
            <el-table-column prop="column" label="列名" min-width="120" show-overflow-tooltip />
            <el-table-column prop="error_count" label="错误数" width="100" align="center">
              <template #default="{ row }">
                <el-tag type="warning" size="small">{{ row.error_count }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="expected_type" label="期望类型" width="120" align="center">
              <template #default="{ row }">
                <el-tag :type="typeTagColor(row.expected_type)" size="small">{{ typeLabel(row.expected_type) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="error_rows_text" label="错误行号" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="sample-values">{{ row.error_rows_text }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="error_samples" label="错误值样本" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="sample-values">{{ row.error_samples }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 预检方法说明折叠面板：5种检测方法原理 -->
        <el-collapse v-model="precheckMethodActive" class="precheck-method-collapse">
          <el-collapse-item name="methods" title="预检方法说明">
            <div class="method-list">
              <div class="method-item">
                <el-tag type="warning" size="small" effect="dark">缺失值检测</el-tag>
                <span class="method-desc">使用 isna().sum() 统计每列的 NaN/空值</span>
              </div>
              <div class="method-item">
                <el-tag type="info" size="small" effect="dark">重复行检测</el-tag>
                <span class="method-desc">使用 duplicated() 判断所有列完全相同的行</span>
              </div>
              <div class="method-item">
                <el-tag type="info" size="small" effect="dark">类型识别</el-tag>
                <span class="method-desc">按优先级匹配 email → url → 日期 → 布尔 → 整数 → 数值 → 字符串</span>
              </div>
              <div class="method-item">
                <el-tag type="danger" size="small" effect="dark">异常值检测</el-tag>
                <span class="method-desc">IQR 方法（Q1 - 1.5×IQR 到 Q3 + 1.5×IQR 之外的值为异常）</span>
              </div>
              <div class="method-item">
                <el-tag size="small" effect="dark">类型错误检测</el-tag>
                <span class="method-desc">对推断为数值/日期等类型的 object 列尝试转换，失败即为错误</span>
              </div>
            </div>
          </el-collapse-item>
        </el-collapse>

        <!-- 下一步操作 -->
        <div class="step-actions">
          <el-button type="primary" size="default" @click="goToStep(1)" :disabled="!precheckResult">
            下一步：契约配置
            <el-icon style="margin-left:4px;"><ArrowRight /></el-icon>
          </el-button>
        </div>
      </div>
    </div>

    <!-- ========== Step 2 契约 ========== -->
    <div v-if="currentStep === 1" class="card">
      <div class="card-title">
        <el-icon><Document /></el-icon>
        <span>Step 2 · 列契约配置</span>
      </div>

      <el-alert
        title="基于预检的类型识别结果，自动填充每列的期望类型，点击展开可配置范围、枚举、日期等约束"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 16px;"
      />

      <!-- 契约配置表格：每列一行，展开后显示该列的详细配置 -->
      <el-table :data="contractColumns" border size="small" style="width: 100%;" max-height="600" row-key="name">
        <!-- 展开行：根据 expected_type 动态显示不同的配置项 -->
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="contract-expand">
              <el-form label-width="120px" label-position="right" size="small">
                <!-- integer/number 类型：范围配置 + 小数位数 -->
                <template v-if="isNumericType(row.expected_type)">
                  <el-form-item label="范围约束">
                    <div class="range-config">
                      <div v-for="(range, idx) in row.ranges" :key="idx" class="range-row">
                        <el-input-number
                          v-model="range[0]"
                          :controls="false"
                          size="small"
                          style="width: 120px;"
                          placeholder="最小值"
                        />
                        <span class="range-separator">~</span>
                        <el-input-number
                          v-model="range[1]"
                          :controls="false"
                          size="small"
                          style="width: 120px;"
                          placeholder="最大值"
                        />
                        <el-button
                          size="small"
                          type="danger"
                          link
                          @click="removeRange(row, idx)"
                        >
                          <el-icon><Delete /></el-icon>
                          删除
                        </el-button>
                      </div>
                      <el-button size="small" type="primary" link @click="addRange(row)">
                        <el-icon><CirclePlus /></el-icon>
                        添加范围
                      </el-button>
                      <div class="range-hint">满足任一范围即可，范围允许重叠</div>
                    </div>
                  </el-form-item>
                  <!-- number 类型额外支持小数位数 -->
                  <el-form-item v-if="row.expected_type === 'number'" label="小数位数">
                    <el-input-number
                      v-model="row.decimal_places"
                      :min="0"
                      :max="10"
                      :step="1"
                      size="small"
                      style="width: 140px;"
                    />
                    <span class="form-hint">取值范围 0-10 的整数</span>
                  </el-form-item>
                </template>

                <!-- date 类型：最小/最大日期选择 -->
                <template v-else-if="row.expected_type === 'date'">
                  <el-form-item label="最小日期">
                    <el-date-picker
                      v-model="row.min_date"
                      type="date"
                      size="small"
                      style="width: 200px;"
                      value-format="YYYY-MM-DD"
                      placeholder="选择最小日期"
                    />
                  </el-form-item>
                  <el-form-item label="最大日期">
                    <el-date-picker
                      v-model="row.max_date"
                      type="date"
                      size="small"
                      style="width: 200px;"
                      value-format="YYYY-MM-DD"
                      placeholder="选择最大日期"
                    />
                  </el-form-item>
                </template>

                <!-- string 类型：枚举值、最小/最大长度 -->
                <template v-else-if="row.expected_type === 'string'">
                  <el-form-item label="枚举值">
                    <el-input
                      v-model="row.enum_values_text"
                      size="small"
                      style="width: 360px;"
                      placeholder="多个值用英文逗号分隔，如：技术部,产品部,运营部"
                    />
                    <span class="form-hint">为空表示不限制枚举</span>
                  </el-form-item>
                  <el-form-item label="最小长度">
                    <el-input-number
                      v-model="row.min_length"
                      :min="0"
                      :controls="false"
                      size="small"
                      style="width: 140px;"
                      placeholder="不限"
                    />
                  </el-form-item>
                  <el-form-item label="最大长度">
                    <el-input-number
                      v-model="row.max_length"
                      :min="0"
                      :controls="false"
                      size="small"
                      style="width: 140px;"
                      placeholder="不限"
                    />
                  </el-form-item>
                </template>

                <!-- boolean 类型：布尔表示方式 -->
                <template v-else-if="row.expected_type === 'boolean'">
                  <el-form-item label="布尔表示方式">
                    <el-select v-model="row.bool_representation" size="small" style="width: 200px;">
                      <el-option value="0/1" label="0/1" />
                      <el-option value="是/否" label="是/否" />
                      <el-option value="true/false" label="true/false" />
                      <el-option value="True/False" label="True/False" />
                    </el-select>
                  </el-form-item>
                </template>

                <!-- email/url 类型：仅显示提示 -->
                <template v-else-if="row.expected_type === 'email' || row.expected_type === 'url'">
                  <el-form-item label="约束说明">
                    <span class="form-hint">{{ row.expected_type === 'email' ? '系统将校验邮箱格式' : '系统将校验 URL 格式' }}</span>
                  </el-form-item>
                </template>

                <!-- 通用配置：允许缺失、允许重复（所有类型都显示） -->
                <el-form-item label="允许缺失">
                  <el-switch v-model="row.allow_missing" />
                </el-form-item>
                <el-form-item label="允许重复">
                  <el-switch v-model="row.allow_duplicate" />
                </el-form-item>
              </el-form>
            </div>
          </template>
        </el-table-column>

        <el-table-column type="index" label="#" width="60" align="center" />
        <el-table-column prop="name" label="列名" min-width="140" show-overflow-tooltip />
        <!-- 期望类型：下拉选择，切换时清理不相关字段 -->
        <el-table-column label="期望类型" width="130">
          <template #default="{ row }">
            <el-select
              v-model="row.expected_type"
              size="small"
              style="width: 100%;"
              @change="onExpectedTypeChange(row)"
            >
              <el-option value="integer" label="整数" />
              <el-option value="number" label="数值" />
              <el-option value="string" label="字符" />
              <el-option value="boolean" label="布尔" />
              <el-option value="date" label="日期" />
              <el-option value="email" label="邮箱" />
              <el-option value="url" label="URL" />
            </el-select>
          </template>
        </el-table-column>
        <!-- 范围约束摘要：显示 "0-120" / "0-3, 5-9" / "无" -->
        <el-table-column label="范围约束" min-width="160">
          <template #default="{ row }">
            <span v-if="isNumericType(row.expected_type)" class="range-summary">{{ formatRangeSummary(row) }}</span>
            <span v-else-if="row.expected_type === 'date'" class="range-summary">{{ formatDateRangeSummary(row) }}</span>
            <span v-else-if="row.expected_type === 'string'" class="range-summary">{{ formatStringSummary(row) }}</span>
            <span v-else class="text-muted">-</span>
          </template>
        </el-table-column>
        <!-- 允许缺失：开关 -->
        <el-table-column label="允许缺失" width="100" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.allow_missing" />
          </template>
        </el-table-column>
        <!-- 允许重复：开关 -->
        <el-table-column label="允许重复" width="100" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.allow_duplicate" />
          </template>
        </el-table-column>
      </el-table>

      <div class="step-actions">
        <el-button size="default" @click="goToStep(0)">
          <el-icon style="margin-right:4px;"><ArrowLeft /></el-icon>
          上一步
        </el-button>
        <el-button type="primary" size="default" @click="goToStep(2)">
          下一步：问题清单
          <el-icon style="margin-left:4px;"><ArrowRight /></el-icon>
        </el-button>
      </div>
    </div>

    <!-- ========== Step 3 问题清单 ========== -->
    <div v-if="currentStep === 2" class="card">
      <div class="card-title">
        <el-icon><WarningFilled /></el-icon>
        <span>Step 3 · 问题清单</span>
      </div>

      <el-alert
        title="基于契约分析数据问题，可逐条或批量设置处理方式，配置完成后进入管道配置"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 16px;"
      />

      <!-- 加载中提示 -->
      <div v-if="problemListLoading" class="problem-loading">
        <el-icon class="is-loading" :size="24"><Loading /></el-icon>
        <span style="margin-left:8px;color:var(--text-muted);">正在分析问题清单...</span>
      </div>

      <!-- 顶部汇总卡片：6 个卡片横排 -->
      <el-row v-if="problemList" :gutter="12" class="problem-summary-row">
        <el-col :xs="12" :sm="8" :md="4">
          <div class="problem-summary-card" style="--card-color: #f56c6c;">
            <div class="problem-summary-value" style="color: #f56c6c;">{{ problemList.summary?.missing_values ?? 0 }}</div>
            <div class="problem-summary-label">缺失值</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="8" :md="4">
          <div class="problem-summary-card" style="--card-color: #e6a23c;">
            <div class="problem-summary-value" style="color: #e6a23c;">{{ problemList.summary?.type_errors ?? 0 }}</div>
            <div class="problem-summary-label">类型错误</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="8" :md="4">
          <div class="problem-summary-card" style="--card-color: #f7ba2a;">
            <div class="problem-summary-value" style="color: #f7ba2a;">{{ problemList.summary?.range_errors ?? 0 }}</div>
            <div class="problem-summary-label">范围错误</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="8" :md="4">
          <div class="problem-summary-card" style="--card-color: #9c27b0;">
            <div class="problem-summary-value" style="color: #9c27b0;">{{ problemList.summary?.outliers ?? 0 }}</div>
            <div class="problem-summary-label">异常值</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="8" :md="4">
          <div class="problem-summary-card" style="--card-color: #409eff;">
            <div class="problem-summary-value" style="color: #409eff;">{{ problemList.summary?.row_duplicates ?? 0 }}</div>
            <div class="problem-summary-label">行重复组数</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="8" :md="4">
          <div class="problem-summary-card" style="--card-color: #00bcd4;">
            <div class="problem-summary-value" style="color: #00bcd4;">{{ problemList.summary?.column_duplicates ?? 0 }}</div>
            <div class="problem-summary-label">列重复</div>
          </div>
        </el-col>
      </el-row>

      <!-- 无数据空状态 -->
      <el-empty
        v-if="problemList && !problemListLoading && !hasAnyProblem"
        description="未检测到任何数据问题"
        :image-size="120"
        style="padding: 40px 0;"
      />

      <!-- 问题清单分组（6 组，每组一个面板） -->
      <el-collapse v-if="problemList && !problemListLoading" v-model="problemCollapseActive" class="problem-collapse">

        <!-- 缺失值问题组：数值列 -->
        <el-collapse-item
          v-if="numericMissingProblems.length > 0"
          name="missing_values_numeric"
        >
          <template #title>
            <span class="collapse-title">
              <el-icon style="color:#f56c6c;"><WarningFilled /></el-icon>
              缺失值 · 数值列
              <el-tag size="small" type="danger" effect="plain" style="margin-left:8px;">
                {{ numericMissingProblems.length }} 个
              </el-tag>
            </span>
          </template>
          <div class="batch-actions">
            <span class="batch-label">批量设置：</span>
            <el-select
              v-model="batchStrategy.missing_values_numeric"
              size="small"
              style="width: 160px;"
              placeholder="选择处理方式"
            >
              <el-option
                v-for="opt in getMissingStrategyOptions('integer')"
                :key="opt.value"
                :value="opt.value"
                :label="opt.label"
              />
            </el-select>
            <el-button size="small" type="primary" @click="batchSetNumericMissingStrategy(batchStrategy.missing_values_numeric)">
              应用到全部
            </el-button>
          </div>
          <el-table :data="numericMissingProblems" border size="small" style="width: 100%;" max-height="400">
            <el-table-column type="index" label="#" width="60" align="center" />
            <el-table-column label="行号" width="110" align="center">
              <template #default="{ row }">
                <el-tag size="small" type="info">第 {{ row.row_index + 1 }} 行</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="column" label="列名" min-width="120" show-overflow-tooltip />
            <el-table-column prop="column_type" label="列类型" width="100" align="center">
              <template #default="{ row }">
                <el-tag size="small" :type="typeTagColor(row.column_type)">{{ typeLabel(row.column_type) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="当前值" width="120" align="center">
              <template #default="{ row }">
                <span v-if="row.current_value == null" class="text-muted">(空)</span>
                <span v-else class="sample-values">{{ row.current_value }}</span>
              </template>
            </el-table-column>
            <el-table-column label="处理方式" width="160">
              <template #default="{ row }">
                <el-select
                  v-model="problemStrategies.missing_values[row.originalIndex]"
                  size="small"
                  style="width: 100%;"
                  placeholder="选择处理方式"
                >
                  <el-option
                    v-for="opt in getMissingStrategyOptions(row.column_type)"
                    :key="opt.value"
                    :value="opt.value"
                    :label="opt.label"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="参数" width="160">
              <template #default="{ row }">
                <el-input
                  v-if="problemStrategies.missing_values[row.originalIndex] === 'custom'"
                  v-model="problemParams.missing_values[row.originalIndex]"
                  size="small"
                  placeholder="自定义填充值"
                />
                <span v-else class="text-muted">-</span>
              </template>
            </el-table-column>
          </el-table>
        </el-collapse-item>

        <!-- 缺失值问题组：非数值列 -->
        <el-collapse-item
          v-if="nonNumericMissingProblems.length > 0"
          name="missing_values_non_numeric"
        >
          <template #title>
            <span class="collapse-title">
              <el-icon style="color:#f56c6c;"><WarningFilled /></el-icon>
              缺失值 · 非数值列
              <el-tag size="small" type="danger" effect="plain" style="margin-left:8px;">
                {{ nonNumericMissingProblems.length }} 个
              </el-tag>
            </span>
          </template>
          <div class="batch-actions">
            <span class="batch-label">批量设置：</span>
            <el-select
              v-model="batchStrategy.missing_values_non_numeric"
              size="small"
              style="width: 160px;"
              placeholder="选择处理方式"
            >
              <el-option
                v-for="opt in getMissingStrategyOptions('string')"
                :key="opt.value"
                :value="opt.value"
                :label="opt.label"
              />
            </el-select>
            <el-button size="small" type="primary" @click="batchSetNonNumericMissingStrategy(batchStrategy.missing_values_non_numeric)">
              应用到全部
            </el-button>
          </div>
          <el-table :data="nonNumericMissingProblems" border size="small" style="width: 100%;" max-height="400">
            <el-table-column type="index" label="#" width="60" align="center" />
            <el-table-column label="行号" width="110" align="center">
              <template #default="{ row }">
                <el-tag size="small" type="info">第 {{ row.row_index + 1 }} 行</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="column" label="列名" min-width="120" show-overflow-tooltip />
            <el-table-column prop="column_type" label="列类型" width="100" align="center">
              <template #default="{ row }">
                <el-tag size="small" :type="typeTagColor(row.column_type)">{{ typeLabel(row.column_type) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="当前值" width="120" align="center">
              <template #default="{ row }">
                <span v-if="row.current_value == null" class="text-muted">(空)</span>
                <span v-else class="sample-values">{{ row.current_value }}</span>
              </template>
            </el-table-column>
            <el-table-column label="处理方式" width="160">
              <template #default="{ row }">
                <el-select
                  v-model="problemStrategies.missing_values[row.originalIndex]"
                  size="small"
                  style="width: 100%;"
                  placeholder="选择处理方式"
                >
                  <el-option
                    v-for="opt in getMissingStrategyOptions(row.column_type)"
                    :key="opt.value"
                    :value="opt.value"
                    :label="opt.label"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="参数" width="160">
              <template #default="{ row }">
                <el-input
                  v-if="problemStrategies.missing_values[row.originalIndex] === 'custom'"
                  v-model="problemParams.missing_values[row.originalIndex]"
                  size="small"
                  placeholder="自定义填充值"
                />
                <span v-else class="text-muted">-</span>
              </template>
            </el-table-column>
          </el-table>
        </el-collapse-item>

        <!-- 类型错误问题组 -->
        <el-collapse-item
          v-if="problemList.problems?.type_errors?.length > 0"
          name="type_errors"
        >
          <template #title>
            <span class="collapse-title">
              <el-icon style="color:#e6a23c;"><WarningFilled /></el-icon>
              类型错误问题
              <el-tag size="small" type="warning" effect="plain" style="margin-left:8px;">
                {{ problemList.problems.type_errors.length }} 个
              </el-tag>
            </span>
          </template>
          <div class="batch-actions">
            <span class="batch-label">批量设置：</span>
            <el-select
              v-model="batchStrategy.type_errors"
              size="small"
              style="width: 160px;"
              placeholder="选择处理方式"
            >
              <el-option
                v-for="opt in getStrategyOptions('type_errors')"
                :key="opt.value"
                :value="opt.value"
                :label="opt.label"
              />
            </el-select>
            <el-button size="small" type="primary" @click="batchSetStrategy('type_errors', batchStrategy.type_errors)">
              应用到全部
            </el-button>
          </div>
          <el-table :data="problemList.problems.type_errors" border size="small" style="width: 100%;" max-height="400">
            <el-table-column type="index" label="#" width="60" align="center" />
            <el-table-column label="行号" width="110" align="center">
              <template #default="{ row }">
                <el-tag size="small" type="info">第 {{ row.row_index + 1 }} 行</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="column" label="列名" min-width="120" show-overflow-tooltip />
            <el-table-column label="当前值" width="140">
              <template #default="{ row }">
                <span class="sample-values">{{ row.current_value }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="expected_type" label="期望类型" width="110" align="center">
              <template #default="{ row }">
                <el-tag size="small" :type="typeTagColor(row.expected_type)">{{ typeLabel(row.expected_type) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="处理方式" width="180">
              <template #default="{ $index }">
                <el-select
                  v-model="problemStrategies.type_errors[$index]"
                  size="small"
                  style="width: 100%;"
                  placeholder="选择处理方式"
                >
                  <el-option
                    v-for="opt in getStrategyOptions('type_errors')"
                    :key="opt.value"
                    :value="opt.value"
                    :label="opt.label"
                  />
                </el-select>
              </template>
            </el-table-column>
          </el-table>
        </el-collapse-item>

        <!-- 范围错误问题组 -->
        <el-collapse-item
          v-if="problemList.problems?.range_errors?.length > 0"
          name="range_errors"
        >
          <template #title>
            <span class="collapse-title">
              <el-icon style="color:#f7ba2a;"><WarningFilled /></el-icon>
              范围错误问题
              <el-tag size="small" type="warning" effect="plain" style="margin-left:8px;">
                {{ problemList.problems.range_errors.length }} 个
              </el-tag>
            </span>
          </template>
          <div class="batch-actions">
            <span class="batch-label">批量设置：</span>
            <el-select
              v-model="batchStrategy.range_errors"
              size="small"
              style="width: 160px;"
              placeholder="选择处理方式"
            >
              <el-option
                v-for="opt in getStrategyOptions('range_errors')"
                :key="opt.value"
                :value="opt.value"
                :label="opt.label"
              />
            </el-select>
            <el-button size="small" type="primary" @click="batchSetStrategy('range_errors', batchStrategy.range_errors)">
              应用到全部
            </el-button>
          </div>
          <el-table :data="problemList.problems.range_errors" border size="small" style="width: 100%;" max-height="400">
            <el-table-column type="index" label="#" width="60" align="center" />
            <el-table-column label="行号" width="110" align="center">
              <template #default="{ row }">
                <el-tag size="small" type="info">第 {{ row.row_index + 1 }} 行</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="column" label="列名" min-width="120" show-overflow-tooltip />
            <el-table-column label="当前值" width="120">
              <template #default="{ row }">
                <span class="sample-values">{{ row.current_value }}</span>
              </template>
            </el-table-column>
            <el-table-column label="契约范围" min-width="160">
              <template #default="{ row }">
                <el-tag size="small" type="warning" effect="plain">{{ formatContractRanges(row.contract_ranges) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="处理方式" width="180">
              <template #default="{ $index }">
                <el-select
                  v-model="problemStrategies.range_errors[$index]"
                  size="small"
                  style="width: 100%;"
                  placeholder="选择处理方式"
                >
                  <el-option
                    v-for="opt in getStrategyOptions('range_errors')"
                    :key="opt.value"
                    :value="opt.value"
                    :label="opt.label"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="参数" width="160">
              <template #default="{ row, $index }">
                <el-input
                  v-if="problemStrategies.range_errors[$index] === 'custom'"
                  v-model="problemParams.range_errors[$index]"
                  size="small"
                  placeholder="范围内的自定义值"
                />
                <span v-else class="text-muted">-</span>
              </template>
            </el-table-column>
          </el-table>
        </el-collapse-item>

        <!-- 异常值问题组 -->
        <el-collapse-item
          v-if="problemList.problems?.outliers?.length > 0"
          name="outliers"
        >
          <template #title>
            <span class="collapse-title">
              <el-icon style="color:#9c27b0;"><WarningFilled /></el-icon>
              异常值问题
              <el-tag size="small" effect="plain" style="margin-left:8px;color:#9c27b0;">
                {{ problemList.problems.outliers.length }} 个
              </el-tag>
            </span>
          </template>
          <div class="batch-actions">
            <span class="batch-label">批量设置：</span>
            <el-select
              v-model="batchStrategy.outliers"
              size="small"
              style="width: 160px;"
              placeholder="选择处理方式"
            >
              <el-option
                v-for="opt in getStrategyOptions('outliers')"
                :key="opt.value"
                :value="opt.value"
                :label="opt.label"
              />
            </el-select>
            <el-button size="small" type="primary" @click="batchSetStrategy('outliers', batchStrategy.outliers)">
              应用到全部
            </el-button>
          </div>
          <el-table :data="problemList.problems.outliers" border size="small" style="width: 100%;" max-height="400">
            <el-table-column type="index" label="#" width="60" align="center" />
            <el-table-column label="行号" width="110" align="center">
              <template #default="{ row }">
                <el-tag size="small" type="info">第 {{ row.row_index + 1 }} 行</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="column" label="列名" min-width="120" show-overflow-tooltip />
            <el-table-column label="当前值" width="120">
              <template #default="{ row }">
                <span class="sample-values">{{ row.current_value }}</span>
              </template>
            </el-table-column>
            <el-table-column label="IQR 边界" width="160" align="center">
              <template #default="{ row }">
                <el-tag size="small" type="warning" effect="plain">{{ formatIqrBounds(row.iqr_bounds) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="处理方式" width="180">
              <template #default="{ $index }">
                <el-select
                  v-model="problemStrategies.outliers[$index]"
                  size="small"
                  style="width: 100%;"
                  placeholder="选择处理方式"
                >
                  <el-option
                    v-for="opt in getStrategyOptions('outliers')"
                    :key="opt.value"
                    :value="opt.value"
                    :label="opt.label"
                  />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="参数" width="160">
              <template #default="{ $index }">
                <el-input
                  v-if="problemStrategies.outliers[$index] === 'custom'"
                  v-model="problemParams.outliers[$index]"
                  size="small"
                  placeholder="自定义替换值"
                />
                <span v-else class="text-muted">-</span>
              </template>
            </el-table-column>
          </el-table>
        </el-collapse-item>

        <!-- 行重复问题组 -->
        <el-collapse-item
          v-if="problemList.problems?.row_duplicates?.length > 0"
          name="row_duplicates"
        >
          <template #title>
            <span class="collapse-title">
              <el-icon style="color:#409eff;"><WarningFilled /></el-icon>
              行重复问题
              <el-tag size="small" type="info" effect="plain" style="margin-left:8px;">
                {{ problemList.problems.row_duplicates.length }} 组
              </el-tag>
            </span>
          </template>
          <div class="batch-actions">
            <span class="batch-label">批量设置：</span>
            <el-select
              v-model="batchStrategy.row_duplicates"
              size="small"
              style="width: 160px;"
              placeholder="选择处理方式"
            >
              <el-option
                v-for="opt in getStrategyOptions('row_duplicates')"
                :key="opt.value"
                :value="opt.value"
                :label="opt.label"
              />
            </el-select>
            <el-button size="small" type="primary" @click="batchSetStrategy('row_duplicates', batchStrategy.row_duplicates)">
              应用到全部
            </el-button>
          </div>
          <el-table :data="problemList.problems.row_duplicates" border size="small" style="width: 100%;" max-height="400">
            <el-table-column type="index" label="#" width="60" align="center" />
            <el-table-column label="重复行号" min-width="180">
              <template #default="{ row }">
                <span class="sample-values">{{ formatRowIndices(row.row_indices) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="重复内容" min-width="280">
              <template #default="{ row }">
                <div class="dup-values">
                  <el-tag
                    v-for="(val, key) in row.row_values"
                    :key="key"
                    size="small"
                    type="info"
                    effect="plain"
                    class="dup-value-tag"
                  >
                    {{ key }} = {{ val }}
                  </el-tag>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="处理方式" width="180">
              <template #default="{ $index }">
                <el-select
                  v-model="problemStrategies.row_duplicates[$index]"
                  size="small"
                  style="width: 100%;"
                  placeholder="选择处理方式"
                >
                  <el-option
                    v-for="opt in getStrategyOptions('row_duplicates')"
                    :key="opt.value"
                    :value="opt.value"
                    :label="opt.label"
                  />
                </el-select>
              </template>
            </el-table-column>
          </el-table>
        </el-collapse-item>

        <!-- 列重复问题组 -->
        <el-collapse-item
          v-if="problemList.problems?.column_duplicates?.length > 0"
          name="column_duplicates"
        >
          <template #title>
            <span class="collapse-title">
              <el-icon style="color:#00bcd4;"><WarningFilled /></el-icon>
              列重复问题
              <el-tag size="small" effect="plain" style="margin-left:8px;color:#00bcd4;">
                {{ problemList.problems.column_duplicates.length }} 组
              </el-tag>
            </span>
          </template>
          <div class="batch-actions">
            <span class="batch-label">批量设置：</span>
            <el-select
              v-model="batchStrategy.column_duplicates"
              size="small"
              style="width: 160px;"
              placeholder="选择处理方式"
            >
              <el-option
                v-for="opt in getStrategyOptions('column_duplicates')"
                :key="opt.value"
                :value="opt.value"
                :label="opt.label"
              />
            </el-select>
            <el-button size="small" type="primary" @click="batchSetStrategy('column_duplicates', batchStrategy.column_duplicates)">
              应用到全部
            </el-button>
          </div>
          <el-table :data="problemList.problems.column_duplicates" border size="small" style="width: 100%;" max-height="400">
            <!-- 展开行：显示其他列值 -->
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="dup-expand">
                  <div class="dup-expand-row">
                    <span class="dup-label">其他列值详情：</span>
                    <div class="dup-values">
                      <el-tag
                        v-for="(detail, dIdx) in row.row_details"
                        :key="dIdx"
                        size="small"
                        type="info"
                        effect="plain"
                        class="dup-value-tag"
                      >
                        第 {{ detail.row_index + 1 }} 行：
                        <span v-for="(v, k) in detail.other_values" :key="k" style="margin-left:4px;">
                          {{ k }} = {{ v }};
                        </span>
                      </el-tag>
                    </div>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column type="index" label="#" width="60" align="center" />
            <el-table-column prop="column" label="重复列" min-width="120" show-overflow-tooltip />
            <el-table-column label="重复值" width="140">
              <template #default="{ row }">
                <span class="sample-values">{{ row.duplicate_value }}</span>
              </template>
            </el-table-column>
            <el-table-column label="重复行号" min-width="160">
              <template #default="{ row }">
                <span class="sample-values">{{ formatRowIndices(row.row_indices) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="处理方式" width="180">
              <template #default="{ $index }">
                <el-select
                  v-model="problemStrategies.column_duplicates[$index]"
                  size="small"
                  style="width: 100%;"
                  placeholder="选择处理方式"
                >
                  <el-option
                    v-for="opt in getStrategyOptions('column_duplicates')"
                    :key="opt.value"
                    :value="opt.value"
                    :label="opt.label"
                  />
                </el-select>
              </template>
            </el-table-column>
          </el-table>
        </el-collapse-item>
      </el-collapse>

      <!-- 步骤导航按钮 -->
      <div class="step-actions">
        <el-button size="default" @click="goToStep(1)">
          <el-icon style="margin-right:4px;"><ArrowLeft /></el-icon>
          上一步
        </el-button>
        <el-button type="primary" size="default" @click="goToStep(3)" :disabled="!problemList">
          下一步：管道配置
          <el-icon style="margin-left:4px;"><ArrowRight /></el-icon>
        </el-button>
      </div>
    </div>

    <!-- ========== Step 4 管道 ========== -->
    <div v-if="currentStep === 3" class="card">
      <div class="card-title">
        <el-icon><Setting /></el-icon>
        <span>Step 4 · 清洗管道配置</span>
      </div>

      <el-alert
        title="管道已根据问题清单自动生成，处理方式沿用 Step 3 配置。此处仅调整执行顺序，可拖拽或使用上移/下移按钮"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 16px;"
      />

      <!-- 列操作/行过滤规则提示：固定文案，告知执行顺序与列名变化规则（三种执行模式共用此界面） -->
      <el-alert
        title="列操作与行过滤规则"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 16px;"
      >
        <div class="pipeline-rule-list">
          <div>· 同一列被多次操作：按管道顺序依次执行，以最后一次为准（如重命名两次，使用后一个名称）</div>
          <div>· 同一行被多次过滤：逐次收紧，不会出错</div>
          <div>· 列重命名后，后续的行过滤/列操作请使用新列名；用旧列名写的条件不会生效（会被跳过）</div>
        </div>
      </el-alert>

      <!-- 顶部工具栏：重新生成、清空、说明 -->
      <div class="pipeline-toolbar">
        <el-button size="small" type="primary" plain @click="regeneratePipeline">
          <el-icon style="margin-right:4px;"><MagicStick /></el-icon>
          根据问题清单重新生成
        </el-button>
        <el-button size="small" plain @click="clearPipeline">
          <el-icon style="margin-right:4px;"><Delete /></el-icon>
          清空管道
        </el-button>
        <span class="pipeline-toolbar-hint">
          列操作 / 行过滤只能添加到管道末尾
        </span>
      </div>

      <el-row :gutter="16">
        <!-- 左侧：可用操作列表 -->
        <el-col :xs="24" :sm="8">
          <div class="pipeline-palette">
            <div class="palette-title">可用操作（点击添加）</div>
            <div
              v-for="op in availableOperations"
              :key="op.type"
              class="palette-item"
              :class="{ 'palette-item-terminal': op.terminalOnly }"
              @click="addPipelineOperation(op.type)"
            >
              <el-icon :color="op.color"><component :is="op.icon" /></el-icon>
              <div class="palette-item-text">
                <div class="palette-item-name">{{ op.name }}</div>
                <div class="palette-item-desc">{{ op.desc }}</div>
              </div>
              <el-icon class="palette-item-add"><CirclePlus /></el-icon>
            </div>
          </div>
        </el-col>

        <!-- 右侧：已配置管道（自动生成，可拖拽调整顺序） -->
        <el-col :xs="24" :sm="16">
          <div class="pipeline-configured">
            <div class="palette-title">
              已配置管道（按顺序执行）
              <el-tag v-if="pipeline.length > 0" size="small" type="info">{{ pipeline.length }} 步</el-tag>
            </div>

            <div v-if="pipeline.length === 0" class="pipeline-empty">
              <el-icon :size="32" color="#c0c4cc"><Setting /></el-icon>
              <div style="margin-top:8px;color:var(--text-muted);">点击左侧操作或"重新生成"按钮添加清洗步骤</div>
            </div>

            <!-- 拖拽列表 -->
            <div
              v-for="(op, idx) in pipeline"
              :key="op.id"
              class="pipeline-item"
              :class="{
                'pipeline-item-dragging': dragIndex === idx,
                'pipeline-item-terminal': isTerminalOperation(op.operation)
              }"
              draggable="true"
              @dragstart="onDragStart(idx)"
              @dragover.prevent="onDragOver(idx)"
              @drop="onDrop(idx)"
              @dragend="onDragEnd"
            >
              <div class="pipeline-item-header">
                <div class="pipeline-item-left">
                  <el-icon class="drag-handle" title="拖拽排序"><Rank /></el-icon>
                  <el-tag size="small" :type="operationTagType(op.operation)">{{ idx + 1 }}</el-tag>
                  <span class="pipeline-item-name">{{ operationName(op.operation) }}</span>
                  <el-tag v-if="isTerminalOperation(op.operation)" size="small" type="warning" effect="plain">末尾</el-tag>
                </div>
                <div class="pipeline-item-right">
                  <el-button
                    size="small"
                    link
                    @click="movePipelineItem(idx, -1)"
                    :disabled="idx === 0 || !canMoveTo(op.operation, idx, -1)"
                    title="上移"
                  >
                    <el-icon><ArrowUp /></el-icon>
                  </el-button>
                  <el-button
                    size="small"
                    link
                    @click="movePipelineItem(idx, 1)"
                    :disabled="idx === pipeline.length - 1 || !canMoveTo(op.operation, idx, 1)"
                    title="下移"
                  >
                    <el-icon><ArrowDown /></el-icon>
                  </el-button>
                  <el-button size="small" link type="danger" @click="removePipelineItem(idx)" title="删除">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
              </div>

              <!-- 管道项摘要（不重复配置处理方式，仅显示来自问题清单的摘要） -->
              <div class="pipeline-item-summary">
                <template v-if="getPipelineItemSummary(op)">
                  <span class="summary-icon">└─</span>
                  <span class="summary-text">{{ getPipelineItemSummary(op) }}</span>
                </template>
                <span v-else class="summary-empty">
                  {{ isTerminalOperation(op.operation) ? '未配置' : '无相关问题' }}
                </span>
              </div>

              <!-- 仅列操作和行过滤保留参数配置区域 -->
              <div v-if="op.operation === 'column_ops'" class="pipeline-item-body">
                <el-radio-group v-model="op.params.action" size="small">
                  <el-radio-button value="rename">重命名</el-radio-button>
                  <el-radio-button value="delete">删除</el-radio-button>
                </el-radio-group>
                <el-select
                  v-model="op.params.column"
                  size="small"
                  style="width: 200px; margin-left: 12px;"
                  placeholder="选择列"
                >
                  <!-- 下拉显示当前管道内有效列名（前序重命名已生效），避免选到已被改名的旧列名 -->
                  <el-option v-for="col in effectiveColumnNamesAt(idx)" :key="col" :label="col" :value="col" />
                </el-select>
                <el-input
                  v-if="op.params.action === 'rename'"
                  v-model="op.params.new_name"
                  size="small"
                  style="width: 160px; margin-left: 12px;"
                  placeholder="新列名"
                />
                <div
                  v-if="op.params.action === 'rename'"
                  style="font-size:11px;color:var(--text-muted);margin-top:4px;width:100%;"
                >
                  重命名后，后续步骤请引用新列名（用旧列名写条件不会生效）
                </div>
              </div>

              <div v-else-if="op.operation === 'row_filter'" class="pipeline-item-body">
                <el-input
                  v-model="op.params.condition"
                  size="small"
                  style="width: 100%;"
                  placeholder="过滤条件，如：age > 18 & status == 'active'"
                />
                <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">
                  支持列名、比较运算符（&gt; &lt; == != &gt;= &lt;=）和逻辑运算符（& | !）
                </div>
                <div style="font-size:11px;color:#e6a23c;margin-top:4px;">
                  请使用当前有效的列名（已重命名的列请用新名称）
                </div>
              </div>
            </div>
          </div>
        </el-col>
      </el-row>

      <!-- 执行清洗按钮 -->
      <div class="step-actions">
        <el-button size="default" @click="goToStep(2)">
          <el-icon style="margin-right:4px;"><ArrowLeft /></el-icon>
          上一步
        </el-button>
        <el-button
          type="primary"
          size="default"
          @click="executeCleaning"
          :loading="executeLoading"
          :disabled="pipeline.length === 0"
        >
          <el-icon style="margin-right:4px;"><VideoPlay /></el-icon>
          执行清洗
        </el-button>
      </div>
    </div>

    <!-- ========== Step 5 审计 ========== -->
    <div v-if="currentStep === 4" class="card">
      <div class="card-title">
        <el-icon><DataAnalysis /></el-icon>
        <span>Step 5 · 清洗审计报告</span>
      </div>

      <div v-if="auditReport">
        <!-- 摘要卡片：原始/清洗后的行列数 + 操作数 -->
        <h4 class="section-title">清洗摘要</h4>
        <div class="audit-summary">
          <div class="summary-card">
            <div class="summary-label">原始行数</div>
            <div class="summary-value">{{ auditReport.summary?.original_rows ?? '-' }}</div>
          </div>
          <div class="summary-card">
            <div class="summary-label">清洗后行数</div>
            <div class="summary-value" style="color: var(--success);">{{ auditReport.summary?.cleaned_rows ?? '-' }}</div>
          </div>
          <div class="summary-card">
            <div class="summary-label">原始列数</div>
            <div class="summary-value">{{ auditReport.summary?.original_cols ?? '-' }}</div>
          </div>
          <div class="summary-card">
            <div class="summary-label">清洗后列数</div>
            <div class="summary-value" style="color: var(--success);">{{ auditReport.summary?.cleaned_cols ?? '-' }}</div>
            <div v-if="markedColumnsCount > 0" class="summary-hint">含 {{ markedColumnsCount }} 个标记列</div>
          </div>
          <div class="summary-card">
            <div class="summary-label">操作数</div>
            <div class="summary-value">{{ operationsCount }}</div>
          </div>
        </div>

        <!-- 4 维度质量评分（前后对比） -->
        <h4 class="section-title">质量评分（4 维度 · 前后对比）</h4>
        <div class="quality-grid">
          <div class="quality-card" v-for="dim in qualityDimensions" :key="dim.key">
            <div class="quality-label">{{ dim.label }}</div>
            <div class="quality-compare">
              <div class="quality-before">
                <div class="quality-before-label">清洗前</div>
                <div class="quality-before-value" :style="{ color: getQualityColor(getQualityBeforeScore(dim.key)) }">
                  {{ getQualityBeforeScore(dim.key) }}%
                </div>
              </div>
              <div class="quality-arrow">→</div>
              <div class="quality-after">
                <div class="quality-after-label">清洗后</div>
                <div class="quality-after-value" :style="{ color: getQualityColor(getQualityScore(dim.key)) }">
                  {{ getQualityScore(dim.key) }}%
                </div>
              </div>
            </div>
            <div class="quality-desc">{{ dim.desc }}</div>
          </div>
        </div>

        <!-- 列级统计表格 -->
        <h4 class="section-title">列级统计对比</h4>
        <el-table
          v-if="columnStatsRows.length > 0"
          :data="columnStatsRows"
          border
          size="small"
          style="width: 100%;"
          max-height="300"
        >
          <el-table-column type="index" label="#" width="60" align="center" />
          <el-table-column prop="column" label="列名" width="140" show-overflow-tooltip />
          <el-table-column label="数据类型" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="getDataTypeTagType(row.data_type)" size="small">{{ getDataTypeLabel(row.data_type) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="缺失值数（前→后）" align="center">
            <template #default="{ row }">
              <template v-if="row.missing_before || row.missing_after">
                <span style="color:#f56c6c;">{{ row.missing_before }}</span>
                <span style="margin: 0 6px;color:#909399;">→</span>
                <span style="color:#67c23a;">{{ row.missing_after }}</span>
              </template>
              <span v-else style="color:#909399;">-</span>
            </template>
          </el-table-column>
          <el-table-column label="缺失率（前→后）" align="center">
            <template #default="{ row }">
              <template v-if="row.missing_rate_before || row.missing_rate_after">
                <span style="color:#f56c6c;">{{ row.missing_rate_before }}%</span>
                <span style="margin: 0 6px;color:#909399;">→</span>
                <span style="color:#67c23a;">{{ row.missing_rate_after }}%</span>
              </template>
              <span v-else style="color:#909399;">-</span>
            </template>
          </el-table-column>
          <el-table-column label="异常值数（前→后）" align="center">
            <template #default="{ row }">
              <template v-if="row.outlier_before || row.outlier_after">
                <span style="color:#f56c6c;">{{ row.outlier_before }}</span>
                <span style="margin: 0 6px;color:#909399;">→</span>
                <span style="color:#67c23a;">{{ row.outlier_after }}</span>
              </template>
              <span v-else style="color:#909399;">-</span>
            </template>
          </el-table-column>
          <el-table-column label="重复行数（前→后）" align="center">
            <template #default="{ row }">
              <template v-if="row.duplicate_before || row.duplicate_after">
                <span style="color:#f56c6c;">{{ row.duplicate_before }}</span>
                <span style="margin: 0 6px;color:#909399;">→</span>
                <span style="color:#67c23a;">{{ row.duplicate_after }}</span>
              </template>
              <span v-else style="color:#909399;">-</span>
            </template>
          </el-table-column>
        </el-table>
        <div v-else class="empty-hint">暂无列级统计数据</div>

        <!-- 行级对比表格 -->
        <h4 class="section-title">行级对比（原始值 vs 修改后值）</h4>
        <el-table
          v-if="rowDiffList.length > 0"
          :data="paginatedRowDiff"
          border
          size="small"
          style="width: 100%;"
          max-height="400"
        >
          <el-table-column type="index" label="#" width="60" align="center" />
          <el-table-column prop="row" label="行号" width="80" align="center" />
          <el-table-column prop="column" label="列名" width="120" show-overflow-tooltip />
          <el-table-column label="错误类型" width="120" align="center">
            <template #default="{ row }">
              <el-tag :type="diffTypeColor(row.error_type)" size="small">
                {{ diffTypeLabel(row.error_type) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="处理方法" width="120" align="center">
            <template #default="{ row }">
              <el-tag :type="getMethodTagType(row.method)" size="small">{{ row.method || '未知' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="原始值" width="150" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="diff-old">{{ row.old_value || '(空)' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="修改后值" width="150" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="diff-new">{{ row.new_value || '(空)' }}</span>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-if="rowDiffList.length > rowDiffPageSize"
          v-model:current-page="rowDiffCurrentPage"
          v-model:page-size="rowDiffPageSize"
          :page-sizes="[10, 20, 50, 100]"
          :total="rowDiffList.length"
          layout="sizes, prev, pager, next, jumper"
          small
          background
          style="margin-top: 12px; justify-content: flex-end;"
        />
        <div v-else-if="rowDiffList.length === 0" class="empty-hint">数据无差异，清洗未改变任何数据</div>

        <!-- 新增标记列说明：清洗后若新增了标记列（标记类策略），列出列名与含义 -->
        <template v-if="markedColumns.length > 0">
          <h4 class="section-title">新增标记列</h4>
          <ul class="marked-columns-list">
            <li v-for="(item, idx) in markedColumns" :key="idx" class="marked-columns-item">
              <el-tag size="small" type="warning" effect="plain" style="margin-right: 6px;">
                {{ item.label }}
              </el-tag>
              <span class="marked-columns-desc">{{ item.description }}</span>
            </li>
          </ul>
        </template>

        <!-- 操作按钮 -->
        <div class="step-actions">
          <el-button size="default" @click="goToStep(3)">
            <el-icon style="margin-right:4px;"><ArrowLeft /></el-icon>
            上一步
          </el-button>
          <el-button type="success" size="default" @click="saveCleaningResult" :loading="saveLoading">
            <el-icon style="margin-right:4px;"><Check /></el-icon>
            保存清洗结果
          </el-button>
          <el-button size="default" @click="resetWizard">
            <el-icon style="margin-right:4px;"><Refresh /></el-icon>
            开始新的清洗
          </el-button>
        </div>
      </div>
    </div>

    <!-- ========== 警告对话框（dry-run 检测到警告时弹出） ========== -->
    <el-dialog
      v-model="warningDialogVisible"
      title="清洗警告确认"
      width="640px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="dry-run 预检检测到以下警告，是否强制执行？"
        style="margin-bottom: 12px;"
      />
      <el-table :data="warningList" border size="small" style="width: 100%;" max-height="300">
        <el-table-column type="index" label="#" width="60" align="center" />
        <el-table-column prop="type" label="类型" width="140" show-overflow-tooltip />
        <el-table-column prop="message" label="警告说明" min-width="200" show-overflow-tooltip />
        <el-table-column prop="suggestion" label="建议" min-width="180" show-overflow-tooltip />
      </el-table>
      <template #footer>
        <el-button @click="warningDialogVisible = false">返回修改</el-button>
        <el-button type="warning" @click="confirmForceExecute">强制执行</el-button>
      </template>
    </el-dialog>

    <!-- ========== 错误对话框（dry-run 检测到错误时弹出，阻断执行） ========== -->
    <el-dialog
      v-model="dryRunErrorDialogVisible"
      title="管道配置错误"
      width="640px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-alert
        type="error"
        :closable="false"
        show-icon
        title="dry-run 预检检测到以下错误，必须修改后才能执行"
        style="margin-bottom: 12px;"
      />
      <el-table :data="dryRunErrors" border size="small" style="width: 100%;" max-height="300">
        <el-table-column type="index" label="#" width="60" align="center" />
        <el-table-column prop="type" label="类型" width="140" show-overflow-tooltip />
        <el-table-column prop="message" label="错误说明" min-width="200" show-overflow-tooltip />
        <el-table-column prop="suggestion" label="建议" min-width="180" show-overflow-tooltip />
      </el-table>
      <template #footer>
        <el-button type="primary" @click="dryRunErrorDialogVisible = false">返回修改</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script>
export default { name: 'DataCleaning' }
</script>

<script setup>
import { ref, reactive, computed, inject, markRaw, onMounted, onActivated } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import DataSourceSelector from '../components/DataSourceSelector.vue'
import DataPreview from '../components/DataPreview.vue'

// DataSourceSelector组件引用，用于上传后调用reload刷新下拉框
const dataSourceSelectorRef = ref(null)
import {
  Search, Check, Upload, UploadFilled, Download, View, WarningFilled, Delete, Edit,
  Document, Setting, DataAnalysis, DataLine, ArrowRight, ArrowLeft, ArrowUp, ArrowDown,
  CirclePlus, Rank, VideoPlay, Loading, Refresh, Files, Tools, MagicStick, Grid, Promotion
} from '@element-plus/icons-vue'
import {
  uploadCleaningFile, fetchCleaningRawData,
  getCleaningPrecheck, postCleaningPrecheck, executeCleaningComprehensive,
  analyzeProblems, dryRunPipeline, recordCleaningStep, fetchDatasetData
} from '../api/index.js'
import { addTask } from '../stores/taskPanel.js'

const datasetStore = inject('datasetStore')

// ========== 数据集状态 ==========
const cleaningRawData = ref([])
const datasetId = ref(null)
// 记录上次已确认选中的数据集 ID，用于切换时用户取消后恢复（v-model 已先于 @change 更新，无法用 datasetId 回溯旧值）
const confirmedDatasetId = ref(null)
const currentDatasetName = ref('')

// 数据源配置（本地/远程模式）
const sourceConfig = ref({ mode: 'local', datasetId: null, remote: null })

// ====== 数据预览 ======
const previewColumns = ref([])
const previewRows = ref([])
const previewLoading = ref(false)
const previewTotal = ref(0)
const previewEmptyText = ref('')

// 加载数据预览（本地数据集前10行；远程模式后端暂不支持预览）
async function loadPreview() {
  if (sourceConfig.value.mode !== 'local' || !sourceConfig.value.datasetId) {
    previewColumns.value = []
    previewRows.value = []
    previewTotal.value = 0
    previewEmptyText.value = sourceConfig.value.mode === 'remote' ? '远程模式暂不支持数据预览' : ''
    return
  }
  previewLoading.value = true
  previewEmptyText.value = ''
  try {
    const res = await fetchDatasetData(sourceConfig.value.datasetId, 1, 10)
    const data = res.data
    if (data && Array.isArray(data.data)) {
      previewRows.value = data.data
      previewColumns.value = data.columns || (data.data[0] ? Object.keys(data.data[0]) : [])
      previewTotal.value = data.total_rows ?? data.data.length
    } else if (Array.isArray(data)) {
      previewRows.value = data
      previewColumns.value = data[0] ? Object.keys(data[0]) : []
      previewTotal.value = data.length
    } else {
      previewRows.value = []
      previewColumns.value = []
      previewTotal.value = 0
    }
  } catch {
    previewRows.value = []
    previewColumns.value = []
    previewTotal.value = 0
    previewEmptyText.value = '获取数据预览失败'
  } finally {
    previewLoading.value = false
  }
}

// 是否已有有效数据源选择
const hasDataSource = computed(() => {
  if (sourceConfig.value.mode === 'local') return !!sourceConfig.value.datasetId
  if (sourceConfig.value.mode === 'remote') return !!(sourceConfig.value.remote?.connection_id && sourceConfig.value.remote?.table_name)
  return false
})

// 数据源选择回调
function onSourceSelect(config) {
  if (config.mode === 'local') {
    if (config.datasetId) {
      onDatasetChange(config.datasetId)
    } else {
      // 清空选择
      datasetId.value = null
      confirmedDatasetId.value = null
      currentDatasetName.value = ''
    }
    sourceConfig.value = { mode: 'local', datasetId: config.datasetId, remote: null }
    loadPreview()
  } else if (config.mode === 'remote') {
    // 远程模式：与本地切换保持一致的确认逻辑
    const doSwitchRemote = () => {
      datasetId.value = null
      confirmedDatasetId.value = null
      currentDatasetName.value = config.remote?.table_name || ''
      sourceConfig.value = { mode: 'remote', datasetId: null, remote: config.remote }
      // 重置向导状态，清除上一个数据源的预检结果和配置残留
      resetWizardState()
      // 远程模式：内嵌数据预览暂不支持，置空并提示
      loadPreview()
    }
    // 如果当前有未完成的清洗流程，提示用户确认
    if (precheckResult.value && currentStep.value > 0) {
      ElMessageBox.confirm(
        '当前清洗流程尚未完成，切换数据集将重置当前进度。确定要切换吗？',
        '确认切换',
        {
          confirmButtonText: '确定切换',
          cancelButtonText: '取消',
          type: 'warning'
        }
      ).then(() => {
        doSwitchRemote()
      }).catch(() => {
        // 用户取消切换，DataSourceSelector的选中状态由其内部v-model控制
        // 这里不清除状态，让用户继续之前的操作
      })
      return
    }
    doSwitchRemote()
  }
}

// ========== 上传 ==========
const uploadFile = ref(null)
const uploadLoading = ref(false)

// ========== 向导步骤状态 ==========
// 0=预检 1=契约 2=问题清单 3=管道 4=审计
const currentStep = ref(0)

// ========== Step 1 预检状态 ==========
const precheckLoading = ref(false)
const precheckResult = ref(null)
// 预检方法说明折叠面板展开状态（默认折叠）
const precheckMethodActive = ref([])

// ========== Step 2 契约状态 ==========
// 列契约配置：基于预检的类型识别结果自动填充
const contractColumns = ref([])

// ========== Step 3 问题清单状态 ==========
const problemList = ref(null)          // 问题清单数据（包含 summary 与 problems）
const problemListLoading = ref(false)  // 问题清单加载状态
// 用户配置的处理方式：{ missing_values: {0: 'mean', 1: 'mode'}, type_errors: {0: 'delete'}, ... }
const problemStrategies = ref({})
// 处理方式对应的自定义参数（如 custom 时填充值）：结构与 problemStrategies 一致
const problemParams = ref({})
// 折叠面板默认展开项（默认展开全部有问题的组）
const problemCollapseActive = ref([])
// 批量设置时各组选中的处理方式
const batchStrategy = reactive({
  missing_values_numeric: '',
  missing_values_non_numeric: '',
  type_errors: '',
  range_errors: '',
  outliers: '',
  row_duplicates: '',
  column_duplicates: ''
})

// ========== Step 4 管道状态 ==========
// pipeline 项结构：{ id, operation, params }
// - id: 前端自增 ID，作为 v-for key
// - operation: 操作类型。其中 row_duplicates/column_duplicates/type_errors/range_errors/
//   outliers/missing_values 与后端 problem_strategies 的问题类型键对齐；
//   column_ops/row_filter 为管道特有的追加操作，不是 problem_strategies 的问题类型
// - params: 参数对象（仅 column_ops/row_filter 由用户在管道页内配置；其他操作的处理方式来自 Step 3）
const pipeline = ref([])
const executeLoading = ref(false)
const warningDialogVisible = ref(false)
const warningList = ref([])
const dragIndex = ref(null)      // 当前拖拽的管道项索引
// 标记管道是否已根据问题清单自动生成，避免每次进入 Step 4 都覆盖用户调整
const pipelineAutoGenerated = ref(false)
// dry-run 返回的错误列表（阻断执行），与 warnings 分开展示
const dryRunErrors = ref([])
// dry-run 错误对话框显隐：errors 不允许强制执行，只能返回修改
const dryRunErrorDialogVisible = ref(false)

// ========== Step 5 审计状态 ==========
const auditReport = ref(null)
const rowDiffCurrentPage = ref(1)
const rowDiffPageSize = ref(20)

const saveLoading = ref(false)

// ========== 状态保持：按数据集 ID 保存表单状态 ==========
// 切换到其他模块后回来，向导状态保持；仅在用户上传新数据或切换数据集时重置
const datasetFormStates = ref({})

function saveFormState(id) {
  if (!id) return
  datasetFormStates.value[id] = {
    currentStep: currentStep.value,
    precheckResult: precheckResult.value ? JSON.parse(JSON.stringify(precheckResult.value)) : null,
    contractColumns: JSON.parse(JSON.stringify(contractColumns.value)),
    problemList: problemList.value ? JSON.parse(JSON.stringify(problemList.value)) : null,
    problemStrategies: JSON.parse(JSON.stringify(problemStrategies.value)),
    problemParams: JSON.parse(JSON.stringify(problemParams.value)),
    pipeline: JSON.parse(JSON.stringify(pipeline.value)),
    pipelineAutoGenerated: pipelineAutoGenerated.value,
    auditReport: auditReport.value ? JSON.parse(JSON.stringify(auditReport.value)) : null
  }
}

// 恢复指定数据集上次保存的向导状态（keep-alive 从其他模块切回时调用）
// 修复：此前 saveFormState 只保存从不恢复，注释声称的"状态保持"实际未实现
function restoreFormState(id) {
  const saved = datasetFormStates.value[id]
  if (!saved) return
  // 仅在向导处于初始状态（未开始新流程）时恢复，避免覆盖用户当前正在进行的操作
  if (currentStep.value !== 0 || precheckResult.value) return
  currentStep.value = saved.currentStep || 0
  precheckResult.value = saved.precheckResult || null
  contractColumns.value = saved.contractColumns || []
  problemList.value = saved.problemList || null
  problemStrategies.value = saved.problemStrategies || {}
  problemParams.value = saved.problemParams || {}
  pipeline.value = saved.pipeline || []
  pipelineAutoGenerated.value = saved.pipelineAutoGenerated || false
  auditReport.value = saved.auditReport || null
}

// ========== 可用清洗操作定义 ==========
// 8 类操作（与后端 problem_strategies 问题类型对齐，便于管道与问题清单联动）
// 列操作（column_ops）和行过滤（row_filter）只能添加到管道末尾，前端在 addPipelineOperation 中强制限制
// icon 使用 markRaw 包装实际组件引用，避免被 Vue 响应式系统代理（组件应为不可变对象），
// 同时保证 <component :is="op.icon" /> 能正确解析为已导入的图标组件
const availableOperations = [
  { type: 'row_duplicates', name: '行重复处理', desc: '处理全行重复', icon: markRaw(Files), color: '#409eff', terminalOnly: false },
  { type: 'column_duplicates', name: '列重复处理', desc: '处理指定列重复', icon: markRaw(Grid), color: '#00bcd4', terminalOnly: false },
  { type: 'type_errors', name: '类型错误处理', desc: '删除/标记/强制转换', icon: markRaw(Document), color: '#909399', terminalOnly: false },
  { type: 'range_errors', name: '范围错误处理', desc: '截断/删除/填充', icon: markRaw(DataLine), color: '#9c27b0', terminalOnly: false },
  { type: 'outliers', name: '异常值处理', desc: '截断/删除/填充', icon: markRaw(WarningFilled), color: '#f56c6c', terminalOnly: false },
  { type: 'missing_values', name: '缺失值处理', desc: '均值/中位数/众数/删除/自定义', icon: markRaw(Edit), color: '#e6a23c', terminalOnly: false },
  { type: 'column_ops', name: '列操作', desc: '重命名/删除列（只能添加到末尾）', icon: markRaw(Setting), color: '#67c23a', terminalOnly: true },
  { type: 'row_filter', name: '行过滤', desc: '按条件过滤（只能添加到末尾）', icon: markRaw(Search), color: '#00bcd4', terminalOnly: true }
]

// 操作类型 → 中文名
function operationName(type) {
  const op = availableOperations.find(o => o.type === type)
  return op ? op.name : type
}

// 操作类型 → 标签颜色
function operationTagType(type) {
  const map = {
    row_duplicates: 'info',
    column_duplicates: 'info',
    type_errors: 'info',
    range_errors: '',
    outliers: 'danger',
    missing_values: 'warning',
    column_ops: 'success',
    row_filter: 'info'
  }
  return map[type] || ''
}

// 判断操作类型是否只能添加到管道末尾（列操作、行过滤）
function isTerminalOperation(type) {
  const op = availableOperations.find(o => o.type === type)
  return !!(op && op.terminalOnly)
}

// ========== 计算属性：预检结果展示 ==========
// 累加每列缺失值数量（取 count 字段）
const missingValuesCount = computed(() => {
  const mv = precheckResult.value?.missing_values
  if (!mv) return 0
  if (Array.isArray(mv)) {
    return mv.reduce((s, v) => s + (Number(v?.count || 0) || 0), 0)
  }
  if (typeof mv === 'object') {
    return Object.values(mv).reduce((s, v) => {
      const count = typeof v === 'number' ? v : (Number(v?.count || 0) || 0)
      return s + count
    }, 0)
  }
  return 0
})

// 重复行总数：取 full_row_count
const duplicateRowsCount = computed(() => {
  const dr = precheckResult.value?.duplicate_rows
  if (!dr) return 0
  if (typeof dr === 'number') return dr
  if (typeof dr === 'object') return Number(dr.full_row_count || dr.count || 0)
  return 0
})

const duplicateRowsPercent = computed(() => {
  // 优先使用后端直接返回的 percentage
  const pct = precheckResult.value?.duplicate_rows?.percentage
  if (pct != null) return pct + '%'
  // 兜底计算
  const total = precheckResult.value?.duplicate_rows?.total_rows || 0
  if (!total) return '-'
  return ((duplicateRowsCount.value / total) * 100).toFixed(2) + '%'
})

// 累加每列异常值数量（取 count 字段）
const outliersCount = computed(() => {
  const ol = precheckResult.value?.outliers
  if (!ol) return 0
  if (Array.isArray(ol)) {
    return ol.reduce((s, v) => s + (Number(v?.count || 0) || 0), 0)
  }
  if (typeof ol === 'object') {
    return Object.values(ol).reduce((s, v) => {
      const count = typeof v === 'number' ? v : (Number(v?.count || 0) || 0)
      return s + count
    }, 0)
  }
  return 0
})

// 累加每列类型错误数量（取 count 字段）
const typeErrorsCount = computed(() => {
  const te = precheckResult.value?.type_errors
  if (!te) return 0
  if (Array.isArray(te)) {
    return te.reduce((s, v) => s + (Number(v?.count || 0) || 0), 0)
  }
  if (typeof te === 'object') {
    return Object.values(te).reduce((s, v) => {
      const count = typeof v === 'number' ? v : (Number(v?.count || 0) || 0)
      return s + count
    }, 0)
  }
  return 0
})

const precheckAlertType = computed(() => {
  const total = missingValuesCount.value + duplicateRowsCount.value + outliersCount.value + typeErrorsCount.value
  return total === 0 ? 'success' : 'warning'
})

const precheckSummary = computed(() => {
  return `共发现 ${missingValuesCount.value} 个缺失值、${duplicateRowsCount.value} 行重复、${outliersCount.value} 个异常值、${typeErrorsCount.value} 个类型错误`
})

// 行号格式化：将索引数组转为"第XX、YY行"格式（索引从0开始，行号=索引+1）
// 超过 10 个时截断为"第XX、YY、...行（共ZZ行）"
function formatRowIndices(indices, maxDisplay = 10) {
  if (!Array.isArray(indices) || indices.length === 0) return '-'
  const validIndices = indices.map(i => Number(i)).filter(i => !Number.isNaN(i))
  if (validIndices.length === 0) return '-'
  if (validIndices.length <= maxDisplay) {
    return '第' + validIndices.map(i => i + 1).join('、') + '行'
  }
  const preview = validIndices.slice(0, maxDisplay).map(i => i + 1).join('、')
  return `第${preview}、...行（共${validIndices.length}行）`
}

// 缺失值表格行：显示列名、缺失数、百分比、行号（索引+1）
// 后端可能返回 {col: {count, percentage, row_indices, total_count}} 或旧版 {col: count}
const missingValueRows = computed(() => {
  const mv = precheckResult.value?.missing_values
  if (!mv) return []
  const total = precheckResult.value?.total_rows || 1
  // 兼容数组格式：[{column, count, row_indices}]
  if (Array.isArray(mv)) {
    return mv.map(item => {
      const count = Number(item.count || item.missing_count || 0) || 0
      const percentage = item.percentage != null
        ? Number(item.percentage)
        : (count / total * 100)
      return {
        column: item.column || item.name,
        missing_count: count,
        missing_percent: percentage.toFixed(2) + '%',
        row_indices_text: formatRowIndices(item.row_indices)
      }
    })
  }
  // 对象格式：{col: {count, percentage, row_indices}} 或 {col: count}
  if (typeof mv === 'object') {
    return Object.entries(mv).map(([col, info]) => {
      const isObj = typeof info === 'object' && info !== null
      const count = isObj ? (Number(info.count || 0) || 0) : (Number(info) || 0)
      const percentage = isObj && info.percentage != null
        ? Number(info.percentage)
        : (count / total * 100)
      const rowIndices = isObj ? info.row_indices : null
      return {
        column: col,
        missing_count: count,
        missing_percent: percentage.toFixed(2) + '%',
        row_indices_text: formatRowIndices(rowIndices)
      }
    })
  }
  return []
})

// 重复行组表格数据：展开行可查看每组重复行的行号和列值
// 后端返回 {full_row_count, groups: [{row_indices, row_values}], total_groups, suggestion}
const duplicateGroupRows = computed(() => {
  const dr = precheckResult.value?.duplicate_rows
  if (!dr || typeof dr !== 'object') return []
  const groups = Array.isArray(dr.groups) ? dr.groups : []
  // 最多展示 5 组，超过时由 duplicateGroupsTruncated 提示
  const displayed = groups.slice(0, 5)
  return displayed.map((g, idx) => {
    const rowIndices = Array.isArray(g.row_indices) ? g.row_indices : []
    const rowValues = g.row_values || {}
    // 列值预览：拼接前 3 个键值对
    const previewEntries = Object.entries(rowValues).slice(0, 3)
    const preview = previewEntries.map(([k, v]) => `${k}=${v}`).join(', ')
    return {
      group_index: idx + 1,
      row_count: rowIndices.length,
      row_indices_text: formatRowIndices(rowIndices),
      row_values: rowValues,
      row_values_preview: preview + (Object.keys(rowValues).length > 3 ? '...' : '')
    }
  })
})

// 重复行组总数（用于显示"前5组（共XX组）"）
const duplicateTotalGroups = computed(() => {
  const dr = precheckResult.value?.duplicate_rows
  if (!dr || typeof dr !== 'object') return 0
  if (dr.total_groups != null) return Number(dr.total_groups) || 0
  return Array.isArray(dr.groups) ? dr.groups.length : 0
})

// 是否被截断（实际组数大于展示数）
const duplicateGroupsTruncated = computed(() => {
  return duplicateTotalGroups.value > duplicateGroupRows.value.length
})

// 类型识别表格行
const typeDetectionRows = computed(() => {
  const td = precheckResult.value?.type_detection
  if (!td) return []
  // 兼容两种格式：{col: {type, samples}} 或 [{column, type, samples}]
  if (Array.isArray(td)) {
    return td.map(item => ({
      column: item.column || item.name,
      inferred_type: item.type || item.inferred_type || 'string',
      sample_values: Array.isArray(item.samples) ? item.samples.slice(0, 5).join(', ') : (item.sample_values || '-')
    }))
  }
  if (typeof td === 'object') {
    return Object.entries(td).map(([col, info]) => ({
      column: col,
      inferred_type: typeof info === 'string' ? info : (info.type || info.inferred_type || 'string'),
      sample_values: typeof info === 'object' && info.samples
        ? (Array.isArray(info.samples) ? info.samples.slice(0, 5).join(', ') : info.samples)
        : '-'
    }))
  }
  return []
})

// 异常值表格行：显示列名、异常值数、行号、异常值样本、IQR边界
// 后端返回 {col: {count, row_indices, values, bounds: {lower, upper}}}
const outlierRows = computed(() => {
  const ol = precheckResult.value?.outliers
  if (!ol) return []
  if (Array.isArray(ol)) {
    // 旧版数组格式按列聚合
    const byCol = {}
    for (const item of ol) {
      const col = item.column
      if (!byCol[col]) byCol[col] = { column: col, count: 0, indices: [], values: [], bounds: null }
      byCol[col].count++
      if (item.row !== undefined) byCol[col].indices.push(item.row)
      if (item.value !== undefined) byCol[col].values.push(item.value)
      if (item.bounds) byCol[col].bounds = item.bounds
    }
    return Object.values(byCol).map(v => buildOutlierRow(v))
  }
  if (typeof ol === 'object') {
    return Object.entries(ol).map(([col, info]) => {
      const isObj = typeof info === 'object' && info !== null
      const count = isObj ? (Number(info.count || 0) || 0) : (Number(info) || 0)
      return buildOutlierRow({
        column: col,
        count,
        indices: isObj ? (info.row_indices || info.indices || []) : [],
        values: isObj ? (info.values || []) : [],
        bounds: isObj ? info.bounds : null
      })
    })
  }
  return []
})

// 构造单行异常值展示数据：行号、异常值样本与行索引一一对应，IQR边界格式"[lower, upper]"
function buildOutlierRow({ column, count, indices, values, bounds }) {
  const safeIndices = Array.isArray(indices) ? indices : []
  const safeValues = Array.isArray(values) ? values : []
  // 异常值样本与行号一一对应显示："行91=150, 行153=-5"
  let valuesText = '-'
  if (safeValues.length > 0) {
    const pairs = safeValues.slice(0, 10).map((v, i) => {
      const idx = safeIndices[i]
      const rowLabel = idx != null ? `第${Number(idx) + 1}行=` : ''
      return `${rowLabel}${String(v)}`
    })
    valuesText = pairs.join(', ') + (safeValues.length > 10 ? ` ...（共${safeValues.length}个）` : '')
  }
  // IQR边界格式：[lower, upper]
  let boundsText = '-'
  if (bounds && (bounds.lower != null || bounds.upper != null)) {
    const lower = bounds.lower != null ? bounds.lower : '-∞'
    const upper = bounds.upper != null ? bounds.upper : '+∞'
    boundsText = `[${lower}, ${upper}]`
  }
  return {
    column,
    outlier_count: count,
    row_indices_text: formatRowIndices(safeIndices),
    values_text: valuesText,
    bounds_text: boundsText
  }
}

// 类型错误表格行：显示列名、错误数、期望类型、错误行号、错误值样本
// 后端返回 {col: {count, samples, error_rows: [{row_index, value}], expected_type}}
const typeErrorRows = computed(() => {
  const te = precheckResult.value?.type_errors
  if (!te) return []
  if (Array.isArray(te)) {
    // 旧版数组格式按列聚合
    const byCol = {}
    for (const item of te) {
      const col = item.column
      if (!byCol[col]) byCol[col] = { column: col, count: 0, samples: [], error_rows: [], expected_type: item.expected_type }
      byCol[col].count++
      if (item.value !== undefined) byCol[col].samples.push(item.value)
      if (item.row_index != null) byCol[col].error_rows.push({ row_index: item.row_index, value: item.value })
    }
    return Object.values(byCol).map(v => buildTypeErrorRow(v))
  }
  if (typeof te === 'object') {
    return Object.entries(te).map(([col, info]) => {
      const isObj = typeof info === 'object' && info !== null
      const count = isObj ? (Number(info.count || 0) || 0) : (Number(info) || 0)
      return buildTypeErrorRow({
        column: col,
        count,
        samples: isObj ? (info.samples || []) : [],
        error_rows: isObj ? (info.error_rows || []) : [],
        expected_type: isObj ? (info.expected_type || '') : ''
      })
    })
  }
  return []
})

// 构造单行类型错误展示数据：错误行号从 error_rows 提取并格式化为"第XX行"
function buildTypeErrorRow({ column, count, samples, error_rows, expected_type }) {
  const safeSamples = Array.isArray(samples) ? samples : []
  const safeErrorRows = Array.isArray(error_rows) ? error_rows : []
  // 错误行号：从 error_rows 提取 row_index
  const rowIndexList = safeErrorRows
    .map(er => er?.row_index)
    .filter(i => i != null)
  // 错误值样本：优先从 error_rows 提取 value，回退到 samples
  const valueList = safeErrorRows.length > 0
    ? safeErrorRows.map(er => er?.value).filter(v => v != null)
    : safeSamples
  return {
    column,
    error_count: count,
    expected_type: expected_type || '-',
    error_rows_text: formatRowIndices(rowIndexList),
    error_samples: valueList.slice(0, 5).map(s => String(s)).join(', ') || '-'
  }
}

// ========== 计算属性：契约配置 ==========
const contractColumnNames = computed(() => contractColumns.value.map(c => c.name))
const numericColumnNames = computed(() =>
  contractColumns.value.filter(c => c.expected_type === 'integer' || c.expected_type === 'number').map(c => c.name)
)

// 计算管道中第 idx 个位置之前的列操作重命名后，当前有效的列名集合
// 管道按顺序执行：前序 rename 已生效（如 年龄→age），后续操作只能引用改名后的列名。
// 这里按"原始列名 → 当前有效列名"链式跟踪（支持连续重命名），保证下拉选项与实际执行结果一致，
// 避免用户在后续步骤中选到已被改名的旧列名导致操作被静默跳过。
function effectiveColumnNamesAt(idx) {
  // 原始列名 → 当前有效列名 的映射（chain: 年龄→age→lianling 最终记 年龄→lianling）
  const effective = new Map()
  const ops = pipeline.value
  for (let i = 0; i < idx && i < ops.length; i++) {
    const op = ops[i]
    if (op.operation === 'column_ops' && op.params?.action === 'rename') {
      const oldName = op.params.column
      const newName = op.params.new_name
      if (!oldName || !newName) continue
      // 若 oldName 本身是某列的当前有效名，则它引用的原始列是 effective 中当前名等于 oldName 的那一项
      let original = oldName
      for (const [orig, cur] of effective) {
        if (cur === oldName) { original = orig; break }
      }
      effective.set(original, newName)
    }
  }
  return contractColumnNames.value.map(c => effective.get(c) || c)
}

function isNumericType(type) {
  return type === 'integer' || type === 'number'
}

// ========== 契约配置：类型切换、范围增删、摘要格式化、输入校验 ==========

// 切换 expected_type 时清理不相关字段，并初始化新类型所需的默认字段
// 例如从 integer 切换到 date：清空 ranges，初始化 min_date/max_date
function onExpectedTypeChange(row) {
  const newType = row.expected_type
  // 清理所有类型相关字段
  row.ranges = []
  row.decimal_places = null
  row.min_date = null
  row.max_date = null
  row.enum_values_text = ''
  row.min_length = null
  row.max_length = null
  // 允许缺失/允许重复为通用字段，保留原值

  // 按新类型初始化默认值
  if (isNumericType(newType)) {
    // 数值列：默认提供一个空范围供用户填写
    row.ranges = [[null, null]]
    if (newType === 'number') {
      row.decimal_places = 1
    }
  } else if (newType === 'boolean') {
    row.bool_representation = '0/1'
  }
}

// 添加新范围：在 ranges 数组末尾追加 [null, null]
function addRange(row) {
  if (!Array.isArray(row.ranges)) row.ranges = []
  row.ranges.push([null, null])
}

function removeRange(row, idx) {
  if (!Array.isArray(row.ranges)) return
  row.ranges.splice(idx, 1)
}

// 格式化数值列范围摘要："0-120" / "0-3, 5-9" / "无"
function formatRangeSummary(row) {
  const validRanges = (row.ranges || []).filter(r => Array.isArray(r) && (r[0] != null || r[1] != null))
  if (validRanges.length === 0) return '无'
  return validRanges.map(r => {
    const min = r[0] != null ? r[0] : '-∞'
    const max = r[1] != null ? r[1] : '+∞'
    return `${min}-${max}`
  }).join(', ')
}

// 格式化日期列范围摘要："2020-01-01 ~ 2025-12-31" / "无"
function formatDateRangeSummary(row) {
  const min = row.min_date || ''
  const max = row.max_date || ''
  if (!min && !max) return '无'
  if (min && max) return `${min} ~ ${max}`
  return min ? `≥ ${min}` : `≤ ${max}`
}

// 格式化字符串列约束摘要：显示枚举值数量或长度限制
function formatStringSummary(row) {
  const parts = []
  const enumText = (row.enum_values_text || '').trim()
  if (enumText) {
    const count = enumText.split(',').map(v => v.trim()).filter(v => v !== '').length
    parts.push(`${count} 个枚举`)
  }
  if (row.min_length != null || row.max_length != null) {
    const min = row.min_length != null ? row.min_length : 0
    const max = row.max_length != null ? row.max_length : '∞'
    parts.push(`长度 ${min}-${max}`)
  }
  return parts.length > 0 ? parts.join('，') : '无'
}

// 契约输入校验：在执行清洗前调用，返回 true 表示通过
// 校验规则：
// - 范围最小值必须小于最大值
// - 小数位数必须是 0-10 的整数
// - 枚举值不能为空（如果填写了）
// - 日期范围：最小日期必须早于最大日期
function validateContract() {
  for (const col of contractColumns.value) {
    const colLabel = `列 "${col.name}"`

    if (isNumericType(col.expected_type)) {
      // 校验范围：min 必须小于 max（两者都填写时）
      for (const range of (col.ranges || [])) {
        if (range && range[0] != null && range[1] != null) {
          if (Number(range[0]) >= Number(range[1])) {
            ElMessage.warning(`${colLabel} 的范围约束：最小值必须小于最大值`)
            return false
          }
        }
      }
      // 校验小数位数：0-10 的整数
      if (col.expected_type === 'number' && col.decimal_places != null) {
        const dp = Number(col.decimal_places)
        if (!Number.isInteger(dp) || dp < 0 || dp > 10) {
          ElMessage.warning(`${colLabel} 的小数位数必须是 0-10 的整数`)
          return false
        }
      }
    } else if (col.expected_type === 'date') {
      // 校验日期范围：min_date 必须早于 max_date（两者都填写时）
      if (col.min_date && col.max_date && col.min_date >= col.max_date) {
        ElMessage.warning(`${colLabel} 的日期范围：最小日期必须早于最大日期`)
        return false
      }
    } else if (col.expected_type === 'string') {
      // 校验枚举值：如果填写了文本，分割后不能产生空值（如 "a,,b"）
      const enumText = (col.enum_values_text || '').trim()
      if (enumText) {
        const values = enumText.split(',').map(v => v.trim())
        if (values.some(v => v === '')) {
          ElMessage.warning(`${colLabel} 的枚举值不能包含空值，请检查逗号分隔`)
          return false
        }
      }
      // 校验长度范围：min_length 必须小于等于 max_length（两者都填写时）
      if (col.min_length != null && col.max_length != null && Number(col.min_length) > Number(col.max_length)) {
        ElMessage.warning(`${colLabel} 的长度范围：最小长度不能大于最大长度`)
        return false
      }
    }
  }
  return true
}

// 类型中文标签
function typeLabel(type) {
  const map = {
    integer: '整数', number: '数值', string: '字符', boolean: '布尔',
    date: '日期', email: '邮箱', url: 'URL'
  }
  return map[type] || type
}

function typeTagColor(type) {
  const map = {
    integer: 'primary', number: 'primary', string: 'info', boolean: 'success',
    date: 'warning', email: 'warning', url: 'warning'
  }
  return map[type] || ''
}

// ========== 计算属性：审计报告 ==========
// 4 个质量维度定义：key 与后端 quality_scores 字段对齐
const qualityDimensions = [
  { key: 'completeness', label: '完整性', desc: '缺失值处理情况' },
  { key: 'uniqueness', label: '唯一性', desc: '重复值处理情况' },
  { key: 'consistency', label: '一致性', desc: '类型一致性' },
  { key: 'validity', label: '有效性', desc: '范围/异常值处理情况' }
]

function getQualityScore(key) {
  const scores = auditReport.value?.quality_scores?.after || auditReport.value?.quality_after || auditReport.value?.quality_scores || {}
  return Number(scores[key]) || 0
}

function getQualityBeforeScore(key) {
  const scores = auditReport.value?.quality_scores?.before || {}
  return Number(scores[key]) || 0
}

function getDataTypeLabel(type) {
  // 支持契约定义的类型（integer/number/string/boolean/date/email/url）
  const map = {
    'integer': '整数',
    'number': '数值',
    'string': '字符串',
    'boolean': '布尔',
    'date': '日期',
    'email': '邮箱',
    'url': 'URL',
    // 兼容 pandas 推断的旧类型
    'numeric': '数值'
  }
  return map[type] || type
}

function getDataTypeTagType(type) {
  const map = {
    'integer': 'primary',
    'number': 'primary',
    'numeric': 'primary',
    'string': 'info',
    'boolean': 'success',
    'date': 'warning',
    'email': 'warning',
    'url': 'warning'
  }
  return map[type] || 'info'
}

function getMethodTagType(method) {
  const map = {
    '标记缺失': 'warning',
    '删除行': 'danger',
    '截断': 'warning',
    '均值填充': 'success',
    '中位数填充': 'success',
    '众数填充': 'success',
    '自定义值填充': 'success',
    '保留原值': 'info',
    '强制转换': 'info',
    '自动处理': 'info',
    '行过滤': 'danger',
    '去重': 'info'
  }
  return map[method] || 'info'
}

function getQualityColor(score) {
  if (score >= 90) return '#67c23a'
  if (score >= 70) return '#409eff'
  if (score >= 50) return '#e6a23c'
  return '#f56c6c'
}

// 质量评分颜色分段：
// 90-100 绿色(success) / 70-89 蓝色(默认) / 50-69 黄色(warning) / 0-49 红色(exception)
const columnStatsRows = computed(() => {
  const stats = auditReport.value?.column_level_stats
  if (!stats) return []
  if (Array.isArray(stats)) return stats
  if (typeof stats === 'object') {
    return Object.entries(stats).map(([col, info]) => ({
      column: col,
      data_type: info.data_type ?? 'string',
      missing_before: info.original_missing ?? 0,
      missing_after: info.cleaned_missing ?? 0,
      missing_rate_before: info.original_missing_rate ?? 0,
      missing_rate_after: info.cleaned_missing_rate ?? 0,
      outlier_before: info.original_outliers ?? 0,
      outlier_after: info.cleaned_outliers ?? 0,
      duplicate_before: info.original_duplicate ?? 0,
      duplicate_after: info.cleaned_duplicate ?? 0
    }))
  }
  return []
})

// 操作数：优先使用后端 operations_count，否则从 operations 数组长度推断，最后回退到管道长度
const operationsCount = computed(() => {
  const report = auditReport.value || {}
  if (typeof report.operations_count === 'number') return report.operations_count
  if (Array.isArray(report.operations)) return report.operations.length
  return pipeline.value.length
})

// operation 类型 → 错误类型标签（用于行级对比表格的"错误类型"列）
function mapOperationToErrorType(op) {
  const map = {
    'row_duplicates': 'duplicate_removed',
    'column_duplicates': 'duplicate_removed',
    'type_errors': 'type_error',
    'range_errors': 'range_error',
    'outliers': 'outlier',
    'missing_values': 'missing'
  }
  return map[op] || 'modified'
}

// 行级变更列表：优先使用后端 row_diff/diff，否则从 operations 数组中聚合 changes/affected_rows
// 同一行的多条变更聚合为一个条目，changes 数组承载该行的所有字段变更
const rowDiffList = computed(() => {
  const report = auditReport.value || {}
  const result = []

  // 1. 后端直接提供 row_level_diff - 按单元格级别显示（每个单元格有独立的错误类型和处理方法）
  if (Array.isArray(report.row_level_diff) && report.row_level_diff.length) {
    result.push(...report.row_level_diff.map(diff => ({
      row: diff.row_index,
      column: diff.column,
      error_type: diff.error_type || '其他',
      method: diff.method || '未知',
      old_value: diff.original_value,
      new_value: diff.cleaned_value
    })))
  } else if (Array.isArray(report.row_diff) && report.row_diff.length) {
    result.push(...report.row_diff)
  } else if (Array.isArray(report.diff) && report.diff.length) {
    result.push(...report.diff)
  }

  // 2. 从 operations 的 affected_rows 中添加被删除的行（行过滤、去重等操作删除的行）
  const ops = report.operations || []
  ops.forEach(op => {
    const errorType = mapOperationToErrorType(op.operation)
    const method = op.method || '未知'
    // 2.1 changes 数组：每个 change 对应一行内某列的修改
    if (!Array.isArray(report.row_level_diff)) {
      ;(op.changes || []).forEach(ch => {
        const rowIdx = ch.row_index
        if (rowIdx === undefined || rowIdx === null) return
        // coerce_or_mark 策略的 status 字段记录了转换成功/失败的详细信息
        // 优先用 status 作为 method 显示，让用户看到"已强制转换为XX"或"转换失败：XX"
        const statusText = ch.status || ''
        result.push({
          row: rowIdx,
          column: ch.column,
          error_type: errorType,
          method: statusText || method,
          old_value: ch.old_value,
          new_value: ch.new_value
        })
      })
    }
    // 2.2 affected_rows：如重复行删除、行过滤删除，仅有行号无字段变更
    // 仅添加未在 result 中出现的行（避免与 row_level_diff 重复）
    ;(op.affected_rows || []).forEach(r => {
      if (!result.some(item => item.row === r && item.column === '(整行)')) {
        result.push({
          row: r,
          column: '(整行)',
          error_type: errorType,
          method: method,
          old_value: '存在',
          new_value: '已删除/处理'
        })
      }
    })
  })

  return result.sort((a, b) => a.row - b.row)
})

const paginatedRowDiff = computed(() => {
  const start = (rowDiffCurrentPage.value - 1) * rowDiffPageSize.value
  return rowDiffList.value.slice(start, start + rowDiffPageSize.value)
})

// operation 类型 → 标记列后缀名（用于生成标记列展示名）
function getMarkLabel(op) {
  const map = {
    'outliers': '异常值',
    'range_errors': '范围错误',
    'type_errors': '类型错误',
    'missing_values': '缺失值'
  }
  return map[op] || '标记'
}

// 新增标记列：优先使用后端 marked_columns 字段；否则从 operations 中提取 strategy 含 'mark' 的变更
// 返回数组：{ column, operation, label, description }
const markedColumns = computed(() => {
  const report = auditReport.value || {}
  const result = []
  const seen = new Set()
  
  if (Array.isArray(report.marked_columns)) {
    report.marked_columns.forEach(item => {
      const col = item.column || ''
      const op = item.operation || item.type
      const key = `${col}_${op}`
      if (!seen.has(key)) {
        seen.add(key)
        let label = item.label || col
        if (!label || typeof label !== 'string') {
          label = col.includes('_标记_') ? col : `${col}_标记_${getMarkLabel(op)}`
        }
        result.push({
          column: col,
          operation: op,
          label: label,
          description: item.description || `标记 ${col} 列的${getMarkLabel(op)}（是/否）`
        })
      }
    })
  }
  
  const ops = report.operations || []
  ops.forEach(op => {
    ;(op.changes || []).forEach(ch => {
      const strategy = String(ch.strategy || '').toLowerCase()
      if (strategy.includes('mark') && ch.column) {
        const col = ch.column
        const markLabel = getMarkLabel(op.operation)
        const markCol = `${col}_标记_${markLabel}`
        const key = `${col}_${op.operation}`
        if (!seen.has(key)) {
          seen.add(key)
          result.push({
            column: markCol,
            operation: op.operation,
            label: markCol,
            description: `标记 ${col} 列的${markLabel}（是/否）`
          })
        }
      }
    })
  })
  
  return result
})

const markedColumnsCount = computed(() => markedColumns.value.length)

// ========== 差异类型辅助函数 ==========
function diffTypeLabel(type) {
  const map = {
    'range_error': '范围错误',
    'type_error': '类型错误',
    'outlier': '异常值',
    'missing': '缺失值填充',
    'duplicate_removed': '重复值删除',
    'modified': '数据修改',
    'deleted': '行删除',
    'added': '行新增'
  }
  return map[type] || type || '修改'
}

function diffTypeColor(type) {
  const map = {
    'range_error': 'warning',
    'type_error': 'danger',
    'outlier': 'warning',
    'missing': 'info',
    'duplicate_removed': 'danger',
    'modified': '',
    'deleted': 'danger',
    'added': 'success'
  }
  return map[type] || ''
}

// ========== 生命周期 ==========
// 首次加载标志：keep-alive 下首次进入会同时触发 onMounted 和 onActivated，
// 用此标志让 onActivated 首次跳过，避免重复请求 /cleaning/raw-data
let isFirstLoad = true

onMounted(async () => {
  try {
    const res = await fetchCleaningRawData()
    cleaningRawData.value = res.data || []
  } catch {
    ElMessage.warning('无法加载清洗模块原始数据列表')
  }
  isFirstLoad = false
})

onActivated(async () => {
  // 首次加载由 onMounted 处理，跳过避免重复请求
  if (isFirstLoad) return
  try {
    const res = await fetchCleaningRawData()
    cleaningRawData.value = res.data || []
  } catch {
    ElMessage.warning('无法加载清洗模块原始数据列表')
  }
  // 异步清洗任务由全局任务面板统一管理轮询，组件激活/失活时无需自行恢复或停止轮询
  // 从其他模块切回时恢复当前数据集的向导状态（修复：此前状态只保存不恢复）
  if (datasetId.value) {
    restoreFormState(datasetId.value)
  }
})

// ========== 文件上传 ==========
function onFileChange(file) {
  uploadFile.value = file.raw || file
}

function cancelUpload() {
  uploadFile.value = null
}

async function doUpload() {
  if (!uploadFile.value) return
  uploadLoading.value = true
  try {
    const res = await uploadCleaningFile(uploadFile.value)
    const data = res.data || {}
    if (data.id) {
      // 刷新下拉框并自动选中新上传的数据集，避免用户在带时间戳的重名文件中难以辨认
      await dataSourceSelectorRef.value?.reload()
      dataSourceSelectorRef.value?.selectDataset(data.id)
      // 上传新数据时重置向导状态
      resetWizardState()
      datasetId.value = data.id
      confirmedDatasetId.value = data.id
      currentDatasetName.value = data.name || uploadFile.value.name
      const exists = cleaningRawData.value.find(d => d.id === data.id)
      if (!exists) {
        cleaningRawData.value.push(data)
      }
      if (datasetStore?.datasets) {
        datasetStore.datasets.push(data)
      }
      ElMessage.success('文件上传成功，已自动选择该文件，请点击"开始预检"')
    } else {
      ElMessage.success('文件上传成功')
    }
    uploadFile.value = null
  } catch {
    ElMessage.error('上传失败，请检查文件格式')
  } finally {
    uploadLoading.value = false
  }
}

// ========== 数据集切换 ==========
function onDatasetChange(val) {
  // 用户取消切换时，恢复到上次确认选择的数据集（v-model 已先更新为新值）
  const restoreSelection = () => {
    datasetId.value = confirmedDatasetId.value
  }
  // 异步清洗任务现已由全局任务面板管理，切换数据集不会中断后台任务，
  // 因此仅需对未完成的本地向导流程提示确认
  // 如果当前已经有预检结果，提示用户确认
  if (precheckResult.value && currentStep.value > 0) {
    ElMessageBox.confirm(
      '当前清洗流程尚未完成，切换数据集将重置当前进度。确定要切换吗？',
      '确认切换',
      {
        confirmButtonText: '确定切换',
        cancelButtonText: '取消',
        type: 'warning'
      }
    ).then(() => {
      doSwitchDataset(val)
    }).catch(restoreSelection)
    return
  }
  
  doSwitchDataset(val)
}

function doSwitchDataset(val) {
  // 保存当前数据集的表单状态
  if (datasetId.value) {
    saveFormState(datasetId.value)
  }
  const ds = cleaningRawData.value.find(d => d.id === val)
  currentDatasetName.value = ds?.name || ''
  datasetId.value = val
  confirmedDatasetId.value = val
  // 切换数据集时完全重置向导状态，不恢复之前的状态
  resetWizardState()
}

// 重置向导状态（不重置数据集列表）
function resetWizardState() {
  currentStep.value = 0
  precheckResult.value = null
  contractColumns.value = []
  problemList.value = null
  problemStrategies.value = {}
  problemParams.value = {}
  problemCollapseActive.value = []
  pipeline.value = []
  // 重置管道项 ID 计数器，避免 keep-alive 下长期使用导致 ID 持续增长
  pipelineItemId = 0
  pipelineAutoGenerated.value = false
  dryRunErrors.value = []
  auditReport.value = null
}

// 完全重置向导（用户在 Step 5 点击"开始新的清洗"）
function resetWizard() {
  resetWizardState()
  ElMessage.info('已重置向导，请重新选择数据集并预检')
}

// ========== Step 1 预检 ==========
async function runPrecheck() {
  if (!hasDataSource.value) {
    ElMessage.warning('请先选择数据源')
    return
  }
  precheckLoading.value = true
  try {
    const isRemote = sourceConfig.value.mode === 'remote'
    let res
    if (isRemote && sourceConfig.value.remote) {
      res = await postCleaningPrecheck({
        remote: sourceConfig.value.remote
      })
    } else {
      res = await getCleaningPrecheck(datasetId.value)
    }
    precheckResult.value = res.data || {}
    // 自动填充 Step 2 契约配置（基于类型识别结果）
    buildContractFromPrecheck()
    // 重置 Step 4 管道状态：进入 Step 4 时会根据问题清单自动生成（Task 11）
    pipeline.value = []
    pipelineAutoGenerated.value = false
    ElMessage.success('预检完成，已自动配置列契约')
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || '预检失败'
    ElMessage.error('预检失败：' + msg)
  } finally {
    precheckLoading.value = false
  }
}

// 基于预检结果构建契约列配置
// 按新契约结构生成默认值：
// - expected_type: 使用预检的 inferred_type
// - allow_missing: 该列有缺失值则默认 true，否则 false
// - allow_duplicate: 默认 true（用户可手动关闭）
// - ranges: 数值列不设置（用户手动配置）
// - decimal_places: number 类型默认 1
// - 其他字段：不设置
function buildContractFromPrecheck() {
  if (!precheckResult.value) {
    contractColumns.value = []
    return
  }
  const td = precheckResult.value.type_detection || {}
  const mv = precheckResult.value.missing_values || {}

  // 兼容两种格式：数组 [{column, type}] 或对象 {col: {type}}
  const entries = Array.isArray(td)
    ? td.map(item => [item.column || item.name, item])
    : Object.entries(td)

  contractColumns.value = entries.map(([col, info]) => {
    const inferredType = typeof info === 'string' ? info : (info.type || info.inferred_type || 'string')
    // 根据缺失值统计判断是否允许缺失：缺失数>0 则默认允许
    const missingInfo = mv[col]
    const missingCount = missingInfo ? (Number(missingInfo.count || missingInfo) || 0) : 0
    // 按新契约结构初始化所有字段，便于展开行直接 v-model 绑定
    return {
      name: col,
      expected_type: inferredType,
      // 数值列范围配置：[[min, max], ...]，初始为单个空范围供用户填写
      ranges: isNumericType(inferredType) ? [[null, null]] : [],
      // number 类型小数位数默认 1
      decimal_places: inferredType === 'number' ? 1 : null,
      // 日期列最小/最大日期
      min_date: null,
      max_date: null,
      // 字符串列枚举值（文本输入，逗号分隔）和长度限制
      enum_values_text: '',
      min_length: null,
      max_length: null,
      // 布尔列表示方式，默认 0/1
      bool_representation: '0/1',
      // 通用约束
      // allow_missing 默认 false：缺失值默认作为问题处理；用户手动开启该列"允许缺失"后不再列为问题（修复）
      allow_missing: false,
      allow_duplicate: true
    }
  })
}

// 基于预检结果自动配置清洗管道（已废弃，管道改由 Step 3 问题清单驱动自动生成）
// 保留空函数体避免影响其他可能的引用，实际逻辑由 generateAutoPipeline 接管
function autoConfigurePipeline() {
  pipeline.value = []
  pipelineAutoGenerated.value = false
}

// ========== 步骤切换 ==========
function goToStep(step) {
  // 切换到 Step 2/3/4/5 前必须有预检结果
  if (step >= 1 && !precheckResult.value) {
    ElMessage.warning('请先完成预检')
    return
  }
  // 切换到 Step 3（问题清单）时：
  // 1. 先验证契约配置（范围最小值必须小于最大值等）
  // 2. 重新获取问题清单（契约修改后需要重新计算）
  // 3. 记录契约配置到操作历史（阶段1）
  if (step === 2) {
    if (!validateContract()) return
    // 记录契约配置到操作历史（fire-and-forget，不阻塞主流程）
    if (datasetId.value) {
      recordCleaningStep({
        dataset_id: datasetId.value,
        step: 'contract_config',
        contract: buildContract()
      }).catch(() => {})
    }
    if (!problemListLoading.value) {
      fetchProblemList()
    }
  }
  // 切换到 Step 4（管道配置）时：
  // 1. 若未自动生成过管道，则根据问题清单自动生成
  // 2. 记录问题清单配置到操作历史（阶段2）
  if (step === 3) {
    if (!pipelineAutoGenerated.value) {
      generateAutoPipeline()
    }
    // 记录问题清单配置到操作历史（fire-and-forget，不阻塞主流程）
    if (datasetId.value) {
      recordCleaningStep({
        dataset_id: datasetId.value,
        step: 'problem_strategy',
        problem_strategies: buildProblemStrategies()
      }).catch(() => {})
    }
  }
  // 切换到 Step 5（审计）前必须有审计报告（除非是异步完成自动跳转）
  if (step === 4 && !auditReport.value) {
    ElMessage.warning('请先执行清洗')
    return
  }
  currentStep.value = step
}

// ========== Step 4 管道操作 ==========
let pipelineItemId = 0

// 策略值 → 中文文案映射，用于生成管道项摘要
// 覆盖 8 类问题所有可能的策略取值（与 Step 3 getStrategyOptions 中的 label 保持一致）
// 同时兼容后端实际使用的策略值（如 delete_all/manual_select）
const strategyTextMap = {
  // 缺失值
  mean: '均值填充',
  median: '中位数填充',
  mode: '众数填充',
  delete: '删除行',
  custom: '自定义值填充',
  mark: '标记缺失',
  // 类型错误
  delete_row: '删除行',
  mark_missing: '标记为缺失',
  coerce_or_mark: '强制转换',
  // 范围错误
  clip_upper: '截断到上边界',
  clip_lower: '截断到下边界',
  clip_nearest: '截断到最近边界',
  // 异常值
  clip: '截断',
  // 重复
  keep_first: '保留第一条',
  keep_last: '保留最后一条',
  delete_all: '全部删除',
  manual_select: '手动选择'
}

// 根据问题清单自动生成管道（Task 11）
// 按后端 dry_run_pipeline() 推荐顺序生成：行重复 → 列重复 → 类型错误 → 范围错误 → 异常值 → 缺失值 → 列操作 → 行过滤
// 列操作和行过滤默认空参数，由用户在管道页内补充配置
function generateAutoPipeline() {
  const pipelineItems = []
  const problems = problemList.value?.problems || {}

  // 仅在问题清单中存在该类问题时才加入对应操作（避免无意义的空步骤）
  if (problems.row_duplicates?.length > 0) {
    pipelineItems.push({ operation: 'row_duplicates', params: {} })
  }
  if (problems.column_duplicates?.length > 0) {
    pipelineItems.push({ operation: 'column_duplicates', params: {} })
  }
  if (problems.type_errors?.length > 0) {
    pipelineItems.push({ operation: 'type_errors', params: {} })
  }
  if (problems.range_errors?.length > 0) {
    pipelineItems.push({ operation: 'range_errors', params: {} })
  }
  if (problems.outliers?.length > 0) {
    pipelineItems.push({ operation: 'outliers', params: {} })
  }
  if (problems.missing_values?.length > 0) {
    pipelineItems.push({ operation: 'missing_values', params: {} })
  }
  // 列操作和行过滤默认空，由用户在管道页内配置参数（始终追加到末尾）
  pipelineItems.push({ operation: 'column_ops', params: getDefaultParams('column_ops') })
  pipelineItems.push({ operation: 'row_filter', params: getDefaultParams('row_filter') })

  // 为每个管道项分配前端自增 ID（v-for key）
  pipeline.value = pipelineItems.map(item => ({
    id: ++pipelineItemId,
    operation: item.operation,
    params: item.params
  }))
  pipelineAutoGenerated.value = true
}

// 重新生成管道：用户点击"根据问题清单重新生成"按钮时调用，会覆盖当前管道
function regeneratePipeline() {
  if (!problemList.value) {
    ElMessage.warning('请先在 Step 3 完成问题清单分析')
    return
  }
  generateAutoPipeline()
  ElMessage.success('已根据问题清单重新生成管道')
}

// 清空管道
function clearPipeline() {
  pipeline.value = []
  // 重置管道项 ID 计数器，使下次添加从 1 开始
  pipelineItemId = 0
  pipelineAutoGenerated.value = false
  ElMessage.info('已清空管道')
}

// 生成管道项摘要文本（不重复配置处理方式，仅展示来自问题清单的统计与策略）
// 返回空字符串时模板显示"未配置"或"无相关问题"
function getPipelineItemSummary(item) {
  const problems = problemList.value?.problems || {}
  const strategies = problemStrategies.value || {}
  const params = problemParams.value || {}
  const op = item.operation

  if (op === 'row_duplicates') {
    const list = problems.row_duplicates || []
    if (list.length === 0) return ''
    const strategy = strategies.row_duplicates?.[0] || list[0]?.suggested_strategy || 'keep_first'
    return `共${list.length}组重复，处理方式：${strategyTextMap[strategy] || strategy}`
  }

  if (op === 'column_duplicates') {
    const list = problems.column_duplicates || []
    if (list.length === 0) return ''
    // 多组列重复可能涉及不同列，按列名聚合显示
    const columnSummary = list.map((p, idx) => {
      const strategy = strategies.column_duplicates?.[idx] || p.suggested_strategy || 'keep_first'
      return `${p.column}:${strategyTextMap[strategy] || strategy}`
    }).join('，')
    return `共${list.length}组重复，${columnSummary}`
  }

  if (op === 'type_errors') {
    const list = problems.type_errors || []
    if (list.length === 0) return ''
    // 按列聚合统计错误数与策略
    const columnMap = new Map()
    list.forEach((p, idx) => {
      const col = p.column || '未知列'
      const strategy = strategies.type_errors?.[idx] || p.suggested_strategy || 'coerce_or_mark'
      if (!columnMap.has(col)) columnMap.set(col, { count: 0, strategy })
      columnMap.get(col).count += 1
    })
    const detail = Array.from(columnMap.entries())
      .map(([col, info]) => `${col}:${strategyTextMap[info.strategy] || info.strategy}`)
      .join('，')
    return `共${list.length}个错误，${detail}`
  }

  if (op === 'range_errors') {
    const list = problems.range_errors || []
    if (list.length === 0) return ''
    const columnMap = new Map()
    list.forEach((p, idx) => {
      const col = p.column || '未知列'
      const strategy = strategies.range_errors?.[idx] || p.suggested_strategy || 'clip'
      if (!columnMap.has(col)) columnMap.set(col, { count: 0, strategy })
      columnMap.get(col).count += 1
    })
    const detail = Array.from(columnMap.entries())
      .map(([col, info]) => `${col}:${strategyTextMap[info.strategy] || info.strategy}`)
      .join('，')
    return `共${list.length}个错误，${detail}`
  }

  if (op === 'outliers') {
    const list = problems.outliers || []
    if (list.length === 0) return ''
    const columnMap = new Map()
    list.forEach((p, idx) => {
      const col = p.column || '未知列'
      const strategy = strategies.outliers?.[idx] || p.suggested_strategy || 'clip'
      if (!columnMap.has(col)) columnMap.set(col, { count: 0, strategy })
      columnMap.get(col).count += 1
    })
    const detail = Array.from(columnMap.entries())
      .map(([col, info]) => `${col}:${strategyTextMap[info.strategy] || info.strategy}`)
      .join('，')
    return `共${list.length}个错误，${detail}`
  }

  if (op === 'missing_values') {
    const list = problems.missing_values || []
    if (list.length === 0) return ''
    // 统计总缺失数：每条问题记录代表一个缺失单元格
    const totalMissing = list.length
    // 按列聚合策略
    const columnMap = new Map()
    list.forEach((p, idx) => {
      const col = p.column || '未知列'
      const strategy = strategies.missing_values?.[idx] || p.suggested_strategy || 'mode'
      if (!columnMap.has(col)) columnMap.set(col, { count: 0, strategy, customValue: '' })
      const entry = columnMap.get(col)
      entry.count += 1
      if (strategy === 'custom' && params.missing_values?.[idx]) {
        entry.customValue = params.missing_values[idx]
      }
    })
    const detail = Array.from(columnMap.entries())
      .map(([col, info]) => {
        const strategyLabel = strategyTextMap[info.strategy] || info.strategy
        return info.customValue
          ? `${col}:${strategyLabel}=${info.customValue}`
          : `${col}:${strategyLabel}`
      })
      .join('，')
    return `共${totalMissing}个缺失，${detail}`
  }

  if (op === 'column_ops') {
    const action = item.params?.action
    const column = item.params?.column
    if (!action || !column) return ''
    const actionLabel = action === 'rename' ? '重命名' : '删除'
    if (action === 'rename' && item.params?.new_name) {
      return `${actionLabel}：${column} → ${item.params.new_name}`
    }
    return `${actionLabel}列：${column}`
  }

  if (op === 'row_filter') {
    const condition = item.params?.condition
    if (!condition) return ''
    return `过滤条件：${condition}`
  }

  return ''
}

// 添加管道操作：列操作和行过滤只能添加到末尾
function addPipelineOperation(type) {
  // 列操作和行过滤只能添加到管道末尾：若已有非末尾的同类操作或位置不当，提示用户
  if (isTerminalOperation(type)) {
    // 找到最后一个非末尾操作的位置，列操作/行过滤只能添加在它之后
    const lastNonTerminalIdx = pipeline.value.length - 1
    // 终端操作只能追加到末尾，直接 push
    pipeline.value.push({
      id: ++pipelineItemId,
      operation: type,
      params: getDefaultParams(type)
    })
    ElMessage.success(`已添加 "${operationName(type)}" 操作（末尾）`)
    return
  }

  // 非终端操作不能添加在已有的列操作/行过滤之后，需插入到第一个终端操作之前
  const firstTerminalIdx = pipeline.value.findIndex(op => isTerminalOperation(op.operation))
  const newItem = {
    id: ++pipelineItemId,
    operation: type,
    params: getDefaultParams(type)
  }
  if (firstTerminalIdx === -1) {
    // 没有终端操作，直接追加
    pipeline.value.push(newItem)
  } else {
    // 插入到第一个终端操作之前
    pipeline.value.splice(firstTerminalIdx, 0, newItem)
  }
  ElMessage.success(`已添加 "${operationName(type)}" 操作`)
}

// 各操作的默认参数（仅 column_ops/row_filter 由用户在管道页内配置，其他操作的默认参数留空）
function getDefaultParams(type) {
  const defaults = {
    row_duplicates: {},
    column_duplicates: {},
    type_errors: {},
    range_errors: {},
    outliers: {},
    missing_values: {},
    // 列操作默认参数：action=重命名，列与新列名由用户选择
    column_ops: { action: 'rename', column: '', new_name: '' },
    // 行过滤默认参数：过滤条件由用户填写
    row_filter: { condition: '' }
  }
  return JSON.parse(JSON.stringify(defaults[type] || {}))
}

function removePipelineItem(idx) {
  pipeline.value.splice(idx, 1)
}

// 判断指定操作能否移动到目标方向（用于禁用上移/下移按钮）
// 列操作和行过滤不能跨越其他操作：只能整体在末尾区间内调整相对顺序
function canMoveTo(operationType, idx, direction) {
  const newIdx = idx + direction
  if (newIdx < 0 || newIdx >= pipeline.value.length) return false

  // 终端操作（列操作/行过滤）不能与非终端操作互换位置
  const targetOp = pipeline.value[newIdx]
  if (isTerminalOperation(operationType) !== isTerminalOperation(targetOp.operation)) {
    return false
  }
  return true
}

// 上下移动调整顺序（已添加终端操作位置约束）
function movePipelineItem(idx, direction) {
  const newIdx = idx + direction
  if (newIdx < 0 || newIdx >= pipeline.value.length) return
  const currentOp = pipeline.value[idx]
  if (!canMoveTo(currentOp.operation, idx, direction)) {
    ElMessage.warning('列操作和行过滤只能在末尾区间内调整顺序')
    return
  }
  const items = pipeline.value
  ;[items[idx], items[newIdx]] = [items[newIdx], items[idx]]
}

// ========== 拖拽排序（HTML5 原生 API） ==========
function onDragStart(idx) {
  dragIndex.value = idx
}

function onDragOver(idx) {
  // 阻止默认行为以允许 drop
}

function onDrop(idx) {
  if (dragIndex.value === null || dragIndex.value === idx) return
  const fromIdx = dragIndex.value
  const draggedOp = pipeline.value[fromIdx]
  const targetOp = pipeline.value[idx]
  // 终端操作与非终端操作不能互换位置
  if (isTerminalOperation(draggedOp.operation) !== isTerminalOperation(targetOp.operation)) {
    ElMessage.warning('列操作和行过滤只能在末尾区间内调整顺序')
    dragIndex.value = null
    return
  }
  const items = pipeline.value
  items.splice(fromIdx, 1)
  items.splice(idx, 0, draggedOp)
  dragIndex.value = null
}

function onDragEnd() {
  dragIndex.value = null
}

// ========== 构建契约和管道请求体 ==========
// 按新契约结构构建：{columns: {col_name: {expected_type, ranges, decimal_places, ...}}}
// 仅包含与该列类型相关的字段，避免发送冗余字段
function buildContract() {
  const columns = {}
  for (const col of contractColumns.value) {
    const colContract = {
      expected_type: col.expected_type,
      allow_missing: col.allow_missing,
      allow_duplicate: col.allow_duplicate
    }

    if (isNumericType(col.expected_type)) {
      // 数值列：过滤掉未填写的范围，仅保留有效范围
      const validRanges = (col.ranges || [])
        .filter(r => Array.isArray(r) && (r[0] != null || r[1] != null))
        .map(r => [r[0], r[1]])
      if (validRanges.length > 0) {
        colContract.ranges = validRanges
      }
      // number 类型携带小数位数
      if (col.expected_type === 'number' && col.decimal_places != null) {
        colContract.decimal_places = col.decimal_places
      }
    } else if (col.expected_type === 'date') {
      // 日期列：仅携带已选择的日期
      if (col.min_date) colContract.min_date = col.min_date
      if (col.max_date) colContract.max_date = col.max_date
    } else if (col.expected_type === 'string') {
      // 字符串列：枚举值由逗号分隔文本转为数组
      const enumText = (col.enum_values_text || '').trim()
      if (enumText) {
        colContract.enum_values = enumText.split(',').map(v => v.trim()).filter(v => v !== '')
      }
      if (col.min_length != null) colContract.min_length = col.min_length
      if (col.max_length != null) colContract.max_length = col.max_length
    } else if (col.expected_type === 'boolean') {
      // 布尔列：携带表示方式
      colContract.bool_representation = col.bool_representation
    }

    columns[col.name] = colContract
  }
  return { columns }
}

// 构建管道请求体：[{operation, params}]
// 后端 execute_cleaning_with_strategies 根据 operation 字段决定执行顺序，
// params 仅对 column_ops/row_filter 有意义（其他操作的处理方式来自 problem_strategies）
function buildPipeline() {
  return pipeline.value.map(op => ({
    operation: op.operation,
    params: op.params ? JSON.parse(JSON.stringify(op.params)) : {}
  }))
}

// 从 problemStrategies/problemParams/problemList 构建后端需要的 problem_strategies 结构
// 后端期望结构：{ 问题类型: [ { row_index/column, strategy, [value], [row_indices], ... } ] }
// 行重复和列重复有特殊字段（row_indices、duplicate_value），需单独处理
function buildProblemStrategies() {
  const result = {}
  const strategies = problemStrategies.value || {}
  const params = problemParams.value || {}
  const problems = problemList.value?.problems || {}

  for (const [problemType, items] of Object.entries(problems)) {
    if (!Array.isArray(items)) continue
    result[problemType] = items.map((problem, idx) => {
      // 优先使用用户配置的策略，回退到后端建议策略
      const strategy = strategies[problemType]?.[idx] || problem.suggested_strategy
      const item = {
        row_index: problem.row_index,
        column: problem.column,
        strategy: strategy
      }
      // 异常值问题：携带问题清单记录的原始 IQR 边界，避免缺失值填充后边界漂移导致异常值漏处理/误处理（修复）
      if (problemType === 'outliers' && problem.iqr_bounds) {
        item.iqr_bounds = problem.iqr_bounds
      }
      // 自定义策略：携带用户填写的自定义值
      if (strategy === 'custom' && params[problemType]?.[idx]) {
        item.value = params[problemType][idx]
      }
      // 行重复：使用 row_indices（一组重复行号），不携带 row_index/column
      if (problemType === 'row_duplicates') {
        item.row_indices = problem.row_indices
        delete item.row_index
        delete item.column
      }
      // 列重复：携带 column/duplicate_value/row_indices，不携带 row_index
      if (problemType === 'column_duplicates') {
        item.column = problem.column
        item.duplicate_value = problem.duplicate_value
        item.row_indices = problem.row_indices
        delete item.row_index
      }
      return item
    })
  }

  return result
}

// ========== Step 3 问题清单：获取数据、处理方式选项、批量设置 ==========

// 是否存在任何问题（用于无数据时显示 el-empty）
const hasAnyProblem = computed(() => {
  const problems = problemList.value?.problems
  if (!problems) return false
  return Object.values(problems).some(arr => Array.isArray(arr) && arr.length > 0)
})

// 缺失值问题：数值列缺失（带原始索引，用于 problemStrategies 访问）
const numericMissingProblems = computed(() => {
  const list = problemList.value?.problems?.missing_values || []
  return list
    .map((item, originalIndex) => ({ ...item, originalIndex }))
    .filter(item => item.column_type === 'integer' || item.column_type === 'number')
})

// 缺失值问题：非数值列缺失（带原始索引）
const nonNumericMissingProblems = computed(() => {
  const list = problemList.value?.problems?.missing_values || []
  return list
    .map((item, originalIndex) => ({ ...item, originalIndex }))
    .filter(item => item.column_type !== 'integer' && item.column_type !== 'number')
})

// 获取问题清单：调用后端 analyzeProblems 接口，传入 buildContract() 构建的契约
const fetchProblemList = async () => {
  if (!hasDataSource.value) {
    ElMessage.warning('请先选择数据集')
    return
  }
  problemListLoading.value = true
  try {
    const contract = buildContract()
    const remote = sourceConfig.value.mode === 'remote' ? sourceConfig.value.remote : null
    const res = await analyzeProblems(datasetId.value, contract, remote)
    problemList.value = res.data || {}
    // 初始化 problemStrategies 与 problemParams，默认使用 suggested_strategy
    initProblemStrategies()
    // 默认展开所有有问题的分组
    initCollapseActive()
    ElMessage.success('问题清单分析完成')
  } catch (e) {
    const msg = e?.response?.data?.message || e?.response?.data?.detail || e?.message || '获取问题清单失败'
    ElMessage.error('获取问题清单失败：' + msg)
  } finally {
    problemListLoading.value = false
  }
}

// 初始化 problemStrategies 与 problemParams
// 默认使用每条问题返回的 suggested_strategy；若缺失则使用各类型的默认策略
function initProblemStrategies() {
  const strategies = {}
  const params = {}
  const problems = problemList.value?.problems || {}
  for (const [problemType, items] of Object.entries(problems)) {
    if (!Array.isArray(items)) continue
    strategies[problemType] = {}
    params[problemType] = {}
    items.forEach((item, idx) => {
      // 优先使用后端返回的 suggested_strategy，否则回退到类型默认策略
      strategies[problemType][idx] = item.suggested_strategy || getDefaultStrategy(problemType)
      params[problemType][idx] = ''
    })
  }
  problemStrategies.value = strategies
  problemParams.value = params
}

// 默认展开所有存在问题的分组
function initCollapseActive() {
  const active = []
  const problems = problemList.value?.problems || {}
  for (const [problemType, items] of Object.entries(problems)) {
    if (Array.isArray(items) && items.length > 0) {
      // 缺失值分为两个子分组
      if (problemType === 'missing_values') {
        if (numericMissingProblems.value.length > 0) {
          active.push('missing_values_numeric')
        }
        if (nonNumericMissingProblems.value.length > 0) {
          active.push('missing_values_non_numeric')
        }
      } else {
        active.push(problemType)
      }
    }
  }
  problemCollapseActive.value = active
}

// 各问题类型的默认处理策略（与后端 suggested_strategy 取值保持一致）
function getDefaultStrategy(problemType) {
  const defaults = {
    missing_values: 'mode',
    type_errors: 'coerce_or_mark',
    range_errors: 'clip',
    outliers: 'clip',
    row_duplicates: 'keep_first',
    column_duplicates: 'keep_first'
  }
  return defaults[problemType] || ''
}

// 缺失值处理方式选项（根据列类型动态过滤）
// 参数 columnType：'integer'/'number' 时返回完整选项，其他类型返回精简选项
// 参数为 'all' 时根据问题清单中实际的列类型动态决定显示哪些选项
function getMissingStrategyOptions(columnType) {
  const numericOptions = [
    { value: 'mean', label: '均值' },
    { value: 'median', label: '中位数' },
    { value: 'mode', label: '众数' },
    { value: 'delete', label: '删除' },
    { value: 'custom', label: '自定义' },
    { value: 'mark', label: '标记' }
  ]
  const otherOptions = [
    { value: 'mode', label: '众数' },
    { value: 'delete', label: '删除' },
    { value: 'custom', label: '自定义' },
    { value: 'mark', label: '标记' }
  ]
  if (columnType === 'all') {
    // 批量设置时根据问题清单中实际的列类型动态决定显示哪些选项
    const missingProblems = problemList.value?.problems?.missing_values || []
    const hasNumericColumn = missingProblems.some(p => 
      p.column_type === 'integer' || p.column_type === 'number'
    )
    return hasNumericColumn ? numericOptions : otherOptions
  }
  if (columnType === 'integer' || columnType === 'number') {
    return numericOptions
  }
  return otherOptions
}

// 获取某类问题的处理方式选项
// 参数 problemType：问题类型
// 参数 columnType：列类型（仅 missing_values 使用）
function getStrategyOptions(problemType, columnType) {
  if (problemType === 'missing_values') {
    return getMissingStrategyOptions(columnType)
  }
  if (problemType === 'type_errors') {
    return [
      { value: 'delete_row', label: '删除行' },
      { value: 'mark_missing', label: '标记为缺失' },
      { value: 'coerce_or_mark', label: '强制转换' }
    ]
  }
  if (problemType === 'range_errors') {
    return [
      { value: 'clip_upper', label: '截断到上边界' },
      { value: 'clip_lower', label: '截断到下边界' },
      { value: 'clip_nearest', label: '截断到最近' },
      { value: 'delete_row', label: '删除行' },
      { value: 'mark', label: '标记' },
      { value: 'mean', label: '均值' },
      { value: 'median', label: '中位数' },
      { value: 'custom', label: '自定义' }
    ]
  }
  if (problemType === 'outliers') {
    return [
      { value: 'clip', label: '截断' },
      { value: 'mean', label: '均值' },
      { value: 'median', label: '中位数' },
      { value: 'mode', label: '众数' },
      { value: 'delete_row', label: '删除行' },
      { value: 'mark', label: '标记' },
      { value: 'custom', label: '自定义' }
    ]
  }
  if (problemType === 'row_duplicates') {
    return [
      { value: 'keep_first', label: '保留第一条' },
      { value: 'keep_last', label: '保留最后一条' },
      { value: 'delete_all', label: '全部删除' }
    ]
  }
  if (problemType === 'column_duplicates') {
    return [
      { value: 'keep_first', label: '保留第一条' },
      { value: 'keep_last', label: '保留最后一条' },
      { value: 'delete_all', label: '全部删除' },
      { value: 'manual_select', label: '手动选择' }
    ]
  }
  return []
}

// 批量设置某类问题的处理方式：一键将所有问题的策略设为同一值
function batchSetStrategy(problemType, strategy) {
  if (!strategy) {
    ElMessage.warning('请先选择处理方式')
    return
  }
  const groupStrategies = problemStrategies.value[problemType]
  if (!groupStrategies) {
    ElMessage.warning('该组暂无问题')
    return
  }
  const count = Object.keys(groupStrategies).length
  for (const idx of Object.keys(groupStrategies)) {
    groupStrategies[idx] = strategy
  }
  ElMessage.success(`已批量设置 ${count} 个问题的处理方式为"${getStrategyLabel(problemType, strategy)}"`)
}

// 批量设置数值列缺失值的处理方式
function batchSetNumericMissingStrategy(strategy) {
  if (!strategy) {
    ElMessage.warning('请先选择处理方式')
    return
  }
  const groupStrategies = problemStrategies.value.missing_values
  if (!groupStrategies) {
    ElMessage.warning('该组暂无问题')
    return
  }
  const items = numericMissingProblems.value
  if (items.length === 0) {
    ElMessage.warning('暂无数值列缺失值问题')
    return
  }
  items.forEach(item => {
    groupStrategies[item.originalIndex] = strategy
  })
  ElMessage.success(`已批量设置 ${items.length} 个数值列缺失值的处理方式`)
}

// 批量设置非数值列缺失值的处理方式
function batchSetNonNumericMissingStrategy(strategy) {
  if (!strategy) {
    ElMessage.warning('请先选择处理方式')
    return
  }
  const groupStrategies = problemStrategies.value.missing_values
  if (!groupStrategies) {
    ElMessage.warning('该组暂无问题')
    return
  }
  const items = nonNumericMissingProblems.value
  if (items.length === 0) {
    ElMessage.warning('暂无非数值列缺失值问题')
    return
  }
  items.forEach(item => {
    groupStrategies[item.originalIndex] = strategy
  })
  ElMessage.success(`已批量设置 ${items.length} 个非数值列缺失值的处理方式`)
}

// 获取策略的中文标签（用于提示消息）
function getStrategyLabel(problemType, value) {
  const options = getStrategyOptions(problemType)
  const hit = options.find(opt => opt.value === value)
  return hit ? hit.label : value
}

// 格式化契约范围显示：[[0, 120]] → "0-120"；[[0, 3], [5, 9]] → "0-3, 5-9"
function formatContractRanges(ranges) {
  if (!Array.isArray(ranges) || ranges.length === 0) return '-'
  return ranges
    .map(r => {
      if (!Array.isArray(r)) return String(r)
      const min = r[0] != null ? r[0] : '-∞'
      const max = r[1] != null ? r[1] : '+∞'
      return `${min}-${max}`
    })
    .join(', ')
}

// 格式化 IQR 边界显示：{lower: 10.5, upper: 65.5} → "[10.5, 65.5]"
function formatIqrBounds(bounds) {
  if (!bounds) return '-'
  const lower = bounds.lower != null ? bounds.lower : '-∞'
  const upper = bounds.upper != null ? bounds.upper : '+∞'
  return `[${lower}, ${upper}]`
}

// ========== 执行清洗 ==========
// 流程：契约校验 → dry-run 预检 → 根据结果分支（错误阻断 / 警告确认 / 无问题执行） → 同步或异步执行
async function executeCleaning() {
  if (pipeline.value.length === 0) {
    ElMessage.warning('请至少添加一个清洗操作')
    return
  }
  if (executeLoading.value) return
  // 执行前校验契约配置（范围、小数位数、枚举值、日期范围等）
  if (!validateContract()) return

  executeLoading.value = true
  try {
    // 1. 调用 dry-run 接口预检管道合理性
    const dryRunResult = await runDryRunCheck()
    if (!dryRunResult) {
      // dry-run 调用失败或出错，已展示错误信息，直接返回
      return
    }

    // 2. 错误阻断：dry-run 返回 errors 时阻止执行，弹出错误对话框展示详情
    if (dryRunResult.errors && dryRunResult.errors.length > 0) {
      dryRunErrors.value = dryRunResult.errors
      dryRunErrorDialogVisible.value = true
      ElMessage.error(`管道配置存在 ${dryRunResult.errors.length} 个错误，请修改后再执行`)
      return
    }
    dryRunErrors.value = []

    // 3. 警告确认：dry-run 返回 warnings 时弹出对话框，用户选择"强制执行"或"返回修改"
    if (dryRunResult.warnings && dryRunResult.warnings.length > 0) {
      warningList.value = dryRunResult.warnings
      warningDialogVisible.value = true
      return
    }

    // 4. 无问题：直接执行清洗
    await doExecuteCleaning(false)
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || '清洗失败'
    ElMessage.error('清洗执行失败：' + msg)
  } finally {
    executeLoading.value = false
  }
}

// 调用 dry-run 接口预检管道配置
// 返回 null 表示调用失败或出错（已展示错误信息），调用方应直接返回
async function runDryRunCheck() {
  if (!hasDataSource.value) {
    ElMessage.warning('请先选择数据集')
    return null
  }
  try {
    const remote = sourceConfig.value.mode === 'remote' ? sourceConfig.value.remote : null
    const res = await dryRunPipeline(datasetId.value, {
      contract: buildContract(),
      problem_strategies: buildProblemStrategies(),
      pipeline: buildPipeline()
    }, remote)
    return res.data || {}
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || 'dry-run 预检失败'
    ElMessage.error('dry-run 预检失败：' + msg)
    return null
  }
}

// 实际执行清洗：调用 /api/cleaning/comprehensive 接口
// force=true 表示用户在警告对话框中确认强制执行
async function doExecuteCleaning(force) {
  const isRemote = sourceConfig.value.mode === 'remote'
  const requestBody = {
    dataset_id: isRemote ? null : datasetId.value,
    contract: buildContract(),
    problem_strategies: buildProblemStrategies(),
    pipeline: buildPipeline(),
    force: force,
    save_result: false
  }
  // 远程模式下添加 remote 参数
  if (isRemote && sourceConfig.value.remote) {
    requestBody.remote = sourceConfig.value.remote
  }
  const res = await executeCleaningComprehensive(requestBody)
  const data = res.data || {}

  if (data.status === 'warning') {
    // 兼容后端在 comprehensive 接口内部再次返回 warning 的情况
    warningList.value = data.warnings || []
    warningDialogVisible.value = true
    return
  }

  if ((data.status === 'queued' || data.status === 'running' || data.status === 'pending') && data.task_record_id) {
    // 大数据集异步执行，使用全局任务面板管理进度
    // 后端可能返回 queued/running/pending 三种状态，统一交给 taskPanel 管理
    const submitDatasetId = datasetId.value
    addTask({
      recordId: data.task_record_id,
      celeryTaskId: data.task_id,
      taskType: 'cleaning',
      operation: '数据清洗',
      moduleLabel: '数据清洗',
      datasetName: currentDatasetName.value || '',
      initialStatus: data.status === 'pending' ? 'pending' : 'running',
      isRemote: sourceConfig.value.mode === 'remote',
    }, (status, summary) => {
        if (status === 'success') {
          // 数据集一致性校验：用户切换数据集后，不覆盖当前审计报告
          if (datasetId.value !== submitDatasetId) {
            ElMessage.info('清洗完成，请切回原数据集查看审计报告')
            return
          }
          // 清洗成功：从 result_summary 中提取审计报告，进入 Step 5（审计）
          ElMessage.success('清洗完成，已生成审计报告')
          if (summary && (summary.audit_report || summary.cleaned_dataset_id)) {
            auditReport.value = summary.audit_report || summary
          }
          currentStep.value = 4
        } else if (status === 'failed') {
          // 清洗失败：展示错误信息
          ElMessage.error(`清洗失败: ${summary?.current_message || '请查看任务面板'}`)
        } else if (status === 'cancelled') {
          ElMessage.info('清洗任务已取消')
        } else if (status === 'warning') {
          ElMessage.warning('清洗检测到潜在问题，请查看任务面板详情')
        }
      })
    ElMessage.info('清洗任务已提交至后台队列，可在任务面板查看进度')
    return
  }

  if (data.status === 'success') {
    // 同步执行成功，直接进入 Step 5（审计）
    auditReport.value = data.audit_report || data
    ElMessage.success(force ? '强制清洗完成，已生成审计报告' : '清洗完成，已生成审计报告')
    currentStep.value = 4
    return
  }

  // 兼容旧版返回格式（无 status 字段）
  if (data.audit_report || data.cleaned_dataset_id || data.results) {
    auditReport.value = data.audit_report || data
    ElMessage.success('清洗完成')
    currentStep.value = 4
  } else {
    ElMessage.warning('后端返回数据格式未识别')
  }
}

// 警告对话框确认后强制执行：用户点击"强制执行"按钮时调用
async function confirmForceExecute() {
  warningDialogVisible.value = false
  executeLoading.value = true
  try {
    await doExecuteCleaning(true)
  } catch (e) {
    const msg = e?.response?.data?.detail || e?.message || '强制清洗失败'
    ElMessage.error('强制清洗失败：' + msg)
  } finally {
    executeLoading.value = false
  }
}

// ========== 保存清洗结果 ==========
async function saveCleaningResult() {
  saveLoading.value = true
  try {
    // 捕获提交时数据集ID，用于异步回调返回时校验数据集一致性
    const submitDatasetId = datasetId.value
    const isRemote = sourceConfig.value.mode === 'remote'
    const requestBody = {
      dataset_id: isRemote ? null : datasetId.value,
      contract: buildContract(),
      problem_strategies: buildProblemStrategies(),
      pipeline: buildPipeline(),
      force: true,
      save_result: true
    }
    if (isRemote && sourceConfig.value.remote) {
      requestBody.remote = sourceConfig.value.remote
    }
    const res = await executeCleaningComprehensive(requestBody)
    const data = res.data || {}

    // 异步分支：大数据集（≥1万行）后端返回 running/queued/pending + task_record_id
    // 修复问题2类：原实现只判断 success，异步状态会走 else 分支误报"保存清洗结果失败"
    if ((data.status === 'queued' || data.status === 'running' || data.status === 'pending') && data.task_record_id) {
      addTask({
        recordId: data.task_record_id,
        celeryTaskId: data.task_id,
        taskType: 'cleaning',
        operation: '保存清洗结果',
        moduleLabel: '数据清洗',
        datasetName: currentDatasetName.value || '',
        initialStatus: data.status === 'pending' ? 'pending' : 'running',
      isRemote: sourceConfig.value.mode === 'remote',
      }, (status, summary) => {
        if (status === 'success') {
          // 数据集一致性校验：用户切换数据集后，不覆盖当前状态
          if (datasetId.value !== submitDatasetId) {
            ElMessage.info('清洗结果已保存，请切回原数据集查看')
            return
          }
          const cleanedId = summary?.cleaned_dataset_id
          if (cleanedId) {
            ElMessage.success(`清洗结果已保存到数据管理（数据集 ID: ${cleanedId}），可在数据管理模块查看`)
          } else {
            ElMessage.success('清洗结果已保存到数据管理')
          }
        } else if (status === 'failed') {
          ElMessage.error(`保存清洗结果失败: ${summary?.current_message || '请查看任务面板'}`)
        } else if (status === 'cancelled') {
          ElMessage.info('保存任务已取消')
        }
      })
      ElMessage.info('保存任务已提交至后台队列，可在任务面板查看进度')
      return
    }

    // 同步成功分支
    if (data.status === 'success') {
      const cleanedId = data.cleaned_dataset_id
      if (cleanedId) {
        ElMessage.success(`清洗结果已保存到数据管理（数据集 ID: ${cleanedId}），可在数据管理模块查看`)
      } else {
        ElMessage.success('清洗结果已保存到数据管理')
      }
    } else {
      ElMessage.error('保存清洗结果失败')
    }
  } catch (error) {
    ElMessage.error('保存清洗结果失败：' + (error.message || '未知错误'))
  } finally {
    saveLoading.value = false
  }
}
</script>

<style scoped>
.data-cleaning {
  display: flex;
  flex-direction: column;
}
.dataset-selector-label {
  font-size: 14px;
  color: var(--text-primary);
  font-weight: 500;
}
.dataset-name-tag {
  margin-left: 8px;
}

/* 卡片标题 */
.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 16px;
}
.card-title .el-icon {
  color: var(--primary);
}

/* 空状态 */
.empty-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  padding: 20px;
  text-align: center;
  justify-content: center;
}

/* 步骤操作按钮区域 */
.step-actions {
  display: flex;
  justify-content: space-between;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid #ebeef5;
}

/* 预检结果区域 */
.precheck-result {
  margin-top: 16px;
}

/* 统计卡片网格 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.stat-card {
  padding: 16px;
  background: linear-gradient(135deg, #fafbff 0%, #f0f4ff 100%);
  border: 1px solid #e5e9f5;
  border-radius: 8px;
  text-align: center;
  transition: all 0.2s;
}
.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}
.stat-value {
  font-size: 28px;
  font-weight: 700;
  font-family: 'Consolas', 'Monaco', monospace;
  margin-bottom: 4px;
}
.stat-unit {
  font-size: 14px;
  font-weight: 400;
}
.stat-label {
  font-size: 13px;
  color: var(--text-secondary);
}

/* 问题分节 */
.problem-section {
  margin-top: 20px;
  padding: 16px;
  background: #f8fafc;
  border-radius: 6px;
}
.problem-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 15px;
  color: var(--text-primary);
}
.sample-values {
  font-family: monospace;
  font-size: 12px;
  color: var(--text-secondary);
  word-break: break-all;
}

/* 管道配置区域 */
.pipeline-palette,
.pipeline-configured {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 12px;
  background: #fafbfc;
  min-height: 320px;
}
.palette-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 可用操作项 */
.palette-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.2s;
}
.palette-item:hover {
  border-color: var(--primary);
  background: #ecf5ff;
}
.palette-item-text {
  flex: 1;
  min-width: 0;
}
.palette-item-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.palette-item-desc {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 2px;
}
.palette-item-add {
  color: var(--primary);
}

/* 已配置管道空状态 */
.pipeline-empty {
  text-align: center;
  padding: 40px 20px;
}

/* 管道项 */
.pipeline-item {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  margin-bottom: 10px;
  transition: all 0.2s;
}
.pipeline-item:hover {
  border-color: #c0c4cc;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.05);
}
.pipeline-item-dragging {
  opacity: 0.5;
  border: 2px dashed var(--primary);
}
.pipeline-item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid #f0f0f0;
  background: #fafbfc;
  border-radius: 6px 6px 0 0;
}
.pipeline-item-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.pipeline-item-right {
  display: flex;
  align-items: center;
  gap: 4px;
}
.pipeline-item-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.drag-handle {
  cursor: move;
  color: #c0c4cc;
}
.drag-handle:hover {
  color: var(--primary);
}
.pipeline-item-body {
  padding: 12px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

/* 管道项摘要：显示来自问题清单的统计与处理方式，灰色小字 */
.pipeline-item-summary {
  padding: 6px 12px 8px 32px;
  font-size: 12px;
  color: var(--text-muted);
  display: flex;
  align-items: flex-start;
  gap: 6px;
  line-height: 1.5;
  border-top: 1px dashed #f0f0f0;
}
.pipeline-item-summary .summary-icon {
  color: #c0c4cc;
  font-weight: 600;
  flex-shrink: 0;
}
.pipeline-item-summary .summary-text {
  flex: 1;
  word-break: break-all;
}
.pipeline-item-summary .summary-empty {
  font-style: italic;
  color: #c0c4cc;
}

/* 终端操作（列操作/行过滤）样式：左侧色条提示只能在末尾 */
.pipeline-item-terminal {
  border-left: 3px solid #e6a23c;
}
.palette-item-terminal {
  border-left: 3px solid #e6a23c;
}

/* 管道顶部工具栏：重新生成 / 清空 / 提示文字 */
.pipeline-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.pipeline-toolbar-hint {
  font-size: 12px;
  color: var(--text-muted);
  margin-left: auto;
}

/* 审计报告区域 */
.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 20px 0 12px 0;
  padding-left: 10px;
  border-left: 3px solid var(--primary);
}
.section-title:first-child {
  margin-top: 0;
}

/* 摘要卡片 */
.audit-summary {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
}
.summary-card {
  padding: 16px;
  background: #f8fafc;
  border-radius: 8px;
  text-align: center;
  border: 1px solid #e4e7ed;
}
.summary-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}
.summary-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--primary);
  font-family: 'Consolas', 'Monaco', monospace;
}
/* 摘要卡片下方的小字提示（如"含 2 个标记列"） */
.summary-hint {
  margin-top: 4px;
  font-size: 11px;
  color: var(--text-muted);
}

/* 新增标记列说明列表 */
.marked-columns-list {
  margin: 0;
  padding: 12px 16px;
  background: #fdf6ec;
  border: 1px solid #f5dab1;
  border-radius: 6px;
  list-style: none;
}
.marked-columns-item {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  padding: 4px 0;
  font-size: 12px;
  line-height: 1.6;
}
.marked-columns-desc {
  color: var(--text-secondary);
}

/* 质量评分网格 */
.quality-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}
.quality-card {
  padding: 16px;
  background: #f8fafc;
  border-radius: 8px;
  border: 1px solid #e4e7ed;
}
.quality-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.quality-compare {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
  gap: 8px;
}
.quality-before, .quality-after {
  flex: 1;
  text-align: center;
}
.quality-before-label, .quality-after-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.quality-before-value, .quality-after-value {
  font-size: 20px;
  font-weight: 700;
}
.quality-arrow {
  color: var(--text-muted);
  font-size: 16px;
}
.quality-desc {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 6px;
}

/* 行级差异 */
.diff-change {
  display: flex;
  align-items: center;
  font-size: 12px;
  padding: 2px 0;
}
.diff-column {
  font-weight: 600;
  color: var(--text-primary);
  margin-right: 4px;
}
.diff-old {
  color: #f56c6c;
  font-family: monospace;
}
.diff-new {
  color: #67c23a;
  font-family: monospace;
}

.text-muted {
  color: var(--text-muted);
  font-size: 12px;
}

/* ========== Step 2 契约配置展开行样式 ========== */
.contract-expand {
  padding: 16px 24px;
  background: #f8fafc;
  border-radius: 4px;
}

/* 范围配置区域 */
.range-config {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}
.range-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.range-separator {
  color: var(--text-secondary);
  font-size: 13px;
}
.range-hint {
  font-size: 11px;
  color: var(--text-muted);
  margin-top: 4px;
}

/* 范围约束摘要 */
.range-summary {
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  color: var(--text-primary);
}

/* 表单项辅助提示文字 */
.form-hint {
  margin-left: 8px;
  font-size: 11px;
  color: var(--text-muted);
}

/* 响应式：小屏幕下统计/审计区域纵向排列 */
@media (max-width: 768px) {
  .stats-grid,
  .audit-summary,
  .quality-grid {
    grid-template-columns: 1fr;
  }
}

/* ========== 重复行展开行样式 ========== */
.dup-expand {
  padding: 8px 16px;
  background: #f8fafc;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.dup-expand-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
  line-height: 1.6;
}
.dup-label {
  flex-shrink: 0;
  color: var(--text-primary);
  font-weight: 600;
}
.dup-values {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.dup-value-tag {
  font-family: 'Consolas', 'Monaco', monospace;
}

/* 截断提示 */
.truncated-hint {
  margin-top: 8px;
  text-align: right;
  font-size: 12px;
  color: var(--text-muted);
  font-style: italic;
}

/* ========== 预检方法说明折叠面板 ========== */
.precheck-method-collapse {
  margin-top: 20px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  background: #fafbfc;
}
.method-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 0;
}
.method-item {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  line-height: 1.6;
}
.method-desc {
  color: var(--text-secondary);
}

/* ========== Step 3 问题清单样式 ========== */

/* 加载中提示 */
.problem-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 0;
  color: var(--text-secondary);
}

/* 顶部汇总卡片行 */
.problem-summary-row {
  margin-bottom: 16px;
}

/* 单个汇总卡片：使用 --card-color 变量驱动边框色 */
.problem-summary-card {
  padding: 16px 12px;
  background: linear-gradient(135deg, #fafbff 0%, #f0f4ff 100%);
  border: 1px solid var(--card-color, #e5e9f5);
  border-left: 4px solid var(--card-color, #409eff);
  border-radius: 8px;
  text-align: center;
  transition: all 0.2s;
}
.problem-summary-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}
.problem-summary-value {
  font-size: 26px;
  font-weight: 700;
  font-family: 'Consolas', 'Monaco', monospace;
  margin-bottom: 4px;
  line-height: 1.2;
}
.problem-summary-label {
  font-size: 13px;
  color: var(--text-secondary);
}

/* 折叠面板容器 */
.problem-collapse {
  margin-top: 8px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  background: #fafbfc;
}

/* 折叠面板标题 */
.collapse-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

/* 批量设置操作区 */
.batch-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0 12px 0;
  margin-bottom: 8px;
  border-bottom: 1px dashed #e4e7ed;
}
.batch-label {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 600;
}

/* 响应式：小屏幕下汇总卡片调整为 2 列 */
@media (max-width: 768px) {
  .problem-summary-row .el-col {
    margin-bottom: 8px;
  }
}
</style>
