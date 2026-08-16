<template>
  <div class="feature-engineering">
    <!-- ========== 数据上传 ========== -->
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
        :disabled="uploading"
      >
        <el-icon class="upload-icon" :size="48"><UploadFilled /></el-icon>
        <div class="upload-text">拖拽文件到此处，或 <em>点击上传</em></div>
        <div class="upload-hint">支持 CSV、Excel (.xlsx/.xls)、JSON 格式，最大 100MB</div>
      </el-upload>
      <div v-if="uploadFile" class="flex-center gap-sm mt-sm">
        <el-tag type="info" effect="plain">{{ uploadFile.name }}</el-tag>
        <el-button type="primary" size="small" @click="doUpload" :loading="uploading">
          <el-icon><Upload /></el-icon>
          开始上传
        </el-button>
        <el-button size="small" @click="cancelUpload">取消</el-button>
      </div>
    </div>

    <!-- ========== 选择数据集 ========== -->
    <div class="card">
      <div class="card-title">
        <el-icon><Folder /></el-icon>
        <span>选择数据集</span>
      </div>
      <DataSourceSelector
        ref="dataSourceSelectorRef"
        module-source="feature_engineering"
        @select="onSourceSelect"
      />
      <!-- 数据预览：选择数据集后自动加载 -->
      <DataPreview
        v-if="hasDataSource"
        :columns="dsPreviewColumns"
        :rows="dsPreviewRows"
        :loading="dsPreviewLoading"
        :total="dsPreviewTotal"
        :empty-text="dsPreviewEmptyText"
      />
      <!-- 无可用数据的空状态提示 -->
      <div v-if="availableDatasets.length === 0 && !datasetsLoading" class="empty-hint" style="margin-top:10px;color:var(--text-muted);">
        <el-icon><UploadFilled /></el-icon>
        <span>暂无可用数据，请先上传文件</span>
      </div>
    </div>

    <!-- ========== 列池管理 ========== -->
    <div v-if="currentColumns.length > 0" class="card">
      <!-- 预检结果摘要 -->
      <div v-if="precheckResult && precheckResult.summary" class="precheck-summary">
        <div class="precheck-summary-header">
          <el-icon v-if="precheckLoading" class="is-loading"><Loading /></el-icon>
          <span style="font-weight:600;">数据质量预检</span>
          <el-tag size="small" type="info">{{ precheckResult.row_count }} 行 × {{ precheckResult.column_count }} 列</el-tag>
        </div>
        <div class="precheck-summary-body">
          <el-tag v-if="precheckResult.summary.columns_with_nan > 0" type="warning" size="small">
            缺失值列: {{ precheckResult.summary.columns_with_nan }}
          </el-tag>
          <el-tag v-if="precheckResult.summary.columns_with_inf > 0" type="danger" size="small">
            无穷大列: {{ precheckResult.summary.columns_with_inf }}
          </el-tag>
          <el-tag v-if="precheckResult.summary.constant_columns > 0" type="warning" size="small">
            常量列: {{ precheckResult.summary.constant_columns }}
          </el-tag>
          <el-tag v-if="precheckResult.summary.high_cardinality_columns > 0" type="warning" size="small">
            高基数列: {{ precheckResult.summary.high_cardinality_columns }}
          </el-tag>
          <el-tag v-if="precheckResult.summary.columns_with_nan === 0 && precheckResult.summary.columns_with_inf === 0 && precheckResult.summary.constant_columns === 0" type="success" size="small">
            数据质量良好
          </el-tag>
        </div>
        <div v-if="precheckResult.recommendations && precheckResult.recommendations.length > 0" class="precheck-recommendations">
          <span v-for="(rec, i) in precheckResult.recommendations" :key="i" class="precheck-rec-item">
            <el-icon style="color:#909399;font-size:12px;"><QuestionFilled /></el-icon>{{ rec }}
          </span>
        </div>
      </div>
      <div class="card-header">
        <span class="card-title">列池管理 ({{ currentColumns.length }} 列)</span>
        <div style="display: flex; gap: 8px;">
          <el-button type="success" size="small" @click="openExportDialog">
            导出产物
          </el-button>
          <el-button size="small" @click="refreshColumnPool">
            刷新列池
          </el-button>
        </div>
      </div>
      <!-- 按模块分组显示 -->
      <div v-for="group in columnGroups" :key="group.key" class="pool-group">
        <div class="pool-group-header">
          <span class="pool-group-label">{{ group.label }}</span>
          <span class="pool-group-count">{{ group.columns.length }} 列</span>
        </div>
        <div style="display: flex; flex-wrap: wrap; gap: 8px;">
          <el-tag
            v-for="col in group.columns"
            :key="col.name"
            :type="col.tagType"
            closable
            :disable-transitions="false"
            size="default"
            @close="deleteColumn(col)"
            @dblclick="startRenameColumn(col)"
          >
            <span v-if="renamingCol === col.name" style="display:inline-flex;align-items:center;gap:4px;">
              <input
                v-model="renameValue"
                style="width:100px;border:1px solid #409eff;border-radius:3px;padding:2px 4px;"
                @keyup.enter="confirmRename(col)"
                @blur="confirmRename(col)"
                @keyup.escape="cancelRename"
                ref="renameInput"
              />
            </span>
            <template v-else>
              <el-tooltip :content="col.tooltip + (col.hasIssue ? '｜' + getColumnIssueText(col) : '')" placement="top">
                <span :style="{ color: col.tagColor }">{{ col.name }}</span>
              </el-tooltip>
              <span style="color:#909399;font-size:11px;margin-left:4px;">({{ col.type || col.dtype }})</span>
              <!-- 有问题的列显示警告图标 -->
              <el-tooltip v-if="col.hasIssue" :content="getColumnIssueText(col)" placement="top">
                <el-icon style="color:#e6a23c;margin-left:2px;font-size:12px;"><WarningFilled /></el-icon>
              </el-tooltip>
            </template>
          </el-tag>
        </div>
      </div>
      <div style="margin-top: 8px; color: #909399; font-size: 12px;">
        提示：双击列名可重命名，点击 × 可删除列（仅非原始列可删除），列池只能通过模块操作增加
      </div>
    </div>

    <!-- ========== 步骤2: 特征构造 ========== -->
    <div v-if="currentColumns.length > 0" class="card">
      <div class="card-header">
        <span class="card-title">模块1: 特征构造
          <el-tooltip content="通过四则运算、多项式、对数变换、分箱、时间拆解、类别交叉、Target编码等构造新特征" placement="top">
            <el-icon style="color:#909399;cursor:help;font-size:14px;"><QuestionFilled /></el-icon>
          </el-tooltip>
        </span>
      </div>

      <!-- 四则运算 -->
      <div class="section">
        <div class="section-header">
          <span>四则运算<span style="color:#909399;font-size:12px;margin-left:4px;">（支持常数，如 age + 10）</span></span>
          <el-tag v-if="getSubOperationStatus('arithmetic')" :type="getSubOperationStatus('arithmetic').type" size="small">
            {{ getSubOperationStatus('arithmetic').text }}
          </el-tag>
          <el-button size="small" :disabled="getSubOperationStatus('arithmetic')?.type === 'danger'" @click="addArithmeticRow">添加运算</el-button>
        </div>
        <div class="help-hint">对两列进行加减乘除运算生成新特征，col2 可直接输入数字作为常数</div>
        <div v-for="(row, idx) in arithmeticRows" :key="idx" class="operation-row">
          <el-input v-model="row.name" placeholder="新特征名称" style="width: 150px;" size="small" />
          <el-select v-model="row.col1" placeholder="列1" style="width: 200px;" size="small">
            <el-option v-for="c in currentColumns" :key="c.name" :label="c.name" :value="c.name">
              <span>{{ c.name }}</span>
              <el-tag :type="getColumnStatusTagType(c, 'arithmetic')" size="small" style="margin-left:8px;">{{ getColumnStatusText(c, 'arithmetic') }}</el-tag>
              <span style="color:#909399;font-size:11px;margin-left:4px;">({{ c.type }})</span>
            </el-option>
          </el-select>
          <el-select v-model="row.op" style="width: 60px;" size="small">
            <el-option v-for="o in ['+','-','*','/']" :key="o" :label="o" :value="o" />
          </el-select>
          <el-autocomplete
            v-model="row.col2"
            :fetch-suggestions="(q, cb) => cb(currentColumns.filter(c => c.name.includes(q)).map(c => ({value: c.name})))"
            placeholder="列名或常数"
            style="width: 130px;"
            size="small"
          />
          <span v-if="row.col1 && row.op && row.col2" class="name-preview">默认: fe_{{ row.col1 }}_{{ row.op }}_{{ row.col2 }}</span>
          <el-button size="small" type="danger" @click="arithmeticRows.splice(idx, 1)">删除</el-button>
        </div>
      </div>

      <!-- 多项式 + 对数变换 -->
      <div class="section">
        <div class="section-header">
          <span>多项式特征 / 对数变换</span>
          <el-tag v-if="getSubOperationStatus('polynomial')" :type="getSubOperationStatus('polynomial').type" size="small">
            {{ getSubOperationStatus('polynomial').text }}
          </el-tag>
          <el-button size="small" :disabled="getSubOperationStatus('polynomial')?.type === 'danger'" @click="addPolyRow">添加</el-button>
        </div>
        <div class="help-hint">多项式: 生成 x², x³ 等高次幂特征；对数变换: 对数值取 log(1+x)，用于压缩大值范围、处理偏态分布</div>
        <div v-for="(row, idx) in polyRows" :key="idx" class="operation-row">
          <el-select v-model="row.type" style="width: 120px;" size="small">
            <el-option label="多项式" value="polynomial" />
            <el-option label="对数变换" value="log_transform" />
          </el-select>
          <el-select v-model="row.column" placeholder="选择列" style="width: 200px;" size="small">
            <el-option v-for="c in numericColumns" :key="c.name" :label="c.name" :value="c.name" :disabled="getColumnStatusForOperation(c, 'polynomial') === 'unavailable'">
              <span>{{ c.name }}</span>
              <el-tag :type="getColumnStatusTagType(c, 'polynomial')" size="small" style="margin-left:8px;">{{ getColumnStatusText(c, 'polynomial') }}</el-tag>
              <span style="color:#909399;font-size:11px;margin-left:4px;">({{ c.type }})</span>
            </el-option>
          </el-select>
          <el-input-number v-if="row.type === 'polynomial'" v-model="row.degree" :min="2" :max="5" size="small" style="width: 80px;" />
          <el-input v-model="row.name" placeholder="新列名(可选)" style="width: 150px;" size="small" />
          <span v-if="row.column" class="name-preview">
            默认: {{ row.type === 'log_transform' ? `fe_log_${row.column}` : polyDefaultNames(row) }}
          </span>
          <el-button size="small" type="danger" @click="polyRows.splice(idx, 1)">删除</el-button>
        </div>
      </div>

      <!-- 分箱 -->
      <div class="section">
        <div class="section-header">
          <span>分箱
            <el-tooltip placement="top" effect="light">
              <template #content>
                <div style="max-width:400px;line-height:1.6;">
                  <strong>名词解释：</strong>将连续数值离散化为若干区间（箱），每个样本落入一个箱<br>
                  <strong>等宽分箱：</strong>按值范围均匀分段，每箱宽度相同<br>
                  <strong>等频分箱：</strong>每箱包含相同数量样本，箱宽度可能不同<br>
                  <strong>核心缺陷：</strong>等宽对异常值敏感（极端值导致某些箱几乎空）；等频可能切断重要边界<br>
                  <strong>适用数据：</strong>连续数值型特征，特别是有非线性关系的特征<br>
                  <strong>适用场景：</strong>决策树/随机森林（减少过拟合）、评分卡模型、数据可视化
                </div>
              </template>
              <el-icon style="color:#909399;cursor:help;font-size:14px;"><QuestionFilled /></el-icon>
            </el-tooltip>
          </span>
          <el-tag v-if="getSubOperationStatus('binning')" :type="getSubOperationStatus('binning').type" size="small">
            {{ getSubOperationStatus('binning').text }}
          </el-tag>
          <el-button size="small" :disabled="getSubOperationStatus('binning')?.type === 'danger'" @click="addBinningRow">添加分箱</el-button>
        </div>
        <div class="help-hint">将连续数值离散化为区间。等宽=按值范围均匀分段，等频=每段包含相同数量样本</div>
        <div v-for="(row, idx) in binningRows" :key="idx" class="operation-row">
          <el-select v-model="row.column" placeholder="选择列" style="width: 200px;" size="small">
            <el-option v-for="c in numericColumns" :key="c.name" :label="c.name" :value="c.name" :disabled="getColumnStatusForOperation(c, 'binning') === 'unavailable'">
              <span>{{ c.name }}</span>
              <el-tag :type="getColumnStatusTagType(c, 'binning')" size="small" style="margin-left:8px;">{{ getColumnStatusText(c, 'binning') }}</el-tag>
              <span style="color:#909399;font-size:11px;margin-left:4px;">({{ c.type }})</span>
            </el-option>
          </el-select>
          <el-input-number v-model="row.bins" :min="2" :max="20" size="small" style="width: 80px;" />
          <el-select v-model="row.method" style="width: 120px;" size="small">
            <el-option label="等宽分箱" value="equal_width" />
            <el-option label="等频分箱" value="equal_freq" />
          </el-select>
          <el-input v-model="row.name" placeholder="新列名(可选)" style="width: 150px;" size="small" />
          <span v-if="row.column" class="name-preview">默认: fe_{{ row.column }}_{{ row.method === 'equal_freq' ? 'ef' : 'ew' }}_bin</span>
          <el-button size="small" type="danger" @click="binningRows.splice(idx, 1)">删除</el-button>
        </div>
      </div>

      <!-- 时间拆解 -->
      <div class="section">
        <div class="section-header">
          <span>时间拆解</span>
          <el-tag v-if="getSubOperationStatus('time')" :type="getSubOperationStatus('time').type" size="small">
            {{ getSubOperationStatus('time').text }}
          </el-tag>
          <el-button size="small" :disabled="getSubOperationStatus('time')?.type === 'danger'" @click="addTimeRow">添加时间拆解</el-button>
        </div>
        <div class="help-hint">从日期列中提取年/月/日/星期/季度/是否周末，每选一项生成一列新特征</div>
        <div v-for="(row, idx) in timeRows" :key="idx" class="operation-row">
          <el-select v-model="row.column" placeholder="选择列" style="width: 200px;" size="small">
            <el-option v-for="c in currentColumns" :key="c.name" :label="c.name" :value="c.name" :disabled="getColumnStatusForOperation(c, 'time') === 'unavailable'">
              <span>{{ c.name }}</span>
              <el-tag :type="getColumnStatusTagType(c, 'time')" size="small" style="margin-left:8px;">{{ getColumnStatusText(c, 'time') }}</el-tag>
              <span style="color:#909399;font-size:11px;margin-left:4px;">({{ c.type }})</span>
            </el-option>
          </el-select>
          <el-checkbox-group v-model="row.extract" size="small" style="display:inline-flex;flex-wrap:wrap;gap:4px;">
            <el-checkbox label="year" size="small">年</el-checkbox>
            <el-checkbox label="month" size="small">月</el-checkbox>
            <el-checkbox label="day" size="small">日</el-checkbox>
            <el-checkbox label="weekday" size="small">星期</el-checkbox>
            <el-checkbox label="quarter" size="small">季度</el-checkbox>
            <el-checkbox label="is_weekend" size="small">是否周末</el-checkbox>
          </el-checkbox-group>
          <span v-if="row.column && row.extract.length > 0" class="name-preview">
            默认列名: {{ row.extract.map(e => `fe_${row.column}_${e}`).join(', ') }}
          </span>
          <el-button size="small" type="danger" @click="timeRows.splice(idx, 1)">删除</el-button>
        </div>
      </div>

      <!-- 类别交叉 -->
      <div class="section">
        <div class="section-header">
          <span>类别交叉
            <el-tooltip placement="top" effect="light">
              <template #content>
                <div style="max-width:400px;line-height:1.6;">
                  <strong>名词解释：</strong>组合多个类别列生成新特征，如 city+job → "北京_工程师"<br>
                  <strong>核心作用：</strong>捕捉多个类别特征之间的交互信息，单列无法表达的组合模式<br>
                  <strong>适用数据：</strong>两个或多个类别型（字符串）列<br>
                  <strong>适用场景：</strong>决策树/随机森林、推荐系统、需要捕捉特征交互的场景<br>
                  <strong>注意事项：</strong>组合后唯一值数量可能急剧增加（city×job可能产生上千种组合）
                </div>
              </template>
              <el-icon style="color:#909399;cursor:help;font-size:14px;"><QuestionFilled /></el-icon>
            </el-tooltip>
          </span>
          <el-tag v-if="getSubOperationStatus('cross')" :type="getSubOperationStatus('cross').type" size="small">
            {{ getSubOperationStatus('cross').text }}
          </el-tag>
          <el-button size="small" :disabled="getSubOperationStatus('cross')?.type === 'danger'" @click="addCategoryCrossRow">添加</el-button>
        </div>
        <div class="help-hint">组合多个文本列生成新特征（如 city+job → "北京_工程师"），需选择≥2个类别列</div>
        <div v-for="(row, idx) in categoryCrossRows" :key="idx" class="operation-row">
          <el-select v-model="row.columns" multiple placeholder="选择列(≥2个)" style="width: 280px;" size="small">
            <el-option v-for="c in stringColumns" :key="c.name" :label="c.name" :value="c.name" :disabled="getColumnStatusForOperation(c, 'cross') === 'unavailable'">
              <span>{{ c.name }}</span>
              <el-tag :type="getColumnStatusTagType(c, 'cross')" size="small" style="margin-left:8px;">{{ getColumnStatusText(c, 'cross') }}</el-tag>
              <span style="color:#909399;font-size:11px;margin-left:4px;">({{ c.type }})</span>
            </el-option>
          </el-select>
          <el-input v-model="row.name" placeholder="新列名(可选)" style="width: 150px;" size="small" />
          <span v-if="row.columns.length >= 2" class="name-preview">
            默认: fe_{{ row.columns.join('_') }}_cross
          </span>
          <el-button size="small" type="danger" @click="categoryCrossRows.splice(idx, 1)">删除</el-button>
        </div>
      </div>

      <!-- Target编码 -->
      <div class="section">
        <div class="section-header">
          <span>Target编码
            <el-tooltip placement="top" effect="light">
              <template #content>
                <div style="max-width:400px;line-height:1.6;">
                  <strong>名词解释：</strong>用目标变量的均值替换类别值，如"北京"→北京地区的平均收入<br>
                  <strong>核心缺陷：</strong>容易过拟合（小样本类别均值不稳定）、需要目标变量、泄露目标信息<br>
                  <strong>适用数据：</strong>高基数类别特征（类别数很多，One-Hot会产生太多列）<br>
                  <strong>适用场景：</strong>回归问题、Kaggle竞赛、需要压缩高基数类别的场景<br>
                  <strong>注意事项：</strong>需要指定一个数值型目标列，编码后的值反映该类别对目标的平均影响
                </div>
              </template>
              <el-icon style="color:#909399;cursor:help;font-size:14px;"><QuestionFilled /></el-icon>
            </el-tooltip>
          </span>
          <el-tag v-if="getSubOperationStatus('target_encoding')" :type="getSubOperationStatus('target_encoding').type" size="small">
            {{ getSubOperationStatus('target_encoding').text }}
          </el-tag>
          <el-button size="small" :disabled="getSubOperationStatus('target_encoding')?.type === 'danger'" @click="addTargetEncodingRow">添加</el-button>
        </div>
        <div class="help-hint">用目标列的均值替换类别值，需选择一个类别列和一个数值型目标列</div>
        <div v-for="(row, idx) in targetEncodingRows" :key="idx" class="operation-row">
          <el-select v-model="row.column" placeholder="编码列(类别)" style="width: 180px;" size="small">
            <el-option v-for="c in stringColumns" :key="c.name" :label="c.name" :value="c.name" :disabled="getColumnStatusForOperation(c, 'target_encoding') === 'unavailable'">
              <span>{{ c.name }}</span>
              <el-tag :type="getColumnStatusTagType(c, 'target_encoding')" size="small" style="margin-left:8px;">{{ getColumnStatusText(c, 'target_encoding') }}</el-tag>
              <span style="color:#909399;font-size:11px;margin-left:4px;">({{ c.type }})</span>
            </el-option>
          </el-select>
          <el-select v-model="row.target_column" placeholder="目标列(数值)" style="width: 180px;" size="small">
            <el-option v-for="c in numericColumns" :key="c.name" :label="c.name" :value="c.name" :disabled="getColumnStatusForOperation(c, 'arithmetic') === 'unavailable'">
              <span>{{ c.name }}</span>
              <el-tag :type="getColumnStatusTagType(c, 'arithmetic')" size="small" style="margin-left:8px;">{{ getColumnStatusText(c, 'arithmetic') }}</el-tag>
              <span style="color:#909399;font-size:11px;margin-left:4px;">({{ c.type }})</span>
            </el-option>
          </el-select>
          <el-input v-model="row.name" placeholder="新列名(可选)" style="width: 150px;" size="small" />
          <span v-if="row.column && row.target_column" class="name-preview">
            默认: fe_{{ row.column }}_target_enc
          </span>
          <el-button size="small" type="danger" @click="targetEncodingRows.splice(idx, 1)">删除</el-button>
        </div>
      </div>

      <el-button type="primary" :loading="constructing" @click="executeConstruct" style="margin-top: 12px;">
        执行特征构造
      </el-button>
      <div v-if="constructResult" style="margin-top: 8px; color: #67c23a;">
        {{ constructResult }}
      </div>
    </div>

    <!-- ========== 模块2: 特征编码 ========== -->
    <div v-if="currentColumns.length > 0" class="card">
      <div class="card-header">
        <span class="card-title">模块2: 特征编码
          <el-tooltip placement="top" effect="light">
            <template #content>
              <div style="max-width:450px;line-height:1.6;">
                <strong>One-Hot编码：</strong>每个类别生成一列0/1，如"红/绿/蓝"→红=1,绿=0,蓝=0<br>
                <strong>核心缺陷：</strong>高基数特征会产生大量列（维度爆炸）、稀疏矩阵占用空间<br>
                <strong>适用数据：</strong>低基数类别特征（类别数≤10-20）<br>
                <strong>适用场景：</strong>线性模型、神经网络、无序类别特征<br><br>
                <strong>Label编码：</strong>每个类别映射为整数0,1,2...，如"红/绿/蓝"→0,1,2<br>
                <strong>核心缺陷：</strong>引入虚假顺序关系（模型可能认为2>1），不适合线性模型<br>
                <strong>适用数据：</strong>有序类别特征或高基数特征<br>
                <strong>适用场景：</strong>决策树/随机森林/XGBoost（不依赖数值大小）
              </div>
            </template>
            <el-icon style="color:#909399;cursor:help;font-size:14px;"><QuestionFilled /></el-icon>
          </el-tooltip>
        </span>
        <el-tag v-if="getOperationStatus('encode')" :type="getOperationStatus('encode').type" size="small" style="margin-left:8px;">
          {{ getOperationStatus('encode').text }}
        </el-tag>
      </div>
      <div class="section">
        <div class="section-header">
          <span>选择要编码的列</span>
          <el-button size="small" @click="addEncodeRow">添加编码</el-button>
        </div>
        <div class="help-hint">One-Hot编码: 生成多个 ohe_ 前缀列，保留原列；Label编码: 生成一个 le_ 前缀列，类别映射为 0,1,2...</div>
        <div v-for="(row, idx) in encodeRows" :key="idx" class="operation-row">
          <el-select v-model="row.column" placeholder="选择列" style="width: 200px;" size="small">
            <el-option v-for="c in stringColumns" :key="c.name" :label="c.name" :value="c.name" :disabled="getColumnStatusForOperation(c, 'encode') === 'unavailable'">
              <span>{{ c.name }}</span>
              <el-tag :type="getColumnStatusTagType(c, 'encode')" size="small" style="margin-left:8px;">{{ getColumnStatusText(c, 'encode') }}</el-tag>
              <span style="color:#909399;font-size:11px;margin-left:4px;">({{ c.type }})</span>
            </el-option>
          </el-select>
          <el-select v-model="row.method" style="width: 120px;" size="small">
            <el-option label="One-Hot" value="onehot" />
            <el-option label="Label" value="label" />
          </el-select>
          <el-input v-model="row.name" placeholder="新列名前缀(可选)" style="width: 160px;" size="small" />
          <span v-if="row.column" class="name-preview">
            默认: {{ row.method === 'onehot' ? `ohe_${row.column}_类别名` : `le_${row.column}` }}
          </span>
          <el-button size="small" type="danger" @click="encodeRows.splice(idx, 1)">删除</el-button>
        </div>
      </div>
      <el-button type="primary" :loading="encoding" :disabled="getOperationStatus('encode')?.type === 'danger'" @click="executeEncode" style="margin-top: 12px;">
        执行特征编码
      </el-button>
      <div v-if="encodeResult" style="margin-top: 8px; color: #67c23a;">
        {{ encodeResult }}
      </div>
    </div>

    <!-- ========== 模块3: 特征缩放 ========== -->
    <div v-if="currentColumns.length > 0" class="card">
      <div class="card-header">
        <span class="card-title">模块3: 特征缩放
          <el-tooltip placement="top" effect="light">
            <template #content>
              <div style="max-width:450px;line-height:1.6;">
                <strong>StandardScaler（标准化）：</strong>将数据转换为均值=0、标准差=1的分布<br>
                <strong>核心缺陷：</strong>对异常值敏感（异常值会拉偏均值和标准差）、不保证固定范围<br>
                <strong>适用数据：</strong>近似正态分布的数据、无明显异常值的数值特征<br>
                <strong>适用场景：</strong>PCA降维、SVM、逻辑回归、线性回归（假设数据正态）<br><br>
                <strong>MinMaxScaler（归一化）：</strong>将数据缩放到[0,1]区间，公式：(x-min)/(max-min)<br>
                <strong>核心缺陷：</strong>对异常值极度敏感（极端值会压缩大部分数据到很小范围）<br>
                <strong>适用数据：</strong>分布不均匀但无极端异常值、需要固定范围的特征<br>
                <strong>适用场景：</strong>神经网络/深度学习、图像处理、需要固定输入范围的模型
              </div>
            </template>
            <el-icon style="color:#909399;cursor:help;font-size:14px;"><QuestionFilled /></el-icon>
          </el-tooltip>
        </span>
        <el-tag v-if="getOperationStatus('scale')" :type="getOperationStatus('scale').type" size="small" style="margin-left:8px;">
          {{ getOperationStatus('scale').text }}
        </el-tag>
      </div>
      <div class="help-hint" style="margin-bottom:8px;">StandardScaler(标准化): 均值0方差1，适合PCA、SVM、逻辑回归；MinMaxScaler(归一化): 缩放到[0,1]，适合神经网络</div>
      <div class="operation-row">
        <el-select v-model="scaleMethod" style="width: 150px;" size="small">
          <el-option label="StandardScaler" value="standard" />
          <el-option label="MinMaxScaler" value="minmax" />
        </el-select>
        <el-select v-model="scaleColumns" multiple placeholder="选择列(空=全部数值)" style="width: 400px;" size="small">
          <el-option v-for="c in numericColumns" :key="c.name" :label="c.name" :value="c.name" :disabled="getColumnStatusForOperation(c, 'scale') === 'unavailable'">
            <span>{{ c.name }}</span>
            <el-tag :type="getColumnStatusTagType(c, 'scale')" size="small" style="margin-left:8px;">{{ getColumnStatusText(c, 'scale') }}</el-tag>
            <span style="color:#909399;font-size:11px;margin-left:4px;">({{ c.type }})</span>
          </el-option>
        </el-select>
      </div>
      <div v-if="scaleColumns.length > 0" class="name-preview" style="margin-top:4px;">
        默认列名: {{ scaleColumns.map(c => `${scaleMethod === 'standard' ? 'std' : 'norm'}_${c}`).join(', ') }}
      </div>
      <el-button type="primary" :loading="scaling" :disabled="getOperationStatus('scale')?.type === 'danger'" @click="executeScale" style="margin-top: 12px;">
        执行特征缩放
      </el-button>
      <div v-if="scaleResult" style="margin-top: 8px; color: #67c23a;">
        {{ scaleResult }}
      </div>
    </div>

    <!-- ========== 模块4: 特征降维 ========== -->
    <div v-if="currentColumns.length > 0" class="card">
      <div class="card-header">
        <span class="card-title">模块4: 特征降维
          <el-tooltip placement="top" effect="light">
            <template #content>
              <div style="max-width:450px;line-height:1.6;">
                <strong>PCA（主成分分析）：</strong>线性降维，保留数据最大方差方向，生成正交主成分<br>
                <strong>核心缺陷：</strong>只能捕捉线性关系、对异常值敏感、主成分可解释性差<br>
                <strong>适用数据：</strong>线性相关性强的高维数值数据、特征间存在多重共线性<br>
                <strong>适用场景：</strong>数据压缩、去噪、可视化、作为其他模型的预处理<br><br>
                <strong>t-SNE（t-分布随机邻域嵌入）：</strong>非线性降维，保留局部结构，适合高维可视化<br>
                <strong>核心缺陷：</strong>计算复杂度高（大数据集很慢）、结果不稳定（每次运行不同）、不保留全局结构<br>
                <strong>适用数据：</strong>高维数据（通常n_components=2或3用于可视化）<br>
                <strong>适用场景：</strong>数据可视化、聚类探索、发现数据流形结构<br>
                <strong>注意：</strong>通常只用于可视化分析，不建议用于下游建模
              </div>
            </template>
            <el-icon style="color:#909399;cursor:help;font-size:14px;"><QuestionFilled /></el-icon>
          </el-tooltip>
        </span>
        <el-tag v-if="getOperationStatus('reduce')" :type="getOperationStatus('reduce').type" size="small" style="margin-left:8px;">
          {{ getOperationStatus('reduce').text }}
        </el-tag>
      </div>
      <el-alert
        type="info"
        :closable="false"
        style="margin-bottom:8px;"
        title="建议先执行特征缩放（模块3）再降维，以获得更好的降维效果"
      />
      <div class="help-hint" style="margin-bottom:8px;">PCA: 线性降维，输出各主成分解释方差比；t-SNE: 非线性降维，适合可视化（n_components ≤ 3）</div>
      <div class="operation-row">
        <el-select v-model="reduceMethod" style="width: 120px;" size="small">
          <el-option label="PCA" value="pca" />
          <el-option label="t-SNE" value="tsne" />
        </el-select>
        <el-input-number v-model="reduceNComponents" :min="1" :max="10" size="small" style="width: 180px;" />
        <span style="color:#909399;font-size:13px;">个组件</span>
        <el-select v-model="reduceColumns" multiple placeholder="选择列(空=全部数值)" style="width: 400px;" size="small">
          <el-option v-for="c in numericColumns" :key="c.name" :label="c.name" :value="c.name" :disabled="getColumnStatusForOperation(c, 'reduce') === 'unavailable'">
            <span>{{ c.name }}</span>
            <el-tag :type="getColumnStatusTagType(c, 'reduce')" size="small" style="margin-left:8px;">{{ getColumnStatusText(c, 'reduce') }}</el-tag>
            <span style="color:#909399;font-size:11px;margin-left:4px;">({{ c.type }})</span>
          </el-option>
        </el-select>
      </div>
      <el-input v-model="reduceNamePrefix" placeholder="新列名前缀(可选，如 pca_)" style="width: 200px;margin-top:8px;" size="small" />
      <div v-if="reduceNComponents > 0" class="name-preview" style="margin-top:4px;">
        默认列名: {{ Array.from({length: reduceNComponents}, (_, i) => `${reduceMethod === 'pca' ? 'pca' : 'tsne'}_${i+1}`).join(', ') }}
      </div>
      <el-button type="primary" :loading="reducing" :disabled="getOperationStatus('reduce')?.type === 'danger'" @click="executeReduce" style="margin-top: 12px;">
        执行特征降维
      </el-button>
      <div v-if="reduceResult" style="margin-top: 8px; color: #67c23a;">
        {{ reduceResult }}
      </div>
    </div>

    <!-- ========== 模块5: 特征选择 ========== -->
    <div v-if="currentColumns.length > 0" class="card">
      <div class="card-header">
        <span class="card-title">模块5: 特征选择
          <el-tooltip placement="top" effect="light">
            <template #content>
              <div style="max-width:450px;line-height:1.6;">
                <strong>名词解释：</strong>根据特征与目标变量的相关性，选择最相关的特征子集<br>
                <strong>核心缺陷：</strong>可能遗漏交互特征、基于单变量统计可能忽略特征组合效果<br>
                <strong>适用数据：</strong>特征维度较高、可能存在冗余特征的数据<br>
                <strong>适用场景/模型：</strong>线性模型（减少多重共线性）、决策树类模型（减少过拟合）、特征数量远大于样本数量时<br><br>
                <strong>卡方检验：</strong>衡量分类特征与目标变量的独立性，适合分类任务<br>
                <strong>互信息：</strong>衡量两个变量之间的依赖关系，可捕捉非线性关系<br>
                <strong>皮尔逊相关：</strong>衡量线性相关性，适合回归任务<br>
                <strong>树模型重要性：</strong>基于随机森林的特征重要性，综合考虑特征贡献
              </div>
            </template>
            <el-icon style="color:#909399;cursor:help;font-size:14px;"><QuestionFilled /></el-icon>
          </el-tooltip>
        </span>
        <el-tag v-if="getOperationStatus('select_features')" :type="getOperationStatus('select_features').type" size="small" style="margin-left:8px;">
          {{ getOperationStatus('select_features').text }}
        </el-tag>
      </div>
      <div class="help-hint" style="margin-bottom:12px;">根据特征与目标变量的相关性，筛选出最相关的 Top-K 个特征</div>

      <!-- 目标列选择 -->
      <div class="operation-row" style="margin-bottom:12px;">
        <span style="color:#606266;font-size:13px;">目标列：</span>
        <el-select v-model="featureSelectTarget" placeholder="选择目标列" style="width: 280px;" size="small">
          <el-option v-for="c in currentColumns" :key="c.name" :label="c.name" :value="c.name" :disabled="getColumnStatusForOperation(c, 'select') === 'unavailable'">
            <span>{{ c.name }}</span>
            <el-tag :type="getColumnStatusTagType(c, 'select')" size="small" style="margin-left:8px;">{{ getColumnStatusText(c, 'select') }}</el-tag>
            <span style="color:#909399;font-size:11px;margin-left:4px;">({{ c.type }})</span>
          </el-option>
        </el-select>
        <el-select v-model="featureSelectTaskType" style="width: 120px;" size="small">
          <el-option label="分类任务" value="classification" />
          <el-option label="回归任务" value="regression" />
        </el-select>
      </div>

      <!-- 方法选择 -->
      <div class="operation-row" style="margin-bottom:12px;">
        <span style="color:#606266;font-size:13px;margin-right:8px;">方法：</span>
        <el-radio-group v-model="featureSelectMethod" size="small">
          <el-radio-button label="chi2">卡方检验</el-radio-button>
          <el-radio-button label="mutual_info">互信息</el-radio-button>
          <el-radio-button label="pearson">皮尔逊相关</el-radio-button>
          <el-radio-button label="tree">树模型重要性</el-radio-button>
        </el-radio-group>
      </div>

      <!-- 保留特征数滑块 -->
      <div style="margin-bottom:12px;">
        <span style="color:#606266;font-size:13px;">保留特征数：</span>
        <el-slider
          v-model="featureSelectTopK"
          :min="1"
          :max="Math.max(1, availableFeaturesForSelect.length)"
          style="width: 300px;display:inline-block;vertical-align:middle;margin-left:12px;"
          size="small"
        />
        <span style="color:#909399;font-size:12px;margin-left:12px;">{{ featureSelectTopK }} / {{ availableFeaturesForSelect.length }}</span>
      </div>

      <!-- 实时提示：选择目标列后剩余可用特征列数 -->
      <el-alert
        v-if="featureSelectTarget && availableFeaturesForSelect.length === 0"
        title="无可用特征列"
        type="error"
        :closable="false"
        show-icon
        style="margin-bottom:12px;"
        description="排除目标列和含缺失值/无穷大/常量的列后，没有可用的数值特征列。请更换目标列或先在数据清洗模块处理数据。"
      />
      <el-alert
        v-else-if="featureSelectTarget && availableFeaturesForSelect.length < numericColumns.length"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom:12px;"
        :title="`可用特征列：${availableFeaturesForSelect.length} / ${numericColumns.length}（已排除目标列和有质量问题的列）`"
      />

      <el-button type="primary" :loading="selectingFeatures" :disabled="selectButtonDisabled" @click="executeSelectFeatures" style="margin-bottom:12px;">
        开始特征选择
      </el-button>

      <!-- 特征重要性结果表格 -->
      <div v-if="featureSelectionResult" style="margin-top:12px;">
        <el-alert
          v-if="featureSelectionResult.excluded_columns?.length > 0"
          :title="`已自动排除 ${featureSelectionResult.excluded_columns.length} 个存在质量问题的特征列：${featureSelectionResult.excluded_details?.join('、') || ''}`"
          type="warning"
          :closable="false"
          show-icon
          style="margin-bottom: 12px;"
          description="这些列包含缺失值或无穷大值，未参与本次特征选择。建议先在数据清洗模块处理好数据后，重新执行特征选择以获得更完整的结果。"
        />
        <el-divider content-position="left">
          <span style="color:#409eff;font-weight:600;">特征选择结果</span>
          <span style="color:#909399;font-size:12px;margin-left:8px;">
            选中 {{ featureSelectionResult.selected_features?.length || 0 }} 个特征，共 {{ featureSelectionResult.total_features || 0 }} 个特征参与评估
          </span>
        </el-divider>
        <el-table :data="featureSelectionTableData" stripe size="small" max-height="300" style="width:100%;">
          <el-table-column prop="rank" label="排名" width="60" />
          <el-table-column prop="name" label="特征名" min-width="150" />
          <el-table-column prop="score" label="得分" min-width="100" sortable>
            <template #default="{ row }">
              {{ row.score.toFixed(4) }}
            </template>
          </el-table-column>
          <el-table-column prop="source" label="来源类型" width="100">
            <template #default="{ row }">
              <el-tag :type="row.sourceType" size="small">{{ row.source }}</el-tag>
            </template>
          </el-table-column>
        </el-table>

        <!-- 导出特征选择产物按钮 -->
        <div style="margin-top:12px;">
          <el-button type="success" :loading="exportingSelected" @click="executeExportSelected">
            导出特征选择产物
          </el-button>
        </div>
      </div>
    </div>

    <!-- ========== 导出对话框 ========== -->
    <el-dialog v-model="showExportDialog" title="导出自定义产物" width="680px">
      <p style="color:#606266;margin-bottom:12px;">从列池中选择需要的列，导出为 CSV 文件（按模块分类展示）</p>
      <!-- 顶部快捷操作 -->
      <div style="margin-bottom:12px;display:flex;gap:8px;align-items:center;">
        <el-button size="small" @click="exportSelectedColumns = currentColumns.map(c => c.name)">全选</el-button>
        <el-button size="small" @click="exportSelectedColumns = []">清空</el-button>
        <el-divider direction="vertical" />
        <el-button size="small" @click="exportSelectedColumns = currentColumns.filter(c => c.source === 'original').map(c => c.name)">仅原始列</el-button>
      </div>
      <!-- 按模块分组展示：全选 checkbox 在 el-checkbox-group 外，避免干扰 v-model -->
      <div v-for="group in exportableColumnGroups" :key="group.key" class="export-group">
        <div class="export-group-header">
          <el-checkbox
            :model-value="isGroupAllSelected(group)"
            :indeterminate="isGroupIndeterminate(group)"
            @change="toggleGroupSelection(group, $event)"
          >
            <span :style="{ color: group.color, fontWeight: 600 }">{{ group.label }}</span>
            <span style="color:#909399;font-size:12px;margin-left:4px;">({{ getGroupSelectedCount(group) }}/{{ group.columns.length }})</span>
          </el-checkbox>
        </div>
        <el-checkbox-group v-model="exportSelectedColumns" class="export-group-body">
          <el-checkbox
            v-for="col in group.columns"
            :key="col.name"
            :label="col.name"
            :value="col.name"
          >
            <el-tag :type="col.tagType" size="small">{{ col.name }}</el-tag>
            <span style="color:#909399;font-size:11px;margin-left:4px;">({{ col.type || col.dtype }})</span>
          </el-checkbox>
        </el-checkbox-group>
      </div>
      <template #footer>
        <span style="color:#909399;font-size:12px;margin-right:auto;">已选 {{ exportSelectedColumns.length }} / {{ currentColumns.length }} 列</span>
        <el-button @click="showExportDialog = false">取消</el-button>
        <el-button type="primary" :loading="exporting" @click="executeExport" :disabled="exportSelectedColumns.length === 0">
          导出 ({{ exportSelectedColumns.length }} 列)
        </el-button>
      </template>
    </el-dialog>

    <!-- ========== 数据预览对话框（后端分页） ========== -->
    <el-dialog v-model="showPreview" title="数据预览" width="80%" top="5vh">
      <el-table :data="previewRows" border stripe size="small" v-loading="previewLoading"
        style="width:100%;" max-height="500">
        <el-table-column type="index" label="#" width="50" fixed />
        <el-table-column
          v-for="col in previewColumns"
          :key="col"
          :prop="col"
          :label="col"
          min-width="120"
          show-overflow-tooltip
        />
      </el-table>
      <div class="flex-center mt-sm" style="justify-content: flex-end;">
        <el-pagination
          v-model:current-page="previewPage"
          v-model:page-size="previewPageSize"
          :page-sizes="[20, 50, 100]"
          :total="previewTotal"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="loadPreviewData"
          @size-change="loadPreviewData"
          small background
        />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onActivated, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { QuestionFilled, UploadFilled, Loading, WarningFilled } from '@element-plus/icons-vue'
