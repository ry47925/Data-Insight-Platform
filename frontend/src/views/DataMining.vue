<template>
  <div class="data-mining">
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
        aria-label="上传数据文件进行数据挖掘分析"
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
      <DataSourceSelector ref="dataSourceSelectorRef" module-source="data_mining" @select="onSourceSelect" />
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

    <!-- 主内容区：选择数据集后显示 -->
    <div v-if="hasDataSource" class="mining-layout">
      <!-- ========== 预检结果 & 算法推荐卡片 ========== -->
      <div class="card precheck-card">
        <div class="card-title">
          <el-icon><DataAnalysis /></el-icon>
          <span>数据预检与算法推荐</span>
          <el-button
            size="small"
            text
            :loading="precheckLoading"
            @click="executePrecheck"
            style="margin-left:auto;"
          >
            <el-icon><Refresh /></el-icon>
            重新预检
          </el-button>
        </div>

        <!-- 加载中 -->
        <div v-if="precheckLoading" class="empty-state">
          <el-icon class="is-loading" :size="36"><Loading /></el-icon>
          <div class="empty-text">正在分析数据特征并生成算法推荐...</div>
        </div>

        <!-- 预检结果 -->
        <div v-else-if="precheckResult">
          <!-- 数据概况 -->
          <h4 class="section-subtitle">数据概况</h4>
          <div class="stats-grid mb-md">
            <div class="stat-card">
              <div class="stat-value">{{ precheckResult.data_profile?.row_count ?? '-' }}</div>
              <div class="stat-label">数据行数</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ precheckResult.data_profile?.col_count ?? '-' }}</div>
              <div class="stat-label">数据列数</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ precheckResult.data_profile?.numeric_count ?? '-' }}</div>
              <div class="stat-label">数值列数</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ precheckResult.data_profile?.categorical_count ?? '-' }}</div>
              <div class="stat-label">类别列数</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ formatPercent(precheckResult.data_profile?.missing_percentage) }}</div>
              <div class="stat-label">缺失值比例</div>
            </div>
          </div>

          <!-- 预检检查项 -->
          <div v-if="hasChecks" class="mb-md">
            <h4 class="section-subtitle">预检结果</h4>
            <el-alert
              v-for="(item, idx) in precheckErrors"
              :key="'err-' + idx"
              type="error"
              :closable="false"
              class="precheck-alert"
              show-icon
            >
              <template #title>{{ item.message }}</template>
            </el-alert>
            <el-alert
              v-for="(item, idx) in precheckWarnings"
              :key="'warn-' + idx"
              type="warning"
              :closable="false"
              class="precheck-alert"
              show-icon
            >
              <template #title>{{ item.message }}</template>
            </el-alert>
            <el-alert
              v-for="(item, idx) in precheckInfos"
              :key="'info-' + idx"
              type="info"
              :closable="false"
              class="precheck-alert"
              show-icon
            >
              <template #title>{{ item.message }}</template>
            </el-alert>
          </div>

          <!-- 算法推荐 -->
          <div>
            <h4 class="section-subtitle">算法推荐</h4>
            <div class="recommend-grid">
              <!-- 聚类推荐 -->
              <div class="recommend-item" :class="precheckResult.recommendations?.cluster?.recommended ? 'recommend-yes' : 'recommend-no'">
                <div class="recommend-header">
                  <el-icon class="recommend-icon">
                    <Check v-if="precheckResult.recommendations?.cluster?.recommended" />
                    <Close v-else />
                  </el-icon>
                  <span class="recommend-title">聚类分析</span>
                  <el-tooltip
                    content="聚类分析将样本划分为若干簇，使同簇样本相似、异簇样本相异。常用 KMeans、DBSCAN、层次聚类。"
                    placement="top" effect="dark" :show-after="200"
                  >
                    <el-icon class="help-icon"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </div>
                <div class="recommend-body">
                  <template v-if="precheckResult.recommendations?.cluster?.recommended">
                    <div class="recommend-algos">
                      <el-tag v-for="algo in precheckResult.recommendations.cluster.algorithms" :key="algo" size="small" type="success" effect="plain">
                        {{ algorithmLabel('cluster', algo) }}
                      </el-tag>
                    </div>
                    <div class="recommend-reason">{{ precheckResult.recommendations.cluster.reason }}</div>
                  </template>
                  <div v-else class="recommend-reason">{{ precheckResult.recommendations?.cluster?.reason || '当前数据不适合聚类分析' }}</div>
                </div>
              </div>

              <!-- 关联规则推荐 -->
              <div class="recommend-item" :class="precheckResult.recommendations?.association?.recommended ? 'recommend-yes' : 'recommend-no'">
                <div class="recommend-header">
                  <el-icon class="recommend-icon">
                    <Check v-if="precheckResult.recommendations?.association?.recommended" />
                    <Close v-else />
                  </el-icon>
                  <span class="recommend-title">关联规则</span>
                  <el-tooltip
                    content="关联规则从事务数据中挖掘 X 推出 Y 的频繁模式，衡量指标为支持度、置信度、提升度。"
                    placement="top" effect="dark" :show-after="200"
                  >
                    <el-icon class="help-icon"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </div>
                <div class="recommend-body">
                  <template v-if="precheckResult.recommendations?.association?.recommended">
                    <div class="recommend-algos">
                      <el-tag v-for="algo in precheckResult.recommendations.association.algorithms" :key="algo" size="small" type="success" effect="plain">
                        {{ algorithmLabel('association', algo) }}
                      </el-tag>
                    </div>
                    <div class="recommend-reason">{{ precheckResult.recommendations.association.reason }}</div>
                  </template>
                  <div v-else class="recommend-reason">{{ precheckResult.recommendations?.association?.reason || '当前数据不适合关联规则挖掘' }}</div>
                </div>
              </div>

              <!-- 序列模式推荐 -->
              <div class="recommend-item" :class="precheckResult.recommendations?.sequence?.recommended ? 'recommend-yes' : 'recommend-no'">
                <div class="recommend-header">
                  <el-icon class="recommend-icon">
                    <Check v-if="precheckResult.recommendations?.sequence?.recommended" />
                    <Close v-else />
                  </el-icon>
                  <span class="recommend-title">序列模式</span>
                  <el-tooltip
                    content="序列模式挖掘按时间顺序找出频繁出现的事件序列，如用户行为路径。常用 PrefixSpan、GSP。"
                    placement="top" effect="dark" :show-after="200"
                  >
                    <el-icon class="help-icon"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </div>
                <div class="recommend-body">
                  <template v-if="precheckResult.recommendations?.sequence?.recommended">
                    <div class="recommend-algos">
                      <el-tag v-for="algo in precheckResult.recommendations.sequence.algorithms" :key="algo" size="small" type="success" effect="plain">
                        {{ algorithmLabel('sequence', algo) }}
                      </el-tag>
                    </div>
                    <div class="recommend-reason">{{ precheckResult.recommendations.sequence.reason }}</div>
                  </template>
                  <div v-else class="recommend-reason">{{ precheckResult.recommendations?.sequence?.reason || '当前数据不适合序列模式挖掘' }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 预检失败 -->
        <div v-else class="empty-state">
          <div class="empty-icon"><el-icon :size="48"><Warning /></el-icon></div>
          <div class="empty-text">预检未完成</div>
          <el-button type="primary" size="small" @click="executePrecheck" style="margin-top:12px;">立即预检</el-button>
        </div>
      </div>

      <!-- ========== 参数配置卡片 ========== -->
      <div class="card">
        <div class="card-title">
          <el-icon><Setting /></el-icon>
          <span>参数配置</span>
          <el-tooltip
            content="切换不同挖掘任务时，已填写的参数会保留。"
            placement="top" effect="dark" :show-after="200"
          >
            <el-icon class="help-icon" style="margin-left:6px;"><QuestionFilled /></el-icon>
          </el-tooltip>
        </div>

        <el-tabs v-model="activeTab" class="mining-tabs" @tab-change="onTabChange">
          <!-- ===== 聚类分析 Tab ===== -->
          <el-tab-pane name="cluster">
            <template #label>
              <span class="tab-label">
                <el-icon><DataAnalysis /></el-icon>
                聚类分析
                <el-tooltip
                  content="将样本划分为若干簇，使同簇内样本相似度高、不同簇间相似度低。"
                  placement="top" effect="dark" :show-after="200"
                >
                  <el-icon class="help-icon"><QuestionFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>

            <!-- 算法选择 -->
            <div class="param-group">
              <div class="param-label">
                算法选择
                <el-tooltip
                  content="KMeans 适合球形簇；DBSCAN 适合任意形状并能识别噪声；层次聚类适合发现层级结构。"
                  placement="top" effect="dark" :show-after="200"
                >
                  <el-icon class="help-icon"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <el-radio-group v-model="clusterAlgorithm" @change="onClusterAlgorithmChange">
                <el-radio-button
                  v-for="algo in clusterAlgoOptions"
                  :key="algo.name"
                  :label="algo.name"
                  :class="{ 'algo-recommended': algo.recommended, 'algo-not-recommended': !algo.recommended }"
                >
                  {{ algo.display_name }}
                  <el-tag v-if="algo.recommended" size="small" type="success" effect="plain" style="margin-left: 4px;">推荐</el-tag>
                  <el-tag v-else size="small" type="info" effect="plain" style="margin-left: 4px;">慎用</el-tag>
                </el-radio-button>
              </el-radio-group>
            </div>

            <!-- 特征列选择 -->
            <div class="param-group">
              <div class="param-label">
                选择特征列
                <span style="color:#F56C6C;">*</span>
                <el-tooltip
                  content="选择用于聚类的数值特征列，至少选择一列。算法将基于这些列计算样本相似度。"
                  placement="top" effect="dark" :show-after="200"
                >
                  <el-icon class="help-icon"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <el-select
                v-model="clusterSelectedColumns"
                multiple
                filterable
                placeholder="请选择数值特征列"
                style="width: 100%;"
                :disabled="!hasDataSource"
              >
                <el-option
                  v-for="col in numericColumns"
                  :key="col"
                  :label="col"
                  :value="col"
                />
              </el-select>
              <div class="param-hint">
                <el-icon><InfoFilled /></el-icon>
                已选择 {{ clusterSelectedColumns.length }} 列，可选数值列 {{ numericColumns.length }} 列
              </div>
            </div>

            <!-- KMeans 参数 -->
            <template v-if="clusterAlgorithm === 'kmeans'">
              <div class="param-group">
                <div class="param-label">
                  簇数 K
                  <el-tooltip
                    content="将数据划分成多少个簇。值越大簇越细。可通过肘部法则或轮廓系数确定。"
                    placement="top" effect="dark" :show-after="200"
                  >
                    <el-icon class="help-icon"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </div>
                <div class="param-value-row">
                  <div class="param-value">{{ clusterParams.n_clusters }}</div>
                  <el-button
                    size="small"
                    type="primary"
                    plain
                    :loading="clusterRecommendLoading"
                    @click="recommendClusterParams"
                  >
                    <el-icon><MagicStick /></el-icon>
                    自动推荐
                  </el-button>
                </div>
                <el-slider
                  v-model="clusterParams.n_clusters"
                  :min="2"
                  :max="10"
                  :step="1"
                  :marks="{ 2: '2', 5: '5', 10: '10' }"
                />
                <div v-if="clusterRecommendation" class="recommend-info">
                  <el-icon><InfoFilled /></el-icon>
                  <span>推荐K值：{{ clusterRecommendation.n_clusters }}（以轮廓系数为主）</span>
                  <div v-if="clusterRecommendation.elbow_k && clusterRecommendation.elbow_k !== clusterRecommendation.n_clusters" style="font-size:11px;color:var(--text-secondary);margin-top:2px;margin-left:22px;">
                    肘部法则推荐K={{ clusterRecommendation.elbow_k }}，轮廓系数推荐K={{ clusterRecommendation.silhouette_k || clusterRecommendation.n_clusters }}，采用轮廓系数结果
                  </div>
                  <div v-if="clusterRecommendation.reason" style="font-size:11px;color:var(--text-secondary);margin-left:22px;">{{ clusterRecommendation.reason }}</div>
                </div>
              </div>

              <el-collapse class="advanced-settings">
                <el-collapse-item title="高级设置" name="adv">
                  <div class="param-group">
                    <div class="param-label">
                      初始化方式
                      <el-tooltip
                        content="k-means++ 通过智能选择初始中心加速收敛；random 随机选择初始中心。"
                        placement="top" effect="dark" :show-after="200"
                      >
                        <el-icon class="help-icon"><QuestionFilled /></el-icon>
                      </el-tooltip>
                    </div>
                    <el-select v-model="clusterParams.init" style="width:100%;">
                      <el-option label="k-means++" value="k-means++" />
                      <el-option label="random" value="random" />
                    </el-select>
                  </div>
                  <div class="param-group">
                    <div class="param-label">
                      最大迭代次数
                      <el-tooltip
                        content="单次运行的最多迭代次数，达到上限未收敛将提前停止。"
                        placement="top" effect="dark" :show-after="200"
                      >
                        <el-icon class="help-icon"><QuestionFilled /></el-icon>
                      </el-tooltip>
                    </div>
                    <el-input-number v-model="clusterParams.max_iter" :min="100" :max="1000" :step="50" style="width:100%;" />
                  </div>
                  <div class="param-group">
                    <div class="param-label">
                      运行次数
                      <el-tooltip
                        content="以不同初始中心重复运行的次数，取最优结果作为最终聚类。"
                        placement="top" effect="dark" :show-after="200"
                      >
                        <el-icon class="help-icon"><QuestionFilled /></el-icon>
                      </el-tooltip>
                    </div>
                    <el-input-number v-model="clusterParams.n_init" :min="1" :max="20" :step="1" style="width:100%;" />
                  </div>
                </el-collapse-item>
              </el-collapse>
            </template>

            <!-- DBSCAN 参数 -->
            <template v-if="clusterAlgorithm === 'dbscan'">
              <div class="param-group">
                <div class="param-label">
                  邻域半径 eps
                  <el-tooltip
                    content="以样本为中心的邻域半径。eps 越小，密度要求越高，产生的簇越多。"
                    placement="top" effect="dark" :show-after="200"
                  >
                    <el-icon class="help-icon"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </div>
                <div class="param-value-row">
                  <el-input-number v-model="clusterParams.eps" :min="0.01" :max="10" :step="0.1" :precision="3" style="flex:1;" />
                  <el-button
                    size="small"
                    type="primary"
                    plain
                    :loading="clusterRecommendLoading"
                    @click="recommendClusterParams"
                  >
                    <el-icon><MagicStick /></el-icon>
                    自动推荐
                  </el-button>
                </div>
              </div>
              <div class="param-group">
                <div class="param-label">
                  最小样本数 min_samples
                  <el-tooltip
                    content="核心点邻域内最少样本数，决定簇的密度门槛。常取 2 倍特征数。"
                    placement="top" effect="dark" :show-after="200"
                  >
                    <el-icon class="help-icon"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </div>
                <div class="param-value-row">
                  <el-input-number v-model="clusterParams.min_samples" :min="1" :max="100" :step="1" style="flex:1;" />
                  <el-button
                    size="small"
                    type="primary"
                    plain
                    :loading="clusterRecommendLoading"
                    @click="recommendClusterParams"
                  >
                    <el-icon><MagicStick /></el-icon>
                    自动推荐
                  </el-button>
                </div>
              </div>
              <div v-if="clusterRecommendation" class="recommend-info">
                <el-icon><InfoFilled /></el-icon>
                <span>{{ clusterRecommendation.reason }}</span>
              </div>

              <el-collapse class="advanced-settings">
                <el-collapse-item title="高级设置" name="adv">
                  <div class="param-group">
                    <div class="param-label">
                      距离度量
                      <el-tooltip
                        content="euclidean 欧氏距离；manhattan 曼哈顿距离；cosine 余弦相似度距离。"
                        placement="top" effect="dark" :show-after="200"
                      >
                        <el-icon class="help-icon"><QuestionFilled /></el-icon>
                      </el-tooltip>
                    </div>
                    <el-select v-model="clusterParams.metric" style="width:100%;">
                      <el-option label="euclidean (欧氏)" value="euclidean" />
                      <el-option label="manhattan (曼哈顿)" value="manhattan" />
                      <el-option label="cosine (余弦)" value="cosine" />
                    </el-select>
                  </div>
                </el-collapse-item>
              </el-collapse>
            </template>

            <!-- 层次聚类参数 -->
            <template v-if="clusterAlgorithm === 'hierarchical'">
              <div class="param-group">
                <div class="param-label">
                  簇数
                  <el-tooltip
                    content="从层次树自顶向下切分得到的目标簇数。"
                    placement="top" effect="dark" :show-after="200"
                  >
                    <el-icon class="help-icon"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </div>
                <div class="param-value-row">
                  <div class="param-value">{{ clusterParams.n_clusters }}</div>
                  <el-button
                    size="small"
                    type="primary"
                    plain
                    :loading="clusterRecommendLoading"
                    @click="recommendClusterParams"
                  >
                    <el-icon><MagicStick /></el-icon>
                    自动推荐
                  </el-button>
                </div>
                <el-slider
                  v-model="clusterParams.n_clusters"
                  :min="2"
                  :max="10"
                  :step="1"
                  :marks="{ 2: '2', 5: '5', 10: '10' }"
                />
                <div v-if="clusterRecommendation" class="recommend-info">
                  <el-icon><InfoFilled /></el-icon>
                  <span>推荐K值：{{ clusterRecommendation.n_clusters }}（以轮廓系数为主）</span>
                  <div v-if="clusterRecommendation.elbow_k && clusterRecommendation.elbow_k !== clusterRecommendation.n_clusters" style="font-size:11px;color:var(--text-secondary);margin-top:2px;margin-left:22px;">
                    肘部法则推荐K={{ clusterRecommendation.elbow_k }}，轮廓系数推荐K={{ clusterRecommendation.silhouette_k || clusterRecommendation.n_clusters }}，采用轮廓系数结果
                  </div>
                  <div v-if="clusterRecommendation.reason" style="font-size:11px;color:var(--text-secondary);margin-left:22px;">{{ clusterRecommendation.reason }}</div>
                </div>
              </div>

              <el-collapse class="advanced-settings">
                <el-collapse-item title="高级设置" name="adv">
                  <div class="param-group">
                    <div class="param-label">
                      链接方式
                      <el-tooltip
                        content="ward 最小化簇内方差；average 平均距离；complete 最大距离；single 最近距离。"
                        placement="top" effect="dark" :show-after="200"
                      >
                        <el-icon class="help-icon"><QuestionFilled /></el-icon>
                      </el-tooltip>
                    </div>
                    <el-select v-model="clusterParams.linkage" style="width:100%;">
                      <el-option label="ward (方差最小)" value="ward" />
                      <el-option label="average (平均距离)" value="average" />
                      <el-option label="complete (最大距离)" value="complete" />
                      <el-option label="single (最近距离)" value="single" />
                    </el-select>
                  </div>
                </el-collapse-item>
              </el-collapse>
            </template>
          </el-tab-pane>

          <!-- ===== 关联规则 Tab ===== -->
          <el-tab-pane name="association">
            <template #label>
              <span class="tab-label">
                <el-icon><Connection /></el-icon>
                关联规则
                <el-tooltip
                  content="从事务数据中挖掘 X 推出 Y 的关联模式，常用于购物篮分析。"
                  placement="top" effect="dark" :show-after="200"
                >
                  <el-icon class="help-icon"><QuestionFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>

            <!-- 算法选择 -->
            <div class="param-group">
              <div class="param-label">
                算法选择
                <el-tooltip
                  content="Apriori 通过候选集生成与剪枝挖掘频繁项集，易于理解；FP-Growth 基于 FP 树结构，通常更快。"
                  placement="top" effect="dark" :show-after="200"
                >
                  <el-icon class="help-icon"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <el-radio-group v-model="assocAlgorithm" @change="onAssocAlgorithmChange">
                <el-radio-button
                  v-for="algo in assocAlgoOptions"
                  :key="algo.name"
                  :label="algo.name"
                  :class="{ 'algo-recommended': algo.recommended, 'algo-not-recommended': !algo.recommended }"
                >
                  {{ algo.display_name }}
                  <el-tag v-if="algo.recommended" size="small" type="success" effect="plain" style="margin-left: 4px;">推荐</el-tag>
                  <el-tag v-else size="small" type="info" effect="plain" style="margin-left: 4px;">慎用</el-tag>
                </el-radio-button>
              </el-radio-group>
            </div>

            <!-- 数据格式 -->
            <div class="param-group">
              <div class="param-label">
                数据格式
                <el-tooltip
                  placement="top" effect="dark" :show-after="200"
                >
                  <template #content>
                    <div style="max-width: 260px; line-height: 1.6;">
                      <div><b>购物篮格式（推荐）</b>：每行一个事务项，按事务标识列分组，结果有明确业务意义。</div>
                      <div style="margin-top: 6px;"><b>自动二值化</b>：一键运行，无需选列，但容易产生结构性关联（置信度虚高），业务价值有限，仅适合初步探索。</div>
                    </div>
                  </template>
                  <el-icon class="help-icon"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <el-radio-group v-model="assocDataFormat">
                <el-radio label="basket">购物篮格式（事务ID + 项列）</el-radio>
                <el-radio label="binary">自动二值化（无需选列）</el-radio>
              </el-radio-group>
            </div>

            <!-- 购物篮格式需要选列 -->
            <template v-if="assocDataFormat === 'basket'">
              <div class="param-group">
                <div class="param-label">
                  事务标识列
                  <span style="color:#F56C6C;">*</span>
                  <el-tooltip
                    content="用于分组的标识列，相同标识的记录属于同一事务，如订单号、用户ID。"
                    placement="top" effect="dark" :show-after="200"
                  >
                    <el-icon class="help-icon"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </div>
                <el-select
                  v-model="assocTidColumn"
                  placeholder="请选择事务标识列"
                  style="width: 100%;"
                  :disabled="!hasDataSource"
                  filterable
                >
                  <el-option
                    v-for="col in allColumns"
                    :key="col"
                    :label="col"
                    :value="col"
                  />
                </el-select>
              </div>
              <div class="param-group">
                <div class="param-label">
                  项列
                  <span style="color:#F56C6C;">*</span>
                  <el-tooltip
                    content="要挖掘关联关系的项所在的列，如商品名称、服务项目、症状标签等。"
                    placement="top" effect="dark" :show-after="200"
                  >
                    <el-icon class="help-icon"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </div>
                <el-select
                  v-model="assocItemColumn"
                  placeholder="请选择项列"
                  style="width: 100%;"
                  :disabled="!hasDataSource"
                  filterable
                >
                  <el-option
                    v-for="col in allColumns"
                    :key="col"
                    :label="col"
                    :value="col"
                  />
                </el-select>
              </div>
            </template>

            <!-- 最小支持度 -->
            <div class="param-group">
              <div class="param-label">
                最小支持度
                <el-tooltip
                  content="项集在数据中出现的频率下限。支持度太低会产生大量无意义规则；太高可能漏掉有价值的弱关联。"
                  placement="top" effect="dark" :show-after="200"
                >
                  <el-icon class="help-icon"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <div class="param-value-row">
                <div class="param-value">{{ assocParams.min_support }}</div>
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :loading="assocRecommendLoading"
                  @click="recommendAssocParams"
                >
                  <el-icon><MagicStick /></el-icon>
                  自动推荐
                </el-button>
              </div>
              <el-slider
                v-model="assocParams.min_support"
                :min="0.01"
                :max="1.0"
                :step="0.01"
                :marks="{ 0.01: '1%', 0.1: '10%', 0.5: '50%', 1.0: '100%' }"
              />
              <div v-if="assocRecommendation" class="recommend-info">
                <el-icon><InfoFilled /></el-icon>
                <span>推荐值：{{ assocRecommendation.min_support }}。{{ assocRecommendation.reason }}</span>
              </div>
            </div>

            <!-- 最小置信度 -->
            <div class="param-group">
              <div class="param-label">
                最小置信度
                <el-tooltip
                  content="在出现 X 的事务中，Y 也同时出现的概率下限。反映规则可靠程度，过高会导致规则过少。"
                  placement="top" effect="dark" :show-after="200"
                >
                  <el-icon class="help-icon"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <div class="param-value">{{ assocParams.min_confidence }}</div>
              <el-slider
                v-model="assocParams.min_confidence"
                :min="0.5"
                :max="1.0"
                :step="0.01"
                :marks="{ 0.5: '50%', 0.8: '80%', 1.0: '100%' }"
              />
            </div>

            <!-- 高级设置 -->
            <el-collapse class="advanced-settings">
              <el-collapse-item title="高级设置" name="adv">
                <div class="param-group">
                  <div class="param-label">
                    最小提升度
                    <el-tooltip
                      content="提升度衡量 X 对 Y 出现的提升作用，大于 1 表示正相关。1.0 表示相互独立。"
                      placement="top" effect="dark" :show-after="200"
                    >
                      <el-icon class="help-icon"><QuestionFilled /></el-icon>
                    </el-tooltip>
                  </div>
                  <el-input-number v-model="assocParams.min_lift" :min="1.0" :max="5.0" :step="0.1" :precision="2" style="width:100%;" />
                </div>
                <div class="param-group">
                  <div class="param-label">
                    最大项集长度
                    <el-tooltip
                      content="限制频繁项集的最大项数，避免组合爆炸。设为 0 表示不限制。"
                      placement="top" effect="dark" :show-after="200"
                    >
                      <el-icon class="help-icon"><QuestionFilled /></el-icon>
                    </el-tooltip>
                  </div>
                  <div class="flex-center gap-sm">
                    <el-input-number v-model="assocParams.max_itemset" :min="0" :max="10" :step="1" style="flex:1;" />
                    <el-tag size="small" type="info">0 表示不限制</el-tag>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </el-tab-pane>

          <!-- ===== 序列模式 Tab ===== -->
          <el-tab-pane name="sequence">
            <template #label>
              <span class="tab-label">
                <el-icon><TrendCharts /></el-icon>
                序列模式
                <el-tooltip
                  content="按时间顺序挖掘频繁出现的事件序列，如用户行为路径、操作序列。"
                  placement="top" effect="dark" :show-after="200"
                >
                  <el-icon class="help-icon"><QuestionFilled /></el-icon>
                </el-tooltip>
              </span>
            </template>

            <!-- 算法选择 -->
            <div class="param-group">
              <div class="param-label">
                算法选择
                <el-tooltip
                  content="PrefixSpan 通过投影数据库递归挖掘序列模式；GSP 通过候选生成与剪枝，原理类似 Apriori。"
                  placement="top" effect="dark" :show-after="200"
                >
                  <el-icon class="help-icon"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <el-radio-group v-model="seqAlgorithm" @change="onSeqAlgorithmChange">
                <el-radio-button
                  v-for="algo in seqAlgoOptions"
                  :key="algo.name"
                  :label="algo.name"
                  :class="{ 'algo-recommended': algo.recommended, 'algo-not-recommended': !algo.recommended }"
                >
                  {{ algo.display_name }}
                  <el-tag v-if="algo.recommended" size="small" type="success" effect="plain" style="margin-left: 4px;">推荐</el-tag>
                  <el-tag v-else size="small" type="info" effect="plain" style="margin-left: 4px;">慎用</el-tag>
                </el-radio-button>
              </el-radio-group>
            </div>

            <!-- 列配置 -->
            <div class="param-group">
              <div class="param-label">
                序列ID列
                <span style="color:#F56C6C;">*</span>
                <el-tooltip
                  content="标识每个独立序列的列，如用户ID、会话ID。相同ID的事件按时间排序构成一个序列。"
                  placement="top" effect="dark" :show-after="200"
                >
                  <el-icon class="help-icon"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <el-select
                v-model="seqColumns.seq_id_column"
                placeholder="请选择序列ID列（自动检测含 id/user 的列）"
                style="width: 100%;"
                :disabled="!hasDataSource"
              filterable
            >
              <el-option
                v-for="col in allColumns"
                :key="col"
                :label="col + (seqAutoDetected.seq_id_column === col ? '（已自动识别）' : '')"
                :value="col"
              />
            </el-select>
          </div>
          <div class="param-group">
            <div class="param-label">
              时间列
                <span style="color:#F56C6C;">*</span>
                <el-tooltip
                  content="用于在序列内排序事件的时间列，如时间戳、日期。"
                  placement="top" effect="dark" :show-after="200"
                >
                  <el-icon class="help-icon"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <el-select
                v-model="seqColumns.time_column"
                placeholder="请选择时间列（自动检测 datetime 列）"
                style="width: 100%;"
                :disabled="!hasDataSource"
                filterable
              >
                <el-option
                  v-for="col in datetimeColumns"
                  :key="col"
                  :label="col + (seqAutoDetected.time_column === col ? '（已自动识别）' : '')"
                  :value="col"
                />
              </el-select>
              <div v-if="datetimeColumns.length === 0" class="param-hint">
                <el-icon><Warning /></el-icon>
                未检测到时间列，可手动指定任意可排序的列
              </div>
            </div>
            <div class="param-group">
              <div class="param-label">
                事件列
                <span style="color:#F56C6C;">*</span>
                <el-tooltip
                  content="构成序列事件的实际内容列，如页面名称、操作类型。建议选择类别列。"
                  placement="top" effect="dark" :show-after="200"
                >
                  <el-icon class="help-icon"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <el-select
                v-model="seqColumns.event_column"
                placeholder="请选择事件列"
                style="width: 100%;"
                :disabled="!hasDataSource"
                filterable
              >
                <el-option
                  v-for="col in categoricalColumns"
                  :key="col"
                  :label="col"
                  :value="col"
                />
              </el-select>
            </div>

            <!-- 最小支持度 -->
            <div class="param-group">
              <div class="param-label">
                最小支持度
                <el-tooltip
                  content="序列模式在所有序列中出现的频率下限。值越小挖掘出的模式越多，但可能包含噪声。"
                  placement="top" effect="dark" :show-after="200"
                >
                  <el-icon class="help-icon"><QuestionFilled /></el-icon>
                </el-tooltip>
              </div>
              <div class="param-value-row">
                <div class="param-value">{{ seqParams.min_support }}</div>
                <el-button
                  size="small"
                  type="primary"
                  plain
                  :loading="seqRecommendLoading"
                  @click="recommendSeqParams"
                >
                  <el-icon><MagicStick /></el-icon>
                  自动推荐
                </el-button>
              </div>
              <el-slider
                v-model="seqParams.min_support"
                :min="0.01"
                :max="1.0"
                :step="0.01"
                :marks="{ 0.01: '1%', 0.1: '10%', 0.5: '50%', 1.0: '100%' }"
              />
              <div v-if="seqRecommendation" class="recommend-info">
                <el-icon><InfoFilled /></el-icon>
                <span>推荐值：{{ seqRecommendation.min_support }}。{{ seqRecommendation.reason }}</span>
              </div>
            </div>

            <!-- 高级设置 -->
            <el-collapse class="advanced-settings">
              <el-collapse-item title="高级设置" name="adv">
                <div class="param-group">
                  <div class="param-label">
                    最大序列长度
                    <el-tooltip
                      content="限制挖掘出的序列模式的最大长度，避免组合爆炸。设为 0 表示不限制。"
                      placement="top" effect="dark" :show-after="200"
                    >
                      <el-icon class="help-icon"><QuestionFilled /></el-icon>
                    </el-tooltip>
                  </div>
                  <div class="param-value-row">
                    <div class="param-value">{{ seqParams.max_len }}</div>
                    <el-tag size="small" type="info">0 表示不限制</el-tag>
                  </div>
                  <el-input-number
                    v-model="seqParams.max_len"
                    :min="0"
                    :max="20"
                    :step="1"
                    style="width:100%;"
                  />
                </div>
              </el-collapse-item>
            </el-collapse>
          </el-tab-pane>
        </el-tabs>

        <!-- 执行按钮 -->
        <div class="execute-section">
          <el-button
            type="primary"
            size="large"
            @click="executeMining"
            :loading="miningLoading"
            :disabled="!canExecute"
            style="width: 100%;"
          >
            <el-icon v-if="!miningLoading"><Cpu /></el-icon>
            {{ miningLoading ? '分析中...' : (canExecute ? '执行分析' : blockReason || '无法执行') }}
          </el-button>
          <div v-if="!canExecute && blockReason" class="block-reason">
            <el-icon><Warning /></el-icon>
            <span>{{ blockReason }}</span>
          </div>
        </div>
      </div>

      <!-- ========== 结果展示卡片 ========== -->
      <div class="card">
        <div class="card-title">
          <el-icon><TrendCharts /></el-icon>
          <span>结果展示</span>
        </div>

        <!-- 聚类结果 -->
        <div v-if="activeTab === 'cluster' && clusterResult">
          <!-- 统计指标 -->
          <div class="stats-grid mb-md">
            <div class="stat-card">
              <div class="stat-value">{{ algorithmLabel('cluster', clusterResult.algorithm) }}</div>
              <div class="stat-label">算法</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ clusterResult.n_clusters ?? '-' }}</div>
              <div class="stat-label">簇数</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ clusterResult.algorithm === 'dbscan' ? formatPercent(clusterResult.noise_percentage) : formatScore(clusterResult.silhouette_score) }}</div>
              <div class="stat-label">{{ clusterResult.algorithm === 'dbscan' ? '噪声比例' : '轮廓系数' }}</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ clusterResult.sample_count ?? '-' }}</div>
              <div class="stat-label">样本数</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ clusterResult.features_used?.length ?? '-' }}</div>
              <div class="stat-label">特征数</div>
            </div>
            <div v-if="clusterResult.algorithm === 'dbscan'" class="stat-card">
              <div class="stat-value">{{ clusterResult.noise_count ?? 0 }}</div>
              <div class="stat-label">噪声点数</div>
            </div>
          </div>

          <!-- 推荐参数信息 -->
          <el-alert
            v-if="clusterResult.recommended_params && clusterResult.used_recommendation"
            type="info"
            :closable="false"
            class="mb-md"
            show-icon
          >
            <template #title>本次分析使用了推荐的参数</template>
            <div style="font-size:12px;line-height:1.7;">
              <div v-if="clusterResult.recommended_params.n_clusters !== undefined">
                推荐簇数：{{ clusterResult.recommended_params.n_clusters }}
              </div>
              <div v-if="clusterResult.recommended_params.eps !== undefined">
                推荐邻域半径 eps：{{ clusterResult.recommended_params.eps }}
              </div>
              <div v-if="clusterResult.recommended_params.min_samples !== undefined">
                推荐最小样本数：{{ clusterResult.recommended_params.min_samples }}
              </div>
              <div v-if="clusterResult.recommended_params.elbow_k && clusterResult.recommended_params.elbow_k !== clusterResult.recommended_params.n_clusters" style="color:var(--text-secondary);">
                肘部法则推荐 K={{ clusterResult.recommended_params.elbow_k }}（辅助参考）
              </div>
              <div v-if="clusterResult.recommended_params.reason" style="color:var(--text-secondary);">
                {{ clusterResult.recommended_params.reason }}
              </div>
            </div>
          </el-alert>

          <!-- 质量评估 -->
          <div v-if="clusterResult.quality_assessment && clusterResult.quality_assessment.length > 0" class="mb-md">
            <el-alert
              v-for="(item, index) in clusterResult.quality_assessment"
              :key="index"
              :type="item.level === 'warning' ? 'warning' : 'info'"
              :closable="false"
              show-icon
            >
              <template #title>结果质量评估</template>
              <div style="font-size:12px;">{{ item.message }}</div>
            </el-alert>
          </div>

          <!-- 可视化 Tab -->
          <el-tabs v-model="clusterResultTab" class="result-tabs" @tab-change="onClusterResultTabChange">
            <el-tab-pane label="散点图" name="scatter">
              <div v-if="clusterResult.projection_2d && clusterResult.projection_2d.length > 0" ref="clusterChartRef" class="chart-area"></div>
              <div v-else class="empty-state">
                <div class="empty-icon"><el-icon :size="48"><TrendCharts /></el-icon></div>
                <div class="empty-text">本次结果未提供 2D 投影数据，无法绘制散点图</div>
              </div>
            </el-tab-pane>
            <el-tab-pane label="数据预览" name="data">
              <el-table v-if="clusterResult.preview_data && clusterResult.preview_data.rows && clusterResult.preview_data.rows.length" :data="clusterResult.preview_data.rows" border size="small" max-height="400">
                <el-table-column
                  v-for="col in clusterResult.preview_data.columns"
                  :key="col"
                  :prop="col"
                  :label="col"
                  min-width="100"
                  show-overflow-tooltip
                />
              </el-table>
              <div v-else class="empty-state">
                <div class="empty-text">未提供数据预览</div>
              </div>
            </el-tab-pane>
            <el-tab-pane label="评估指标" name="metrics">
              <!-- DBSCAN：显示噪声统计 -->
              <div v-if="clusterResult.algorithm === 'dbscan'" class="mb-md">
                <h4 class="section-subtitle">噪声统计</h4>
                <div class="metric-row">
                  <span class="metric-label">噪声点数</span>
                  <span class="metric-value">{{ clusterResult.noise_count ?? 0 }}</span>
                </div>
                <div class="metric-row">
                  <span class="metric-label">噪声比例</span>
                  <span class="metric-value">{{ formatPercent(clusterResult.noise_percentage) }}</span>
                </div>
                <div class="metric-row">
                  <span class="metric-label">有效簇数</span>
                  <span class="metric-value">{{ clusterResult.n_clusters ?? '-' }}</span>
                  <el-tooltip
                    content="去除噪声点后的实际聚类簇数"
                    placement="top" effect="dark" :show-after="200"
                  >
                    <el-icon class="help-icon"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </div>
              </div>
              <!-- 其他算法：显示轮廓系数 -->
              <div v-else class="mb-md">
                <h4 class="section-subtitle">轮廓系数</h4>
                <div class="metric-row">
                  <span class="metric-label">轮廓系数</span>
                  <span class="metric-value">{{ formatScore(clusterResult.silhouette_score) }}</span>
                  <el-tooltip
                    content="范围 [-1, 1]，越接近 1 表示簇内紧凑、簇间分离，聚类效果越好。"
                    placement="top" effect="dark" :show-after="200"
                  >
                    <el-icon class="help-icon"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </div>
              </div>
              <div v-if="clusterResult.cluster_stats && clusterResult.cluster_stats.length > 0">
                <h4 class="section-subtitle">各簇统计</h4>
                <el-table :data="clusterResult.cluster_stats" border size="small" max-height="300">
                  <el-table-column prop="cluster" label="簇号" width="100" align="center">
                    <template #default="{ row }">
                      <el-tag v-if="row.cluster === -1 || row.cluster === '-1'" type="info" size="small">噪声</el-tag>
                      <span v-else>{{ row.cluster }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column prop="count" label="样本数" width="120" align="center" />
                  <el-table-column label="占比" width="120" align="center">
                    <template #default="{ row }">
                      {{ row.percentage !== undefined ? Number(row.percentage).toFixed(2) + '%' : '-' }}
                    </template>
                  </el-table-column>
                </el-table>
              </div>
            </el-tab-pane>
          </el-tabs>

          <!-- 保存到数据管理 -->
          <div class="save-section mt-md">
            <el-button
              v-if="!clusterResult.saved"
              type="primary"
              @click="saveClusterResult"
              :loading="clusterSaveLoading"
              icon="Download"
            >
              保存到数据管理
            </el-button>
            <el-alert
              v-else
              type="success"
              :closable="false"
              show-icon
            >
              <template #title>聚类结果已保存到数据集</template>
              <div style="font-size:12px;">结果中新增 cluster 列，可在数据管理模块查看与导出。</div>
            </el-alert>
          </div>
        </div>

        <!-- 关联规则结果 -->
        <div v-else-if="activeTab === 'association' && assocResult">
          <!-- 统计指标 -->
          <div class="stats-grid mb-md">
            <div class="stat-card">
              <div class="stat-value">{{ algorithmLabel('association', assocResult.algorithm) }}</div>
              <div class="stat-label">算法</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ assocResult.total_rules ?? 0 }}</div>
              <div class="stat-label">规则数量</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ assocResult.min_support ?? '-' }}</div>
              <div class="stat-label">最小支持度</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ assocResult.min_confidence ?? '-' }}</div>
              <div class="stat-label">最小置信度</div>
            </div>
          </div>

          <!-- 推荐参数信息 -->
          <el-alert
            v-if="assocResult.recommended_params && assocResult.used_recommendation"
            type="info"
            :closable="false"
            class="mb-md"
            show-icon
          >
            <template #title>本次分析使用了推荐的参数</template>
            <div style="font-size:12px;line-height:1.7;">
              <div v-if="assocResult.recommended_params.min_support !== undefined">
                推荐最小支持度：{{ assocResult.recommended_params.min_support }}
              </div>
              <div v-if="assocResult.recommended_params.min_confidence !== undefined">
                推荐最小置信度：{{ assocResult.recommended_params.min_confidence }}
              </div>
              <div v-if="assocResult.recommended_params.reason" style="color:var(--text-secondary);">
                {{ assocResult.recommended_params.reason }}
              </div>
            </div>
          </el-alert>

          <!-- 质量评估 -->
          <div v-if="assocResult.quality_assessment && assocResult.quality_assessment.length > 0" class="mb-md">
            <el-alert
              v-for="(item, index) in assocResult.quality_assessment"
              :key="index"
              :type="item.level === 'warning' ? 'warning' : 'info'"
              :closable="false"
              show-icon
            >
              <template #title>结果质量评估</template>
              <div style="font-size:12px;">{{ item.message }}</div>
            </el-alert>
          </div>

          <!-- 可视化 Tab -->
          <el-tabs v-model="assocResultTab" class="result-tabs">
            <el-tab-pane label="规则列表" name="rules">
              <el-table v-if="assocResult.rules && assocResult.rules.length > 0" :data="paginatedAssocRules" border size="small" max-height="400">
                <el-table-column label="前项" min-width="180" show-overflow-tooltip>
                  <template #default="{ row }">
                    {{ formatItemList(row.antecedent) }}
                  </template>
                </el-table-column>
                <el-table-column label="后项" min-width="180" show-overflow-tooltip>
                  <template #default="{ row }">
                    {{ formatItemList(row.consequent) }}
                  </template>
                </el-table-column>
                <el-table-column label="支持度" width="110" align="center">
                  <template #default="{ row }">
                    {{ formatScore(row.support) }}
                  </template>
                </el-table-column>
                <el-table-column label="置信度" width="110" align="center">
                  <template #default="{ row }">
                    {{ formatScore(row.confidence) }}
                  </template>
                </el-table-column>
                <el-table-column label="提升度" width="110" align="center">
                  <template #default="{ row }">
                    <el-tag :type="row.lift > 1 ? 'success' : (row.lift < 1 ? 'danger' : 'info')" size="small">
                      {{ formatScore(row.lift) }}
                    </el-tag>
                  </template>
                </el-table-column>
              </el-table>
              <div v-if="assocResult.rules && assocResult.rules.length > 0" class="flex-center mt-sm" style="justify-content: flex-end;">
                <el-pagination
                  v-model:current-page="assocPage"
                  v-model:page-size="assocPageSize"
                  :page-sizes="[20, 50, 100]"
                  :total="assocResult.rules.length"
                  layout="total, sizes, prev, pager, next, jumper"
                  small background
                />
              </div>
              <div v-else class="empty-state">
                <div class="empty-icon"><el-icon :size="48"><Warning /></el-icon></div>
                <div class="empty-text">未找到满足条件的关联规则</div>
                <div class="empty-hint">可尝试调低最小支持度或最小置信度后重试</div>
              </div>
            </el-tab-pane>
            <el-tab-pane label="统计" name="stats">
              <div class="stats-grid">
                <div class="stat-card">
                  <div class="stat-value">{{ assocResult.total_rules ?? 0 }}</div>
                  <div class="stat-label">规则总数</div>
                </div>
                <div class="stat-card">
                  <div class="stat-value">{{ formatScore(assocStats.avg_support) }}</div>
                  <div class="stat-label">平均支持度</div>
                </div>
                <div class="stat-card">
                  <div class="stat-value">{{ formatScore(assocStats.avg_confidence) }}</div>
                  <div class="stat-label">平均置信度</div>
                </div>
                <div class="stat-card">
                  <div class="stat-value">{{ formatScore(assocStats.avg_lift) }}</div>
                  <div class="stat-label">平均提升度</div>
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>

          <!-- 保存到数据管理 -->
          <div class="save-section mt-md">
            <el-button
              v-if="!assocResult.saved"
              type="primary"
              @click="saveAssocResult"
              :loading="assocSaveLoading"
              icon="Download"
            >
              保存到数据管理
            </el-button>
            <el-alert
              v-else
              type="success"
              :closable="false"
              show-icon
            >
              <template #title>关联规则结果已保存</template>
              <div style="font-size:12px;">规则详情可在数据管理模块查看与导出。</div>
            </el-alert>
          </div>
        </div>

        <!-- 序列模式结果 -->
        <div v-else-if="activeTab === 'sequence' && seqResult">
          <!-- 统计指标 -->
          <div class="stats-grid mb-md">
            <div class="stat-card">
              <div class="stat-value">{{ algorithmLabel('sequence', seqResult.algorithm) }}</div>
              <div class="stat-label">算法</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ seqResult.total_patterns ?? 0 }}</div>
              <div class="stat-label">模式数量</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ seqResult.n_sequences ?? '-' }}</div>
              <div class="stat-label">序列数</div>
            </div>
            <div class="stat-card">
              <div class="stat-value">{{ seqResult.min_support ?? '-' }}</div>
              <div class="stat-label">最小支持度</div>
            </div>
          </div>

          <!-- 推荐参数信息 -->
          <el-alert
            v-if="seqResult.recommended_params && seqResult.used_recommendation"
            type="info"
            :closable="false"
            class="mb-md"
            show-icon
          >
            <template #title>本次分析使用了推荐的参数</template>
            <div style="font-size:12px;line-height:1.7;">
              <div v-if="seqResult.recommended_params.min_support !== undefined">
                推荐最小支持度：{{ seqResult.recommended_params.min_support }}
              </div>
              <div v-if="seqResult.recommended_params.reason" style="color:var(--text-secondary);">
                {{ seqResult.recommended_params.reason }}
              </div>
            </div>
          </el-alert>

          <!-- 质量评估 -->
          <div v-if="seqResult.quality_assessment && seqResult.quality_assessment.length > 0" class="mb-md">
            <el-alert
              v-for="(item, index) in seqResult.quality_assessment"
              :key="index"
              :type="item.level === 'warning' ? 'warning' : 'info'"
              :closable="false"
              show-icon
            >
              <template #title>结果质量评估</template>
              <div style="font-size:12px;">{{ item.message }}</div>
            </el-alert>
          </div>

          <!-- 可视化 Tab -->
          <el-tabs v-model="seqResultTab" class="result-tabs">
            <el-tab-pane label="模式列表" name="patterns">
              <el-table v-if="seqResult.top_patterns && seqResult.top_patterns.length > 0" :data="paginatedSeqPatterns" border size="small" max-height="400">
                <el-table-column label="序列" min-width="320" show-overflow-tooltip>
                  <template #default="{ row }">
                    <el-tag v-for="(item, idx) in formatSequence(row.sequence)" :key="idx" size="small" class="seq-tag">
                      {{ item }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="支持度" width="140" align="center">
                  <template #default="{ row }">
                    {{ formatScore(row.support) }}
                  </template>
                </el-table-column>
              </el-table>
              <div v-if="seqResult.top_patterns && seqResult.top_patterns.length > 0" class="flex-center mt-sm" style="justify-content: flex-end;">
                <el-pagination
                  v-model:current-page="seqPage"
                  v-model:page-size="seqPageSize"
                  :page-sizes="[20, 50, 100]"
                  :total="seqResult.top_patterns.length"
                  layout="total, sizes, prev, pager, next, jumper"
                  small background
                />
              </div>
              <div v-else class="empty-state">
                <div class="empty-icon"><el-icon :size="48"><Warning /></el-icon></div>
                <div class="empty-text">未找到满足条件的序列模式</div>
                <div class="empty-hint">可尝试调低最小支持度后重试</div>
              </div>
            </el-tab-pane>
            <el-tab-pane label="统计" name="stats">
              <div class="stats-grid">
                <div class="stat-card">
                  <div class="stat-value">{{ seqResult.total_patterns ?? 0 }}</div>
                  <div class="stat-label">模式总数</div>
                </div>
                <div class="stat-card">
                  <div class="stat-value">{{ formatScore(seqStats.avg_support) }}</div>
                  <div class="stat-label">平均支持度</div>
                </div>
                <div class="stat-card">
                  <div class="stat-value">{{ seqStats.max_length }}</div>
                  <div class="stat-label">最长模式长度</div>
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>

          <!-- 保存到数据管理 -->
          <div class="save-section mt-md">
            <el-button
              v-if="!seqResult.saved"
              type="primary"
              @click="saveSeqResult"
              :loading="seqSaveLoading"
              icon="Download"
            >
              保存到数据管理
            </el-button>
            <el-alert
              v-else
              type="success"
              :closable="false"
              show-icon
            >
              <template #title>序列模式结果已保存</template>
              <div style="font-size:12px;">模式详情可在数据管理模块查看与导出。</div>
            </el-alert>
          </div>
        </div>

        <!-- 无结果提示 -->
        <div v-else class="empty-state">
          <div class="empty-icon"><el-icon :size="48"><Search /></el-icon></div>
          <div class="empty-text">请选择数据集并配置参数后，点击"执行分析"</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, watch, onMounted, onActivated, onBeforeUnmount, nextTick, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Refresh, UploadFilled, Setting, Cpu, DataAnalysis, Connection,
  Upload, Folder, DataLine, QuestionFilled, InfoFilled, Search,
  TrendCharts, Check, Close, Warning, MagicStick, Loading
} from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import {
  uploadMiningFile,
  fetchMiningRawData,
  runDataMiningClustering,
  runDataMiningAssociationRules,
  runDataMiningSequence,
  precheckMiningData,
  recommendMiningParams,
  fetchRemoteColumnPool,
  fetchTaskRecords,
  getTaskProgress,
  fetchDatasetData
} from '../api/index.js'
import { addTask } from '../stores/taskPanel.js'
import DataSourceSelector from '../components/DataSourceSelector.vue'
import DataPreview from '../components/DataPreview.vue'

