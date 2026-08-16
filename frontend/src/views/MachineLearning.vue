<template>
  <div class="machine-learning">
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
        aria-label="上传数据文件进行机器学习分析"
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
      <DataSourceSelector ref="dataSourceSelectorRef" module-source="ml" @select="onSourceSelect" />
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

    <!-- ========== 预检结果展示(位于任务配置上方,先预检再配置) ========== -->
    <div v-if="hasDataSource && (precheckLoading || precheckResult)" class="card">
      <div class="card-title">
        <el-icon><DataAnalysis /></el-icon>
        <span>训练前预检</span>
        <el-tag v-if="precheckLoading" type="info" effect="plain" size="small" style="margin-left:8px;">检测中...</el-tag>
        <el-tag v-else-if="precheckResult?.can_train" type="success" effect="plain" size="small" style="margin-left:8px;">可训练</el-tag>
        <el-tag v-else type="danger" effect="plain" size="small" style="margin-left:8px;">存在阻断错误</el-tag>
      </div>

      <div v-if="precheckResult">
        <!-- 数据概况 -->
        <el-descriptions :column="4" border size="small" style="margin-bottom:12px;">
          <el-descriptions-item label="数据行数">{{ precheckResult.data_profile.row_count }}</el-descriptions-item>
          <el-descriptions-item label="总列数">{{ precheckResult.data_profile.col_count }}</el-descriptions-item>
          <el-descriptions-item label="数值列">{{ precheckResult.data_profile.numeric_count }}</el-descriptions-item>
          <el-descriptions-item label="分类列">{{ precheckResult.data_profile.categorical_count }}</el-descriptions-item>
          <el-descriptions-item label="缺失值">
            {{ precheckResult.data_profile.missing_total }} ({{ (precheckResult.data_profile.missing_rate * 100).toFixed(1) }}%)
          </el-descriptions-item>
          <el-descriptions-item label="常量列">
            <span v-if="precheckResult.data_profile.constant_columns.length">
              {{ precheckResult.data_profile.constant_columns.length }} 个
            </span>
            <span v-else>无</span>
          </el-descriptions-item>
          <el-descriptions-item label="高基数列">
            <span v-if="precheckResult.data_profile.high_cardinality_columns.length">
              {{ precheckResult.data_profile.high_cardinality_columns.length }} 个
            </span>
            <span v-else>无</span>
          </el-descriptions-item>
        </el-descriptions>

        <!-- 阻断错误 -->
        <el-alert
          v-for="err in precheckResult.checks.errors"
          :key="err.code"
          :title="err.message"
          type="error"
          show-icon
          :closable="false"
          style="margin-bottom:6px;"
        />

        <!-- 警告 -->
        <el-alert
          v-for="warn in precheckResult.checks.warnings"
          :key="warn.code"
          :title="warn.message"
          type="warning"
          show-icon
          :closable="false"
          style="margin-bottom:6px;"
        />

        <!-- 信息提示 -->
        <el-alert
          v-for="info in precheckResult.checks.infos"
          :key="info.code"
          :title="info.message"
          type="info"
          show-icon
          :closable="false"
          style="margin-bottom:6px;"
        />

        <!-- 目标列推荐总览(按列显示推荐分类/回归及原因,与算法推荐配合使用) -->
        <div v-if="precheckResult.target_column_recommendations && precheckResult.target_column_recommendations.length" style="margin-top:12px;">
          <div style="font-size:13px;color:var(--text-muted);margin-bottom:8px;display:flex;align-items:center;">
            <span>目标列推荐(✓ 推荐 ✗ 不推荐,鼠标悬停查看原因):</span>
            <el-tooltip placement="top" effect="dark">
              <template #content>
                <div style="max-width:320px;line-height:1.6;">
                  <strong>目标列推荐规则:</strong><br/>
                  • 数值列+唯一值>10:推荐回归(预测连续数值)<br/>
                  • 数值列+唯一值2-10:推荐分类(类别数适中)<br/>
                  • 分类列+唯一值2-20:推荐分类<br/>
                  • 分类列+唯一值>20:都不推荐(需先编码)<br/>
                  • 唯一值<2或缺失率>50%:都不推荐
                </div>
              </template>
              <el-icon style="margin-left:4px;cursor:help;color:#909399;font-size:14px;"><QuestionFilled /></el-icon>
            </el-tooltip>
          </div>
          <el-table
            :data="precheckResult.target_column_recommendations"
            size="small"
            border
            style="width:100%;"
            :max-height="240"
          >
            <el-table-column prop="column" label="列名" min-width="120" show-overflow-tooltip />
            <el-table-column label="类型" width="80">
              <template #default="{ row }">
                <el-tag :type="row.is_numeric ? 'success' : 'info'" size="small" effect="plain">
                  {{ row.is_numeric ? '数值' : '分类' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="unique_values" label="唯一值" width="70" align="center" />
            <el-table-column label="缺失率" width="70" align="center">
              <template #default="{ row }">
                {{ (row.missing_rate * 100).toFixed(1) }}%
              </template>
            </el-table-column>
            <el-table-column label="分类" width="60" align="center">
              <template #default="{ row }">
                <el-tooltip :content="row.reason" placement="top" effect="dark">
                  <span :style="row.recommend_classification ? 'color:#67c23a;font-weight:bold;' : 'color:#c0c4cc;'">
                    {{ row.recommend_classification ? '✓' : '✗' }}
                  </span>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column label="回归" width="60" align="center">
              <template #default="{ row }">
                <el-tooltip :content="row.reason" placement="top" effect="dark">
                  <span :style="row.recommend_regression ? 'color:#67c23a;font-weight:bold;' : 'color:#c0c4cc;'">
                    {{ row.recommend_regression ? '✓' : '✗' }}
                  </span>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column label="推荐说明" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <span style="font-size:12px;color:var(--text-muted);">{{ row.reason }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 算法推荐(按分类和回归两个 Tab 分区显示,标注推荐度评分,Top1标记最佳) -->
        <div v-if="precheckResult.algorithm_recommendations" style="margin-top:12px;">
          <div style="font-size:13px;color:var(--text-muted);margin-bottom:8px;display:flex;align-items:center;">
            <span>算法推荐(按推荐度评分排序,✓ 推荐 ✗ 不推荐,鼠标悬停查看原因):</span>
            <el-tooltip placement="top" effect="dark">
              <template #content>
                <div style="max-width:340px;line-height:1.6;">
                  <strong>算法评分标准(0-100分):</strong><br/>
                  • 88-92分:工业首选(XGBoost/LightGBM,训练快+精度高)<br/>
                  • 82-85分:推荐(随机森林/GBDT,精度高)<br/>
                  • 78分:基线模型(线性/决策树,速度快)<br/>
                  • 72分:可用但有更优选择<br/>
                  • 55分以下:不推荐(小数据集易过拟合/大数据集训练慢)<br/>
                  <strong>评分依据:</strong>数据量、算法复杂度、训练效率、过拟合风险
                </div>
              </template>
              <el-icon style="margin-left:4px;cursor:help;color:#909399;font-size:14px;"><QuestionFilled /></el-icon>
            </el-tooltip>
          </div>
          <el-tabs v-model="precheckActiveTab" style="margin-top:-5px;">
            <el-tab-pane label="分类算法" name="classification">
              <div style="display:flex;flex-wrap:wrap;gap:6px;">
                <el-tooltip
                  v-for="(rec, idx) in precheckResult.algorithm_recommendations.classification || []"
                  :key="rec.algorithm"
                  :content="`${rec.reason}\n推荐度: ${rec.score}分`"
                  placement="top"
                  effect="dark"
                >
                  <el-tag
                    :type="rec.recommended ? 'success' : 'warning'"
                    effect="plain"
                    size="small"
                    style="cursor:default;"
                  >
                    {{ idx === 0 ? '⭐ ' : '' }}{{ rec.label_cn }} {{ rec.score }}分{{ rec.recommended ? ' ✓' : ' ✗' }}
                  </el-tag>
                </el-tooltip>
              </div>
            </el-tab-pane>
            <el-tab-pane label="回归算法" name="regression">
              <div style="display:flex;flex-wrap:wrap;gap:6px;">
                <el-tooltip
                  v-for="(rec, idx) in precheckResult.algorithm_recommendations.regression || []"
                  :key="rec.algorithm"
                  :content="`${rec.reason}\n推荐度: ${rec.score}分`"
                  placement="top"
                  effect="dark"
                >
                  <el-tag
                    :type="rec.recommended ? 'success' : 'warning'"
                    effect="plain"
                    size="small"
                    style="cursor:default;"
                  >
                    {{ idx === 0 ? '⭐ ' : '' }}{{ rec.label_cn }} {{ rec.score }}分{{ rec.recommended ? ' ✓' : ' ✗' }}
                  </el-tag>
                </el-tooltip>
              </div>
            </el-tab-pane>
          </el-tabs>
        </div>
      </div>
    </div>

    <!-- ========== 任务配置卡片 ========== -->
    <div v-if="hasDataSource" class="card">
      <div class="card-title">
        <el-icon><Setting /></el-icon>
        <span>任务配置</span>
        <el-tag v-if="featureRecLoading" type="info" effect="plain" size="small" style="margin-left:8px;">特征推荐中...</el-tag>
        <!-- 自动推荐按钮:点击后根据预检结果自动填充任务类型+最高推荐度算法+特征列 -->
        <el-button
          type="primary"
          size="small"
          style="margin-left:12px;"
          :disabled="!canAutoRecommend"
          @click="autoRecommend"
        >
          <el-icon style="margin-right:4px;"><MagicStick /></el-icon>
          自动推荐
        </el-button>
        <span v-if="!canAutoRecommend && form.targetColumn" style="margin-left:8px;font-size:12px;color:var(--text-muted);">
          (当前目标列不推荐做分类/回归,无法自动推荐)
        </span>
        <span v-else-if="!canAutoRecommend" style="margin-left:8px;font-size:12px;color:var(--text-muted);">
          (请先选择目标列)
        </span>
      </div>

      <el-form :inline="false" label-position="top" size="default">
        <el-row :gutter="20">
          <!-- 目标列(选择后自动联动任务类型和特征列推荐,下拉框标注推荐分类/回归) -->
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item label="目标列 (Target)">
              <el-tooltip content="要预测的目标变量列。选择后系统会自动判断任务类型(分类/回归)并推荐特征列。下拉框中 ✓ 标记推荐的任务类型" placement="top" effect="dark">
                <el-select
                  v-model="form.targetColumn"
                  placeholder="选择目标列"
                  style="width: 100%;"
                  :disabled="availableColumns.length === 0"
                  filterable
                  allow-create
                  default-first-option
                >
                  <el-option
                    v-for="col in availableColumns"
                    :key="col"
                    :value="col"
                  >
                    <template #default>
                      <span>{{ col }}</span>
                      <span v-if="getTargetColumnRec(col)" style="float:right;font-size:12px;">
                        <el-tag v-if="getTargetColumnRec(col).recommend_classification && getTargetColumnRec(col).recommend_regression" type="success" size="small" effect="plain" style="margin-left:4px;">分类✓ 回归✓</el-tag>
                        <el-tag v-else-if="getTargetColumnRec(col).recommend_classification" type="success" size="small" effect="plain" style="margin-left:4px;">分类✓</el-tag>
                        <el-tag v-else-if="getTargetColumnRec(col).recommend_regression" type="warning" size="small" effect="plain" style="margin-left:4px;">回归✓</el-tag>
                        <el-tag v-else type="info" size="small" effect="plain" style="margin-left:4px;">不推荐</el-tag>
                      </span>
                    </template>
                  </el-option>
                </el-select>
              </el-tooltip>
            </el-form-item>
          </el-col>

          <!-- 任务类型(可手动切换,会联动算法列表;目标列不支持的任务类型会被禁用) -->
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item label="任务类型">
              <el-tooltip :content="taskTypeTooltip" placement="top" effect="dark">
                <el-radio-group v-model="form.taskType" style="width: 100%;">
                  <el-radio-button label="classification" :disabled="classificationDisabled">分类</el-radio-button>
                  <el-radio-button label="regression" :disabled="regressionDisabled">回归</el-radio-button>
                </el-radio-group>
              </el-tooltip>
            </el-form-item>
          </el-col>

          <!-- 算法选择(显示中文名+推荐度评分+推荐标记,与预检一致;不推荐算法选中时弹提示可强制选择) -->
          <el-col :xs="24" :sm="12" :md="6">
            <el-form-item label="算法">
              <el-tooltip :content="currentAlgorithmExplanation || algorithmTooltip" placement="top" effect="dark">
                <el-select
                  v-model="form.algorithm"
                  placeholder="选择算法"
                  style="width: 100%;"
                  @change="onAlgorithmChange"
                >
                  <el-option
                    v-for="algo in algorithmOptions"
                    :key="algo.value"
                    :value="algo.value"
                    :label="algo.label"
                  >
                    <template #default>
                      <span>{{ algo.label }}</span>
                      <span v-if="getAlgorithmRec(algo.value)" style="float:right;font-size:12px;">
                        <span :style="getAlgorithmRec(algo.value).recommended ? 'color:#67c23a;' : 'color:#e6a23c;'">
                          {{ getAlgorithmRec(algo.value).recommended ? '✓ 推荐' : '✗ 不推荐' }} {{ getAlgorithmRec(algo.value).score }}分
                        </span>
                      </span>
                    </template>
                  </el-option>
                </el-select>
              </el-tooltip>
            </el-form-item>
          </el-col>

          <!-- 特征列(显示智能推荐评分,默认勾选高关联度特征) -->
          <el-col :xs="24" :sm="24" :md="6">
            <el-form-item label="特征列 (Features)">
              <el-tooltip content="用于预测目标列的输入特征。选择目标列后系统会自动勾选高关联度特征(评分≥0.1),可手动调整。鼠标悬停选项查看评分详情" placement="top" effect="dark">
                <el-select
                  v-model="form.featureColumns"
                  multiple
                  collapse-tags
                  collapse-tags-tooltip
                  placeholder="选择特征列（可多选）"
                  style="width: 100%;"
                  :disabled="availableColumns.length === 0"
                  clearable
                >
                  <el-option v-for="col in availableColumns" :key="col" :value="col" :disabled="col === form.targetColumn">
                    <template #default>
                      <span>{{ col }}</span>
                      <span
                        v-if="col === form.targetColumn"
                        style="float:right;color:var(--text-muted);font-size:12px;"
                      >
                        目标列
                      </span>
                      <span
                        v-else-if="getFeatureScore(col)"
                        style="float:right;color:var(--text-muted);font-size:12px;"
                      >
                        评分 {{ getFeatureScore(col).score.toFixed(2) }}
                      </span>
                    </template>
                  </el-option>
                </el-select>
              </el-tooltip>
            </el-form-item>
          </el-col>
        </el-row>

        <!-- 特征推荐详情(展开后显示所有特征的评分和推荐原因) -->
        <el-collapse v-if="featureRecommendations.length" style="margin-top:8px;">
          <el-collapse-item name="1">
            <template #title>
              <span>特征推荐详情(按关联度排序,绿色为自动勾选,灰色为未自动勾选,悬停查看原因)</span>
              <el-tooltip placement="top" effect="dark">
                <template #content>
                  <div style="max-width:320px;line-height:1.6;">
                    <strong>特征评分标准(0-1):</strong><br/>
                    • 数值特征→数值目标:Pearson相关系数绝对值<br/>
                    • 数值特征→分类目标:ANOVA F值归一化<br/>
                    • 分类特征→分类目标:卡方值归一化<br/>
                    • 分类特征→数值目标:组间方差占比<br/>
                    <strong>自动勾选阈值:</strong>评分≥0.1
                  </div>
                </template>
                <el-icon style="margin-left:4px;cursor:help;color:#909399;font-size:14px;"><QuestionFilled /></el-icon>
              </el-tooltip>
            </template>
            <div style="display:flex;flex-wrap:wrap;gap:6px;">
              <el-tooltip
                v-for="feat in featureRecommendations"
                :key="feat.column"
                :content="feat.should_select ? `✓ 自动勾选: ${feat.reason}` : `✗ 未自动勾选: ${feat.reason}`"
                placement="top"
                effect="dark"
              >
                <el-tag
                  :type="feat.should_select ? 'success' : 'info'"
                  effect="plain"
                  size="small"
                  style="cursor:default;"
                >
                  {{ feat.should_select ? '✓' : '✗' }} {{ feat.column }} ({{ feat.score.toFixed(2) }})
                </el-tag>
              </el-tooltip>
            </div>
          </el-collapse-item>
        </el-collapse>
      </el-form>
    </div>

    <!-- ========== 数据集划分 ========== -->
    <div v-if="hasDataSource" class="card">
      <div class="card-title">
        <el-icon><Files /></el-icon>
        <span>数据集划分</span>
        <el-tag v-if="dataVolume" type="success" effect="plain" style="margin-left:12px;">
          当前数据量: {{ dataVolume }} 条
        </el-tag>
        <el-tag type="warning" effect="plain" style="margin-left:8px;">
          推荐比例: {{ recommendedTestSize ? `${(1 - recommendedTestSize).toFixed(1)} : ${recommendedTestSize.toFixed(1)}` : '-' }}
        </el-tag>
        <el-tooltip content="本平台采用训练集+测试集两划分,并通过 K 折交叉验证(CV)代替独立验证集。训练集用于模型训练和超参调优,测试集完全独立仅用于最终评估,避免数据泄露导致准确率虚高。" placement="top" effect="dark">
          <el-icon style="color:var(--text-muted);margin-left:8px;cursor:help;"><QuestionFilled /></el-icon>
        </el-tooltip>
      </div>

      <el-form label-position="top">
        <el-row :gutter="20" align="middle">
          <el-col :xs="24" :sm="16">
            <el-form-item>
              <template #label>
                <span>
                  训练集比例
                  <el-tooltip content="训练集占整体数据的比例，剩余为测试集。系统会根据数据量给出推荐值" placement="top">
                    <el-icon style="color:var(--text-muted);margin-left:4px;cursor:help;"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </span>
              </template>
              <div class="split-control">
                <el-slider
                  v-model="form.testSize"
                  :min="0.05"
                  :max="0.5"
                  :step="0.05"
                  :format-tooltip="val => `测试集 ${(val * 100).toFixed(0)}%`"
                  style="flex:1;"
                  @change="onSplitChange"
                />
                <el-input-number
                  v-model="form.testSize"
                  :min="0.05"
                  :max="0.5"
                  :step="0.05"
                  :precision="2"
                  size="default"
                  style="width: 130px;margin-left:12px;"
                  @change="onSplitChange"
                />
                <el-button size="default" @click="useRecommendedSplit" style="margin-left:8px;">
                  使用推荐值
                </el-button>
              </div>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="8">
            <el-form-item label="实际划分">
              <div class="split-preview">
                <div class="split-item">
                  <el-tag type="success" effect="dark">训练集</el-tag>
                  <span class="split-count">{{ actualTrainSize }} 条</span>
                  <span class="split-pct">({{ ((1 - form.testSize) * 100).toFixed(0) }}%)</span>
                </div>
                <div class="split-item">
                  <el-tag type="warning" effect="dark">测试集</el-tag>
                  <span class="split-count">{{ actualTestSize }} 条</span>
                  <span class="split-pct">({{ (form.testSize * 100).toFixed(0) }}%)</span>
                </div>
              </div>
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </div>

    <!-- ========== 调优控制 ========== -->
    <div v-if="hasDataSource" class="card">
      <div class="card-title">
        <el-icon><Tools /></el-icon>
        <span>调优与训练</span>
      </div>

      <el-row :gutter="20" align="middle">
        <el-col :xs="24" :sm="8">
          <el-form-item label="K折交叉验证">
            <el-tooltip content="将训练集划分为K份，每次用K-1份训练、1份验证，循环K次取平均。值越大越稳定但越慢" placement="top" effect="dark">
              <el-input-number
                v-model="form.cvFolds"
                :min="2"
                :max="20"
                size="default"
                style="width: 100%;"
              />
            </el-tooltip>
          </el-form-item>
        </el-col>

        <el-col :xs="24" :sm="8">
          <el-form-item label="随机种子">
            <el-tooltip content="设置随机种子以确保实验可复现。相同种子+相同数据+相同参数=相同结果。修改种子可引入随机性" placement="top" effect="dark">
              <el-input-number
                v-model="form.randomSeed"
                :min="0"
                :max="999999"
                size="default"
                style="width: 100%;"
              />
            </el-tooltip>
          </el-form-item>
        </el-col>

        <el-col :xs="24" :sm="16">
          <el-form-item label="执行操作">
            <div class="action-buttons">
              <el-tooltip content="使用默认超参数直接训练，速度最快" placement="top" effect="dark">
                <el-button
                  type="primary"
                  size="default"
                  :loading="loading.train"
                  :disabled="!canTrain"
                  @click="trainModel(false)"
                >
                  <el-icon style="margin-right:4px;"><VideoPlay /></el-icon>
                  训练
                </el-button>
              </el-tooltip>

              <el-tooltip content="L2级调优：使用随机搜索（RandomizedSearchCV）在超参数空间中快速采样，对比训练更快" placement="top" effect="dark">
                <el-button
                  type="success"
                  size="default"
                  :loading="loading.tuneL2"
                  :disabled="!canTrain"
                  @click="trainModel(true, 'random')"
                >
                  <el-icon style="margin-right:4px;"><MagicStick /></el-icon>
                  L2自动调优
                </el-button>
              </el-tooltip>

              <el-tooltip content="L3级调优：使用网格搜索（GridSearchCV）穷举所有超参数组合，最准确但耗时最长" placement="top" effect="dark">
                <el-button
                  type="warning"
                  size="default"
                  :loading="loading.tuneL3"
                  :disabled="!canTrain"
                  @click="trainModel(true, 'grid')"
                >
                  <el-icon style="margin-right:4px;"><Grid /></el-icon>
                  L3自动调优
                </el-button>
              </el-tooltip>
            </div>
          </el-form-item>
        </el-col>
      </el-row>
    </div>

    <!-- ========== 训练结果展示 ========== -->
    <div v-if="trainResult" class="card">
      <div class="card-title">
        <el-icon><DataAnalysis /></el-icon>
        <span>训练结果</span>
        <el-tag type="success" effect="dark" style="margin-left:12px;">
          {{ getAlgorithmLabel(trainResult.algorithm) }}
        </el-tag>
        <el-tag :type="form.taskType === 'classification' ? 'primary' : 'warning'" effect="plain" style="margin-left:8px;">
          {{ form.taskType === 'classification' ? '分类任务' : '回归任务' }}
        </el-tag>
      </div>

      <!-- 评估指标卡片 -->
      <h4 class="section-title">
        评估指标
        <el-tooltip content="模型在测试集上的评估结果，不同任务类型关注的指标不同" placement="top">
          <el-icon style="color:#909399;cursor:help;margin-left:4px;"><QuestionFilled /></el-icon>
        </el-tooltip>
      </h4>
      <div class="metrics-grid">
        <template v-if="resultTaskType === 'classification'">
          <div class="metric-card">
            <div class="metric-label">
              准确率 Accuracy
              <el-tooltip :content="mlGlossary.accuracy" placement="top">
                <el-icon style="color:#909399;cursor:help;margin-left:4px;font-size:13px;"><QuestionFilled /></el-icon>
              </el-tooltip>
            </div>
            <div class="metric-value">{{ formatPercent(trainResult.metrics?.accuracy) }}</div>
            <div class="metric-desc">预测正确的比例</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">
              精确率 Precision
              <el-tooltip :content="mlGlossary.precision" placement="top">
                <el-icon style="color:#909399;cursor:help;margin-left:4px;font-size:13px;"><QuestionFilled /></el-icon>
              </el-tooltip>
            </div>
            <div class="metric-value">{{ formatPercent(trainResult.metrics?.precision) }}</div>
            <div class="metric-desc">预测为正例中实际为正例的比例</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">
              召回率 Recall
              <el-tooltip :content="mlGlossary.recall" placement="top">
                <el-icon style="color:#909399;cursor:help;margin-left:4px;font-size:13px;"><QuestionFilled /></el-icon>
              </el-tooltip>
            </div>
            <div class="metric-value">{{ formatPercent(trainResult.metrics?.recall) }}</div>
            <div class="metric-desc">实际正例中被正确预测的比例</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">
              F1 分数
              <el-tooltip :content="mlGlossary.f1" placement="top">
                <el-icon style="color:#909399;cursor:help;margin-left:4px;font-size:13px;"><QuestionFilled /></el-icon>
              </el-tooltip>
            </div>
            <div class="metric-value">{{ formatPercent(trainResult.metrics?.f1) }}</div>
            <div class="metric-desc">精确率与召回率的调和平均</div>
          </div>
          <div v-if="trainResult.metrics?.roc_auc !== undefined" class="metric-card">
            <div class="metric-label">
              ROC AUC
              <el-tooltip :content="mlGlossary.rocAuc" placement="top">
                <el-icon style="color:#909399;cursor:help;margin-left:4px;font-size:13px;"><QuestionFilled /></el-icon>
              </el-tooltip>
            </div>
            <div class="metric-value">{{ trainResult.metrics.roc_auc?.toFixed(4) }}</div>
            <div class="metric-desc">二分类模型区分能力</div>
          </div>
        </template>
        <template v-else>
          <div class="metric-card">
            <div class="metric-label">
              R² 决定系数
              <el-tooltip :content="mlGlossary.r2" placement="top">
                <el-icon style="color:#909399;cursor:help;margin-left:4px;font-size:13px;"><QuestionFilled /></el-icon>
              </el-tooltip>
            </div>
            <div class="metric-value">{{ trainResult.metrics?.r2?.toFixed(4) }}</div>
            <div class="metric-desc">模型解释方差的比例，越接近1越好</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">
              MSE
              <el-tooltip :content="mlGlossary.mse" placement="top">
                <el-icon style="color:#909399;cursor:help;margin-left:4px;font-size:13px;"><QuestionFilled /></el-icon>
              </el-tooltip>
            </div>
            <div class="metric-value">{{ trainResult.metrics?.mse?.toFixed(4) }}</div>
            <div class="metric-desc">均方误差</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">
              RMSE
              <el-tooltip :content="mlGlossary.rmse" placement="top">
                <el-icon style="color:#909399;cursor:help;margin-left:4px;font-size:13px;"><QuestionFilled /></el-icon>
              </el-tooltip>
            </div>
            <div class="metric-value">{{ trainResult.metrics?.rmse?.toFixed(4) }}</div>
            <div class="metric-desc">均方根误差</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">
              MAE
              <el-tooltip :content="mlGlossary.mae" placement="top">
                <el-icon style="color:#909399;cursor:help;margin-left:4px;font-size:13px;"><QuestionFilled /></el-icon>
              </el-tooltip>
            </div>
            <div class="metric-value">{{ trainResult.metrics?.mae?.toFixed(4) }}</div>
            <div class="metric-desc">平均绝对误差</div>
          </div>
        </template>
      </div>

      <!-- 交叉验证 -->
      <h4 class="section-title">
        交叉验证结果
        <el-tooltip :content="mlGlossary.cvFolds" placement="top">
          <el-icon style="color:#909399;cursor:help;margin-left:4px;"><QuestionFilled /></el-icon>
        </el-tooltip>
      </h4>
      <div class="cv-summary">
        <el-tooltip :content="mlGlossary.cvMean" placement="top">
          <el-tag type="info" effect="plain">CV Mean ({{ resultTaskType === 'classification' ? 'F1' : 'R²' }}): {{ trainResult.metrics?.cv_mean?.toFixed(4) }}</el-tag>
        </el-tooltip>
        <el-tooltip :content="mlGlossary.cvStd" placement="top">
          <el-tag type="info" effect="plain">CV Std: {{ trainResult.metrics?.cv_std?.toFixed(4) }}</el-tag>
        </el-tooltip>
        <el-tooltip :content="mlGlossary.cvFolds" placement="top">
          <el-tag type="info" effect="plain">折数: {{ form.cvFolds }}</el-tag>
        </el-tooltip>
      </div>
      <el-table
        v-if="trainResult.metrics?.cv_scores"
        :data="cvScoreRows"
        border
        size="small"
        style="width: 100%;margin-top:8px;"
        max-height="200"
      >
        <el-table-column type="index" label="折序号" width="80" align="center" />
        <el-table-column prop="score" label="分数" align="center">
          <template #default="{ row }">
            <el-tag :type="row.score >= (trainResult.metrics?.cv_mean || 0) ? 'success' : 'warning'" effect="plain">
              {{ row.score?.toFixed(4) }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>

      <!-- 调优结果 -->
      <template v-if="trainResult.tune_results">
        <h4 class="section-title">
          调优结果
          <el-tooltip content="超参数自动调优的过程与最佳结果" placement="top">
            <el-icon style="color:#909399;cursor:help;margin-left:4px;"><QuestionFilled /></el-icon>
          </el-tooltip>
        </h4>
        <div class="tune-summary">
          <el-tooltip
            :content="trainResult.tune_results.method === 'grid' ? mlGlossary.gridSearch : mlGlossary.randomSearch"
            placement="top"
          >
            <el-tag type="success" effect="dark">
              调优方法: {{ trainResult.tune_results.method === 'grid' ? '网格搜索 (Grid)' : '随机搜索 (Random)' }}
            </el-tag>
          </el-tooltip>
          <el-tooltip content="所有候选超参数组合在交叉验证中取得的最高平均分数" placement="top">
            <el-tag type="success" effect="plain">最佳分数: {{ trainResult.tune_results.best_score?.toFixed(4) }}</el-tag>
          </el-tooltip>
          <el-tooltip content="本次调优实际尝试的超参数组合数（网格搜索为全部，随机搜索为采样数）" placement="top">
            <el-tag type="success" effect="plain">候选数量: {{ trainResult.tune_results.n_candidates }}</el-tag>
          </el-tooltip>
        </div>
        <el-table
          v-if="trainResult.best_params && Object.keys(trainResult.best_params).length > 0"
          :data="bestParamRows"
          border
          size="small"
          style="width: 100%;margin-top:8px;"
        >
          <el-table-column prop="name" label="超参数" />
          <el-table-column prop="value" label="最佳值">
            <template #default="{ row }">
              <el-tag type="primary" effect="plain">{{ row.value }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <!-- 特征重要性 -->
      <h4 class="section-title">
        特征重要性
        <el-tooltip :content="mlGlossary.featureImportance" placement="top">
          <el-icon style="color:#909399;cursor:help;margin-left:4px;"><QuestionFilled /></el-icon>
        </el-tooltip>
      </h4>
      <el-table
        v-if="featureImportanceRows.length > 0"
        :data="featureImportanceRows"
        border
        size="small"
        style="width: 100%;"
      >
        <el-table-column type="index" label="序号" width="80" align="center" />
        <el-table-column prop="feature" label="特征名" />
        <el-table-column prop="importance" label="重要性" align="center">
          <template #default="{ row }">
            <el-tag :type="row.importance > 0.1 ? 'success' : (row.importance > 0.01 ? 'warning' : 'info')" effect="plain">
              {{ row.importance?.toFixed(4) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="占比" align="center">
          <template #default="{ row }">
            <el-progress
              :percentage="(row.importance / maxImportance * 100)"
              :stroke-width="10"
              :show-text="false"
            />
            <span style="margin-left:8px;">{{ ((row.importance / totalImportance) * 100).toFixed(1) }}%</span>
          </template>
        </el-table-column>
      </el-table>
      <div v-else class="empty-hint">该算法不支持特征重要性展示</div>
    </div>

    <!-- ========== 模型列表 ========== -->
    <div v-if="hasDataSource" class="card">
      <div class="card-title">
        <el-icon><Box /></el-icon>
        <span>已训练模型</span>
        <el-button size="small" style="margin-left:auto;" @click="loadModelList" :loading="loading.models">
          <el-icon style="margin-right:4px;"><Refresh /></el-icon>
          刷新
        </el-button>
      </div>

      <el-table
        v-loading="loading.models"
        :data="modelList"
        border
        stripe
        size="small"
        style="width: 100%;"
        empty-text="暂无已训练模型"
      >
        <el-table-column type="index" label="#" width="60" align="center" />
        <el-table-column prop="name" label="模型名称" show-overflow-tooltip min-width="220" />
        <el-table-column label="算法" width="140" show-overflow-tooltip>
          <template #default="{ row }">
            {{ getAlgorithmLabel(row.algorithm) }}
          </template>
        </el-table-column>
        <el-table-column label="任务类型" width="100" align="center">
          <template #default="{ row }">
            <el-tag
              :type="isClassificationModel(row.algorithm) ? 'success' : 'warning'"
              effect="plain"
              size="small"
            >
              {{ isClassificationModel(row.algorithm) ? '分类' : '回归' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="核心指标" width="160" align="center">
          <template #header>
            <span>核心指标
              <el-tooltip content="该模型最值得关注的单一指标，分类看准确率、回归看R²" placement="top">
                <el-icon style="color:#909399;cursor:help;margin-left:2px;font-size:12px;"><QuestionFilled /></el-icon>
              </el-tooltip>
            </span>
          </template>
          <template #default="{ row }">
            <el-tooltip
              v-if="isClassificationModel(row.algorithm) && row.metrics?.accuracy !== undefined"
              :content="mlGlossary.accuracy"
              placement="top"
            >
              <el-tag type="success" effect="plain" size="small">
                准确率: {{ (row.metrics.accuracy * 100).toFixed(1) }}%
              </el-tag>
            </el-tooltip>
            <el-tooltip
              v-else-if="!isClassificationModel(row.algorithm) && row.metrics?.r2 !== undefined"
              :content="mlGlossary.r2"
              placement="top"
            >
              <el-tag type="success" effect="plain" size="small">
                R²: {{ row.metrics.r2?.toFixed(4) }}
              </el-tag>
            </el-tooltip>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="180" align="center">
          <template #default="{ row }">
            <span style="font-size:12px;color:var(--text-secondary);">{{ formatDate(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" align="center" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link size="small" @click="openBatchPredict(row)">
              <el-icon style="margin-right:2px;"><MagicStick /></el-icon>
              批量预测
            </el-button>
            <el-button type="success" link size="small" @click="runTestEvaluate(row)">
              <el-icon style="margin-right:2px;"><Cpu /></el-icon>
              测试集评估
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="modelListTotal > 0" class="flex-center mt-sm" style="justify-content: flex-end;">
        <el-pagination
          v-model:current-page="modelListPage"
          v-model:page-size="modelListPageSize"
          :page-sizes="[20, 50, 100]"
          :total="modelListTotal"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="() => loadModelList()"
          @size-change="() => loadModelList()"
          small background
        />
      </div>
    </div>

    <!-- ========== 批量预测对话框 ========== -->
    <el-dialog
      v-model="predictDialogVisible"
      title="批量预测"
      width="80%"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <div v-if="currentPredictModel">
        <el-descriptions :column="2" border size="small" style="margin-bottom:16px;">
          <el-descriptions-item label="模型名称">{{ currentPredictModel.name }}</el-descriptions-item>
          <el-descriptions-item label="算法">{{ getAlgorithmLabel(currentPredictModel.algorithm) }}</el-descriptions-item>
        </el-descriptions>

        <!-- 模型所需特征列提示(帮助用户确认数据格式) -->
        <el-alert
          v-if="currentPredictModel.feature_columns && currentPredictModel.feature_columns.length"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom:16px;"
        >
          <template #title>
            <span>该模型需要 {{ currentPredictModel.feature_columns.length }} 个特征列</span>
          </template>
          <div style="font-size:12px;line-height:1.6;margin-top:4px;">
            <span>所需特征列: </span>
            <el-tag v-for="col in currentPredictModel.feature_columns" :key="col" size="small" effect="plain" style="margin:2px;">
              {{ col }}
            </el-tag>
            <div style="margin-top:4px;color:#909399;">预测数据必须包含以上所有列(目标列可缺失,仅用于对比)</div>
          </div>
        </el-alert>

        <el-form label-position="top">
          <!-- 方式一：上传新文件 -->
          <el-form-item label="上传待预测文件">
            <el-upload
              drag
              :auto-upload="false"
              :show-file-list="false"
              :on-change="onPredictFileChange"
              accept=".csv,.xlsx,.xls,.json"
              :disabled="predictUploadLoading"
              style="width: 100%;"
            >
              <el-icon class="upload-icon" :size="36"><UploadFilled /></el-icon>
              <div class="upload-text" style="font-size:14px;">拖拽文件到此处，或 <em>点击上传</em></div>
              <div class="upload-hint" style="font-size:12px;">支持 CSV、Excel、JSON，需包含模型所需的特征列</div>
            </el-upload>
            <div v-if="predictUploadFile" class="flex-center gap-sm mt-sm">
              <el-tag type="info" effect="plain">{{ predictUploadFile.name }}</el-tag>
              <el-button type="primary" size="small" @click="doPredictUpload" :loading="predictUploadLoading">
                上传并预测
              </el-button>
              <el-button size="small" @click="cancelPredictUpload">取消</el-button>
            </div>
          </el-form-item>

          <!-- 方式二：选择已有数据 -->
          <el-divider>或选择已有数据</el-divider>
          <el-form-item label="选择预测数据">
            <el-select
              v-model="predictDatasetId"
              placeholder="选择已上传的预测数据文件"
              style="width: 100%;"
              filterable
              clearable
            >
              <!-- :label 用于折叠态显示名称；展开列表用自定义 slot 展示色点/名称/#id/时间/行数 -->
              <el-option v-for="ds in predictDataList" :key="ds.id" :value="ds.id" :label="ds.name">
                <div class="ds-option">
                  <span class="ds-dot" :style="{ background: getDatasetColor(ds) }"></span>
                  <span class="ds-name">{{ ds.name }}</span>
                  <span class="ds-meta">{{ ds.id != null ? `#${ds.id}` : '' }} · {{ formatDsTime(ds.created_at) }} · {{ ds.row_count ? ds.row_count.toLocaleString() : '?' }} 行</span>
                </div>
              </el-option>
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button
              type="primary"
              @click="onBatchPredict(predictDatasetId)"
              :loading="loading.predict"
              :disabled="!predictDatasetId"
            >
              <el-icon style="margin-right:4px;"><Promotion /></el-icon>
              开始预测
            </el-button>
          </el-form-item>
        </el-form>

        <!-- 预测结果预览 -->
        <div v-if="predictResult" class="predict-result">
          <el-alert
            :title="`预测完成，共 ${predictResult.row_count} 条结果`"
            type="success"
            :closable="false"
            show-icon
            style="margin-bottom:12px;"
          />
          <h4 class="section-title">
            预测结果预览
            <el-tooltip :content="mlGlossary.batchPredict" placement="top">
              <el-icon style="color:#909399;cursor:help;margin-left:4px;"><QuestionFilled /></el-icon>
            </el-tooltip>
          </h4>
          <el-table :data="predictPreviewRows" border size="small" max-height="400" style="width:100%;">
            <el-table-column type="index" label="#" width="60" align="center" />
            <el-table-column label="原数据索引" align="center">
              <template #header>
                <span>原数据索引
                  <el-tooltip :content="mlGlossary.predictIndex" placement="top">
                    <el-icon style="color:#909399;cursor:help;margin-left:2px;font-size:12px;"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </span>
              </template>
              <template #default="{ row }">{{ row.index }}</template>
            </el-table-column>
            <el-table-column label="预测值" align="center">
              <template #header>
                <span>预测值
                  <el-tooltip :content="mlGlossary.predictLabel" placement="top">
                    <el-icon style="color:#909399;cursor:help;margin-left:2px;font-size:12px;"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </span>
              </template>
              <template #default="{ row }">
                <el-tag type="primary" effect="plain" size="small">{{ row.prediction }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column v-if="hasProbability" label="预测概率" align="center">
              <template #header>
                <span>预测概率
                  <el-tooltip :content="mlGlossary.predictProba" placement="top">
                    <el-icon style="color:#909399;cursor:help;margin-left:2px;font-size:12px;"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </span>
              </template>
              <template #default="{ row }">
                <div v-if="row.probabilities" style="display:flex;flex-direction:column;gap:4px;">
                  <div v-for="(p, idx) in row.probabilities" :key="idx" style="display:flex;align-items:center;gap:6px;font-size:12px;">
                    <span style="min-width:80px;">类别 {{ probaLabels[idx] || idx }}:</span>
                    <el-progress :percentage="(p * 100)" :stroke-width="6" style="flex:1;" />
                    <span style="min-width:48px;text-align:right;">{{ (p * 100).toFixed(1) }}%</span>
                  </div>
                </div>
                <span v-else>-</span>
              </template>
            </el-table-column>
          </el-table>
          <div class="flex-center mt-sm" style="justify-content: flex-end;">
            <el-pagination
              v-model:current-page="predictPage"
              v-model:page-size="predictPageSize"
              :page-sizes="[20, 50, 100]"
              :total="predictTotal"
              layout="total, sizes, prev, pager, next, jumper"
              small background
            />
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="predictDialogVisible = false">关闭</el-button>
        <el-button v-if="predictResult" type="success" @click="downloadPredictResult">
          <el-icon style="margin-right:4px;"><Download /></el-icon>
          下载结果
        </el-button>
      </template>
    </el-dialog>

    <!-- ========== 测试集评估对话框（期末考试） ========== -->
    <el-dialog
      v-model="testEvalDialogVisible"
      title="测试集独立评估（期末考试）"
      width="85%"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <div v-if="testEvalResult">
        <el-alert
          :title="'测试集共 ' + testEvalResult.test_size + ' 条样本，完全独立于训练过程'"
          type="info"
          :closable="false"
          show-icon
          :description="'测试集在训练过程中完全不可见，用于评估模型在未知新数据上的真实泛化能力。'"
          style="margin-bottom:16px;"
        />

        <!-- 性能指标卡片 -->
        <h4 class="section-title">性能指标</h4>
        <!-- 分类任务：突出精确率/召回率/F1/AUC -->
        <div v-if="testEvalResult.task_type === 'classification'" style="margin-bottom:20px;">
          <div style="font-size:12px;color:#909399;margin-bottom:8px;">
            分类任务核心指标：精确率（预测为正例中实际为正例的比例）、召回率（实际正例中被正确预测的比例）、F1分数（两者的调和平均）
          </div>
          <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;">
            <div style="padding:16px;background:#f0f9eb;border-radius:8px;text-align:center;border:2px solid #67c23a;">
              <div style="font-size:12px;color:#67c23a;margin-bottom:6px;">精确率 (Precision)</div>
              <div style="font-size:28px;font-weight:bold;color:#67c23a;">{{ (testEvalResult.metrics.precision * 100).toFixed(2) }}%</div>
              <div style="font-size:10px;color:#909399;">预测为正例中实际为正例</div>
            </div>
            <div style="padding:16px;background:#fdf6ec;border-radius:8px;text-align:center;border:2px solid #e6a23c;">
              <div style="font-size:12px;color:#e6a23c;margin-bottom:6px;">召回率 (Recall)</div>
              <div style="font-size:28px;font-weight:bold;color:#e6a23c;">{{ (testEvalResult.metrics.recall * 100).toFixed(2) }}%</div>
              <div style="font-size:10px;color:#909399;">实际正例中被正确预测</div>
            </div>
            <div style="padding:16px;background:#fef0f0;border-radius:8px;text-align:center;border:2px solid #f56c6c;">
              <div style="font-size:12px;color:#f56c6c;margin-bottom:6px;">F1 分数</div>
              <div style="font-size:28px;font-weight:bold;color:#f56c6c;">{{ (testEvalResult.metrics.f1 * 100).toFixed(2) }}%</div>
              <div style="font-size:10px;color:#909399;">精确率和召回率的调和平均</div>
            </div>
            <div style="padding:16px;background:#ecf5ff;border-radius:8px;text-align:center;border:2px solid #409eff;">
              <div style="font-size:12px;color:#409eff;margin-bottom:6px;">AUC 值</div>
              <div style="font-size:28px;font-weight:bold;color:#409eff;">{{ (testEvalResult.metrics.roc_auc || 0).toFixed(4) }}</div>
              <div style="font-size:10px;color:#909399;">ROC曲线下面积，越接近1越好</div>
            </div>
          </div>
          <div style="margin-top:12px;padding:12px;background:#f4f4f5;border-radius:8px;">
            <span style="font-size:12px;color:#909399;">准确率 (Accuracy): {{ (testEvalResult.metrics.accuracy * 100).toFixed(2) }}%</span>
            <span style="font-size:10px;color:#c0c4cc;margin-left:8px;">（仅供参考，不平衡数据集下准确率可能误导）</span>
          </div>
        </div>
        <!-- 回归任务：突出MAE/RMSE/R² -->
        <div v-if="testEvalResult.task_type === 'regression'" style="margin-bottom:20px;">
          <div style="font-size:12px;color:#909399;margin-bottom:8px;">
            回归任务核心指标：MAE（平均绝对误差，越小越好）、RMSE（均方根误差，对大误差敏感）、R²（决定系数，越接近1越好）
          </div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;">
            <div style="padding:16px;background:#f0f9eb;border-radius:8px;text-align:center;border:2px solid #67c23a;">
              <div style="font-size:12px;color:#67c23a;margin-bottom:6px;">MAE 平均绝对误差</div>
              <div style="font-size:28px;font-weight:bold;color:#67c23a;">{{ testEvalResult.metrics.mae?.toFixed(4) }}</div>
              <div style="font-size:10px;color:#909399;">越小越好，预测值与真实值差距</div>
            </div>
            <div style="padding:16px;background:#fdf6ec;border-radius:8px;text-align:center;border:2px solid #e6a23c;">
              <div style="font-size:12px;color:#e6a23c;margin-bottom:6px;">RMSE 均方根误差</div>
              <div style="font-size:28px;font-weight:bold;color:#e6a23c;">{{ testEvalResult.metrics.rmse?.toFixed(4) }}</div>
              <div style="font-size:10px;color:#909399;">对大误差更敏感，越小越好</div>
            </div>
            <div style="padding:16px;background:#ecf5ff;border-radius:8px;text-align:center;border:2px solid #409eff;">
              <div style="font-size:12px;color:#409eff;margin-bottom:6px;">R² 决定系数</div>
              <div style="font-size:28px;font-weight:bold;color:#409eff;">{{ testEvalResult.metrics.r2?.toFixed(4) }}</div>
              <div style="font-size:10px;color:#909399;">越接近1越好，模型解释力</div>
            </div>
          </div>
          <div style="margin-top:12px;padding:12px;background:#f4f4f5;border-radius:8px;">
            <span style="font-size:12px;color:#909399;">MAPE 平均相对误差: {{ (testEvalResult.metrics.mape || 0).toFixed(2) }}%</span>
            <span style="font-size:10px;color:#c0c4cc;margin-left:8px;">（相对误差百分比，越小越好）</span>
          </div>
        </div>

        <!-- 真实值vs预测值对比表 -->
        <h4 class="section-title">
          真实值 vs 预测值
          <el-tooltip :content="mlGlossary.testEval" placement="top">
            <el-icon style="color:#909399;cursor:help;margin-left:4px;"><QuestionFilled /></el-icon>
          </el-tooltip>
        </h4>
        <el-table :data="testEvalPreviewRows" border size="small" max-height="400" style="width:100%;">
          <el-table-column type="index" label="#" width="60" align="center" />
          <el-table-column label="真实值" align="center" width="120">
            <template #header>
              <span>真实值
                <el-tooltip content="样本真实的标签值，是评估模型好坏的参照标准" placement="top">
                  <el-icon style="color:#909399;cursor:help;margin-left:2px;font-size:12px;"><QuestionFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>
            <template #default="{ row }">
              <span>{{ row.y_true }}</span>
            </template>
          </el-table-column>
          <el-table-column label="预测值" align="center" width="120">
            <template #header>
              <span>预测值
                <el-tooltip :content="mlGlossary.predictLabel" placement="top">
                  <el-icon style="color:#909399;cursor:help;margin-left:2px;font-size:12px;"><QuestionFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>
            <template #default="{ row }">
              <span>{{ typeof row.y_pred === 'number' ? row.y_pred.toFixed(2) : row.y_pred }}</span>
            </template>
          </el-table-column>
          <!-- 分类任务：显示是否正确 -->
          <el-table-column v-if="testEvalResult?.task_type === 'classification'" prop="correct" label="是否正确" align="center" width="100">
            <template #header>
              <span>是否正确
                <el-tooltip content="预测值与真实值是否完全一致，是分类任务最基本的对错判断" placement="top">
                  <el-icon style="color:#909399;cursor:help;margin-left:2px;font-size:12px;"><QuestionFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>
            <template #default="{ row }">
              <el-icon v-if="row.correct" style="color:#67c23a;font-size:18px;"><CircleCheck /></el-icon>
              <el-icon v-else style="color:#f56c6c;font-size:18px;"><CircleClose /></el-icon>
            </template>
          </el-table-column>
          <!-- 回归任务：显示误差 -->
          <el-table-column v-if="testEvalResult?.task_type === 'regression'" prop="abs_error" label="绝对误差" align="center" width="100">
            <template #header>
              <span>绝对误差
                <el-tooltip :content="mlGlossary.mae" placement="top">
                  <el-icon style="color:#909399;cursor:help;margin-left:2px;font-size:12px;"><QuestionFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>
            <template #default="{ row }">
              <span :style="{ color: row.abs_error > 10 ? '#f56c6c' : '#67c23a' }">{{ row.abs_error?.toFixed(2) }}</span>
            </template>
          </el-table-column>
          <el-table-column v-if="testEvalResult?.task_type === 'regression'" prop="rel_error" label="相对误差%" align="center" width="100">
            <template #header>
              <span>相对误差%
                <el-tooltip :content="mlGlossary.mape" placement="top">
                  <el-icon style="color:#909399;cursor:help;margin-left:2px;font-size:12px;"><QuestionFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>
            <template #default="{ row }">
              <span :style="{ color: row.rel_error > 20 ? '#f56c6c' : '#67c23a' }">{{ row.rel_error?.toFixed(1) }}%</span>
            </template>
          </el-table-column>
        </el-table>
        <div class="flex-center mt-sm" style="justify-content: flex-end;">
          <el-pagination
            v-model:current-page="testEvalPage"
            v-model:page-size="testEvalPageSize"
            :page-sizes="[30, 50, 100]"
            :total="testEvalTotal"
            layout="total, sizes, prev, pager, next, jumper"
            small background
          />
        </div>
      </div>
      <template #footer>
        <el-button @click="testEvalDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script>
export default { name: 'MachineLearning' }
</script>

<script setup>
import { ref, reactive, inject, computed, watch, nextTick, onMounted, onActivated, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  UploadFilled, Upload, Folder, DataLine, Refresh, Setting, QuestionFilled,
  Files, Tools, VideoPlay, MagicStick, Grid, DataAnalysis, Box, Delete,
  Promotion, Download, Cpu, Document, CircleCheck, CircleClose
} from '@element-plus/icons-vue'
import {
  uploadMLFile, fetchMLRawData, fetchDatasetById,
  trainSupervised, listModels, batchPredict,
  exportModelFile, testSetEvaluate, exportModelReport, api,
  mlPrecheck, recommendFeatures, fetchRemoteColumnPool,
  fetchDatasetData
} from '../api/index.js'
import { addTask } from '../stores/taskPanel.js'
import DataSourceSelector from '../components/DataSourceSelector.vue'
import DataPreview from '../components/DataPreview.vue'
import { getDatasetColor } from '../utils/labels.js'

// 格式化创建时间为 `MM-DD HH:mm`
function formatDsTime(iso) {
  if (!iso) return '--'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '--'
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// DataSourceSelector组件引用，用于上传后调用reload刷新下拉框
const dataSourceSelectorRef = ref(null)

const datasetStore = inject('datasetStore')

// ========== 默认超参数配置(与后端算法注册表保持一致,共 14 个算法) ==========
const defaultHyperparams = {
  logistic_regression: { C: [0.01, 0.1, 1, 10, 100], solver: ['lbfgs', 'liblinear'] },
  svm: { C: [0.1, 1, 10], kernel: ['linear', 'rbf'], gamma: ['scale', 'auto'] },
  decision_tree: { max_depth: [3, 5, 10, null], min_samples_split: [2, 5, 10] },
  naive_bayes: { var_smoothing: [1e-9, 1e-8, 1e-7, 1e-6] },
  knn: { n_neighbors: [3, 5, 7, 11, 15], weights: ['uniform', 'distance'] },
  linear_regression: {},  // 线性回归无超参
  ridge_regression: { alpha: [0.01, 0.1, 1, 10, 100] },
  lasso_regression: { alpha: [0.01, 0.1, 1, 10, 100] },
  random_forest: { n_estimators: [50, 100, 200], max_depth: [3, 5, 10, null], min_samples_split: [2, 5, 10] },
  adaboost: { n_estimators: [50, 100, 200], learning_rate: [0.01, 0.1, 1.0] },
  gbdt: { n_estimators: [50, 100, 200], max_depth: [3, 5, 7], learning_rate: [0.01, 0.1, 0.2] },
  xgboost: { n_estimators: [50, 100, 200], max_depth: [3, 5, 7], learning_rate: [0.01, 0.1, 0.2] },
  lightgbm: { n_estimators: [50, 100, 200], num_leaves: [31, 63, 127], learning_rate: [0.01, 0.1, 0.2] },
  mlp: { hidden_layer_sizes: [[32], [64], [64, 32], [128, 64]], alpha: [0.0001, 0.001, 0.01] }
}

// ========== 算法名称映射(用于显示,共 14 个算法) ==========
const algorithmLabelMap = {
  logistic_regression: '逻辑回归',
  svm: '支持向量机',
  decision_tree: '决策树',
  naive_bayes: '朴素贝叶斯',
  knn: 'K近邻',
  linear_regression: '线性回归',
  random_forest: '随机森林',
  ridge_regression: '岭回归',
  lasso_regression: 'Lasso回归',
  adaboost: 'AdaBoost',
  gbdt: '梯度提升树',
  xgboost: 'XGBoost',
  lightgbm: 'LightGBM',
  mlp: '多层感知机'
}

// 分类算法列表(11 个:逻辑回归/SVM/决策树/朴素贝叶斯/KNN/随机森林/AdaBoost/GBDT/XGBoost/LightGBM/MLP)
const classificationAlgorithms = [
  { value: 'logistic_regression', label: '逻辑回归' },
  { value: 'svm', label: '支持向量机' },
  { value: 'decision_tree', label: '决策树' },
  { value: 'naive_bayes', label: '朴素贝叶斯' },
  { value: 'knn', label: 'K近邻' },
  { value: 'random_forest', label: '随机森林' },
  { value: 'adaboost', label: 'AdaBoost' },
  { value: 'gbdt', label: '梯度提升树' },
  { value: 'xgboost', label: 'XGBoost' },
  { value: 'lightgbm', label: 'LightGBM' },
  { value: 'mlp', label: '多层感知机' }
]

// 回归算法列表(12 个:线性回归/岭回归/Lasso/SVM/决策树/KNN/随机森林/AdaBoost/GBDT/XGBoost/LightGBM/MLP)
const regressionAlgorithms = [
  { value: 'linear_regression', label: '线性回归' },
  { value: 'ridge_regression', label: '岭回归' },
  { value: 'lasso_regression', label: 'Lasso回归' },
  { value: 'svm', label: '支持向量回归' },
  { value: 'decision_tree', label: '决策树' },
  { value: 'knn', label: 'K近邻' },
  { value: 'random_forest', label: '随机森林' },
  { value: 'adaboost', label: 'AdaBoost' },
  { value: 'gbdt', label: '梯度提升树' },
  { value: 'xgboost', label: 'XGBoost' },
  { value: 'lightgbm', label: 'LightGBM' },
  { value: 'mlp', label: '多层感知机' }
]

// ========== 训练配置表单（必须在algorithmOptions之前定义） ==========
const form = reactive({
  targetColumn: '',
  featureColumns: [],
  taskType: 'classification',
  algorithm: 'random_forest',
  testSize: 0.2,
  cvFolds: 5,
  randomSeed: 42
})

// 根据任务类型动态返回算法选项
const algorithmOptions = computed(() => {
  return form.taskType === 'classification' ? classificationAlgorithms : regressionAlgorithms
})

// 监听任务类型切换，自动选择该任务类型下推荐度最高的算法
// 没有预检结果时回退到默认算法
watch(() => form.taskType, (newType) => {
  const topAlgo = getTopAlgorithm(newType)
  if (topAlgo) {
    form.algorithm = topAlgo.algorithm
  } else {
    // 无预检结果时使用默认算法
    form.algorithm = newType === 'classification' ? 'random_forest' : 'linear_regression'
  }
})

// ========== 目标列推荐 & 算法推荐(从预检结果获取) ==========

// 获取某列的目标列推荐信息(从预检结果中查找)
function getTargetColumnRec(col) {
  if (!precheckResult.value?.target_column_recommendations) return null
  return precheckResult.value.target_column_recommendations.find(r => r.column === col) || null
}

// 获取某算法的推荐信息(从预检结果中查找,与预检显示一致)
function getAlgorithmRec(algoId) {
  if (!precheckResult.value?.algorithm_recommendations || !form.taskType) return null
  const recs = precheckResult.value.algorithm_recommendations[form.taskType] || []
  return recs.find(r => r.algorithm === algoId) || null
}

// ========== 任务类型禁用逻辑 & 自动推荐 ==========

// 当前目标列的推荐信息
const currentTargetColumnRec = computed(() => {
  if (!form.targetColumn) return null
  return getTargetColumnRec(form.targetColumn)
})

// 是否禁用分类任务:目标列明确不推荐分类时禁用
const classificationDisabled = computed(() => {
  if (!form.targetColumn) return false
  const rec = currentTargetColumnRec.value
  // 没有预检结果时不禁用,有预检结果且明确不推荐分类时禁用
  if (!rec) return false
  return !rec.recommend_classification
})

// 是否禁用回归任务:目标列明确不推荐回归时禁用
const regressionDisabled = computed(() => {
  if (!form.targetColumn) return false
  const rec = currentTargetColumnRec.value
  if (!rec) return false
  return !rec.recommend_regression
})

// 任务类型 tooltip(动态显示禁用原因)
const taskTypeTooltip = computed(() => {
  const base = '分类：预测离散类别(如是否/类别);回归:预测连续数值(如价格/销量)。目标列不支持的任务类型会被禁用'
  const rec = currentTargetColumnRec.value
  if (!form.targetColumn) return base
  if (!rec) return base
  if (!rec.recommend_classification || !rec.recommend_regression) {
    return `${base}\n当前目标列: ${rec.reason}`
  }
  return base
})

// 是否可以执行自动推荐:已选目标列且目标列至少支持一种任务类型
const canAutoRecommend = computed(() => {
  if (!form.targetColumn) return false
  const rec = currentTargetColumnRec.value
  if (!rec) return false
  return rec.recommend_classification || rec.recommend_regression
})

// 获取某任务类型下推荐度最高的算法
function getTopAlgorithm(taskType) {
  if (!precheckResult.value?.algorithm_recommendations) return null
  const recs = precheckResult.value.algorithm_recommendations[taskType] || []
  if (recs.length === 0) return null
  // 已按 score 降序排序,取第一个
  return recs[0]
}

// 自动推荐:根据预检结果自动填充任务类型+最高推荐度算法+特征列
async function autoRecommend() {
  if (!canAutoRecommend.value) {
    ElMessage.warning('请先选择目标列,且目标列需支持分类或回归任务')
    return
  }
  const rec = currentTargetColumnRec.value
  // 选择任务类型:优先选推荐的任务类型,若两者都推荐则比较最高算法评分
  let targetTaskType = form.taskType
  if (rec.recommend_classification && rec.recommend_regression) {
    const clsTop = getTopAlgorithm('classification')
    const regTop = getTopAlgorithm('regression')
    const clsScore = clsTop?.score || 0
    const regScore = regTop?.score || 0
    targetTaskType = clsScore >= regScore ? 'classification' : 'regression'
  } else if (rec.recommend_classification) {
    targetTaskType = 'classification'
  } else if (rec.recommend_regression) {
    targetTaskType = 'regression'
  }

  // 切换任务类型(会触发 watch 重置算法,需在切换后手动设置最高分算法)
  if (form.taskType !== targetTaskType) {
    form.taskType = targetTaskType
    // 等待 watch 触发完毕再设置算法,使用 nextTick
    await nextTick()
  }

  // 设置当前任务类型下推荐度最高的算法
  const topAlgo = getTopAlgorithm(targetTaskType)
  if (topAlgo) {
    form.algorithm = topAlgo.algorithm
  }

  // 触发特征列推荐并自动勾选
  // 立即触发,不走防抖
  if (featureRecTimer) clearTimeout(featureRecTimer)
  featureRecommendations.value = []
  featureRecLoading.value = true
  await loadFeatureRecommendations()

  ElMessage.success(`已自动推荐: ${targetTaskType === 'classification' ? '分类' : '回归'}任务 / ${getAlgorithmLabel(form.algorithm)} / ${form.featureColumns.length} 个特征列`)
}

// 算法变更时检查:不推荐算法选中时弹提示,用户可强制选择或回退
let lastAlgorithm = ''  // 记录变更前的算法,用于回退
async function onAlgorithmChange(newAlgo) {
  const rec = getAlgorithmRec(newAlgo)
  if (!rec) {
    lastAlgorithm = newAlgo
    return
  }
  if (rec.recommended) {
    // 推荐算法,直接接受
    lastAlgorithm = newAlgo
    return
  }
  // 不推荐算法,弹提示让用户确认
  try {
    await ElMessageBox.confirm(
      `${rec.label_cn} 不推荐用于当前数据:\n${rec.reason}\n\n是否仍要强制使用该算法?`,
      '算法选择提示',
      {
        confirmButtonText: '强制使用',
        cancelButtonText: '换回原算法',
        type: 'warning'
      }
    )
    // 用户确认强制使用
    lastAlgorithm = newAlgo
    ElMessage.warning(`已强制使用 ${rec.label_cn},可能影响训练效果或耗时`)
  } catch (e) {
    // 用户取消,回退到上一个算法
    if (lastAlgorithm) {
      form.algorithm = lastAlgorithm
    } else {
      // 没有上一个算法,选择推荐度最高的
      const topAlgo = getTopAlgorithm(form.taskType)
      if (topAlgo) {
        form.algorithm = topAlgo.algorithm
      }
    }
  }
}

// ========== 特征列智能推荐 ==========
const featureRecommendations = ref([])  // 特征列推荐列表
const featureRecLoading = ref(false)    // 推荐加载状态
let featureRecTimer = null              // 防抖定时器

// 监听目标列变化,自动联动任务类型并触发特征列推荐
// 加 300ms 防抖避免快速切换目标列时频繁请求
watch(() => form.targetColumn, (newCol, oldCol) => {
  if (!newCol || newCol === oldCol) return
  // 立即清空旧推荐并显示 loading,避免用户误以为没有推荐
  featureRecommendations.value = []
  featureRecLoading.value = true
  if (featureRecTimer) clearTimeout(featureRecTimer)
  featureRecTimer = setTimeout(() => {
    loadFeatureRecommendations()
  }, 300)
})

// 加载特征列推荐
async function loadFeatureRecommendations() {
  // 兼容远程模式:远程模式下 datasetId 为空,用 hasDataSource 判断数据源是否就绪
  if (!hasDataSource.value || !form.targetColumn) {
    featureRecommendations.value = []
    return
  }
  featureRecLoading.value = true
  try {
    const isRemote = sourceConfig.value.mode === 'remote'
    const remote = isRemote ? sourceConfig.value.remote : null
    const res = await recommendFeatures(isRemote ? null : datasetId.value, form.targetColumn, remote)
    const data = res.data
    // 联动任务类型:后端根据目标列类型自动判断
    if (data.task_type && data.task_type !== form.taskType) {
      form.taskType = data.task_type
    }
    featureRecommendations.value = data.feature_recommendations || []
    // 自动勾选推荐的特征列(should_select=true 的)
    form.featureColumns = featureRecommendations.value
      .filter(f => f.should_select)
      .map(f => f.column)
  } catch (e) {
    console.error('特征列推荐失败:', e)
    featureRecommendations.value = []
  } finally {
    featureRecLoading.value = false
  }
}

// 获取某列的推荐评分(用于在特征列选择框旁边显示)
function getFeatureScore(col) {
  const rec = featureRecommendations.value.find(f => f.column === col)
  return rec || null
}

// 获取算法中文名称（兼容多种后端格式）
// 后端可能返回: "随机森林（分类）" / "random_forest (classification)" / "random_forest" / "随机森林"
function getAlgorithmLabel(algorithm) {
  if (!algorithm) return '-'
  // 去除任务类型标注(兼容全角括号和半角括号)
  // 全角: "随机森林（分类）" → "随机森林"
  // 半角: "random_forest (classification)" → "random_forest"
  let pureName = algorithm.replace(/（.*）$/, '').replace(/\s*\(.*\)\s*$/, '').trim()
  // 英文名转中文名
  return algorithmLabelMap[pureName] || pureName
}

// ========== 算法tooltip说明(覆盖全部 14 个算法) ==========
const algorithmExplanations = {
  logistic_regression: '逻辑回归：线性分类模型，适合线性可分数据，速度快，可解释性强，适合基线模型和小数据集',
  svm: '支持向量机(SVM/SVR)：在高维空间找最优分界，小数据集表现好，大数据集训练慢(O(n²)~O(n³))，需要标准化',
  decision_tree: '决策树：树形规则结构，可解释性极强，能处理非线性，但容易过拟合，适合作为基线模型',
  naive_bayes: '朴素贝叶斯：基于贝叶斯定理的概率分类器，假设特征独立，训练极快，适合文本分类和小数据',
  knn: 'K近邻(KNN)：基于距离的惰性学习，无需训练过程，预测时计算全量距离，大数据集预测慢，需要标准化',
  linear_regression: '线性回归：最简单的回归模型，假设线性关系，速度快可解释，作为回归基线模型',
  ridge_regression: '岭回归：带 L2 正则化的线性回归，能抑制多重共线性，减少过拟合，适合高维数据',
  lasso_regression: 'Lasso回归：带 L1 正则化的线性回归，能进行特征选择(系数压缩为0)，适合稀疏特征数据',
  random_forest: '随机森林：集成多棵决策树取多数投票/平均，精度高抗过拟合，能处理非线性，工业界常用',
  adaboost: 'AdaBoost：串行训练弱分类器，每个关注前一个分错的样本，适合二分类，对噪声敏感',
  gbdt: '梯度提升树(GBDT)：串行训练决策树拟合残差，精度高，但串行训练较慢，大数据集建议用 XGBoost/LightGBM',
  xgboost: 'XGBoost：GBDT 的工程优化版，支持并行计算和原生缺失值处理，训练快精度高，工业界首选集成算法',
  lightgbm: 'LightGBM：微软开源的 GBDT 优化版，基于直方图算法训练极快，内存占用低，适合大数据集',
  mlp: '多层感知机(MLP)：全连接神经网络，能拟合复杂非线性关系，需要充足数据，小数据集易过拟合，需要标准化'
}

const algorithmTooltip = computed(() => {
  // 显示当前任务类型下所有算法的简要说明
  const algoList = form.taskType === 'classification' ? classificationAlgorithms : regressionAlgorithms
  return algoList.map(a => `${a.label}：${algorithmExplanations[a.value] || ''}`).join('\n')
})

// 当前选中算法的详细说明(用于算法下拉框旁的 ? 图标)
const currentAlgorithmExplanation = computed(() => {
  return algorithmExplanations[form.algorithm] || ''
})

// ========== 机器学习专有名词解释（用于 ? 图标 tooltip） ==========
// 参考 FeatureEngineering.vue 的实现，每个名词配一段通俗说明，方便初学者理解
const mlGlossary = {
  // 任务概念
  target: '要预测的目标变量列。分类任务一般为类别标签（如"是否流失"），回归任务为连续数值（如"房价"）',
  features: '用于预测目标列的输入特征（自变量）。不选则默认使用除目标列外的全部列',
  classification: '分类任务：预测离散的类别标签，例如"是/否"、"高/中/低"、"猫/狗/鸟"',
  regression: '回归任务：预测连续数值，例如"价格""销量""温度"，输出是实数',

  // 数据集划分
  trainTest: '训练集用于拟合模型参数，测试集用于评估模型的真实泛化能力。两者必须严格隔离',
  cvFolds: 'K折交叉验证：将训练集均分为K份，每次用K-1份训练、1份验证，循环K次取平均，减小单次划分的偶然性',
  recommendedSplit: '系统根据数据量给出的推荐测试集比例，小数据集建议0.2，大数据集可降至0.1',

  // 调优
  tuneL2: 'L2级调优：使用随机搜索（RandomizedSearchCV）在超参数空间中按分布采样，对比网格搜索速度更快',
  tuneL3: 'L3级调优：使用网格搜索（GridSearchCV）穷举所有超参数组合，最准确但耗时最长',
  gridSearch: '网格搜索：在预设的参数网格中逐个组合尝试，选出CV分数最高的组合',
  randomSearch: '随机搜索：在参数空间中按分布随机采样N个组合，适合大参数空间，速度快',

  // 分类指标
  accuracy: '准确率：预测正确的样本占总样本的比例。最直观但在类别不平衡时可能误导',
  precision: '精确率：在模型预测为正例的样本中，实际为正例的比例。关注"预测的准不准"',
  recall: '召回率：在所有实际正例中，被模型正确预测出来的比例。关注"找的全不全"',
  f1: 'F1分数：精确率与召回率的调和平均（2×P×R/(P+R)），综合反映模型质量',
  rocAuc: 'ROC曲线下面积，越接近1代表模型区分正负样本的能力越强，0.5相当于随机猜',
  confusion: '二分类：阳性=标签为正例，阴性=标签为负例。真正例/假正例/真负例/假负例组成混淆矩阵',

  // 回归指标
  r2: 'R² 决定系数：模型解释的方差占总方差的比例，1表示完美预测，0表示和均值一样，负值比均值还差',
  mse: 'MSE 均方误差：预测值与真实值之差的平方的平均值。放大了较大误差的惩罚',
  rmse: 'RMSE 均方根误差：MSE的平方根，与原数据同量纲，对大误差更敏感',
  mae: 'MAE 平均绝对误差：预测值与真实值之差的绝对值的平均，直观反映平均偏离程度',
  mape: 'MAPE 平均绝对百分比误差：以百分比衡量误差大小，便于跨量级数据比较',

  // 特征与模型
  featureImportance: '特征重要性：衡量每个特征对模型预测的贡献度，值越大说明该特征越关键',
  cvMean: 'CV Mean：K折交叉验证的平均分数，反映模型在训练集上的整体稳定性',
  cvStd: 'CV Std：K折交叉验证分数的标准差，越小说明模型越稳定',

  // 预测
  predictIndex: '原数据索引：该预测结果在原始数据集中的行位置（从0开始），便于回溯',
  predictProba: '预测概率：分类任务中模型对每个类别的置信度，值越高越确定',
  predictLabel: '预测值：模型根据特征给出的最终输出。分类是类别，回归是连续数值',
  batchPredict: '批量预测：使用已训练模型对新数据逐行预测，适合对大量样本一次性打标',
  testEval: '测试集独立评估：用训练时完全未见的测试集评估模型，模拟"期末考试"',

  // 业务概念
  overfit: '过拟合：模型在训练集上表现很好但在测试集上很差，说明学到了训练集的噪声',
  underfit: '欠拟合：模型在训练集和测试集上都表现差，说明模型太简单或特征不足',
  pipeline: 'Pipeline：把数据预处理、特征工程、模型训练串成一条流水线，预测时复用相同的处理步骤'
}

// ========== 数据集状态 ==========
const mlRawData = ref([])
const datasetId = ref(null)
const currentDataset = ref(null)
const availableColumns = ref([])

// 数据源选择器状态（本地/远程）
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

const hasDataSource = computed(() => {
  if (sourceConfig.value.mode === 'local') return !!sourceConfig.value.datasetId
  if (sourceConfig.value.mode === 'remote') return !!(sourceConfig.value.remote)
  return false
})

// 数据源选择回调
async function onSourceSelect(config) {
  if (config.mode === 'local') {
    datasetId.value = config.datasetId
    sourceConfig.value = { mode: 'local', datasetId: config.datasetId, remote: null }
    // 触发数据集变更逻辑
    onDatasetChange(config.datasetId)
    loadPreview()
  } else {
    // 远程模式：清空本地数据集选择，加载远程表 schema 获取列名
    datasetId.value = null
    sourceConfig.value = { mode: 'remote', datasetId: null, remote: config.remote }
    // 重置状态（含目标列和特征列，避免上一个数据集的残留配置影响远程模式）
    currentDataset.value = null
    precheckResult.value = null
    availableColumns.value = []
    featureRecommendations.value = []
    modelList.value = []
    modelListTotal.value = 0
    trainResult.value = null
    // 重置目标列和特征列，确保切换数据源后能重新触发特征列推荐
    form.targetColumn = ''
    form.featureColumns = []
    // 加载远程表当前生效的列信息（含特征工程动态新增的构造列）
    if (config.remote?.connection_id && config.remote?.table_name) {
      try {
        const res = await fetchRemoteColumnPool(config.remote.connection_id, config.remote.table_name)
        const poolData = res.data || {}
        availableColumns.value = (poolData.columns || []).map(col => col.name).filter(Boolean)
        // 远程模式不自动选目标列，避免选中ID等非合适列导致特征推荐为0
        // 用户手动选择目标列后会自动触发 watch → 特征列推荐
        ElMessage.success(`已加载远程表 ${config.remote.table_name} 的 ${availableColumns.value.length} 个列`)
        // 远程模式自动触发预检，生成算法推荐
        runPrecheck()
      } catch (e) {
        availableColumns.value = []
        ElMessage.error('加载远程表列信息失败：' + (e?.response?.data?.detail || e?.message || '未知错误'))
      }
    }
    // 远程模式：内嵌数据预览暂不支持，置空并提示
    loadPreview()
  }
}

// ========== 上传 ==========
const uploadFile = ref(null)
const uploadLoading = ref(false)

// ========== 加载状态 ==========
const loading = reactive({
  info: false,
  train: false,
  tuneL2: false,
  tuneL3: false,
  models: false,
  predict: false
})

// ========== 训练结果 ==========
const trainResult = ref(null)

// 训练结果的实际任务类型(优先用 trainResult.task_type, fallback 到 form.taskType)
// 避免用户切换任务类型后查看旧训练结果时显示错误的指标
const resultTaskType = computed(() => trainResult.value?.task_type || form.taskType)

// ========== 模型列表（后端分页） ==========
const modelList = ref([])
const modelListPage = ref(1)
const modelListPageSize = ref(50)
const modelListTotal = ref(0)

// ========== 批量预测 ==========
const predictDialogVisible = ref(false)
const currentPredictModel = ref(null)
const predictDatasetId = ref(null)
const predictResult = ref(null)
const predictUploadFile = ref(null)
const predictUploadLoading = ref(false)
const predictDataList = ref([])  // 预测数据列表（从数据管理获取）

// ========== 测试集评估 ==========
const testEvalDialogVisible = ref(false)
const testEvalResult = ref(null)
// 测试集评估分页状态（客户端分页，数据来自任务返回）
const testEvalPage = ref(1)
const testEvalPageSize = ref(30)

const testEvalPreviewRows = computed(() => {
  if (!testEvalResult.value) return []
  // 使用后端返回的 samples 数组，客户端分页切片
  const samples = testEvalResult.value.samples || []
  const start = (testEvalPage.value - 1) * testEvalPageSize.value
  const end = start + testEvalPageSize.value
  const rows = []
  for (let i = start; i < end && i < samples.length; i++) {
    const s = samples[i]
    rows.push({
      y_true: s.y_true,
      y_pred: s.y_pred,
      correct: s.correct,
      abs_error: s.abs_error,
      rel_error: s.rel_error
    })
  }
  return rows
})

// 测试集评估总数
const testEvalTotal = computed(() => testEvalResult.value?.samples?.length || 0)

// 评估结果变化时重置分页到第一页
watch(() => testEvalResult.value, () => {
  testEvalPage.value = 1
})

// ========== 计算属性 ==========
// 当前数据集数据量
const dataVolume = computed(() => currentDataset.value?.row_count || 0)

// 智能推荐测试集比例（基于数据量）
const recommendedTestSize = computed(() => {
  const n = dataVolume.value
  if (n <= 0) return 0.2
  if (n < 1000) return 0.3
  if (n <= 10000) return 0.2
  return 0.1
})

// 实际训练集大小
const actualTrainSize = computed(() => {
  if (!dataVolume.value) return 0
  return Math.floor(dataVolume.value * (1 - form.testSize))
})

// 实际测试集大小
const actualTestSize = computed(() => {
  if (!dataVolume.value) return 0
  return Math.floor(dataVolume.value * form.testSize)
})

// 是否可训练：预检存在阻断错误时禁止训练，避免小数据/无特征数据训练报底层堆栈错误
const canTrain = computed(() => {
  return hasDataSource.value && form.targetColumn && precheckResult.value?.can_train !== false
})

// 交叉验证分数行
const cvScoreRows = computed(() => {
  const scores = trainResult.value?.metrics?.cv_scores || []
  return scores.map((score, idx) => ({ index: idx + 1, score }))
})

// 最佳参数行
const bestParamRows = computed(() => {
  const params = trainResult.value?.best_params || {}
  return Object.entries(params).map(([name, value]) => ({ name, value: String(value) }))
})

// 特征重要性行
const featureImportanceRows = computed(() => {
  const fi = trainResult.value?.feature_importance || {}
  const entries = Object.entries(fi)
  entries.sort((a, b) => b[1] - a[1])
  return entries.map(([feature, importance]) => ({ feature, importance }))
})

// 最大特征重要性
const maxImportance = computed(() => {
  const rows = featureImportanceRows.value
  if (rows.length === 0) return 0
  return Math.max(...rows.map(r => r.importance))
})

// 总特征重要性
const totalImportance = computed(() => {
  const rows = featureImportanceRows.value
  if (rows.length === 0) return 1
  return rows.reduce((sum, r) => sum + r.importance, 0) || 1
})

// 预测概率标签
const probaLabels = computed(() => {
  const proba = predictResult.value?.probabilities
  if (!proba || proba.length === 0) return []
  return Object.keys(proba[0] || {}).map(k => k)
})

// 是否含预测概率（分类任务）
const hasProbability = computed(() => {
  return predictResult.value?.probabilities && predictResult.value.probabilities.length > 0
})

// 预测结果分页状态（客户端分页，数据来自任务返回）
const predictPage = ref(1)
const predictPageSize = ref(20)

// 预测预览行（客户端分页切片）
const predictPreviewRows = computed(() => {
  const predictions = predictResult.value?.predictions || []
  const probabilities = predictResult.value?.probabilities || []
  const start = (predictPage.value - 1) * predictPageSize.value
  const end = start + predictPageSize.value
  return predictions.slice(start, end).map((prediction, idx) => {
    const realIdx = start + idx
    const row = { index: realIdx, prediction }
    if (probabilities[realIdx]) {
      // 概率是数组形式
      if (Array.isArray(probabilities[realIdx])) {
        row.probabilities = probabilities[realIdx]
      } else {
        row.probabilities = Object.values(probabilities[realIdx])
      }
    }
    return row
  })
})

// 预测结果总数
const predictTotal = computed(() => predictResult.value?.predictions?.length || 0)

// 预测结果变化时重置分页到第一页
watch(() => predictResult.value, () => {
  predictPage.value = 1
})

// ========== 辅助方法 ==========
function formatPercent(val) {
  if (val === undefined || val === null) return '-'
  return (val * 100).toFixed(2) + '%'
}

function formatDate(iso) {
  if (!iso) return '-'
  try {
    let d
    // 如果时间字符串不包含时区标识，假设它是UTC时间
    const hasTimezone = iso.includes('Z') || /[+-]\d{2}:\d{2}$/.test(iso)
    if (!hasTimezone) {
      d = new Date(iso + 'Z')
    } else {
      d = new Date(iso)
    }
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

function isClassificationModel(algorithm) {
  if (!algorithm) return false
  // 后端保存的格式可能是:
  //   - 新格式(全角括号+中文): "随机森林（分类）" / "随机森林（回归）"
  //   - 旧格式(半角括号+英文): "random_forest (classification)"
  //   - 纯算法名(英文/中文): "random_forest" / "随机森林"
  // 优先按任务类型关键词判断(最可靠)
  if (algorithm.includes('分类')) return true
  if (algorithm.includes('回归')) return false
  if (algorithm.includes('classification')) return true
  if (algorithm.includes('regression')) return false
  // 兜底:按算法名查注册表(纯算法名场景)
  // 仅分类算法:logistic_regression/naive_bayes
  // 仅回归算法:linear_regression/ridge_regression/lasso_regression
  // 同时支持:SVM/决策树/KNN/随机森林/AdaBoost/GBDT/XGBoost/LightGBM/MLP → 默认按分类处理
  if (algorithm.includes('linear_regression') || algorithm.includes('ridge_regression') || algorithm.includes('lasso_regression')) {
    return false
  }
  return true
}

function onSplitChange() {
  // 触发 actualTrainSize 和 actualTestSize 重算
}

// 使用推荐划分比例
function useRecommendedSplit() {
  form.testSize = recommendedTestSize.value
  ElMessage.success(`已使用推荐比例: ${(1 - form.testSize).toFixed(1)} : ${form.testSize.toFixed(1)}`)
}

// ========== 数据集管理 ==========
async function loadMLRawData() {
  try {
    const res = await fetchMLRawData()
    mlRawData.value = res.data || []
  } catch {
    ElMessage.warning('无法加载ML模块原始数据列表')
  }
}

// 加载数据集信息（获取列名）
async function loadDatasetInfo() {
  // 远程模式下数据信息已在 onSourceSelect 中加载，无需重复加载
  if (sourceConfig.value.mode === 'remote') return
  if (!datasetId.value) return
  loading.info = true
  try {
    const res = await fetchDatasetById(datasetId.value)
    currentDataset.value = res.data
    // 解析 schema 获取列名（API返回的是 'schema' 字段，不是 'data_schema'）
    const schema = res.data?.schema || res.data?.data_schema
    if (schema && typeof schema === 'object') {
      availableColumns.value = Object.keys(schema)
    } else if (res.data?.data_preview || res.data?.preview) {
      // 从预览数据获取列名
      try {
        const previewData = res.data.data_preview || res.data.preview
        const preview = JSON.parse(previewData.replace(/'/g, '"'))
        if (Array.isArray(preview) && preview.length > 0) {
          availableColumns.value = Object.keys(preview[0])
        }
      } catch {
        availableColumns.value = []
      }
    } else {
      availableColumns.value = []
    }
    if (availableColumns.value.length === 0) {
      ElMessage.warning('未能获取数据列名，请检查数据集')
    } else {
      // 自动选择首个列作为目标列（如果未选择）
      if (!form.targetColumn && availableColumns.value.length > 0) {
        form.targetColumn = availableColumns.value[0]
      }
    }
  } catch (e) {
    ElMessage.error(e?.response?.data?.message || e?.response?.data?.error || e?.response?.data?.detail || e?.message || '加载数据信息失败')
    currentDataset.value = null
    availableColumns.value = []
  } finally {
    loading.info = false
  }
}

// 数据集变化处理
async function onDatasetChange(id) {
  if (!id) {
    currentDataset.value = null
    availableColumns.value = []
    trainResult.value = null
    modelList.value = []
    // 清空预检结果和特征推荐
    precheckResult.value = null
    featureRecommendations.value = []
    return
  }
  // 选择新数据集时，重置训练结果
  trainResult.value = null
  // 重置训练配置：避免旧数据集的目标列/特征列残留，导致训练报"目标列不存在"或用错列训练（修复）
  form.targetColumn = ''
  form.featureColumns = []
  // 清空旧预检结果和特征推荐,触发新预检
  precheckResult.value = null
  featureRecommendations.value = []
  // 重置模型列表分页
  modelListPage.value = 1
  await loadDatasetInfo()
  await loadModelList()
  // 自动触发预检(参考特征工程的实现)
  runPrecheck()
}

// ========== 预检功能 ==========
// 切换数据集后自动调用预检,检查数据质量并给出算法推荐
// 结果与后端 Redis 缓存对齐(5分钟 TTL),同一数据集重复切换不会重复请求
const precheckResult = ref(null)
const precheckLoading = ref(false)
const precheckActiveTab = ref('classification')  // 预检算法推荐 Tab,默认分类

async function runPrecheck() {
  if (!hasDataSource.value) return
  precheckLoading.value = true
  try {
    const isRemote = sourceConfig.value.mode === 'remote'
    const remote = isRemote ? sourceConfig.value.remote : null
    const res = await mlPrecheck(isRemote ? null : datasetId.value, remote)
    precheckResult.value = res.data
  } catch (e) {
    // 预检失败不阻断训练,仅记录错误
    console.error('预检失败:', e)
    precheckResult.value = null
  } finally {
    precheckLoading.value = false
  }
}

// 当前算法是否被预检标记为不推荐或慢警告
// 适配新的预检结构:algorithm_recommendations 是按 task_type 分组的字典
const currentAlgorithmWarning = computed(() => {
  if (!precheckResult.value || !form.algorithm || !form.taskType) return null
  const recs = precheckResult.value.algorithm_recommendations?.[form.taskType] || []
  const rec = recs.find(r => r.algorithm === form.algorithm)
  if (!rec) return null
  if (rec.reason && rec.reason_type === 'warning') return rec.reason
  return null
})

// 加载模型列表（后端分页）
async function loadModelList() {
  // 远程模式：展示该用户远程训练的所有模型（后端按 parent_id 为空过滤）
  if (sourceConfig.value.mode === 'remote') {
    loading.models = true
    try {
      const res = await listModels(0, modelListPage.value, modelListPageSize.value)
      const data = res.data
      modelList.value = data.models || []
      modelListTotal.value = data.total || 0
    } catch {
      ElMessage.warning('无法加载远程模型列表')
      modelList.value = []
      modelListTotal.value = 0
    } finally {
      loading.models = false
    }
    return
  }
  if (!datasetId.value) return
  loading.models = true
  try {
    const res = await listModels(datasetId.value, modelListPage.value, modelListPageSize.value)
    const data = res.data
    modelList.value = data.models || []
    modelListTotal.value = data.total || 0
  } catch {
    ElMessage.warning('无法加载模型列表')
    modelList.value = []
    modelListTotal.value = 0
  } finally {
    loading.models = false
  }
}

// ========== 上传文件 ==========
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
    const res = await uploadMLFile(uploadFile.value)
    const data = res.data || {}
    if (data.id) {
      // 刷新下拉框并自动选中新上传的数据集，避免用户在带时间戳的重名文件中难以辨认
      await dataSourceSelectorRef.value?.reload()
      dataSourceSelectorRef.value?.selectDataset(data.id)
      mlRawData.value.push(data)
      if (datasetStore?.datasets) {
        datasetStore.datasets.push(data)
      }
      ElMessage.success('文件上传成功，已自动加载数据')
      // 通过 onSourceSelect 统一触发状态更新（含 sourceConfig、预检、特征推荐）
      onSourceSelect({ mode: 'local', datasetId: data.id })
    } else {
      ElMessage.success('文件上传成功')
      await loadMLRawData()
    }
    uploadFile.value = null
  } catch {
    ElMessage.error('上传失败，请检查文件格式')
  } finally {
    uploadLoading.value = false
  }
}

// ========== 训练模型 ==========
async function trainModel(autoTune, tuneMethod) {
  if (!canTrain.value) {
    ElMessage.warning('请先选择数据集和目标列')
    return
  }
  if (loading.train || loading.tuneL2 || loading.tuneL3) return

  // 大数据慢算法确认(SVM/KNN 在大数据上训练慢,预检给出预计时间让用户决定)
  if (currentAlgorithmWarning.value) {
    try {
      await ElMessageBox.confirm(
        currentAlgorithmWarning.value,
        '算法训练提示',
        {
          confirmButtonText: '继续训练',
          cancelButtonText: '取消',
          type: 'warning'
        }
      )
    } catch {
      // 用户取消
      return
    }
  }

  // 设置加载状态
  if (autoTune && tuneMethod === 'grid') {
    loading.tuneL3 = true
  } else if (autoTune && tuneMethod === 'random') {
    loading.tuneL2 = true
  } else {
    loading.train = true
  }

  // 构造请求
  // 捕获提交时的数据集ID，用于同步/异步响应返回时校验数据集一致性，避免页面污染
  const submitDatasetId = datasetId.value
  const isRemote = sourceConfig.value.mode === 'remote'
  // 回归任务中 random_forest 同样使用 random_forest 算法标识
  const algorithm = form.algorithm
  const config = {
    dataset_id: isRemote ? null : datasetId.value,
    target_column: form.targetColumn,
    feature_columns: form.featureColumns.length > 0 ? form.featureColumns : undefined,
    task_type: form.taskType,
    algorithm: algorithm,
    test_size: form.testSize,
    cv_folds: form.cvFolds,
    auto_tune: !!autoTune,
    tune_method: autoTune ? (tuneMethod || 'random') : 'random',
    hyperparams: autoTune ? (defaultHyperparams[algorithm] || {}) : {},
    random_seed: form.randomSeed
  }
  // 远程数据源配置
  if (isRemote && sourceConfig.value.remote) {
    config.remote = sourceConfig.value.remote
  }

  try {
    const res = await trainSupervised(config)
    const data = res.data || {}

    // 异步队列：后端返回 queued/running/pending + task_record_id，提交到全局任务面板管理
    if ((data.status === 'queued' || data.status === 'running' || data.status === 'pending') && data.task_record_id) {
      // 提交到全局任务面板，store内部自动管理轮询
      addTask({
        recordId: data.task_record_id,
        celeryTaskId: data.task_id,
        taskType: 'ml_training',
        operation: autoTune ? (tuneMethod === 'grid' ? '网格搜索调优' : '随机搜索调优') : '模型训练',
        moduleLabel: '机器学习',
        datasetName: currentDataset.value?.name || '',
        initialStatus: data.status === 'pending' ? 'pending' : 'running',
      isRemote: sourceConfig.value.mode === 'remote',
      }, (status, summary) => {
        // 任务完成回调：成功时刷新模型列表，并按数据集一致性展示评估结果
        if (status === 'success') {
          modelListPage.value = 1
          loadModelList()
          if (datasetId.value === submitDatasetId && summary) {
            trainResult.value = summary
            ElMessage.success('训练完成，已展示评估结果')
          } else {
            ElMessage.success('训练完成，请切回原数据集查看结果')
          }
        } else if (status === 'failed') {
          ElMessage.error(`训练失败: ${summary?.current_message || '请查看任务面板'}`)
        } else if (status === 'cancelled') {
          ElMessage.info('训练任务已取消')
        }
      })
      ElMessage.info(data.message || '训练任务已提交至后台队列')
      return
    }

    // 同步结果：校验数据集一致性后展示，避免 await 期间用户切换数据集导致页面污染
    if (datasetId.value === submitDatasetId) {
      trainResult.value = data
      const tip = autoTune
        ? (tuneMethod === 'grid' ? 'L3网格搜索调优' : 'L2随机搜索调优')
        : '训练'
      ElMessage.success(`${tip}完成，模型ID: ${data?.model_id}`)
      // 刷新模型列表（仅当前数据集一致时才刷新，避免刷新到错误数据集的模型列表）
      modelListPage.value = 1
      await loadModelList()
    } else {
      // 数据集已切换，不展示结果，仅提示用户切回原数据集查看
      ElMessage.success('训练完成，请切回原数据集查看结果')
    }
  } catch (e) {
    // 输出详细错误日志到控制台便于排查
    console.error('【训练错误】', e)
    console.error('请求配置:', config)
    console.error('响应:', e?.response?.data)
    const msg = e?.response?.data?.message || e?.response?.data?.error || e?.response?.data?.detail || e?.message || '训练失败'
    ElMessage.error(`训练失败: ${msg}`)
  } finally {
    loading.train = false
    loading.tuneL2 = false
    loading.tuneL3 = false
  }
}

// 处理批量预测结果（同步任务专用）
// 异步任务的结果由全局任务面板的回调处理，不经过此函数
function handleBatchPredictResult(data) {
  // 同步成功：data 含完整预测结果，直接渲染到预测结果区域
  predictResult.value = data
  const saveHint = '已自动保存到【数据管理 → 机器学习预测数据 → 批量预测结果】，可在该模块预览或下载'
  if (data?.warnings?.length) {
    ElMessage.warning(`预测完成，共 ${data?.row_count || 0} 条结果，${saveHint}。注意: ${data.warnings.join('；')}`)
  } else {
    ElMessage.success(`预测完成，共 ${data?.row_count || 0} 条结果，${saveHint}`)
  }
}

// ========== 测试集独立评估（期末考试） ==========
async function runTestEvaluate(row) {
  try {
    testEvalResult.value = null
    testEvalDialogVisible.value = true
    const res = await testSetEvaluate(row.id)
    testEvalResult.value = res.data
    ElMessage.success('测试集评估完成')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '测试集评估失败')
    testEvalDialogVisible.value = false
  }
}

// ========== 导出模型文件 ==========
async function handleExportModel(row) {
  try {
    const res = await exportModelFile(row.id)
    const blob = new Blob([res.data])
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = row.name + '.pkl'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    ElMessage.success('模型文件已开始下载')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '导出模型失败')
  }
}

// ========== 导出模型报告到数据管理 ==========
async function handleExportReport(row) {
  try {
    const res = await exportModelReport(row.id)
    ElMessage.success(res.data?.message || '模型报告已导出到数据管理')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '导出报告失败')
  }
}

async function openBatchPredict(row) {
  currentPredictModel.value = row
  predictDatasetId.value = null
  predictResult.value = null
  predictUploadFile.value = null
  predictDialogVisible.value = true
  // 加载预测数据列表（从数据管理获取 predict_data 类型）
  await loadPredictDataList()
}

// 加载预测数据列表
async function loadPredictDataList() {
  try {
    const res = await api.get('/datasets/', { params: { artifact_type: 'predict_data' } })
    predictDataList.value = res.data || []
  } catch {
    predictDataList.value = []
  }
}

// 选择预测上传文件
function onPredictFileChange(file) {
  predictUploadFile.value = file.raw
}

// 取消预测上传
function cancelPredictUpload() {
  predictUploadFile.value = null
}

// 上传并预测
async function doPredictUpload() {
  if (!predictUploadFile.value || !currentPredictModel.value) return
  predictUploadLoading.value = true
  try {
    // 1. 上传文件到预测数据模块
    const formData = new FormData()
    formData.append('file', predictUploadFile.value)
    const uploadRes = await api.post('/datasets/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      params: {
        module_source: 'ml',
        artifact_type: 'predict_data'
      }
    })
    const newDatasetId = uploadRes.data?.id
    if (!newDatasetId) {
      ElMessage.error('上传失败，未获取数据集ID')
      return
    }
    // 上传完成，清空文件选择
    predictUploadFile.value = null
    // 2. 用新数据集ID进行预测（复用 onBatchPredict 支持异步分发）
    await onBatchPredict(newDatasetId)
  } catch (e) {
    const msg = e?.response?.data?.message || e?.response?.data?.error || e?.response?.data?.detail || e?.message || '上传失败'
    ElMessage.error(msg)
  } finally {
    predictUploadLoading.value = false
  }
}

// 批量预测：支持异步分发（≥1万行后端返回 task_record_id，前端轮询进度）
// 参数 predictDatasetId 为待预测的数据集ID（从下拉选择或上传文件后获取）
async function onBatchPredict(predictDatasetId) {
  if (!predictDatasetId) {
    ElMessage.warning('请选择待预测的数据集')
    return
  }
  if (!currentPredictModel.value) {
    ElMessage.warning('请先选择模型')
    return
  }
  loading.predict = true
  try {
    const res = await batchPredict(currentPredictModel.value.id, {
      dataset_id: predictDatasetId
    })
    const data = res.data || {}
    // 异步分发检测：大数据集（≥1万行）后端返回 queued/running/pending + task_record_id
    if ((data.status === 'queued' || data.status === 'running' || data.status === 'pending') && data.task_record_id) {
      // 提交到全局任务面板，store内部自动管理轮询
      const submitDatasetId = datasetId.value
      addTask({
        recordId: data.task_record_id,
        celeryTaskId: data.task_id,
        taskType: 'ml',
        operation: '批量预测',
        moduleLabel: '机器学习',
        datasetName: currentDataset.value?.name || '',
        initialStatus: data.status === 'pending' ? 'pending' : 'running',
      isRemote: sourceConfig.value.mode === 'remote',
      }, (status, summary) => {
        // 预测完成后刷新预测数据列表（异步结果已落库到数据管理）
        if (status === 'success') {
          loadPredictDataList()
          // 方案1：回调检查对话框状态
          // 对话框仍打开且数据集一致：直接展示结果，用户可立即查看
          // 对话框已关闭或数据集已切换：不设置 predictResult，提示用户从任务面板查看
          if (predictDialogVisible.value && datasetId.value === submitDatasetId && summary) {
            predictResult.value = summary
            ElMessage.success(`预测完成，共 ${summary.prediction_count || 0} 条结果`)
          } else {
            ElMessage.success('预测完成，可点击任务面板"查看结果"查看预测详情')
          }
        } else if (status === 'failed') {
          ElMessage.error(`预测失败: ${summary?.current_message || '请查看任务面板'}`)
        } else if (status === 'cancelled') {
          ElMessage.info('预测任务已取消')
        }
      }, (summary) => {
        // 方案2：onViewResult 回调 - 用户点击任务面板"查看结果"时调用
        // 重新打开批量预测对话框并回填 resultSummary，让用户查看预测详情
        if (summary) {
          predictDialogVisible.value = true
          predictResult.value = summary
        }
      })
      ElMessage.info(data.message || '批量预测任务已提交')
      return
    }
    // 同步任务：直接处理结果（含 predictions/probabilities，可预览前20行）
    handleBatchPredictResult(data)
  } catch (e) {
    // 503: Celery 不可用（大数据集不降级）
    if (e.response?.status === 503) {
      ElMessage.error('数据量较大（≥1万行），Celery 服务不可用，无法执行批量预测。请启动 Celery 服务或使用小数据集')
    } else if (e.response?.status === 429) {
      // 429: 单用户并发任务超限
      ElMessage.warning(e.response?.data?.detail || '异步任务数超限，请等待现有任务完成或取消后再试')
    } else {
      const msg = e?.response?.data?.message || e?.response?.data?.error || e?.response?.data?.detail || e?.message || '预测失败'
      ElMessage.error(msg)
    }
  } finally {
    loading.predict = false
  }
}

function downloadPredictResult() {
  if (!predictResult.value?.predictions) return
  const csvContent = generatePredictCsv(predictResult.value)
  const blob = new Blob(['\uFEFF' + csvContent], { type: 'text/csv' })
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
  link.download = `predict_result_${ts}.csv`
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
  ElMessage.success('预测结果已下载')
}

function generatePredictCsv(result) {
  const lines = ['index,prediction']
  const predictions = result.predictions || []
  const probabilities = result.probabilities || []
  predictions.forEach((p, idx) => {
    let line = `${idx},${p}`
    if (probabilities[idx]) {
      if (Array.isArray(probabilities[idx])) {
        probabilities[idx].forEach((prob, ci) => {
          line += `,${prob}`
        })
      }
    }
    lines.push(line)
  })
  return lines.join('\n')
}

// 处理模型名称更新事件
function handleModelNameUpdate(e) {
  const { id, name } = e.detail
  const idx = modelList.value.findIndex(m => m.id === id)
  if (idx >= 0) {
    modelList.value[idx].name = name
  }
}

// ========== 生命周期 ==========
onMounted(async () => {
  window.addEventListener('ml-model-name-updated', handleModelNameUpdate)
  await loadMLRawData()
})

onActivated(async () => {
  await loadMLRawData()
})

onBeforeUnmount(() => {
  window.removeEventListener('ml-model-name-updated', handleModelNameUpdate)
})
</script>

<style scoped>
.machine-learning {
  display: flex;
  flex-direction: column;
}

/* 卡片标题图标 */
.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: var(--text-primary);
}
.card-title .el-icon {
  color: var(--primary);
}

/* 分割比例控制 */
.split-control {
  display: flex;
  align-items: center;
  width: 100%;
}
.split-preview {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 12px;
  background: var(--primary-light);
  border-radius: var(--radius-sm);
}
.split-item {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}
.split-count {
  font-weight: 600;
  color: var(--text-primary);
}
.split-pct {
  color: var(--text-secondary);
  font-size: 12px;
}

/* 调优控制按钮组 */
.action-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

/* 结果展示 */
.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 16px 0 10px 0;
  padding-left: 10px;
  border-left: 3px solid var(--primary);
}
.section-title:first-child {
  margin-top: 0;
}

/* 评估指标卡片 */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}
.metric-card {
  padding: 16px;
  background: linear-gradient(135deg, #fafbff 0%, #f0f4ff 100%);
  border: 1px solid #e5e9f5;
  border-radius: var(--radius);
  transition: all var(--transition);
}
.metric-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--card-hover-shadow);
}
.metric-label {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}
.metric-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--primary);
  margin-bottom: 4px;
  font-family: 'Consolas', 'Monaco', monospace;
}
.metric-desc {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.4;
}

/* CV 摘要 */
.cv-summary,
.tune-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

/* 预测结果 */
.predict-result {
  margin-top: 12px;
}

/* 空状态 */
.empty-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}

/* 数据集下拉选项：色点 + 名称 + 元信息 */
.ds-option {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  overflow: hidden;
}

.ds-dot {
  flex: none;
  width: 9px;
  height: 9px;
  border-radius: 50%;
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
</style>