import DataSourceSelector from '../components/DataSourceSelector.vue'
import DataPreview from '../components/DataPreview.vue'

// DataSourceSelector组件引用，用于上传后调用reload刷新下拉框
const dataSourceSelectorRef = ref(null)
import {
  fetchFeatureDatasets,
  fetchFeatureData,
  fetchColumnPool,
  fetchRemoteColumnPool,
  deleteConstructedColumn,
  deleteRemoteConstructedColumn,
  renameFeatureColumn,
  precheckFeatureDataset,
  constructFeatures,
  encodeFeatures,
  scaleFeatures,
  reduceFeatures,
  selectFeatures,
  uploadFeatureFile,
  exportSelectedFeatures,
  exportColumnPool,
  fetchDatasetData
} from '@/api'
import { addTask } from '../stores/taskPanel.js'

// 统一错误信息提取：优先取后端 message（用户友好），避免显示 detail（含 traceback）
function extractErrorMessage(e, defaultMsg = '操作失败') {
  return e?.response?.data?.message || e?.message || defaultMsg
}

// ========== 数据状态 ==========
const selectedDatasetId = ref(null)
const availableDatasets = ref([])
const datasetsLoading = ref(false)
const uploading = ref(false)

// 数据源配置（本地/远程模式）
const sourceConfig = ref({ mode: 'local', datasetId: null, remote: null })