// DataSourceSelector组件引用，用于上传后调用reload刷新下拉框
const dataSourceSelectorRef = ref(null)

// ====== 算法标签映射 ======
const algorithmLabels = {
  cluster: { kmeans: 'KMeans', dbscan: 'DBSCAN', hierarchical: '层次聚类' },
  association: { apriori: 'Apriori', fpgrowth: 'FP-Growth' },
  sequence: { prefixspan: 'PrefixSpan', gsp: 'GSP' }
}

function algorithmLabel(type, algo) {
  if (!algo) return '-'
  return algorithmLabels[type]?.[algo] || algo
}

// ====== 上传相关 ======
const uploadFile = ref(null)
const uploadLoading = ref(false)

// ====== 数据集列表 ======
const miningRawData = ref([])
const datasetLoading = ref(false)
const datasetId = ref(null)
const currentDataset = ref(null)
// 最近一次已加载/切换的数据集ID，用于判断 keep-alive 重新激活时数据集是否变化，
// 变化才清空结果，未变化则保留上次分析结果（解决切换模块回来结果消失的问题）
const lastLoadedDatasetId = ref(null)

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

// 获取当前数据源标识（本地：dataset id；远程：connection_id::table_name）
// 用于异步/同步结果返回时校验数据源一致性，避免等待期间切换数据源导致结果串显
function getSourceKey() {
  if (sourceConfig.value.mode === 'remote') {
    const r = sourceConfig.value.remote
    return (r?.connection_id && r?.table_name) ? `remote:${r.connection_id}::${r.table_name}` : null
  }
  return currentDataset.value?.id ? `local:${currentDataset.value.id}` : null
}