// 是否已有有效数据源选择
const hasDataSource = computed(() => {
  if (sourceConfig.value.mode === 'local') return !!sourceConfig.value.datasetId
  if (sourceConfig.value.mode === 'remote') return !!(sourceConfig.value.remote?.connection_id && sourceConfig.value.remote?.table_name)
  return false
})

// ====== 数据集内嵌数据预览（与弹窗预览 previewColumns 区分） ======
const dsPreviewColumns = ref([])
const dsPreviewRows = ref([])
const dsPreviewLoading = ref(false)
const dsPreviewTotal = ref(0)
const dsPreviewEmptyText = ref('')

// 加载数据预览（本地数据集前10行；远程模式后端暂不支持预览）
async function loadDsPreview() {
  if (sourceConfig.value.mode !== 'local' || !sourceConfig.value.datasetId) {
    dsPreviewColumns.value = []
    dsPreviewRows.value = []
    dsPreviewTotal.value = 0
    if (sourceConfig.value.mode === 'remote') {
      dsPreviewEmptyText.value = '远程模式暂不支持数据预览'
    }
    return
  }
  dsPreviewLoading.value = true
  dsPreviewEmptyText.value = ''
  try {
    const res = await fetchDatasetData(sourceConfig.value.datasetId, 1, 10)
    const data = res.data
    if (data && Array.isArray(data.data)) {
      dsPreviewRows.value = data.data
      dsPreviewColumns.value = data.columns || (data.data[0] ? Object.keys(data.data[0]) : [])
      dsPreviewTotal.value = data.total_rows ?? data.data.length
    } else if (Array.isArray(data)) {
      dsPreviewRows.value = data
      dsPreviewColumns.value = data[0] ? Object.keys(data[0]) : []
      dsPreviewTotal.value = data.length
    } else {
      dsPreviewRows.value = []
      dsPreviewColumns.value = []
      dsPreviewTotal.value = 0
    }
  } catch {
    dsPreviewRows.value = []
    dsPreviewColumns.value = []
    dsPreviewTotal.value = 0
    dsPreviewEmptyText.value = '获取数据预览失败'
  } finally {
    dsPreviewLoading.value = false
  }
}