// 数据源选择回调
async function onSourceSelect(config) {
  if (config.mode === 'local') {
    const newId = config.datasetId || null
    const idChanged = newId !== datasetId.value
    // 设置 datasetId，确保预检等依赖 datasetId.value 的地方拿到正确值
    // watch(datasetId) 会在值变化时自动触发 onDatasetChange
    datasetId.value = newId
    if (!newId) {
      currentDataset.value = null
    }
    sourceConfig.value = { mode: 'local', datasetId: config.datasetId, remote: null }
    // 值未变化时（如重复选择同一数据集），手动触发以确保状态刷新
    if (newId && !idChanged) {
      onDatasetChange(newId)
    }
    // 选择数据集后恢复该数据集最近一次成功的分析结果
    // （异步执行：watch(datasetId) 触发的清空先发生，恢复结果后回填）
    restoreLatestResults()
    loadPreview()
  } else if (config.mode === 'remote') {
    // 远程模式：清空本地数据集，加载远程表列信息并触发预检
    datasetId.value = null
    lastLoadedDatasetId.value = null
    currentDataset.value = null
    sourceConfig.value = { mode: 'remote', datasetId: null, remote: config.remote }
    // 清空旧列信息和预检结果
    clusterResult.value = null
    assocResult.value = null
    seqResult.value = null
    precheckResult.value = null
    clusterSelectedColumns.value = []
    assocTidColumn.value = ''
    assocItemColumn.value = ''
    seqColumns.seq_id_column = ''
    seqColumns.time_column = ''
    seqColumns.event_column = ''
    clusterRecommendation.value = null
    assocRecommendation.value = null
    seqRecommendation.value = null

    // 加载远程表当前生效的列信息（含特征工程动态新增的构造列）
    if (config.remote?.connection_id && config.remote?.table_name) {
      try {
        const res = await fetchRemoteColumnPool(config.remote.connection_id, config.remote.table_name)
        const poolData = res.data || {}
        const cols = poolData.columns || []
        // 远程列池的 type 已是统一分类（numeric/string/datetime），直接按类型过滤
        allColumns.value = cols.map(c => c.name).filter(Boolean)
        numericColumns.value = cols.filter(c => c.type === 'numeric').map(c => c.name).filter(Boolean)
        categoricalColumns.value = cols.filter(c => c.type === 'string').map(c => c.name).filter(Boolean)
        datetimeColumns.value = cols.filter(c => c.type === 'datetime').map(c => c.name).filter(Boolean)
        ElMessage.success(`已加载远程表 ${config.remote.table_name} 的 ${allColumns.value.length} 个列`)
        // 远程模式也自动触发预检
        executePrecheck()
      } catch (e) {
        allColumns.value = []
        numericColumns.value = []
        categoricalColumns.value = []
        datetimeColumns.value = []
        ElMessage.error('加载远程表列信息失败：' + (e?.response?.data?.detail || e?.message || '未知错误'))
      }
    } else {
      allColumns.value = []
      numericColumns.value = []
      categoricalColumns.value = []
      datetimeColumns.value = []
    }
    // 切换数据源后恢复该远程表最近一次成功的分析结果
    restoreLatestResults()
    // 远程模式：内嵌数据预览暂不支持，置空并提示
    loadPreview()
  }
}

// ====== 列信息 ======
const allColumns = ref([])
const numericColumns = ref([])
const categoricalColumns = ref([])
const datetimeColumns = ref([])

// ====== 预检结果 ======
const precheckLoading = ref(false)
const precheckResult = ref(null)

const precheckErrors = computed(() => precheckResult.value?.checks?.errors || [])
const precheckWarnings = computed(() => precheckResult.value?.checks?.warnings || [])
const precheckInfos = computed(() => precheckResult.value?.checks?.info || [])
const hasChecks = computed(() =>
  precheckErrors.value.length + precheckWarnings.value.length + precheckInfos.value.length > 0
)

const clusterAlgoOptions = computed(() => {
  const details = precheckResult.value?.recommendations?.cluster?.algorithm_details || []
  const moduleRecommended = precheckResult.value?.recommendations?.cluster?.recommended
  if (details.length > 0) {
    return details
  }
  const isRecommended = moduleRecommended !== false
  return [
    { name: 'kmeans', display_name: 'KMeans', recommended: isRecommended, reason: '经典聚类算法' },
    { name: 'dbscan', display_name: 'DBSCAN', recommended: isRecommended, reason: '适合任意形状簇' },
    { name: 'hierarchical', display_name: '层次聚类', recommended: isRecommended, reason: '层次结构清晰' }
  ]
})

const assocAlgoOptions = computed(() => {
  const details = precheckResult.value?.recommendations?.association?.algorithm_details || []
  const moduleRecommended = precheckResult.value?.recommendations?.association?.recommended
  if (details.length > 0) {
    return details
  }
  const isRecommended = moduleRecommended !== false
  return [
    { name: 'apriori', display_name: 'Apriori', recommended: isRecommended, reason: '经典关联规则算法' },
    { name: 'fpgrowth', display_name: 'FP-Growth', recommended: isRecommended, reason: '高效挖掘算法' }
  ]
})