// 列池：{ name, type, source: 'original'|'generated' }
const currentColumns = ref([])
const currentDatasetId = ref(null) // 当前加载的数据集ID（用于调用API）

// 当前数据集对象（仅取 name 用于任务面板展示，避免在调用 addTask 时重复查找）
const currentDataset = computed(() =>
  availableDatasets.value.find(d => d.id === currentDatasetId.value) || null
)

// 预检结果：数据质量检测 + 操作可行性判断
const precheckResult = ref(null)
const precheckLoading = ref(false)

// 列池管理
const renamingCol = ref(null)
const renameValue = ref('')
const renameInput = ref(null)

// ========== 计算属性 ==========
const numericColumns = computed(() => currentColumns.value.filter(c => c.type === 'numeric'))
const stringColumns = computed(() => currentColumns.value.filter(c => c.type === 'string'))
const datetimeColumns = computed(() => currentColumns.value.filter(c => c.type === 'datetime'))

// 特征构造子操作状态：返回每个子操作的可用性
// opType: arithmetic/polynomial/binning/time/cross
function getSubOperationStatus(opType) {
  switch (opType) {
    case 'arithmetic':
      // 四则运算需要≥1个数值列（或任意列+常数）
      if (numericColumns.value.length === 0) return { type: 'danger', text: '无数值列' }
      return { type: 'success', text: `可用数值列 ${numericColumns.value.length}` }
    case 'polynomial':
      // 多项式/对数变换需要≥1个数值列
      if (numericColumns.value.length === 0) return { type: 'danger', text: '无数值列' }
      return { type: 'success', text: `可用数值列 ${numericColumns.value.length}` }
    case 'binning':
      // 分箱需要≥1个数值列
      if (numericColumns.value.length === 0) return { type: 'danger', text: '无数值列' }
      return { type: 'success', text: `可用数值列 ${numericColumns.value.length}` }
    case 'time':
      // 时间拆解需要≥1个日期时间列
      if (datetimeColumns.value.length === 0) return { type: 'danger', text: '无日期列' }
      return { type: 'success', text: `可用日期列 ${datetimeColumns.value.length}` }
    case 'cross':
      // 类别交叉需要≥2个字符串列
      if (stringColumns.value.length < 2) return { type: 'danger', text: '类别列不足2个' }
      return { type: 'success', text: `可用类别列 ${stringColumns.value.length}` }
    case 'target_encoding':
      // Target编码需要≥1个字符串列 + ≥1个数值列
      if (stringColumns.value.length === 0) return { type: 'danger', text: '无类别列' }
      if (numericColumns.value.length === 0) return { type: 'danger', text: '无数值目标列' }
      return { type: 'success', text: `可用类别列 ${stringColumns.value.length}` }
    default:
      return null
  }
}