const seqAlgoOptions = computed(() => {
  const details = precheckResult.value?.recommendations?.sequence?.algorithm_details || []
  const moduleRecommended = precheckResult.value?.recommendations?.sequence?.recommended
  if (details.length > 0) {
    return details
  }
  const isRecommended = moduleRecommended !== false
  return [
    { name: 'prefixspan', display_name: 'PrefixSpan', recommended: isRecommended, reason: '高效序列模式算法' },
    { name: 'gsp', display_name: 'GSP', recommended: isRecommended, reason: '经典序列模式算法' }
  ]
})

// ====== 当前激活的 Tab ======
const activeTab = ref('cluster')

// ====== 执行按钮可用性判断 ======
const canExecute = computed(() => {
  if (!precheckResult.value) return true // 还没预检，允许执行
  const rec = precheckResult.value.recommendations?.[activeTab.value]
  if (!rec) return true
  return rec.can_execute !== false
})

const blockReason = computed(() => {
  if (!precheckResult.value) return ''
  const rec = precheckResult.value.recommendations?.[activeTab.value]
  if (!rec) return ''
  return rec.block_reason || ''
})

// ====== 聚类分析状态（切换 Tab 时保留） ======
const clusterAlgorithm = ref('kmeans') // kmeans / dbscan / hierarchical
const clusterSelectedColumns = ref([])
const clusterParams = reactive({
  n_clusters: 5,
  init: 'k-means++',
  max_iter: 300,
  n_init: 10,
  eps: 0.5,
  min_samples: 5,
  metric: 'euclidean',
  linkage: 'ward'
})
const clusterRecommendation = ref(null) // 自动推荐结果 { n_clusters, reason, ... }
const clusterRecommendLoading = ref(false)
const clusterUsedRecommendation = ref(false) // 是否使用了自动推荐参数执行

// ====== 关联规则状态（切换 Tab 时保留） ======
const assocAlgorithm = ref('apriori') // apriori / fpgrowth
const assocDataFormat = ref('basket') // basket / binary
const assocTidColumn = ref('')
const assocItemColumn = ref('')
const assocParams = reactive({
  min_support: 0.1,
  min_confidence: 0.8,
  min_lift: 1.0,
  max_itemset: 0 // 0 表示不限制
})
const assocRecommendation = ref(null)
const assocRecommendLoading = ref(false)
const assocUsedRecommendation = ref(false) // 是否使用了自动推荐参数执行

// ====== 序列模式状态（切换 Tab 时保留） ======
const seqAlgorithm = ref('prefixspan') // prefixspan / gsp
const seqColumns = reactive({
  seq_id_column: '',
  time_column: '',
  event_column: ''
})
// 自动检测结果（用于显示"已自动识别"标识）
const seqAutoDetected = reactive({
  seq_id_column: '',
  time_column: '',
  event_column: ''
})
const seqParams = reactive({
  min_support: 0.1,
  max_len: 10 // 最大序列长度，0 表示不限制
})
const seqRecommendation = ref(null)
const seqRecommendLoading = ref(false)
const seqUsedRecommendation = ref(false) // 是否使用了自动推荐参数执行
// 参数推荐应用中的标志：推荐函数写入参数时跳过"手动修改"重置，避免推荐标记被误清
let applyingRecommendation = false

// ====== 保存状态 ======
const clusterSaveLoading = ref(false)
const assocSaveLoading = ref(false)
const seqSaveLoading = ref(false)

// ====== 执行状态 ======
const miningLoading = ref(false)

// ====== 结果数据（每个 Tab 独立保留） ======
const clusterResult = ref(null)
const assocResult = ref(null)
const seqResult = ref(null)

// ====== 关联规则分页（客户端分页，数据来自任务返回） ======
const assocPage = ref(1)
const assocPageSize = ref(20)
// 关联规则分页切片
const paginatedAssocRules = computed(() => {
  const rules = assocResult.value?.rules || []
  const start = (assocPage.value - 1) * assocPageSize.value
  return rules.slice(start, start + assocPageSize.value)
})
// 结果变化时重置分页
watch(assocResult, () => { assocPage.value = 1 })

// ====== 序列模式分页（客户端分页，数据来自任务返回） ======
const seqPage = ref(1)
const seqPageSize = ref(20)
const paginatedSeqPatterns = computed(() => {
  const patterns = seqResult.value?.top_patterns || []
  const start = (seqPage.value - 1) * seqPageSize.value
  return patterns.slice(start, start + seqPageSize.value)
})
watch(seqResult, () => { seqPage.value = 1 })

// 结果展示 Tab
const clusterResultTab = ref('scatter')
const assocResultTab = ref('rules')
const seqResultTab = ref('patterns')

// ====== 图表实例 ======
let clusterChartInstance = null
const clusterChartRef = ref(null)

// ====== 关联规则统计（计算属性） ======
const assocStats = computed(() => {
  const rules = assocResult.value?.rules || []
  if (rules.length === 0) return { avg_support: 0, avg_confidence: 0, avg_lift: 0 }
  const sum = rules.reduce((acc, r) => ({
    support: acc.support + (r.support || 0),
    confidence: acc.confidence + (r.confidence || 0),
    lift: acc.lift + (r.lift || 0)
  }), { support: 0, confidence: 0, lift: 0 })
  return {
    avg_support: sum.support / rules.length,
    avg_confidence: sum.confidence / rules.length,
    avg_lift: sum.lift / rules.length
  }
})

// ====== 序列模式统计（计算属性） ======
const seqStats = computed(() => {
  const patterns = seqResult.value?.top_patterns || []
  if (patterns.length === 0) return { avg_support: 0, max_length: 0 }
  const sumSupport = patterns.reduce((acc, p) => acc + (p.support || 0), 0)
  const maxLength = patterns.reduce((acc, p) => {
    const len = Array.isArray(p.sequence) ? p.sequence.length : 0
    return Math.max(acc, len)
  }, 0)
  return {
    avg_support: sumSupport / patterns.length,
    max_length: maxLength
  }
})

// ====== 文件上传处理 ======
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
    const res = await uploadMiningFile(uploadFile.value)
    ElMessage.success('上传成功')
    uploadFile.value = null
    // 刷新下拉框并自动选中新上传的数据集，避免用户在带时间戳的重名文件中难以辨认
    await dataSourceSelectorRef.value?.reload()
    // 先刷新数据列表，确保 onDatasetChange 能通过列表查到新数据集
    await loadMiningRawData()
    // 上传成功后通过 selectDataset 自动选中新数据集（其内部 emit 会触发 onSourceSelect，
    // 无需再手动调用，避免 onSourceSelect/预检/结果恢复被执行两次）
    const newId = res.data?.id || res.id
    if (newId) {
      dataSourceSelectorRef.value?.selectDataset(newId)
    }
  } catch (e) {
    ElMessage.error('上传失败：' + (extractErrorMessage(e)))
  } finally {
    uploadLoading.value = false
  }
}

// ====== 加载数据集列表 ======
async function loadMiningRawData() {
  datasetLoading.value = true
  try {
    const res = await fetchMiningRawData()
    miningRawData.value = res.data || []
    // 如果当前没有选中数据集，且有可用数据集，自动选择第一个
    if (!hasDataSource.value && miningRawData.value.length > 0) {
      datasetId.value = miningRawData.value[0].id
    }
    // 当前选中的数据集已不存在（被删除），清空选中状态
    if (datasetId.value && !miningRawData.value.some(d => d.id === datasetId.value)) {
      datasetId.value = null
      lastLoadedDatasetId.value = null
    }
    // 数据集变化统一由 watch(datasetId) 触发 onDatasetChange（列信息更新、清空结果、预检），
    // 此处不再手动调用，避免与 watch 双重触发导致预检/结果恢复执行两次
  } catch (e) {
    ElMessage.error('获取数据集列表失败')
  } finally {
    datasetLoading.value = false
  }
  // 加载完成后恢复当前数据源最近一次成功的分析结果（keep-alive 切换回来 / 刷新页面场景）
  restoreLatestResults()
}

// ====== 数据集变化处理 ======
function onDatasetChange(val) {
  // 清空结果
  clusterResult.value = null
  assocResult.value = null
  seqResult.value = null
  // 清空预检结果
  precheckResult.value = null
  // 清空列选择
  clusterSelectedColumns.value = []
  assocTidColumn.value = ''
  assocItemColumn.value = ''
  seqColumns.seq_id_column = ''
  seqColumns.time_column = ''
  seqColumns.event_column = ''
  seqAutoDetected.seq_id_column = ''
  seqAutoDetected.time_column = ''
  seqAutoDetected.event_column = ''
  // 清空推荐结果
  clusterRecommendation.value = null
  assocRecommendation.value = null
  seqRecommendation.value = null

  // 更新当前数据集信息和列信息
  if (val) {
    currentDataset.value = miningRawData.value.find(d => d.id === val) || null
    extractColumnsFromSchema(currentDataset.value?.schema)
    // 自动执行预检
    executePrecheck()
  } else {
    currentDataset.value = null
    allColumns.value = []
    numericColumns.value = []
    categoricalColumns.value = []
    datetimeColumns.value = []
  }
}

// 从 schema 中提取列信息（兼容字典与数组两种格式，同时识别 pandas dtype 和 SQL 数据库类型）
function extractColumnsFromSchema(schema) {
  if (!schema) {
    allColumns.value = []
    numericColumns.value = []
    categoricalColumns.value = []
    datetimeColumns.value = []
    return
  }

  // SQL 数据库类型关键字（大小写不敏感匹配），覆盖 MySQL/PostgreSQL 常见类型
  const numericSqlPatterns = ['int', 'float', 'double', 'decimal', 'numeric', 'number', 'real', 'serial', 'money']
  const categoricalSqlPatterns = ['char', 'text', 'string', 'bool', 'enum', 'json', 'blob', 'binary']
  const datetimeSqlPatterns = ['datetime', 'timestamp', 'date', 'time', 'year']
  // pandas dtype 精确匹配
  const numericDtypes = ['int64', 'float64', 'int', 'float', 'int32', 'float32', 'int16', 'float16', 'uint8', 'uint16', 'uint32', 'uint64']
  const categoricalDtypes = ['object', 'category', 'string', 'bool', 'boolean']

  // 统一类型判断：先精确匹配 pandas dtype，再用 SQL 类型关键字模糊匹配
  function isNumeric(typeStr) {
    if (!typeStr) return false
    const lower = String(typeStr).toLowerCase()
    if (numericDtypes.includes(lower)) return true
    return numericSqlPatterns.some(p => lower.includes(p))
  }
  function isCategorical(typeStr) {
    if (!typeStr) return false
    const lower = String(typeStr).toLowerCase()
    if (categoricalDtypes.includes(lower)) return true
    return categoricalSqlPatterns.some(p => lower.includes(p))
  }
  function isDatetime(typeStr) {
    if (!typeStr) return false
    const lower = String(typeStr).toLowerCase()
    return datetimeSqlPatterns.some(p => lower.includes(p))
  }

  if (Array.isArray(schema)) {
    // 数组格式：[{name, type}, ...]
    allColumns.value = schema.map(c => c.name || c.column).filter(Boolean)
    numericColumns.value = schema
      .filter(c => isNumeric(c.type || c.data_type))
      .map(c => c.name || c.column)
      .filter(Boolean)
    categoricalColumns.value = schema
      .filter(c => isCategorical(c.type || c.data_type))
      .map(c => c.name || c.column)
      .filter(Boolean)
    datetimeColumns.value = schema
      .filter(c => isDatetime(c.type || c.data_type))
      .map(c => c.name || c.column)
      .filter(Boolean)
  } else if (typeof schema === 'object') {
    // 字典格式：{列名: 类型}
    allColumns.value = Object.keys(schema)
    numericColumns.value = Object.entries(schema)
      .filter(([, type]) => isNumeric(type))
      .map(([name]) => name)
    categoricalColumns.value = Object.entries(schema)
      .filter(([, type]) => isCategorical(type))
      .map(([name]) => name)
    datetimeColumns.value = Object.entries(schema)
      .filter(([, type]) => isDatetime(type))
      .map(([name]) => name)
  }
}

// 监听 datasetId 变化，自动加载列信息（数据集切换时清空结果、刷新列与预检）
watch(datasetId, (newVal) => {
  lastLoadedDatasetId.value = newVal || null
  onDatasetChange(newVal)
})

// ====== 数据预检 ======
async function executePrecheck() {
  if (!hasDataSource.value) return
  precheckLoading.value = true
  try {
    const isRemote = sourceConfig.value.mode === 'remote'
    const remote = isRemote ? sourceConfig.value.remote : null
    const res = await precheckMiningData(isRemote ? null : datasetId.value, remote)
    const data = res.data || res
    precheckResult.value = data
    // 用预检检测到的时间列更新下拉框数据源（后端会尝试转换字符串列）
    if (data?.data_profile?.datetime_columns) {
      datetimeColumns.value = data.data_profile.datetime_columns
    }
    // 用预检检测到的类别列补充下拉框数据源
    if (data?.data_profile?.categorical_columns) {
      // 合并去重，保留schema中已有的类别列，同时加入预检检测到的
      const existing = new Set(categoricalColumns.value)
      const merged = [...categoricalColumns.value]
      for (const col of data.data_profile.categorical_columns) {
        if (!existing.has(col)) {
          merged.push(col)
          existing.add(col)
        }
      }
      categoricalColumns.value = merged
    }
    // 序列模式列自动填充移至 Tab 切换时执行，避免在其他模块中显示提示
  } catch (e) {
    ElMessage.error('数据预检失败：' + (extractErrorMessage(e)))
    precheckResult.value = null
  } finally {
    precheckLoading.value = false
  }
}

// 根据预检结果自动填充序列模式所需列
function autoFillSequenceColumns(precheck) {
  if (!precheck?.data_profile) return
  const profile = precheck.data_profile
  // 自动识别序列 ID 列：优先使用预检检测到的 id_columns
  if (profile.id_columns && profile.id_columns.length > 0) {
    seqColumns.seq_id_column = profile.id_columns[0]
    seqAutoDetected.seq_id_column = profile.id_columns[0]
  } else {
    // 否则尝试匹配含 id/user 的列
    const matched = allColumns.value.find(c => /(^|_)(id|user|session)(_|$)/i.test(c))
    if (matched) {
      seqColumns.seq_id_column = matched
      seqAutoDetected.seq_id_column = matched
    } else {
      // 检测不到时提示用户手动选择
      ElMessage.info('未自动检测到序列ID列，请手动选择')
    }
  }
  // 自动识别时间列
  if (profile.datetime_columns && profile.datetime_columns.length > 0) {
    seqColumns.time_column = profile.datetime_columns[0]
    seqAutoDetected.time_column = profile.datetime_columns[0]
  } else if (datetimeColumns.value.length > 0) {
    seqColumns.time_column = datetimeColumns.value[0]
    seqAutoDetected.time_column = datetimeColumns.value[0]
  }
  // 自动识别事件列：优先使用第一个类别列
  if (categoricalColumns.value.length > 0) {
    // 排除已被选作 id 或时间列的列
    const candidate = categoricalColumns.value.find(c =>
      c !== seqColumns.seq_id_column && c !== seqColumns.time_column
    )
    if (candidate) {
      seqColumns.event_column = candidate
      seqAutoDetected.event_column = candidate
    }
  }
}

// ====== Tab 切换处理 ======
function onTabChange() {
  // 切换到序列模式 Tab 时，执行列自动填充
  if (activeTab.value === 'sequence' && precheckResult.value) {
    autoFillSequenceColumns(precheckResult.value)
  }
  // 延迟渲染图表，确保 DOM 已更新
  nextTick(() => {
    if (activeTab.value === 'cluster' && clusterResult.value?.projection_2d && clusterResultTab.value === 'scatter') {
      renderClusterChart()
    }
  })
}

// ====== 算法切换处理：自动调用参数推荐 ======
async function onClusterAlgorithmChange() {
  clusterRecommendation.value = null
  // 切换算法时不自动调用推荐，避免过多请求；保留手动"自动推荐"按钮
}

async function onAssocAlgorithmChange() {
  assocRecommendation.value = null
}

async function onSeqAlgorithmChange() {
  seqRecommendation.value = null
}

// ====== 参数推荐 ======
async function recommendClusterParams() {
  if (!hasDataSource.value) {
    ElMessage.warning('请先选择数据集')
    return
  }
  if (!clusterSelectedColumns.value || clusterSelectedColumns.value.length === 0) {
    ElMessage.warning('请先选择特征列')
    return
  }
  clusterRecommendLoading.value = true
  applyingRecommendation = true
  try {
    const isRemote = sourceConfig.value.mode === 'remote'
    const remote = isRemote ? sourceConfig.value.remote : null
    const res = await recommendMiningParams(isRemote ? null : datasetId.value, 'cluster', clusterAlgorithm.value, clusterSelectedColumns.value, remote)
    const data = res.data || res
    const params = data.recommended_params || {}
    // 应用推荐值
    if (clusterAlgorithm.value === 'kmeans' || clusterAlgorithm.value === 'hierarchical') {
      if (params.n_clusters !== undefined) clusterParams.n_clusters = params.n_clusters
    } else if (clusterAlgorithm.value === 'dbscan') {
      if (params.eps !== undefined) clusterParams.eps = params.eps
      if (params.min_samples !== undefined) clusterParams.min_samples = params.min_samples
    }
    clusterRecommendation.value = { ...params }
    clusterUsedRecommendation.value = true
    ElMessage.success('已应用推荐参数')
  } catch (e) {
    ElMessage.error('参数推荐失败：' + (extractErrorMessage(e)))
  } finally {
    applyingRecommendation = false
    clusterRecommendLoading.value = false
  }
}

async function recommendAssocParams() {
  if (!hasDataSource.value) {
    ElMessage.warning('请先选择数据集')
    return
  }
  assocRecommendLoading.value = true
  applyingRecommendation = true
  try {
    const isRemote = sourceConfig.value.mode === 'remote'
    const remote = isRemote ? sourceConfig.value.remote : null
    const res = await recommendMiningParams(isRemote ? null : datasetId.value, 'association', assocAlgorithm.value, null, remote)
    const data = res.data || res
    const params = data.recommended_params || {}
    if (params.min_support !== undefined) assocParams.min_support = params.min_support
    if (params.min_confidence !== undefined) assocParams.min_confidence = params.min_confidence
    assocRecommendation.value = { ...params }
    assocUsedRecommendation.value = true
    ElMessage.success('已应用推荐参数')
  } catch (e) {
    ElMessage.error('参数推荐失败：' + (extractErrorMessage(e)))
  } finally {
    applyingRecommendation = false
    assocRecommendLoading.value = false
  }
}

async function recommendSeqParams() {
  if (!hasDataSource.value) {
    ElMessage.warning('请先选择数据集')
    return
  }
  seqRecommendLoading.value = true
  applyingRecommendation = true
  try {
    const isRemote = sourceConfig.value.mode === 'remote'
    const remote = isRemote ? sourceConfig.value.remote : null
    const res = await recommendMiningParams(isRemote ? null : datasetId.value, 'sequence', seqAlgorithm.value, null, remote)
    const data = res.data || res
    const params = data.recommended_params || {}
    if (params.min_support !== undefined) seqParams.min_support = params.min_support
    seqRecommendation.value = { ...params }
    seqUsedRecommendation.value = true
    ElMessage.success('已应用推荐参数')
  } catch (e) {
    ElMessage.error('参数推荐失败：' + (extractErrorMessage(e)))
  } finally {
    applyingRecommendation = false
    seqRecommendLoading.value = false
  }
}

// 用户手动修改任意分析参数后，重置"使用了推荐参数"标记（auto_params 回退为 false）
// 仅当参数由推荐函数写入（applyingRecommendation）时跳过，避免推荐标记被误清
watch(clusterParams, () => {
  if (applyingRecommendation) return
  clusterUsedRecommendation.value = false
}, { deep: true })

watch(assocParams, () => {
  if (applyingRecommendation) return
  assocUsedRecommendation.value = false
}, { deep: true })

watch(seqParams, () => {
  if (applyingRecommendation) return
  seqUsedRecommendation.value = false
}, { deep: true })

// ====== 执行分析 ======
async function executeMining() {
  if (!hasDataSource.value) {
    ElMessage.warning('请先选择数据集')
    return
  }

  // 参数校验
  if (activeTab.value === 'cluster') {
    if (clusterSelectedColumns.value.length === 0) {
      ElMessage.warning('请至少选择一个特征列用于聚类分析')
      return
    }
  } else if (activeTab.value === 'association') {
    if (assocDataFormat.value === 'basket') {
      if (!assocTidColumn.value) {
        ElMessage.warning('请选择事务标识列')
        return
      }
      if (!assocItemColumn.value) {
        ElMessage.warning('请选择项列')
        return
      }
      if (assocTidColumn.value === assocItemColumn.value) {
        ElMessage.warning('事务标识列和项列不能相同')
        return
      }
    }
  } else if (activeTab.value === 'sequence') {
    if (!seqColumns.seq_id_column) {
      ElMessage.warning('请选择序列ID列')
      return
    }
    if (!seqColumns.time_column) {
      ElMessage.warning('请选择时间列')
      return
    }
    if (!seqColumns.event_column) {
      ElMessage.warning('请选择事件列')
      return
    }
  }

  miningLoading.value = true

  try {
    if (activeTab.value === 'cluster') {
      await executeCluster()
    } else if (activeTab.value === 'association') {
      await executeAssociation()
    } else if (activeTab.value === 'sequence') {
      await executeSequence()
    }
  } catch (e) {
    // 503: Celery 不可用（大数据集不降级）
    if (e.response?.status === 503) {
      ElMessage.error('数据量较大（≥1万行），Celery 服务不可用，无法执行。请启动 Celery 服务或使用小数据集')
    } else if (e.response?.status === 429) {
      // 429: 单用户并发任务超限
      ElMessage.warning(e.response?.data?.detail || '异步任务数超限，请等待现有任务完成或取消后再试')
    } else {
      ElMessage.error('分析失败：' + (extractErrorMessage(e)))
    }
  } finally {
    // 同步任务执行完成后释放按钮 loading
    // 异步任务进度由全局任务面板接管展示
    miningLoading.value = false
  }
}

// 执行聚类分析
async function executeCluster() {
  const params = {
    algorithm: clusterAlgorithm.value,
    columns: clusterSelectedColumns.value,
    // 是否使用推荐参数：点击自动推荐按钮后置 true，执行时透传给后端记录
    auto_params: clusterUsedRecommendation.value,
    save: false
  }
  if (clusterAlgorithm.value === 'kmeans') {
    params.n_clusters = clusterParams.n_clusters
    params.init = clusterParams.init
    params.max_iter = clusterParams.max_iter
    params.n_init = clusterParams.n_init
  } else if (clusterAlgorithm.value === 'dbscan') {
    params.eps = clusterParams.eps
    params.min_samples = clusterParams.min_samples
    params.metric = clusterParams.metric
  } else if (clusterAlgorithm.value === 'hierarchical') {
    params.n_clusters = clusterParams.n_clusters
    params.linkage = clusterParams.linkage
  }

  // 在 await 之前捕获提交时的数据源标识，供同步/异步响应返回时校验一致性，避免页面污染
  const submitSourceKey = getSourceKey()
  const isRemote = sourceConfig.value.mode === 'remote'
  if (isRemote && sourceConfig.value.remote) {
    params.remote = sourceConfig.value.remote
  }
  const res = await runDataMiningClustering(isRemote ? null : datasetId.value, params)

  // 异步分发检测：大数据集（≥1万行）后端返回 status=queued/running/pending + task_record_id
  // 提交到全局任务面板，store 内部自动管理轮询
  const data = res.data || res
  if ((data.status === 'queued' || data.status === 'running' || data.status === 'pending') && data.task_record_id) {
    addTask({
      recordId: data.task_record_id,
      celeryTaskId: data.task_id,
      taskType: 'data_mining_cluster',
      operation: '聚类分析',
      moduleLabel: '数据挖掘',
      datasetName: currentDataset.value?.name || '',
      initialStatus: data.status === 'pending' ? 'pending' : 'running',
      isRemote: sourceConfig.value.mode === 'remote',
    }, (status, summary) => {
      // 任务完成回调：成功时分发结果到聚类结果处理函数
      if (status === 'success') {
        // 数据源一致性校验：若用户在任务执行期间切换了数据源，不直接渲染结果以免串显
        if (getSourceKey() !== submitSourceKey) {
          ElMessage.success('聚类分析完成，请切回原数据源查看结果')
          return
        }
        handleClusterResult(summary)
      } else if (status === 'failed') {
        ElMessage.error(`聚类分析失败: ${summary?.current_message || '请查看任务面板'}`)
      } else if (status === 'cancelled') {
        ElMessage.info('聚类任务已取消')
      }
    })
    ElMessage.info('数据量较大，已提交异步任务，请等待执行完成')
    return
  }

  // 同步结果：校验数据源一致性后展示，避免 await 期间用户切换数据源导致页面污染
  if (getSourceKey() === submitSourceKey) {
    handleClusterResult(data)
  } else {
    ElMessage.success('聚类分析完成，请切回原数据源查看结果')
  }
}

// 处理聚类分析结果（同步直接调用 / 异步轮询完成后调用 / 结果恢复时静默调用）
function handleClusterResult(data, options = {}) {
  const report = data?.cluster_report || data || {}

  // 转换 cluster_stats 为数组格式（兼容对象/数组）
  let clusterStats = []
  if (Array.isArray(report.cluster_stats)) {
    clusterStats = report.cluster_stats
  } else if (report.cluster_stats && typeof report.cluster_stats === 'object') {
    clusterStats = Object.entries(report.cluster_stats).map(([key, val]) => ({
      cluster: key.replace('cluster_', ''),
      count: val.count,
      percentage: val.percentage
    }))
  }

  const sampleCount = report.sample_count ?? clusterStats.reduce((sum, c) => sum + (c.count || 0), 0)

  // 数据预览列：特征列 + cluster
  const previewColumns = [...(report.features_used || clusterSelectedColumns.value), 'cluster']

  clusterResult.value = {
    algorithm: report.algorithm || clusterAlgorithm.value,
    n_clusters: report.n_clusters,
    silhouette_score: report.silhouette_score,
    features_used: report.features_used || clusterSelectedColumns.value,
    cluster_stats: clusterStats,
    sample_count: sampleCount,
    noise_count: report.noise_count,
    noise_percentage: report.noise_percentage,
    projection_2d: report.projection_2d,
    preview_data: report.preview_data,
    preview_columns: previewColumns,
    params_used: report.params_used,
    recommended_params: report.recommended_params,
    auto_params: report.auto_params,
    // 优先取后端固化的 auto_params（结果恢复/保存时不被本地已重置的标记误导）
    used_recommendation: report.auto_params ?? clusterUsedRecommendation.value,
    quality_assessment: report.quality_assessment || [],
    saved: data?.saved || false,
    dataset_id: data?.dataset_id
  }
  clusterUsedRecommendation.value = false
  if (!options.silent) ElMessage.success('聚类分析完成')
  // 默认显示散点图 Tab，确保渲染
  clusterResultTab.value = 'scatter'
  nextTick(() => {
    if (clusterResult.value?.projection_2d && clusterResult.value.projection_2d.length > 0) {
      renderClusterChart()
    }
  })
}