// 列在特定操作下的状态：available(可用) / warning(警告) / unavailable(不可用)
// operationType: arithmetic/polynomial/binning/time/cross/encode/scale/reduce/select/target_encoding
function getColumnStatusForOperation(col, operationType) {
  if (!col) return 'unavailable'
  const colType = col.type
  const issues = col.issues || []

  // 第一步：类型匹配判断（不匹配直接不可用）
  // 数值型操作：四则运算/多项式/分箱/缩放/降维 都需要数值列
  const numericOps = ['arithmetic', 'polynomial', 'binning', 'scale', 'reduce']
  if (numericOps.includes(operationType) && colType !== 'numeric') return 'unavailable'
  // 编码/类别交叉/Target编码需要字符串（类别）列
  if (['encode', 'cross', 'target_encoding'].includes(operationType) && colType !== 'string') return 'unavailable'
  // 特征选择的目标列：不限制类型，但常量列不可用（无法区分特征重要性）
  if (operationType === 'select' && issues.includes('constant_column')) return 'unavailable'

  // 时间拆解：datetime 类型可用，string 类型可尝试解析（后端用 pd.to_datetime 自动推断格式）
  // CSV 读取后日期列常被识别为 object/string，不应直接禁用
  if (operationType === 'time') {
    if (colType === 'datetime') return 'available'
    if (colType === 'string') return 'warning'  // 可尝试解析，但不确定
    return 'unavailable'
  }

  // 第二步：数据质量问题判断（类型匹配但有问题则警告）
  // 字段名与后端 precheck 返回一致：missing_values/infinite_values/constant_column/high_cardinality
  if (issues.includes('infinite_values') || issues.includes('constant_column')) return 'warning'
  if (issues.includes('missing_values')) return 'warning'
  if (issues.includes('high_cardinality') && ['encode', 'cross', 'target_encoding'].includes(operationType)) return 'warning'

  return 'available'
}

// 获取列状态对应的标签类型
function getColumnStatusTagType(col, operationType) {
  const status = getColumnStatusForOperation(col, operationType)
  if (status === 'available') return 'success'
  if (status === 'warning') return 'warning'
  return 'info'
}

// 获取列状态对应的文字
function getColumnStatusText(col, operationType) {
  const status = getColumnStatusForOperation(col, operationType)
  if (status === 'available') return '可用'
  if (status === 'warning') return '警告'
  return '不可用'
}

// 列池按模块分组
const columnGroups = computed(() => {
  const groups = [
    { key: 'original', label: '原始列', color: '#606266', tagType: '', columns: [] },
    { key: 'construct', label: '特征构造', color: '#409eff', tagType: '', columns: [] },
    { key: 'encode', label: '特征编码', color: '#e6a23c', tagType: 'warning', columns: [] },
    { key: 'scale', label: '特征缩放', color: '#67c23a', tagType: 'success', columns: [] },
    { key: 'reduce', label: '特征降维', color: '#f56c6c', tagType: 'danger', columns: [] },
  ]
  const groupMap = { original: 0, construct: 1, encode: 2, scale: 3, reduce: 4 }
  for (const col of currentColumns.value) {
    const key = col.source === 'original' ? 'original' : (col.module || 'construct')
    const idx = groupMap[key] !== undefined ? groupMap[key] : 1
    if (!groups[idx].columns.includes(col)) {
      groups[idx].columns.push(col)
    }
  }
  return groups.filter(g => g.columns.length > 0)
})

// 多项式默认名称预览
function polyDefaultNames(row) {
  if (!row.column || !row.degree) return ''
  const names = []
  for (let d = 2; d <= row.degree; d++) {
    names.push(`fe_${row.column}^${d}`)
  }
  return names.join(', ')
}

// ========== 模块1: 构造 ==========
const arithmeticRows = ref([])
const polyRows = ref([])
const binningRows = ref([])
const timeRows = ref([])
const categoryCrossRows = ref([])
const targetEncodingRows = ref([])
const constructing = ref(false)
const constructResult = ref('')

// ========== 模块2: 编码 ==========
const encodeRows = ref([])
const encoding = ref(false)
const encodeResult = ref('')

// ========== 模块3: 缩放 ==========
const scaleMethod = ref('standard')
const scaleColumns = ref([])
const scaling = ref(false)
const scaleResult = ref('')

// ========== 模块4: 降维 ==========
const reduceMethod = ref('pca')
const reduceNComponents = ref(2)
const reduceColumns = ref([])
const reduceNamePrefix = ref('')
const reducing = ref(false)
const reduceResult = ref('')

// ========== 模块5: 特征选择 ==========
const featureSelectTarget = ref('')
const featureSelectTaskType = ref('classification')
const featureSelectMethod = ref('mutual_info')
const featureSelectTopK = ref(10)
const selectingFeatures = ref(false)
const featureSelectionResult = ref(null)
const exportingSelected = ref(false)

// 实时计算排除目标列后的可用特征列数
// 与后端 _execute_select_features 的排除逻辑保持一致：
// 1. 仅保留数值列 2. 排除目标列 3. 排除含NaN/inf/常量的列
const availableFeaturesForSelect = computed(() => {
  const target = featureSelectTarget.value
  return currentColumns.value.filter(c =>
    c.type === 'numeric' &&
    c.name !== target &&
    !(c.issues || []).includes('infinite_values') &&
    !(c.issues || []).includes('missing_values') &&
    !(c.issues || []).includes('constant_column')
  )
})

// 特征选择按钮是否被禁用（剩余可用特征列为0时禁用）
const selectButtonDisabled = computed(() => {
  if (getOperationStatus('select_features')?.type === 'danger') return true
  if (!featureSelectTarget.value) return false  // 未选目标列时不禁用，由点击时校验
  return availableFeaturesForSelect.value.length === 0
})

// ========== 导出 ==========
const showExportDialog = ref(false)
const exportSelectedColumns = ref([])
const exporting = ref(false)

// ========== 预览（后端分页） ==========
const showPreview = ref(false)
const previewColumns = ref([])
const previewRows = ref([])
const previewLoading = ref(false)
const previewPage = ref(1)
const previewPageSize = ref(20)
const previewTotal = ref(0)

// 打开预览对话框，重置分页并加载第一页
async function openPreview() {
  // 远程模式暂不支持数据预览（后端 /feature_engineering/data/{dataset_id} 仅支持本地数据集），明确提示而非静默无响应
  if (sourceConfig.value.mode === 'remote') {
    ElMessage.info('远程模式暂不支持数据预览')
    return
  }
  if (!currentDatasetId.value) return
  previewPage.value = 1
  previewPageSize.value = 20
  showPreview.value = true
  await loadPreviewData()
}

// 从后端分页加载预览数据
async function loadPreviewData() {
  if (!currentDatasetId.value) return
  previewLoading.value = true
  try {
    const res = await fetchFeatureData(currentDatasetId.value, previewPage.value, previewPageSize.value)
    const data = res.data
    previewColumns.value = data.columns || []
    previewRows.value = data.rows || []
    previewTotal.value = data.total || 0
  } catch {
    ElMessage.error('获取预览数据失败')
  } finally {
    previewLoading.value = false
  }
}

// ========== 初始化 ==========
async function loadAvailableDatasets() {
  datasetsLoading.value = true
  try {
    const res = await fetchFeatureDatasets()
    availableDatasets.value = res.data || []
  } catch {
    ElMessage.warning('无法加载特征工程数据')
  } finally {
    datasetsLoading.value = false
  }
}

async function refreshColumnPool() {
  const isRemote = sourceConfig.value.mode === 'remote'
  if (isRemote) {
    // 远程模式：重新拉取工作副本列池（含动态新增的构造列）并刷新预检结果
    const remote = sourceConfig.value.remote
    if (remote?.connection_id && remote?.table_name) {
      precheckLoading.value = true
      try {
        const [poolRes, precheckRes] = await Promise.all([
          fetchRemoteColumnPool(remote.connection_id, remote.table_name),
          precheckFeatureDataset(0, remote)
        ])
        applyRemotePool(poolRes.data || {})
        mergePrecheckIntoColumns(precheckRes.data?.columns || [])
        precheckResult.value = precheckRes.data
      } catch (e) {
        ElMessage.error('刷新远程列池失败：' + extractErrorMessage(e))
      } finally {
        precheckLoading.value = false
      }
    }
    return
  }
  if (!currentDatasetId.value) return
  // 刷新列池时同时刷新预检结果（construct/encode/scale/reduce 执行后会改变数据集）。
  // 注意：此处只加载列池，不重置模块参数，避免执行任一操作后清空其他模块已填配置
  await loadPoolForDataset(currentDatasetId.value)
}

// 仅加载本地数据集列池与预检结果（不重置模块参数，供操作后刷新列池复用）
async function loadPoolForDataset(id) {
  if (!id) return
  precheckLoading.value = true
  precheckResult.value = null
  try {
    const [poolRes, precheckRes] = await Promise.all([
      fetchColumnPool(id),
      precheckFeatureDataset(id)
    ])
    currentColumns.value = (poolRes.data.columns || []).map(c => {
      // 合并预检结果中的列信息（issues/NaN/inf/常量等）
      const precheckCol = (precheckRes.data.columns || []).find(pc => pc.name === c.name)
      const issues = precheckCol?.issues || []
      return {
        name: c.name,
        type: c.type,
        source: c.is_original ? 'original' : 'generated',
        module: c.module || '',
        sourceLabel: c.source_label || '',
        tagType: c.is_original ? '' : getModuleTagType(c.module),
        tagColor: c.is_original ? '#606266' : getModuleColor(c.module),
        tooltip: c.is_original ? '原始列' : (c.source_label || '由特征工程生成'),
        issues,
        nanCount: precheckCol?.nan_count || 0,
        infCount: precheckCol?.inf_count || 0,
        zeroCount: precheckCol?.zero_count || 0,
        uniqueCount: precheckCol?.unique_count || 0,
        isConstant: precheckCol?.is_constant || false,
        hasIssue: issues.length > 0
      }
    })
    precheckResult.value = precheckRes.data
  } catch {
    // 预检失败时仍尝试加载列池，保证基本功能可用
    try {
      const poolRes = await fetchColumnPool(id)
      currentColumns.value = (poolRes.data.columns || []).map(c => ({
        name: c.name,
        type: c.type,
        source: c.is_original ? 'original' : 'generated',
        module: c.module || '',
        sourceLabel: c.source_label || '',
        tagType: c.is_original ? '' : getModuleTagType(c.module),
        tagColor: c.is_original ? '#606266' : getModuleColor(c.module),
        tooltip: c.is_original ? '原始列' : (c.source_label || '由特征工程生成'),
        issues: [],
        hasIssue: false
      }))
    } catch {
      ElMessage.error('无法加载列池')
    }
  } finally {
    precheckLoading.value = false
  }
}

// 将远程列池接口返回的数据转换为 currentColumns 格式
function applyRemotePool(poolData) {
  currentColumns.value = (poolData.columns || []).map(col => ({
    name: col.name,
    type: col.type,
    dtype: col.type, // 保留统一分类类型，供 numericColumns 等计算属性过滤
    source: col.source || (col.is_original ? 'original' : 'generated'),
    module: col.module || '',
    sourceLabel: col.sourceLabel || '远程表',
    tagType: '',
    tagColor: col.is_original ? '#606266' : '#409eff',
    // tooltip 与本地 onDatasetSelect 一致：原始列显示"原始列"，构造列显示来源
    tooltip: col.is_original ? '原始列' : (col.sourceLabel || '由特征工程生成'),
    hasIssue: false,
    issues: []
  }))
}

// 将预检结果中的列级信息（issues/NaN/inf/常量/唯一值）合并进 currentColumns
// 供列池行的质量标识和操作可用性判断使用（与本地 onDatasetSelect 行为一致）
function mergePrecheckIntoColumns(precheckColumns) {
  const precheckMap = new Map((precheckColumns || []).map(pc => [pc.name, pc]))
  currentColumns.value.forEach(col => {
    const pc = precheckMap.get(col.name)
    if (!pc) return
    col.issues = pc.issues || []
    col.nanCount = pc.nan_count || 0
    col.infCount = pc.inf_count || 0
    col.zeroCount = pc.zero_count || 0
    col.uniqueCount = pc.unique_count || 0
    col.isConstant = pc.is_constant || false
    // 回填 hasIssue：存在缺失值/无穷大/常量/高基数等任何问题时显示警告图标
    col.hasIssue = (col.issues?.length || 0) > 0
  })
}

// ========== 上传 ==========
const uploadFile = ref(null)

function onFileChange(file) {
  uploadFile.value = file
}

function cancelUpload() {
  uploadFile.value = null
}

async function doUpload() {
  if (!uploadFile.value) return
  uploading.value = true
  try {
    const res = await uploadFeatureFile(uploadFile.value.raw)
    ElMessage.success('上传成功')
    // 刷新下拉框并自动选中新上传的数据集，避免用户在带时间戳的重名文件中难以辨认
    await dataSourceSelectorRef.value?.reload()
    await loadAvailableDatasets()
    selectedDatasetId.value = res.data.id
    dataSourceSelectorRef.value?.selectDataset(res.data.id)
    sourceConfig.value = { mode: 'local', datasetId: res.data.id, remote: null }
    await onDatasetSelect(res.data.id)
    uploadFile.value = null
  } catch (e) {
    ElMessage.error(extractErrorMessage(e, '上传失败'))
  } finally {
    uploading.value = false
  }
}

// 数据源选择回调（DataSourceSelector 的 @select 事件）
async function onSourceSelect(config) {
  if (config.mode === 'local') {
    selectedDatasetId.value = config.datasetId
    sourceConfig.value = { mode: 'local', datasetId: config.datasetId, remote: null }
    if (config.datasetId) {
      onDatasetSelect(config.datasetId)
    } else {
      // 清空选择
      currentColumns.value = []
      currentDatasetId.value = null
      precheckResult.value = null
      resetModuleParams()
    }
    loadDsPreview()
  } else {
    // 远程模式：清空本地数据集选择，加载远程表列池
    selectedDatasetId.value = null
    sourceConfig.value = { mode: 'remote', datasetId: null, remote: config.remote }
    currentDatasetId.value = null
    precheckResult.value = null
    resetModuleParams()
    // 加载远程表当前生效的列信息作为列池
    // 优先读取工作副本（含特征工程动态新增的构造列），无则回退数据库原始列
    if (config.remote?.connection_id && config.remote?.table_name) {
      precheckLoading.value = true
      try {
        // 并行加载列池与预检结果（与本地 onDatasetSelect 行为一致）
        const [poolRes, precheckRes] = await Promise.all([
          fetchRemoteColumnPool(config.remote.connection_id, config.remote.table_name),
          precheckFeatureDataset(0, config.remote)
        ])
        applyRemotePool(poolRes.data || {})
        mergePrecheckIntoColumns(precheckRes.data?.columns || [])
        precheckResult.value = precheckRes.data
        ElMessage.success(`已加载远程表 ${config.remote.table_name} 的 ${currentColumns.value.length} 个列`)
      } catch (e) {
        currentColumns.value = []
        precheckResult.value = null
        ElMessage.error('加载远程表列信息失败：' + extractErrorMessage(e))
      } finally {
        precheckLoading.value = false
      }
    } else {
      currentColumns.value = []
      precheckResult.value = null
    }
    // 远程模式：内嵌数据预览暂不支持，置空并提示
    loadDsPreview()
  }
}

// 将数据库原始类型字符串映射为本地列池统一的分类类型
// 映射规则：数值型→numeric，日期时间型→datetime，其余→string
function mapRemoteType(dbType) {
  if (!dbType) return 'string'
  const t = String(dbType).toUpperCase()
  // 数值类型（含整数、浮点、定点、位类型）
  if (/^(INT|INTEGER|BIGINT|SMALLINT|TINYINT|MEDIUMINT|DECIMAL|NUMERIC|NUMBER|FLOAT|DOUBLE|REAL|BIT|SERIAL|BIGSERIAL)\b/.test(t)) {
    return 'numeric'
  }
  // 日期时间类型
  if (/^(DATE|DATETIME|TIMESTAMP|TIME|YEAR)\b/.test(t)) {
    return 'datetime'
  }
  // 其余（VARCHAR/CHAR/TEXT/BLOB/JSON/ENUM/SET 等）归为字符串
  return 'string'
}

// ========== 选择数据 ==========
// 切换数据集时重置所有模块的参数和结果，避免残留上一个数据集的配置
// 仅重置用户输入和结果，不重置 loading 状态（loading 由各自的操作函数管理）
function resetModuleParams() {
  // 模块1: 特征构造
  arithmeticRows.value = []
  polyRows.value = []
  binningRows.value = []
  timeRows.value = []
  categoryCrossRows.value = []
  targetEncodingRows.value = []
  constructResult.value = ''
  // 模块2: 特征编码
  encodeRows.value = []
  encodeResult.value = ''
  // 模块3: 特征缩放
  scaleMethod.value = 'standard'
  scaleColumns.value = []
  scaleResult.value = ''
  // 模块4: 特征降维
  reduceMethod.value = 'pca'
  reduceNComponents.value = 2
  reduceColumns.value = []
  reduceNamePrefix.value = ''
  reduceResult.value = ''
  // 模块5: 特征选择
  featureSelectTarget.value = ''
  featureSelectTaskType.value = 'classification'
  featureSelectMethod.value = 'mutual_info'
  featureSelectTopK.value = 10
  featureSelectionResult.value = null
  // 导出
  exportSelectedColumns.value = []
}

async function onDatasetSelect(id) {
  if (!id) {
    currentColumns.value = []
    currentDatasetId.value = null
    precheckResult.value = null
    resetModuleParams()
    return
  }
  currentDatasetId.value = id
  // 切换数据集时重置所有模块参数和结果，避免残留上一个数据集的配置
  resetModuleParams()
  // 加载列池与预检结果（仅加载，不重复重置参数）
  await loadPoolForDataset(id)
}

// 获取列的问题描述文本（用于 tooltip）
function getColumnIssueText(col) {
  if (!col.hasIssue) return ''
  const parts = []
  if (col.issues?.includes('missing_values')) parts.push(`缺失值 ${col.nanCount} 个`)
  if (col.issues?.includes('infinite_values')) parts.push(`无穷大值 ${col.infCount} 个`)
  if (col.issues?.includes('constant_column')) parts.push('常量列（所有值相同）')
  if (col.issues?.includes('high_cardinality')) parts.push(`高基数列（唯一值 ${col.uniqueCount}）`)
  return parts.length ? '问题：' + parts.join('，') : ''
}

// 获取操作可行性状态（用于 Tab 徽标）
function getOperationStatus(opKey) {
  if (!precheckResult.value?.operation_feasibility?.[opKey]) return null
  const op = precheckResult.value.operation_feasibility[opKey]
  if (!op.feasible) return { type: 'danger', text: '不可用' }
  if (op.warnings?.length > 0) return { type: 'warning', text: '有警告' }
  return { type: 'success', text: '可用' }
}

// 模块对应的标签颜色
function getModuleTagType(module) {
  const map = { construct: '', encode: 'warning', scale: 'success', reduce: 'danger' }
  return map[module] || ''
}
function getModuleColor(module) {
  const map = { construct: '#409eff', encode: '#e6a23c', scale: '#67c23a', reduce: '#f56c6c' }
  return map[module] || '#67c23a'
}
function getModuleLabel(module) {
  const map = { construct: '特征构造', encode: '特征编码', scale: '特征缩放', reduce: '特征降维' }
  return map[module] || '特征工程'
}

// 方案A：本地追加新列到列池（乐观更新），让用户立即看到新列，不等待网络请求
// 类型暂设为 numeric，方案B后台刷新时会修正为准确类型并补充预检信息
// 用于异步特征工程任务（构造/编码/缩放/降维）完成后的即时反馈
function appendColumnsLocally(newColNames, module) {
  if (!newColNames || newColNames.length === 0) return 0
  const existingNames = new Set(currentColumns.value.map(c => c.name))
  let added = 0
  for (const colName of newColNames) {
    if (!existingNames.has(colName)) {
      currentColumns.value.push({
        name: colName,
        type: 'numeric',
        source: 'generated',
        module: module,
        sourceLabel: getModuleLabel(module),
        tagType: getModuleTagType(module),
        tagColor: getModuleColor(module),
        tooltip: '由特征工程生成',
        issues: [],
        nanCount: 0,
        infCount: 0,
        zeroCount: 0,
        uniqueCount: 0,
        isConstant: false,
        hasIssue: false
      })
      added++
    }
  }
  return added
}