// 执行关联规则挖掘
async function executeAssociation() {
  const params = {
    algorithm: assocAlgorithm.value,
    min_support: assocParams.min_support,
    min_confidence: assocParams.min_confidence,
    min_lift: assocParams.min_lift,
    max_len: assocParams.max_itemset === 0 ? null : assocParams.max_itemset,
    // 是否使用推荐参数：点击自动推荐按钮后置 true，执行时透传给后端记录
    auto_params: assocUsedRecommendation.value,
    save: false
  }
  // 关联规则需始终传递 data_format，操作历史详情据此显示购物篮格式/自动二值化
  if (assocDataFormat.value === 'basket') {
    params.tid_column = assocTidColumn.value
    params.item_column = assocItemColumn.value
    params.data_format = 'basket'
  } else {
    params.data_format = 'binary'
  }

  // 在 await 之前捕获提交时的数据源标识，供同步/异步响应返回时校验一致性，避免页面污染
  const submitSourceKey = getSourceKey()
  const isRemote = sourceConfig.value.mode === 'remote'
  if (isRemote && sourceConfig.value.remote) {
    params.remote = sourceConfig.value.remote
  }
  const res = await runDataMiningAssociationRules(isRemote ? null : datasetId.value, params)

  // 异步分发检测：大数据集（≥1万行）后端返回 status=queued/running/pending + task_record_id
  // 提交到全局任务面板，store 内部自动管理轮询
  const data = res.data || res
  if ((data.status === 'queued' || data.status === 'running' || data.status === 'pending') && data.task_record_id) {
    addTask({
      recordId: data.task_record_id,
      celeryTaskId: data.task_id,
      taskType: 'data_mining_association',
      operation: '关联规则挖掘',
      moduleLabel: '数据挖掘',
      datasetName: currentDataset.value?.name || '',
      initialStatus: data.status === 'pending' ? 'pending' : 'running',
      isRemote: sourceConfig.value.mode === 'remote',
    }, (status, summary) => {
      // 任务完成回调：成功时分发结果到关联规则结果处理函数
      if (status === 'success') {
        // 数据源一致性校验：若用户在任务执行期间切换了数据源，不直接渲染结果以免串显
        if (getSourceKey() !== submitSourceKey) {
          ElMessage.success('关联规则挖掘完成，请切回原数据源查看结果')
          return
        }
        handleAssociationResult(summary)
      } else if (status === 'failed') {
        ElMessage.error(`关联规则挖掘失败: ${summary?.current_message || '请查看任务面板'}`)
      } else if (status === 'cancelled') {
        ElMessage.info('关联规则任务已取消')
      }
    })
    ElMessage.info('数据量较大，已提交异步任务，请等待执行完成')
    return
  }

  // 同步结果：校验数据源一致性后展示，避免 await 期间用户切换数据源导致页面污染
  if (getSourceKey() === submitSourceKey) {
    handleAssociationResult(data)
  } else {
    ElMessage.success('关联规则分析完成，请切回原数据源查看结果')
  }
}

// 处理关联规则挖掘结果（同步直接调用 / 异步轮询完成后调用 / 结果恢复时静默调用）
function handleAssociationResult(data, options = {}) {
  const report = data?.association_report || data || {}

  assocResult.value = {
    algorithm: report.algorithm || assocAlgorithm.value,
    min_support: report.min_support,
    min_confidence: report.min_confidence,
    min_lift: report.min_lift,
    params_used: report.params_used,
    total_rules: report.total_rules ?? (report.rules ? report.rules.length : 0),
    rules: report.rules || [],
    recommended_params: report.recommended_params,
    auto_params: report.auto_params,
    // 优先取后端固化的 auto_params，保证结果恢复/保存时标记一致
    used_recommendation: report.auto_params ?? assocUsedRecommendation.value,
    quality_assessment: report.quality_assessment || [],
    saved: data?.saved || false,
    dataset_id: data?.dataset_id
  }
  assocUsedRecommendation.value = false
  if (!options.silent) ElMessage.success('关联规则挖掘完成')
}

// 执行序列模式挖掘
async function executeSequence() {
  const params = {
    algorithm: seqAlgorithm.value,
    seq_id_column: seqColumns.seq_id_column,
    time_column: seqColumns.time_column,
    event_column: seqColumns.event_column,
    min_support: seqParams.min_support,
    max_len: seqParams.max_len === 0 ? null : seqParams.max_len,
    // 是否使用推荐参数：点击自动推荐按钮后置 true，执行时透传给后端记录
    auto_params: seqUsedRecommendation.value,
    save: false
  }

  // 在 await 之前捕获提交时的数据源标识，供同步/异步响应返回时校验一致性，避免页面污染
  const submitSourceKey = getSourceKey()
  const isRemote = sourceConfig.value.mode === 'remote'
  if (isRemote && sourceConfig.value.remote) {
    params.remote = sourceConfig.value.remote
  }
  const res = await runDataMiningSequence(isRemote ? null : datasetId.value, params)

  // 异步分发检测：大数据集（≥1万行）后端返回 status=queued/running/pending + task_record_id
  // 提交到全局任务面板，store 内部自动管理轮询
  const data = res.data || res
  if ((data.status === 'queued' || data.status === 'running' || data.status === 'pending') && data.task_record_id) {
    addTask({
      recordId: data.task_record_id,
      celeryTaskId: data.task_id,
      taskType: 'data_mining_sequence',
      operation: '序列模式挖掘',
      moduleLabel: '数据挖掘',
      datasetName: currentDataset.value?.name || '',
      initialStatus: data.status === 'pending' ? 'pending' : 'running',
      isRemote: sourceConfig.value.mode === 'remote',
    }, (status, summary) => {
      // 任务完成回调：成功时分发结果到序列模式结果处理函数
      if (status === 'success') {
        // 数据源一致性校验：若用户在任务执行期间切换了数据源，不直接渲染结果以免串显
        if (getSourceKey() !== submitSourceKey) {
          ElMessage.success('序列模式挖掘完成，请切回原数据源查看结果')
          return
        }
        handleSequenceResult(summary)
      } else if (status === 'failed') {
        ElMessage.error(`序列模式挖掘失败: ${summary?.current_message || '请查看任务面板'}`)
      } else if (status === 'cancelled') {
        ElMessage.info('序列模式任务已取消')
      }
    })
    ElMessage.info('数据量较大，已提交异步任务，请等待执行完成')
    return
  }

  // 同步结果：校验数据源一致性后展示，避免 await 期间用户切换数据源导致页面污染
  if (getSourceKey() === submitSourceKey) {
    handleSequenceResult(data)
  } else {
    ElMessage.success('序列模式分析完成，请切回原数据源查看结果')
  }
}

// 处理序列模式挖掘结果（同步直接调用 / 异步轮询完成后调用 / 结果恢复时静默调用）
function handleSequenceResult(data, options = {}) {
  const report = data?.sequence_report || data || {}

  seqResult.value = {
    algorithm: report.algorithm || seqAlgorithm.value,
    min_support: report.min_support,
    total_patterns: report.total_patterns ?? (report.top_patterns ? report.top_patterns.length : 0),
    top_patterns: report.top_patterns || report.patterns || [],
    n_sequences: report.n_sequences,
    seq_id_column: report.seq_id_column,
    time_column: report.time_column,
    event_column: report.event_column,
    params_used: report.params_used,
    recommended_params: report.recommended_params,
    auto_params: report.auto_params,
    // 优先取后端固化的 auto_params，保证结果恢复/保存时标记一致
    used_recommendation: report.auto_params ?? seqUsedRecommendation.value,
    quality_assessment: report.quality_assessment || [],
    saved: data?.saved || false,
    dataset_id: data?.dataset_id
  }
  seqUsedRecommendation.value = false
  if (!options.silent) ElMessage.success('序列模式挖掘完成')
}

// ====== 保存结果到数据管理 ======
async function saveClusterResult() {
  if (!hasDataSource.value || !clusterResult.value) return
  clusterSaveLoading.value = true
  try {
    // 捕获提交时数据源标识，用于异步回调返回时校验数据源一致性
    const submitSourceKey = getSourceKey()
    const params = {
      algorithm: clusterResult.value.algorithm,
      columns: clusterResult.value.features_used,
      // 是否使用推荐参数：复用执行结果中固化的标记，保持记录与展示一致
      auto_params: clusterResult.value.auto_params ?? false,
      save: true
    }
    if (clusterResult.value.algorithm === 'kmeans') {
      params.n_clusters = clusterParams.n_clusters
      params.init = clusterParams.init
      params.max_iter = clusterParams.max_iter
      params.n_init = clusterParams.n_init
    } else if (clusterResult.value.algorithm === 'dbscan') {
      params.eps = clusterParams.eps
      params.min_samples = clusterParams.min_samples
      params.metric = clusterParams.metric
    } else if (clusterResult.value.algorithm === 'hierarchical') {
      params.n_clusters = clusterParams.n_clusters
      params.linkage = clusterParams.linkage
    }
    const isRemote = sourceConfig.value.mode === 'remote'
    if (isRemote && sourceConfig.value.remote) {
      params.remote = sourceConfig.value.remote
    }
    const res = await runDataMiningClustering(isRemote ? null : datasetId.value, params)
    const data = res.data || res

    // 异步分支：大数据集（≥1万行）后端返回 running/queued/pending + task_record_id
    // 修复问题2类：原实现未判断异步状态，直接读取 dataset_id 会导致误判成功
    if ((data.status === 'queued' || data.status === 'running' || data.status === 'pending') && data.task_record_id) {
      addTask({
        recordId: data.task_record_id,
        celeryTaskId: data.task_id,
        taskType: 'data_mining_cluster',
        operation: '保存聚类结果',
        moduleLabel: '数据挖掘',
        datasetName: currentDataset.value?.name || '',
        initialStatus: data.status === 'pending' ? 'pending' : 'running',
        isRemote: sourceConfig.value.mode === 'remote',
      isRemote: sourceConfig.value.mode === 'remote',
      }, (status, summary) => {
        if (status === 'success') {
          // 数据源一致性校验：用户切换数据源后，不覆盖当前状态
          if (getSourceKey() !== submitSourceKey) {
            ElMessage.info('聚类结果已保存，请切回原数据源查看')
            return
          }
          clusterResult.value.saved = true
          clusterResult.value.dataset_id = summary?.dataset_id
          ElMessage.success('聚类结果已保存到数据管理')
        } else if (status === 'failed') {
          ElMessage.error(`保存失败: ${summary?.current_message || '请查看任务面板'}`)
        } else if (status === 'cancelled') {
          ElMessage.info('保存任务已取消')
        }
      })
      ElMessage.info('保存任务已提交至后台队列，可在任务面板查看进度')
      return
    }

    // 同步成功分支
    clusterResult.value.saved = true
    clusterResult.value.dataset_id = data.dataset_id
    ElMessage.success('聚类结果已保存到数据管理')
  } catch (e) {
    ElMessage.error('保存失败：' + (extractErrorMessage(e)))
  } finally {
    clusterSaveLoading.value = false
  }
}

async function saveAssocResult() {
  if (!hasDataSource.value || !assocResult.value) return
  assocSaveLoading.value = true
  try {
    // 捕获提交时数据源标识，用于异步回调返回时校验数据源一致性
    const submitSourceKey = getSourceKey()
    const params = {
      algorithm: assocResult.value.algorithm,
      data_format: assocDataFormat.value,
      min_support: assocResult.value.min_support,
      min_confidence: assocResult.value.min_confidence,
      // 保存参数统一取执行结果固化的值，避免用户中途改表单导致保存内容与展示不一致
      min_lift: assocResult.value.min_lift ?? assocParams.min_lift,
      max_len: assocResult.value.params_used?.max_len ?? (assocParams.max_itemset === 0 ? null : assocParams.max_itemset),
      // 是否使用推荐参数：复用执行结果中固化的标记，保持记录一致
      auto_params: assocResult.value.auto_params ?? false,
      save: true
    }
    // 关联规则需始终传递 data_format，操作历史详情据此显示购物篮格式/自动二值化
    if (assocDataFormat.value === 'basket') {
      params.tid_column = assocTidColumn.value
      params.item_column = assocItemColumn.value
      params.data_format = 'basket'
    } else {
      params.data_format = 'binary'
    }
    const isRemote = sourceConfig.value.mode === 'remote'
    if (isRemote && sourceConfig.value.remote) {
      params.remote = sourceConfig.value.remote
    }
    const res = await runDataMiningAssociationRules(isRemote ? null : datasetId.value, params)
    const data = res.data || res

    // 异步分支：大数据集（≥1万行）后端返回 running/queued/pending + task_record_id
    // 修复问题2类：原实现未判断异步状态，直接读取 dataset_id 会导致误判成功
    if ((data.status === 'queued' || data.status === 'running' || data.status === 'pending') && data.task_record_id) {
      addTask({
        recordId: data.task_record_id,
        celeryTaskId: data.task_id,
        taskType: 'data_mining_association',
        operation: '保存关联规则结果',
        moduleLabel: '数据挖掘',
        datasetName: currentDataset.value?.name || '',
        initialStatus: data.status === 'pending' ? 'pending' : 'running',
        isRemote: sourceConfig.value.mode === 'remote',
      isRemote: sourceConfig.value.mode === 'remote',
      }, (status, summary) => {
        if (status === 'success') {
          if (getSourceKey() !== submitSourceKey) {
            ElMessage.info('关联规则结果已保存，请切回原数据源查看')
            return
          }
          assocResult.value.saved = true
          assocResult.value.dataset_id = summary?.dataset_id
          ElMessage.success('关联规则结果已保存到数据管理')
        } else if (status === 'failed') {
          ElMessage.error(`保存失败: ${summary?.current_message || '请查看任务面板'}`)
        } else if (status === 'cancelled') {
          ElMessage.info('保存任务已取消')
        }
      })
      ElMessage.info('保存任务已提交至后台队列，可在任务面板查看进度')
      return
    }

    // 同步成功分支
    assocResult.value.saved = true
    assocResult.value.dataset_id = data.dataset_id
    ElMessage.success('关联规则结果已保存到数据管理')
  } catch (e) {
    ElMessage.error('保存失败：' + (extractErrorMessage(e)))
  } finally {
    assocSaveLoading.value = false
  }
}

async function saveSeqResult() {
  if (!hasDataSource.value || !seqResult.value) return
  seqSaveLoading.value = true
  try {
    // 捕获提交时数据源标识，用于异步回调返回时校验数据源一致性
    const submitSourceKey = getSourceKey()
    const params = {
      algorithm: seqResult.value.algorithm,
      seq_id_column: seqResult.value.seq_id_column,
      time_column: seqResult.value.time_column,
      event_column: seqResult.value.event_column,
      min_support: seqResult.value.min_support,
      // 保存参数统一取执行结果固化的值，避免用户中途改表单导致保存内容与展示不一致
      max_len: seqResult.value.params_used?.max_len ?? (seqParams.max_len === 0 ? null : seqParams.max_len),
      // 是否使用推荐参数：复用执行结果中固化的标记，保持记录一致
      auto_params: seqResult.value.auto_params ?? false,
      save: true
    }
    const isRemote = sourceConfig.value.mode === 'remote'
    if (isRemote && sourceConfig.value.remote) {
      params.remote = sourceConfig.value.remote
    }
    const res = await runDataMiningSequence(isRemote ? null : datasetId.value, params)
    const data = res.data || res

    // 异步分支：大数据集（≥1万行）后端返回 running/queued/pending + task_record_id
    // 修复问题2类：原实现未判断异步状态，直接读取 dataset_id 会导致误判成功
    if ((data.status === 'queued' || data.status === 'running' || data.status === 'pending') && data.task_record_id) {
      addTask({
        recordId: data.task_record_id,
        celeryTaskId: data.task_id,
        taskType: 'data_mining_sequence',
        operation: '保存序列模式结果',
        moduleLabel: '数据挖掘',
        datasetName: currentDataset.value?.name || '',
        initialStatus: data.status === 'pending' ? 'pending' : 'running',
        isRemote: sourceConfig.value.mode === 'remote',
      isRemote: sourceConfig.value.mode === 'remote',
      }, (status, summary) => {
        if (status === 'success') {
          if (getSourceKey() !== submitSourceKey) {
            ElMessage.info('序列模式结果已保存，请切回原数据源查看')
            return
          }
          seqResult.value.saved = true
          seqResult.value.dataset_id = summary?.dataset_id
          ElMessage.success('序列模式结果已保存到数据管理')
        } else if (status === 'failed') {
          ElMessage.error(`保存失败: ${summary?.current_message || '请查看任务面板'}`)
        } else if (status === 'cancelled') {
          ElMessage.info('保存任务已取消')
        }
      })
      ElMessage.info('保存任务已提交至后台队列，可在任务面板查看进度')
      return
    }

    // 同步成功分支
    seqResult.value.saved = true
    seqResult.value.dataset_id = data.dataset_id
    ElMessage.success('序列模式结果已保存到数据管理')
  } catch (e) {
    ElMessage.error('保存失败：' + (extractErrorMessage(e)))
  } finally {
    seqSaveLoading.value = false
  }
}

// ====== 聚类结果 Tab 切换 ======
function onClusterResultTabChange() {
  nextTick(() => {
    if (clusterResultTab.value === 'scatter' && clusterResult.value?.projection_2d) {
      renderClusterChart()
    }
  })
}

// ====== 渲染聚类散点图 ======
function renderClusterChart() {
  if (!clusterChartRef.value || !clusterResult.value?.projection_2d) return

  // 销毁旧实例
  if (clusterChartInstance) {
    clusterChartInstance.dispose()
    clusterChartInstance = null
  }

  const data = clusterResult.value.projection_2d
  if (!data || data.length === 0) return

  // 提取所有簇号（含 -1 噪声）
  const clusters = [...new Set(data.map(d => d.cluster))].sort((a, b) => {
    // 噪声点（-1）排在最后
    if (a === -1) return 1
    if (b === -1) return -1
    return a - b
  })

  clusterChartInstance = echarts.init(clusterChartRef.value)

  // 为每个簇准备数据
  const series = clusters.map(clusterId => {
    const isNoise = clusterId === -1 || clusterId === '-1'
    return {
      name: isNoise ? '噪声点' : `簇 ${clusterId}`,
      type: 'scatter',
      data: data
        .filter(d => d.cluster === clusterId)
        .map(d => [d.x, d.y]),
      symbolSize: isNoise ? 6 : 8,
      itemStyle: isNoise ? { color: '#9ca3af', opacity: 0.5 } : undefined
    }
  })

  const option = {
    title: { text: '聚类结果 (PCA 2D 投影)', left: 'center' },
    tooltip: {
      trigger: 'item',
      formatter: p => `${p.seriesName}<br/>X: ${p.value[0].toFixed(3)}<br/>Y: ${p.value[1].toFixed(3)}`
    },
    legend: { top: 30, type: 'scroll' },
    grid: { top: 80, bottom: 50, left: 60, right: 30 },
    xAxis: { type: 'value', name: '主成分 1', nameLocation: 'center', nameGap: 30 },
    yAxis: { type: 'value', name: '主成分 2', nameLocation: 'center', nameGap: 40 },
    series
  }

  clusterChartInstance.setOption(option)
  window.addEventListener('resize', handleChartResize)
}

function handleChartResize() {
  clusterChartInstance?.resize()
}

// ====== 工具函数 ======
function formatScore(val) {
  if (val === null || val === undefined) return '-'
  if (typeof val !== 'number') return val
  // 数值类指标统一保留 4 位小数
  return val.toFixed(4)
}

function formatPercent(val) {
  if (val === null || val === undefined) return '-'
  if (typeof val !== 'number') return val
  // 缺失值比例等以百分比显示，保留 2 位小数
  return val.toFixed(2) + '%'
}

// 格式化关联规则前项/后项（数组转字符串）
function formatItemList(items) {
  if (!items) return '-'
  if (Array.isArray(items)) return items.join(', ')
  return String(items)
}

// 格式化序列模式（确保返回数组用于渲染 tag）
function formatSequence(seq) {
  if (!seq) return []
  if (Array.isArray(seq)) return seq
  return [String(seq)]
}

// 统一提取后端错误信息，优先使用 message，其次 detail，最后降级为 axios 默认消息
function extractErrorMessage(e, defaultPrefix = '') {
  const msg = e?.response?.data?.message || e?.response?.data?.detail || e?.message || '未知错误'
  return defaultPrefix ? defaultPrefix + msg : msg
}

// ====== 恢复最近一次成功的分析结果 ======
// 数据挖掘结果仅保存在组件内存中，切换模块（keep-alive）或刷新页面后会丢失。
// 从操作历史中查询当前数据源（本地数据集 / 远程表）最近一次成功的分析记录，
// 解析 result_summary 中的 report 回填结果展示（静默，不弹成功提示）。
async function restoreLatestResults() {
  try {
    const isRemote = sourceConfig.value.mode === 'remote'
    // 无有效数据源时不恢复（直接判断数据集ID / 远程表，不依赖 hasDataSource，
    // 因为首次挂载自动选择数据集时 sourceConfig 尚未同步）
    if (isRemote) {
      if (!sourceConfig.value.remote?.connection_id || !sourceConfig.value.remote?.table_name) return
    } else if (!datasetId.value) {
      return
    }
    // 记录当前数据源标识，防止恢复过程中用户切换数据源导致串数据
    const localDatasetId = isRemote ? null : datasetId.value
    const remoteKey = isRemote
      ? `${sourceConfig.value.remote.connection_id}::${sourceConfig.value.remote.table_name}`
      : null

    // 三种分析类型各取最近一条成功记录（含保存到数据管理的 save_* 记录）
    const restoreConfigs = [
      { ops: ['cluster', 'save_cluster'], handler: handleClusterResult },
      { ops: ['association', 'save_association'], handler: handleAssociationResult },
      { ops: ['sequence', 'save_sequence'], handler: handleSequenceResult }
    ]
    for (const cfg of restoreConfigs) {
      const params = {
        task_type: 'data_mining',
        status: 'success',
        operation_in: cfg.ops,
        page: 1,
        page_size: 1
      }
      if (isRemote) {
        params.connection_id = sourceConfig.value.remote.connection_id
        params.table_name = sourceConfig.value.remote.table_name
      } else {
        params.dataset_id = localDatasetId
      }
      const res = await fetchTaskRecords(params)
      const records = res.data?.records || []
      if (!records.length) continue
      // 数据源一致性二次校验：恢复期间用户切换了数据源则终止本次恢复
      const stillSame = isRemote
        ? (sourceConfig.value.mode === 'remote'
          && `${sourceConfig.value.remote?.connection_id}::${sourceConfig.value.remote?.table_name}` === remoteKey)
        : (!isRemote && sourceConfig.value.mode === 'local' && datasetId.value === localDatasetId)
      if (!stillSame) return
      const detail = await getTaskProgress(records[0].id)
      const summary = detail?.result_summary
      if (!summary) continue
      cfg.handler(summary, { silent: true })
    }
  } catch (e) {
    // 恢复失败不影响主流程，静默处理
  }
}

// ====== 生命周期 ======
onMounted(() => {
  loadMiningRawData()
})

onActivated(() => {
  // keep-alive 重新激活时刷新数据集列表
  loadMiningRawData()
})

// 清理图表实例与 resize 事件
onBeforeUnmount(() => {
  if (clusterChartInstance) {
    clusterChartInstance.dispose()
    clusterChartInstance = null
  }
  window.removeEventListener('resize', handleChartResize)
})
</script>

<style scoped>
.data-mining {
  max-width: 100%;
}

.mining-layout {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.mining-tabs {
  margin-bottom: 16px;
}

:deep(.mining-tabs .el-tabs__header) {
  margin-bottom: 0;
}

:deep(.mining-tabs .el-tabs__item) {
  padding: 0 16px;
}

.tab-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.help-icon {
  color: #909399;
  cursor: help;
  margin-left: 2px;
  font-size: 13px;
}

.param-group {
  padding: 12px 0;
}

.param-label {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 2px;
}

.param-value {
  font-size: 20px;
  font-weight: 600;
  color: var(--primary);
  margin-bottom: 8px;
  text-align: center;
}

.param-value-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.param-value-row .param-value {
  flex: 1;
  text-align: left;
  margin-bottom: 0;
}

.param-hint {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
  color: var(--text-muted);
  background: var(--bg-light, #f8fafc);
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  margin-top: 8px;
  line-height: 1.6;
}

.param-hint .el-icon {
  flex-shrink: 0;
  color: var(--primary);
  margin-top: 2px;
}

.execute-section {
  padding-top: 16px;
  border-top: 1px solid #e5e7eb;
  margin-top: 8px;
}

.block-reason {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding: 8px 12px;
  background: #fef0f0;
  color: #f56c6c;
  font-size: 12px;
  border-radius: 4px;
}

.block-reason .el-icon {
  flex-shrink: 0;
  font-size: 14px;
}

.empty-hint {
  display: flex;
  align-items: center;
  gap: 6px;
}

.section-subtitle {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 12px;
  padding-left: 8px;
  border-left: 3px solid var(--primary);
}

/* ====== 预检卡片样式 ====== */
.precheck-card {
  border-left: 4px solid var(--primary);
}

.precheck-alert {
  margin-bottom: 8px;
}

.precheck-alert:last-child {
  margin-bottom: 0;
}

/* ====== 算法推荐样式 ====== */
.recommend-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 16px;
}

.recommend-item {
  border-radius: var(--radius-sm);
  padding: 16px;
  border: 1px solid #e5e7eb;
  background: #fafbfc;
  transition: box-shadow var(--transition), transform var(--transition);
}

.recommend-item:hover {
  box-shadow: var(--card-shadow);
}

.recommend-yes {
  border-color: #b7eb8f;
  background: #f6ffed;
}

.recommend-no {
  border-color: #ffa39e;
  background: #fff1f0;
}

.recommend-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.recommend-icon {
  font-size: 18px;
}

.recommend-yes .recommend-icon {
  color: var(--success, #10b981);
}

.recommend-no .recommend-icon {
  color: var(--danger, #ef4444);
}

.recommend-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.recommend-body {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.recommend-algos {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.recommend-reason {
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.7;
}

/* ====== 高级设置样式 ====== */
.advanced-settings {
  margin-top: 8px;
  border-top: 1px dashed #e5e7eb;
  padding-top: 8px;
}

.advanced-settings :deep(.el-collapse-item__header) {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
}

.advanced-settings :deep(.el-collapse-item__content) {
  padding-bottom: 0;
}

/* ====== 推荐信息提示 ====== */
.recommend-info {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
  color: var(--primary);
  background: var(--primary-light, #eef1fd);
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  margin-top: 8px;
  line-height: 1.6;
}

.recommend-info .el-icon {
  flex-shrink: 0;
  margin-top: 2px;
}

/* ====== 结果 Tab 样式 ====== */
.result-tabs {
  margin-top: 8px;
}

:deep(.result-tabs .el-tabs__header) {
  margin-bottom: 12px;
}

/* ====== 图表区域样式 ====== */
.chart-area {
  width: 100%;
  min-height: 400px;
  border: 1px solid #e5e7eb;
  border-radius: var(--radius-sm);
  padding: 16px;
  background: #fff;
}

/* ====== 评估指标行 ====== */
.metric-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: #f8fafc;
  border-radius: var(--radius-sm);
}

.metric-label {
  font-size: 14px;
  color: var(--text-secondary);
}

.metric-value {
  font-size: 20px;
  font-weight: 600;
  color: var(--primary);
}

/* ====== 序列 tag 样式 ====== */
.seq-tag {
  margin-right: 4px;
  margin-bottom: 4px;
}

.mt-md {
  margin-top: 20px;
}

.mb-md {
  margin-bottom: 20px;
}

.gap-sm {
  gap: 8px;
}

.flex-center {
  display: flex;
  align-items: center;
}

/* ====== 滑块数字显示修复 ====== */
.param-group :deep(.el-slider) {
  margin: 16px 0 20px 0;
  padding: 0 10px;
}

.param-group :deep(.el-slider__runway) {
  margin: 0;
  height: 4px;
}

.param-group :deep(.el-slider__bar) {
  height: 4px;
}

/* 滑块按钮：倒三角样式（Element Plus的按钮类名是 el-slider__button） */
.param-group :deep(.el-slider__button) {
  width: 0 !important;
  height: 0 !important;
  border-left: 6px solid transparent !important;
  border-right: 6px solid transparent !important;
  border-top: 8px solid var(--primary) !important;
  margin-top: -4px;
  margin-left: -6px;
  background: transparent !important;
  border-radius: 0 !important;
  box-shadow: none !important;
  transition: none !important;
}

.param-group :deep(.el-slider__button::after) {
  display: none !important;
}

.param-group :deep(.el-slider__button-wrapper) {
  transform: translateY(-50%);
  height: 16px;
  width: 16px;
}

.param-group :deep(.el-slider__input) {
  width: 70px;
  margin-left: 12px;
}

.param-group :deep(.el-slider__text) {
  font-size: 12px;
  color: var(--text-secondary);
}

/* marks刻度文字位置调整，防止截断 */
.param-group :deep(.el-slider__marks) {
  top: -22px;
  left: 0;
  right: 0;
}

.param-group :deep(.el-slider__marks-text) {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}

/* 首尾marks文字额外缩进，防止被容器边缘截断 */
.param-group :deep(.el-slider__marks-text:first-child) {
  margin-left: 2px;
}
.param-group :deep(.el-slider__marks-text:last-child) {
  margin-right: 2px;
  transform: translateX(0);
}
</style>