// ========== 列池管理 ==========
async function deleteColumn(col) {
  if (col.is_original || col.source === 'original') {
    ElMessage.warning('原始列不能删除')
    return
  }
  
  // 确认对话框
  try {
    await ElMessageBox.confirm(
      `确定要删除构造列 "${col.name}" 吗？此操作不可恢复。`,
      '确认删除',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch {
    // 用户取消
    return
  }
  
  // 调用后端 API 删除列（远程模式删除工作副本中的构造列）
  try {
    if (sourceConfig.value.mode === 'remote') {
      await deleteRemoteConstructedColumn(sourceConfig.value.remote, col.name)
    } else {
      await deleteConstructedColumn(currentDatasetId.value, col.name)
    }
    // 删除成功后从本地列池中移除
    currentColumns.value = currentColumns.value.filter(c => c.name !== col.name)
    ElMessage.success(`已删除列: ${col.name}`)
  } catch (e) {
    ElMessage.error(extractErrorMessage(e, '删除失败'))
  }
}

function startRenameColumn(col) {
  renamingCol.value = col.name
  renameValue.value = col.name
  nextTick(() => {
    const inp = document.querySelector('.column-pool-rename-input')
    if (inp) inp.focus()
  })
}

function confirmRename(oldCol) {
  if (!renameValue.value || renameValue.value === oldCol.name) {
    cancelRename()
    return
  }
  // 检查重名
  if (currentColumns.value.some(c => c.name === renameValue.value && c.name !== oldCol.name)) {
    ElMessage.warning('列名已存在')
    cancelRename()
    return
  }
  // 调用后端持久化重命名（修复：此前仅改前端状态导致后续操作列不存在）
  const newName = renameValue.value
  const isRemote = sourceConfig.value.mode === 'remote'
  const remote = isRemote ? sourceConfig.value.remote : null
  const datasetId = currentDatasetId.value
  renameFeatureColumn(datasetId, oldCol.name, newName, remote)
    .then(() => {
      const idx = currentColumns.value.findIndex(c => c.name === oldCol.name)
      if (idx >= 0) {
        currentColumns.value[idx].name = newName
      }
      ElMessage.success(`已将列重命名为「${newName}」`)
    })
    .catch(err => {
      ElMessage.error(`重命名失败：${err?.response?.data?.detail || err.message || '未知错误'}`)
    })
    .finally(() => {
      renamingCol.value = null
      renameValue.value = ''
    })
}

function cancelRename() {
  renamingCol.value = null
  renameValue.value = ''
}

// ========== 模块1: 构造 ==========
function addArithmeticRow() {
  arithmeticRows.value.push({ name: '', col1: '', op: '+', col2: '' })
}
function addPolyRow() {
  polyRows.value.push({ type: 'polynomial', column: '', degree: 2, name: '' })
}
function addBinningRow() {
  binningRows.value.push({ column: '', bins: 5, method: 'equal_width', name: '' })
}
function addTimeRow() {
  timeRows.value.push({ column: '', extract: ['year', 'month', 'day'] })
}
function addCategoryCrossRow() {
  categoryCrossRows.value.push({ columns: [], name: '' })
}

function addTargetEncodingRow() {
  targetEncodingRows.value.push({ column: '', target_column: '', name: '' })
}

async function executeConstruct() {
  constructing.value = true
  constructResult.value = ''
  try {
    const operations = { arithmetic: [], polynomial: [], log_transform: [], binning: [], time_split: [], category_cross: [], target_encoding: [] }

    // 四则运算
    for (const row of arithmeticRows.value) {
      if (row.col1 && row.op && row.col2) {
        operations.arithmetic.push({
          name: row.name || `fe_${row.col1}_${row.op}_${row.col2}`,
          col1: row.col1, op: row.op, col2: row.col2
        })
      }
    }

    // 多项式/对数
    for (const row of polyRows.value) {
      if (row.column) {
        if (row.type === 'log_transform') {
          operations.log_transform.push({
            column: row.column,
            name: row.name || `fe_log_${row.column}`
          })
        } else {
          operations.polynomial.push({
            column: row.column,
            degree: row.degree || 2,
            // 默认名只传基础名（不含幂次），后端统一生成 {name}^2、{name}^3，避免列名与幂次内容错位
            name: row.name || `fe_${row.column}`
          })
        }
      }
    }

    // 分箱
    for (const row of binningRows.value) {
      if (row.column) {
        // 根据分箱方法生成后缀，避免同列两种分箱方法列名冲突
        const suffix = row.method === 'equal_freq' ? 'ef' : 'ew'
        operations.binning.push({
          column: row.column,
          bins: row.bins || 5,
          method: row.method || 'equal_width',
          name: row.name || `fe_${row.column}_${suffix}_bin`
        })
      }
    }

    // 时间拆解
    for (const row of timeRows.value) {
      if (row.column && row.extract.length > 0) {
        operations.time_split.push({
          column: row.column,
          extract: row.extract
        })
      }
    }

    // 类别交叉
    for (const row of categoryCrossRows.value) {
      if (row.columns.length >= 2) {
        operations.category_cross.push({
          columns: row.columns,
          separator: '_',
          name: row.name || `fe_${row.columns.join('_')}_cross`
        })
      }
    }

    // Target编码
    for (const row of targetEncodingRows.value) {
      if (row.column && row.target_column) {
        operations.target_encoding.push({
          column: row.column,
          target_column: row.target_column,
          name: row.name || `fe_${row.column}_target_enc`
        })
      }
    }

    // 修复问题1类：同步分支增加数据集一致性校验
    // 在 await 之前捕获 submitDatasetId，供同步/异步分支共用，避免 await 期间用户切换数据集导致页面污染
    const submitDatasetId = currentDatasetId.value
    const isRemote = sourceConfig.value.mode === 'remote'
    const remote = isRemote ? sourceConfig.value.remote : null
    const res = await constructFeatures(isRemote ? null : currentDatasetId.value, operations, remote)
    // 智能异步分发：≥1万行后端返回 status=queued/pending，提交到全局任务面板
    if ((res.data.status === 'running' || res.data.status === 'queued' || res.data.status === 'pending') && res.data.task_record_id) {
      constructing.value = false
      const data = res.data
      addTask({
        recordId: data.task_record_id,
        celeryTaskId: data.task_id,
        taskType: 'feature_engineering_construct',
        operation: '特征构造',
        moduleLabel: '特征工程',
        datasetName: currentDataset.value?.name || '',
        initialStatus: data.status === 'pending' ? 'pending' : 'running',
        isRemote: sourceConfig.value.mode === 'remote',
      }, (status, summary) => {
        // 任务完成回调：成功时刷新列池并清空构造行（与同步路径一致）
        if (status === 'success') {
          // 数据集一致性校验：用户在任务期间切换了数据集则不渲染结果
          if (currentDatasetId.value !== submitDatasetId) {
            ElMessage.success('特征构造完成，请切回原数据集查看结果')
            return
          }
          if (summary?.success) {
            constructResult.value = `构造完成，新增 ${summary.new_columns?.length || 0} 列`
            // 方案A：先在本地列池追加新列（乐观更新），让用户立即看到新列，不等待网络请求
            appendColumnsLocally(summary.new_columns, 'construct')
          }
          if (summary?.exec_errors?.length > 0) {
            ElMessage.warning(summary.exec_errors.join('; '))
          }
          // 方案B：后台刷新列池，确保与服务端一致（修正类型、补充预检信息）
          refreshColumnPool()
          arithmeticRows.value = []
          polyRows.value = []
          binningRows.value = []
          timeRows.value = []
          categoryCrossRows.value = []
          targetEncodingRows.value = []
        } else if (status === 'failed') {
          ElMessage.error(`特征构造失败: ${summary?.current_message || '请查看任务面板'}`)
        } else if (status === 'cancelled') {
          ElMessage.info('特征构造任务已取消')
        }
      })
      return
    }
    // 同步结果：校验数据集一致性后展示，避免 await 期间用户切换数据集导致页面污染
    if (currentDatasetId.value === submitDatasetId) {
      if (res.data.success) {
        constructResult.value = `构造完成，新增 ${res.data.new_columns.length} 列`
        ElMessage.success(constructResult.value)
        // 如果有执行错误（如除法分母含0被拒绝），显示错误提示
        if (res.data.exec_errors && res.data.exec_errors.length > 0) {
          ElMessage.warning(res.data.exec_errors.join('; '))
        }
        // 本地模式：原地更新后刷新列池（dataset_id 不变）
        // 远程模式：新列已保存到工作副本，动态刷新列池（不切换数据源）
        await refreshColumnPool()
        // 清空构造行
        arithmeticRows.value = []
        polyRows.value = []
        binningRows.value = []
        timeRows.value = []
        categoryCrossRows.value = []
        targetEncodingRows.value = []
      } else {
        ElMessage.error(res.data.message || '构造失败')
        if (res.data.errors) {
          ElMessage.error(res.data.errors.join('; '))
        }
      }
    } else {
      // 数据集已切换，不展示结果，仅提示用户切回原数据集查看
      ElMessage.success('特征构造完成，请切回原数据集查看结果')
    }
  } catch (e) {
    ElMessage.error(extractErrorMessage(e, '构造失败'))
  } finally {
    constructing.value = false
  }
}

// ========== 模块2: 编码 ==========
function addEncodeRow() {
  encodeRows.value.push({ column: '', method: 'onehot', name: '' })
}

async function executeEncode() {
  encoding.value = true
  encodeResult.value = ''
  try {
    const encodingList = []
    for (const row of encodeRows.value) {
      if (row.column) {
        encodingList.push({ column: row.column, method: row.method, name: row.name || '' })
      }
    }
    if (encodingList.length === 0) {
      ElMessage.warning('请选择要编码的列')
      encoding.value = false
      return
    }
    // 修复问题1类：同步分支增加数据集一致性校验
    // 在 await 之前捕获 submitDatasetId，供同步/异步分支共用，避免 await 期间用户切换数据集导致页面污染
    const submitDatasetId = currentDatasetId.value
    const isRemote = sourceConfig.value.mode === 'remote'
    const remote = isRemote ? sourceConfig.value.remote : null
    const res = await encodeFeatures(isRemote ? null : currentDatasetId.value, { encoding_list: encodingList }, remote)
    // 智能异步分发：≥1万行后端返回 status=queued/pending，提交到全局任务面板
    if ((res.data.status === 'running' || res.data.status === 'queued' || res.data.status === 'pending') && res.data.task_record_id) {
      encoding.value = false
      const data = res.data
      addTask({
        recordId: data.task_record_id,
        celeryTaskId: data.task_id,
        taskType: 'feature_engineering_encode',
        operation: '特征编码',
        moduleLabel: '特征工程',
        datasetName: currentDataset.value?.name || '',
        initialStatus: data.status === 'pending' ? 'pending' : 'running',
        isRemote: sourceConfig.value.mode === 'remote',
      }, (status, summary) => {
        // 任务完成回调：成功时刷新列池并清空编码行
        if (status === 'success') {
          // 数据集一致性校验：用户在任务期间切换了数据集则不渲染结果
          if (currentDatasetId.value !== submitDatasetId) {
            ElMessage.success('特征编码完成，请切回原数据集查看结果')
            return
          }
          if (summary?.success) {
            encodeResult.value = `编码完成，新增 ${(summary.encoded_columns || []).length} 列`
            // 方案A：先在本地列池追加新列（乐观更新），让用户立即看到新列
            appendColumnsLocally(summary.encoded_columns, 'encode')
          }
          // 方案B：后台刷新列池，确保与服务端一致
          refreshColumnPool()
          encodeRows.value = []
        } else if (status === 'failed') {
          ElMessage.error(`特征编码失败: ${summary?.current_message || '请查看任务面板'}`)
        } else if (status === 'cancelled') {
          ElMessage.info('特征编码任务已取消')
        }
      })
      return
    }
    // 同步结果：校验数据集一致性后展示，避免 await 期间用户切换数据集导致页面污染
    if (currentDatasetId.value === submitDatasetId) {
      if (res.data.success) {
        encodeResult.value = `编码完成，新增 ${(res.data.encoded_columns || []).length} 列`
        ElMessage.success(encodeResult.value)
        // 本地/远程统一刷新列池（远程模式从工作副本读取，含动态新增列）
        await refreshColumnPool()
        encodeRows.value = []
      } else {
        ElMessage.error(res.data.message || '编码失败')
      }
    } else {
      // 数据集已切换，不展示结果，仅提示用户切回原数据集查看
      ElMessage.success('特征编码完成，请切回原数据集查看结果')
    }
  } catch (e) {
    ElMessage.error(extractErrorMessage(e, '编码失败'))
  } finally {
    encoding.value = false
  }
}

// ========== 模块3: 缩放 ==========
async function executeScale() {
  scaling.value = true
  scaleResult.value = ''
  try {
    // 修复问题1类：同步分支增加数据集一致性校验
    // 在 await 之前捕获 submitDatasetId，供同步/异步分支共用，避免 await 期间用户切换数据集导致页面污染
    const submitDatasetId = currentDatasetId.value
    const isRemote = sourceConfig.value.mode === 'remote'
    const remote = isRemote ? sourceConfig.value.remote : null
    const res = await scaleFeatures(isRemote ? null : currentDatasetId.value, {
      method: scaleMethod.value,
      columns: scaleColumns.value
    }, remote)
    // 智能异步分发：≥1万行后端返回 status=queued/pending，提交到全局任务面板
    if ((res.data.status === 'running' || res.data.status === 'queued' || res.data.status === 'pending') && res.data.task_record_id) {
      scaling.value = false
      const data = res.data
      addTask({
        recordId: data.task_record_id,
        celeryTaskId: data.task_id,
        taskType: 'feature_engineering_scale',
        operation: '特征缩放',
        moduleLabel: '特征工程',
        datasetName: currentDataset.value?.name || '',
        initialStatus: data.status === 'pending' ? 'pending' : 'running',
        isRemote: sourceConfig.value.mode === 'remote',
      }, (status, summary) => {
        // 任务完成回调：成功时刷新列池
        if (status === 'success') {
          // 数据集一致性校验：用户在任务期间切换了数据集则不渲染结果
          if (currentDatasetId.value !== submitDatasetId) {
            ElMessage.success('特征缩放完成，请切回原数据集查看结果')
            return
          }
          if (summary?.success) {
            scaleResult.value = `缩放完成，新增 ${(summary.new_columns || []).length} 列`
            // 方案A：先在本地列池追加新列（乐观更新），让用户立即看到新列
            appendColumnsLocally(summary.new_columns, 'scale')
          }
          // 方案B：后台刷新列池，确保与服务端一致
          refreshColumnPool()
        } else if (status === 'failed') {
          ElMessage.error(`特征缩放失败: ${summary?.current_message || '请查看任务面板'}`)
        } else if (status === 'cancelled') {
          ElMessage.info('特征缩放任务已取消')
        }
      })
      return
    }
    // 同步结果：校验数据集一致性后展示，避免 await 期间用户切换数据集导致页面污染
    if (currentDatasetId.value === submitDatasetId) {
      if (res.data.success) {
        scaleResult.value = `缩放完成，新增 ${(res.data.new_columns || []).length} 列`
        ElMessage.success(scaleResult.value)
        // 本地/远程统一刷新列池（远程模式从工作副本读取，含动态新增列）
        await refreshColumnPool()
      } else {
        ElMessage.error(res.data.message || '缩放失败')
      }
    } else {
      // 数据集已切换，不展示结果，仅提示用户切回原数据集查看
      ElMessage.success('特征缩放完成，请切回原数据集查看结果')
    }
  } catch (e) {
    ElMessage.error(extractErrorMessage(e, '缩放失败'))
  } finally {
    scaling.value = false
  }
}

// ========== 模块4: 降维 ==========
async function executeReduce() {
  reducing.value = true
  reduceResult.value = ''
  try {
    const config = {
      method: reduceMethod.value,
      n_components: reduceNComponents.value,
      columns: reduceColumns.value
    }
    if (reduceNamePrefix.value) {
      config.names = Array.from({ length: reduceNComponents.value }, (_, i) => `${reduceNamePrefix.value}${i + 1}`)
    }
    // 修复问题1类：同步分支增加数据集一致性校验
    // 在 await 之前捕获 submitDatasetId，供同步/异步分支共用，避免 await 期间用户切换数据集导致页面污染
    const submitDatasetId = currentDatasetId.value
    const isRemote = sourceConfig.value.mode === 'remote'
    const remote = isRemote ? sourceConfig.value.remote : null
    const res = await reduceFeatures(isRemote ? null : currentDatasetId.value, config, remote)
    // 智能异步分发：≥1万行后端返回 status=queued/pending，提交到全局任务面板
    if ((res.data.status === 'running' || res.data.status === 'queued' || res.data.status === 'pending') && res.data.task_record_id) {
      reducing.value = false
      const data = res.data
      addTask({
        recordId: data.task_record_id,
        celeryTaskId: data.task_id,
        taskType: 'feature_engineering_reduce',
        operation: '特征降维',
        moduleLabel: '特征工程',
        datasetName: currentDataset.value?.name || '',
        initialStatus: data.status === 'pending' ? 'pending' : 'running',
        isRemote: sourceConfig.value.mode === 'remote',
      }, (status, summary) => {
        // 任务完成回调：成功时刷新列池并展示解释方差
        if (status === 'success') {
          // 数据集一致性校验：用户在任务期间切换了数据集则不渲染结果
          if (currentDatasetId.value !== submitDatasetId) {
            ElMessage.success('特征降维完成，请切回原数据集查看结果')
            return
          }
          if (summary?.success) {
            reduceResult.value = `降维完成，新增 ${(summary.new_columns || []).length} 列`
            if (summary.explained_variance) {
              reduceResult.value += ` (解释方差: ${summary.explained_variance.map(v => (v * 100).toFixed(1) + '%').join(', ')})`
            }
            // 方案A：先在本地列池追加新列（乐观更新），让用户立即看到新列
            appendColumnsLocally(summary.new_columns, 'reduce')
          }
          // 方案B：后台刷新列池，确保与服务端一致
          refreshColumnPool()
        } else if (status === 'failed') {
          ElMessage.error(`特征降维失败: ${summary?.current_message || '请查看任务面板'}`)
        } else if (status === 'cancelled') {
          ElMessage.info('特征降维任务已取消')
        }
      })
      return
    }
    // 同步结果：校验数据集一致性后展示，避免 await 期间用户切换数据集导致页面污染
    if (currentDatasetId.value === submitDatasetId) {
      if (res.data.success) {
        reduceResult.value = `降维完成，新增 ${(res.data.new_columns || []).length} 列`
        if (res.data.explained_variance) {
          reduceResult.value += ` (解释方差: ${res.data.explained_variance.map(v => (v * 100).toFixed(1) + '%').join(', ')})`
        }
        ElMessage.success(reduceResult.value)
        // 远程模式下 refreshColumnPool 会跳过，需要手动追加新列
        if (sourceConfig.value.mode === 'remote') {
          appendColumnsLocally(res.data.new_columns, 'reduce')
        } else {
          await refreshColumnPool()
        }
      } else {
        ElMessage.error(res.data.message || '降维失败')
      }
    } else {
      // 数据集已切换，不展示结果，仅提示用户切回原数据集查看
      ElMessage.success('特征降维完成，请切回原数据集查看结果')
    }
  } catch (e) {
    ElMessage.error(extractErrorMessage(e, '降维失败'))
  } finally {
    reducing.value = false
  }
}

// ========== 模块5: 特征选择 ==========
// 特征选择结果表格数据
const featureSelectionTableData = computed(() => {
  if (!featureSelectionResult.value || !featureSelectionResult.value.selected_features) {
    return []
  }
  const selected = featureSelectionResult.value.selected_features || []
  const scores = featureSelectionResult.value.feature_scores || {}
  return selected.map((name, idx) => {
    // 判断来源类型
    const colInfo = currentColumns.value.find(c => c.name === name)
    let source = '未知'
    let sourceType = ''
    if (colInfo) {
      if (colInfo.source === 'original') {
        source = '原始列'
        sourceType = ''
      } else if (colInfo.module === 'construct') {
        source = '特征构造'
        sourceType = ''  // el-tag 不支持 'primary'，用默认蓝色保持视觉一致
      } else if (colInfo.module === 'encode') {
        source = '特征编码'
        sourceType = 'warning'
      } else if (colInfo.module === 'scale') {
        source = '特征缩放'
        sourceType = 'success'
      } else if (colInfo.module === 'reduce') {
        source = '特征降维'
        sourceType = 'danger'
      } else {
        source = colInfo.sourceLabel || '生成列'
        sourceType = 'info'
      }
    }
    return {
      rank: idx + 1,
      name: name,
      score: scores[name] || 0,
      source: source,
      sourceType: sourceType
    }
  })
})

async function executeSelectFeatures() {
  if (!featureSelectTarget.value) {
    ElMessage.warning('请选择目标列')
    return
  }
  // 前端预校验：排除目标列和有质量问题的列后，若无可用特征列则直接提示
  if (availableFeaturesForSelect.value.length === 0) {
    ElMessage.error('排除目标列和含缺失值/无穷大/常量的列后，没有可用的数值特征列。请更换目标列或先清洗数据。')
    return
  }
  selectingFeatures.value = true
  featureSelectionResult.value = null
  try {
    const isRemote = sourceConfig.value.mode === 'remote'
    const config = {
      dataset_id: isRemote ? null : currentDatasetId.value,
      target_column: featureSelectTarget.value,
      method: featureSelectMethod.value,
      task_type: featureSelectTaskType.value,
      top_k: featureSelectTopK.value
    }
    // 修复问题1类：同步分支增加数据集一致性校验
    // 在 await 之前捕获 submitDatasetId，供同步/异步分支共用，避免 await 期间用户切换数据集导致页面污染
    const submitDatasetId = currentDatasetId.value
    // remote 通过 query string 传递，避免与 config 的 Body 参数冲突
    const res = await selectFeatures(config, isRemote ? sourceConfig.value.remote : null)
    // 智能异步分发：≥1万行后端返回 status=queued/pending，提交到全局任务面板
    if ((res.data.status === 'running' || res.data.status === 'queued' || res.data.status === 'pending') && res.data.task_record_id) {
      selectingFeatures.value = false
      const data = res.data
      addTask({
        recordId: data.task_record_id,
        celeryTaskId: data.task_id,
        taskType: 'feature_engineering_select',
        operation: '特征选择',
        moduleLabel: '特征工程',
        datasetName: currentDataset.value?.name || '',
        initialStatus: data.status === 'pending' ? 'pending' : 'running',
        isRemote: sourceConfig.value.mode === 'remote',
      }, (status, summary) => {
        // 任务完成回调：成功时把 final_result 作为结果对象展示（与同步路径一致）
        if (status === 'success') {
          // 数据集一致性校验：用户在任务期间切换了数据集则不渲染结果
          if (currentDatasetId.value !== submitDatasetId) {
            ElMessage.success('特征选择完成，请切回原数据集查看结果')
            return
          }
          featureSelectionResult.value = summary
          if (summary?.excluded_columns?.length > 0) {
            ElMessage.warning(`特征选择完成，已自动排除 ${summary.excluded_columns.length} 个存在质量问题的特征列，建议清洗数据后重新选择`)
          }
        } else if (status === 'failed') {
          ElMessage.error(`特征选择失败: ${summary?.current_message || '请查看任务面板'}`)
        } else if (status === 'cancelled') {
          ElMessage.info('特征选择任务已取消')
        }
      })
      return
    }
    // 同步结果：校验数据集一致性后展示，避免 await 期间用户切换数据集导致页面污染
    if (currentDatasetId.value === submitDatasetId) {
      featureSelectionResult.value = res.data
      if (res.data.excluded_columns?.length > 0) {
        ElMessage.warning(`特征选择完成，已自动排除 ${res.data.excluded_columns.length} 个存在质量问题的特征列，建议清洗数据后重新选择`)
      } else {
        ElMessage.success(`特征选择完成，选中 ${res.data.selected_features?.length || 0} 个特征`)
      }
    } else {
      // 数据集已切换，不展示结果，仅提示用户切回原数据集查看
      ElMessage.success('特征选择完成，请切回原数据集查看结果')
    }
  } catch (e) {
    ElMessage.error(extractErrorMessage(e, '特征选择失败'))
  } finally {
    selectingFeatures.value = false
  }
}

async function executeExportSelected() {
  if (!featureSelectionResult.value || !featureSelectionResult.value.selected_features?.length) {
    ElMessage.warning('没有可导出的特征')
    return
  }
  exportingSelected.value = true
  try {
    const isRemote = sourceConfig.value.mode === 'remote'
    const exportConfig = {
      dataset_id: isRemote ? null : currentDatasetId.value,
      selected_features: featureSelectionResult.value.selected_features,
      target_column: featureSelectTarget.value
    }
    // remote 通过 query string 传递，避免与 config 的 Body 参数冲突
    const res = await exportSelectedFeatures(exportConfig, isRemote ? sourceConfig.value.remote : null)
    if (res.data.success) {
      ElMessage.success(res.data.message)
    }
  } catch (e) {
    ElMessage.error(extractErrorMessage(e, '导出失败'))
  } finally {
    exportingSelected.value = false
  }
}

// 打开导出弹窗：默认选中所有列，复用 columnGroups 分组结构
function openExportDialog() {
  if (currentColumns.value.length === 0) {
    ElMessage.warning('列池为空')
    return
  }
  exportSelectedColumns.value = currentColumns.value.map(c => c.name)
  showExportDialog.value = true
}

// 导出弹窗复用列池分组结构，与列池管理展示一致
const exportableColumnGroups = columnGroups

// 判断分组是否全选
function isGroupAllSelected(group) {
  return group.columns.length > 0 && group.columns.every(c => exportSelectedColumns.value.includes(c.name))
}

// 判断分组是否半选（部分选中）
function isGroupIndeterminate(group) {
  const selectedCount = getGroupSelectedCount(group)
  return selectedCount > 0 && selectedCount < group.columns.length
}

// 获取分组已选数量
function getGroupSelectedCount(group) {
  return group.columns.filter(c => exportSelectedColumns.value.includes(c.name)).length
}

// 切换分组全选/取消全选
function toggleGroupSelection(group, checked) {
  const groupNames = group.columns.map(c => c.name)
  if (checked) {
    // 选中分组中未选的列（去重合并）
    const newSet = new Set([...exportSelectedColumns.value, ...groupNames])
    exportSelectedColumns.value = Array.from(newSet)
  } else {
    // 取消选中分组中的所有列
    exportSelectedColumns.value = exportSelectedColumns.value.filter(n => !groupNames.includes(n))
  }
}

// ========== 导出列池产物（弹窗确认后调用） ==========
async function executeExport() {
  if (exportSelectedColumns.value.length === 0) {
    ElMessage.warning('请选择至少一列')
    return
  }
  exporting.value = true
  try {
    const isRemote = sourceConfig.value.mode === 'remote'
    const exportConfig = {
      dataset_id: isRemote ? null : currentDatasetId.value,
      column_names: exportSelectedColumns.value
    }
    // remote 通过 query string 传递，避免与 config 的 Body 参数冲突
    const res = await exportColumnPool(exportConfig, isRemote ? sourceConfig.value.remote : null)
    if (res.data.success) {
      ElMessage.success(res.data.message)
      showExportDialog.value = false
    }
  } catch (e) {
    ElMessage.error(extractErrorMessage(e, '导出失败'))
  } finally {
    exporting.value = false
  }
}

// ========== 生命周期 ==========
onMounted(() => {
  loadAvailableDatasets()
})

onActivated(() => {
  loadAvailableDatasets()
})
</script>

<style scoped>
.feature-engineering {
  max-width: 1000px;
  margin: 0 auto;
}
.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.empty-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #909399;
}
.section {
  margin-bottom: 12px;
  padding: 10px;
  background: #fafafa;
  border-radius: 6px;
}
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 13px;
  color: #606266;
}
.operation-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.help-hint {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
  padding-left: 4px;
  border-left: 3px solid #c0c4cc;
}
.name-preview {
  font-size: 11px;
  color: #909399;
  font-style: italic;
  white-space: nowrap;
}
.pool-group {
  margin-bottom: 12px;
}
.pool-group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.pool-group-label {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}
.pool-group-count {
  font-size: 12px;
  color: #909399;
}

/* 导出弹窗分组样式 */
.export-group {
  margin-bottom: 16px;
  padding: 10px 12px;
  background: #f5f7fa;
  border-radius: 6px;
}
.export-group-header {
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid #e4e7ed;
}
.export-group-body {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding-left: 24px;
}

/* 预检结果摘要样式 */
.precheck-summary {
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 12px;
}
.precheck-summary-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.precheck-summary-body {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.precheck-recommendations {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.precheck-rec-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #606266;
}
.preview-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.preview-table th, .preview-table td {
  border: 1px solid #ebeef5;
  padding: 6px 10px;
  text-align: left;
  white-space: nowrap;
}
.preview-table th {
  background: #f5f7fa;
  font-weight: 600;
}
</style>