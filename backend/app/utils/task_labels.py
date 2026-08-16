"""操作历史中文字段映射统一模块

集中维护 task_type / operation / status / result_summary key 的中文映射，
被 datasets.py 和 admin.py 共用，避免重复维护。
前端不再需要本地映射表，直接渲染后端返回的 *_label 字段。

命名一致性原则：
- task_type_label / operation_label / status_label：纯中文，与前端菜单/按钮文案一致
- params / result_summary 的 key：纯中文，与前端展示一致
- value 中的模块名/产物类型/操作类型/方法：转中文
- value 中的算法名（xgboost、random_forest）、文件格式（csv）、指标符号（R²、F1、AUC）、数据列名：保留原值
"""

# 模块代码 → 中文显示名（与前端 DataManagement.vue getModuleLabel 保持一致）
MODULE_LABEL_MAP = {
    "raw": "原始数据",
    "upload": "原始数据",
    "cleaning": "数据清洗",
    "ml": "机器学习",
    "ai": "AI分析",
    "feature_engineering": "特征工程",
    "batch_predict": "机器学习",
    "data_analysis": "数据分析",
    "data_mining": "数据挖掘",
    "pipeline": "流程联动",
}

# 产物类型代码 → 中文显示名（与前端 DataManagement.vue getArtifactLabel 保持一致）
ARTIFACT_LABEL_MAP = {
    "raw_data": "原始数据",
    "analysis_data": "原始数据",
    "cleaning_result": "数据清洗产物",
    "cluster_result": "聚类结果",
    "anomaly_result": "异常检测结果",
    "association_rules": "关联规则",
    "sequential_patterns": "序列模式",
    "ml_model": "机器学习模型",
    "ml_report": "机器学习报告",
    "ml_prediction": "预测结果",
    "predict_data": "预测数据",
    "feature_result": "特征工程产物",
    "analysis_report": "数据分析报告",
}

# task_type → 中文标签（与前端菜单名称一致）
# 特征工程5个子类型统一显示"特征工程"，用 operation_label 区分具体操作
# ml_training 统一显示"机器学习"，用 operation_label 区分具体操作
TASK_TYPE_LABELS = {
    "upload": "文件上传",
    "dataset": "数据治理",
    "cleaning": "数据清洗",
    "data_analysis": "数据分析",
    "data_mining": "数据挖掘",
    # 特征工程子类型统一显示父类名（两级分类：task_type=模块名，operation=具体操作）
    "feature_engineering_select": "特征工程",
    "feature_engineering_construct": "特征工程",
    "feature_engineering_encode": "特征工程",
    "feature_engineering_scale": "特征工程",
    "feature_engineering_reduce": "特征工程",
    "feature_engineering": "特征工程",
    # 机器学习统一显示父类名
    "ml": "机器学习",
    "ml_training": "机器学习",
    "ai": "AI分析",
    # 管理员账号操作（记录到用户操作历史，供审计追溯）
    "user_admin": "账号管理",
}

# params.operation → 中文标签（与前端按钮/向导步骤文案一致，纯中文）
# 同时用于 result_summary 中 operation 字段值的中文转换
OPERATION_LABELS = {
    # 数据治理
    "soft_delete": "软删除",
    "batch_delete": "批量删除",
    "permanent_delete": "永久删除",
    "restore": "恢复数据",
    "clear_trash": "清空回收站",
    "clear_all": "清空回收站",
    "edit_meta": "编辑元数据",
    "import_to_module": "跨模块导入",
    # 管理端操作（记录到用户操作历史，供审计追溯）
    "admin_restore": "管理员恢复",
    "admin_permanent_delete": "管理员永久删除",
    "admin_delete_datasource": "管理员删除连接",
    "admin_user_status": "管理员变更账号状态",
    "admin_reset_password": "管理员重置密码",
    "admin_unlock": "管理员解锁账号",
    # 数据清洗4阶段（前端向导步骤文案）
    "contract_config": "契约配置",
    "problem_strategy": "问题清单配置",
    "execute_clean": "执行清洗",
    "save_clean_result": "保存清洗结果",
    "comprehensive_clean": "综合清洗",  # 兼容旧记录
    # 清洗管道步骤（pipeline 中的 operation 值）
    "column_ops": "列操作",
    "row_filter": "行过滤",
    # 数据分析
    "generate_report": "生成报告",
    "save_report": "保存报告",
    # 数据挖掘
    "cluster": "执行聚类分析",
    "association": "执行关联规则",
    "sequence": "执行序列模式",
    # 数据挖掘保存到数据管理（与上方执行分析区分）
    "save_cluster": "保存聚类结果",
    "save_association": "保存关联规则",
    "save_sequence": "保存序列模式",
    # 特征工程
    "select_features": "特征选择",
    "construct_features": "特征构造",
    "encode_features": "特征编码",
    "scale_features": "特征缩放",
    "reduce_features": "特征降维",
    # 特征工程导出
    "export_selected": "导出特征选择产物",
    "export_pool": "导出列池产物",
    # 机器学习
    "train": "模型训练",
    "batch_predict": "批量预测",
    "test_evaluate": "测试集评估",
    "export_report": "报告导出",
    # AI分析
    "ai_chat": "AI对话",
}

# status → 中文标签
STATUS_LABELS = {
    "pending": "等待中",
    "running": "执行中",
    "success": "成功",
    "failed": "失败",
    "cancelled": "已取消",
    "warning": "警告",
    "error": "错误",
}

# failure_category → 中文标签（失败原因分类，用于操作历史详情展示）
# 前端根据此分类决定是否显示"重试"按钮：
# - param_error / data_error：不可重试（需修改参数或处理数据后重新执行）
# - system_error / timeout / network_error / unknown：可重试
FAILURE_CATEGORY_LABELS = {
    "param_error": "参数错误",
    "data_error": "数据问题",
    "system_error": "系统故障",
    "timeout": "执行超时",
    "network_error": "网络错误",
    "unknown": "未知错误",
}

# failure_category → el-tag type 颜色映射
# param_error/data_error 用 danger（红色，强调需用户介入）
# system_error/timeout/network_error 用 warning（橙色，提示可重试）
# unknown 用 info（灰色）
FAILURE_CATEGORY_TAG_TYPE = {
    "param_error": "danger",
    "data_error": "danger",
    "system_error": "warning",
    "timeout": "warning",
    "network_error": "warning",
    "unknown": "info",
}

# 可重试的失败分类集合（后端 is_retryable_failure 用于计算 can_retry 综合字段；
# 前端 labels.js 同名常量仅用于详情抽屉的"不可重试提示"，不再用于判断重试按钮显示）
RETRYABLE_FAILURE_CATEGORIES = {"system_error", "timeout", "network_error", "unknown"}

# el-tag type 颜色映射（Element Plus 仅支持 '' / success / info / warning / danger，不含 primary）
TASK_TYPE_TAG_TYPE = {
    "upload": "info",
    "dataset": "danger",
    "cleaning": "success",
    "data_analysis": "info",
    "data_mining": "warning",
    "feature_engineering_select": "warning",
    "feature_engineering_construct": "warning",
    "feature_engineering_encode": "warning",
    "feature_engineering_scale": "warning",
    "feature_engineering_reduce": "warning",
    "feature_engineering": "warning",
    "ml": "info",
    "ml_training": "info",
    "ai": "",
}

# result_summary / params 的 key → 纯中文标签
# 递归处理时用此映射转换所有层级的 dict key
RESULT_KEY_LABELS = {
    # 通用
    "row_count": "行数",
    "file_size": "文件大小",
    "column_count": "列数",
    "dataset_name": "数据集名称",
    "dataset_id": "数据集ID",
    "operation": "操作",
    "execution_time": "执行耗时",
    # 嵌套结构通用字段
    "params": "参数",
    "config": "配置",
    "operations": "操作清单",
    "arithmetic": "算术运算",
    "op": "运算符",
    "col1": "列1",
    "col2": "列2",
    # 清洗/分析 params 通用字段
    "mode": "模式",
    "force": "强制执行",
    "sections": "章节",
    "pipeline": "管道",
    "problem_strategies": "问题策略",
    # 上传
    "filename": "文件名",
    "module_source": "来源模块",
    "artifact_type": "产物类型",
    "module_label": "模块标签",
    # 数据治理
    "affected_count": "影响数量",
    "target_ids": "目标ID列表",
    "target_count": "目标数量",
    "actual_deleted": "实际删除数",
    "old_name": "原名称",
    "new_name": "新名称",
    "source_dataset_id": "源数据集ID",
    "source_dataset_name": "源数据集名称",
    "source_module": "来源模块",
    "target_module": "目标模块",
    "new_dataset_id": "新数据集ID",
    "new_dataset_name": "新数据集名称",
    "tags_updated": "标签已更新",
    "remarks_updated": "备注已更新",
    "deleted_count": "删除数量",
    "purged_count": "清空数量",
    "cleared_count": "清空数量",
    "changed_fields": "修改字段",
    "changes_detail": "变动详情",
    # 管理端操作留痕字段
    "admin": "操作管理员",
    "note": "备注说明",
    "datasource_name": "数据源名称",
    # 账号管理操作留痕字段
    "username": "用户名",
    "user_id": "用户ID",
    "is_active": "账号状态",
    # 数据清洗4阶段
    "original_rows": "原始行数",
    "cleaned_rows": "清洗后行数",
    "removed_rows": "移除行数",
    "quality_before": "清洗前质量评分",
    "quality_after": "清洗后质量评分",
    "completeness": "完整性",
    "uniqueness": "唯一性",
    "consistency": "一致性",
    "validity": "有效性",
    "problem_counts": "问题数量",
    "missing_values": "缺失值",
    "duplicates": "重复值",
    "type_errors": "类型错误",
    "outliers": "异常值",
    "range_errors": "范围错误",
    "pipeline_steps": "管道步骤数",
    "contract_fields": "契约字段数",
    "contract": "列契约",
    "column": "列名",
    "action": "操作方式",
    "condition": "过滤条件",
    "rename_map": "重命名映射",
    "columns": "列列表",
    "missing_values_strategy": "缺失值处理",
    "duplicates_strategy": "重复值处理",
    "type_errors_strategy": "类型错误处理",
    "missing_values_count": "缺失值数量",
    "duplicates_count": "重复值数量",
    "type_errors_count": "类型错误数量",
    "outliers_count": "异常值数量",
    "range_errors_count": "范围错误数量",
    "affected_columns": "涉及列数",
    "pipeline_order": "管道顺序",
    "has_rename": "列重命名",
    "has_row_filter": "行过滤",
    "audit_rows": "审计行数",
    "save_confirmed": "保存确认",
    "warnings_ignored": "忽略警告数",
    # 错误/警告（清洗拦截、特征构造验证）
    "errors_count": "错误数",
    "errors": "错误列表",
    "warnings_count": "警告数",
    "warnings": "警告列表",
    "validation_failed": "验证失败",
    # 数据分析
    "report_id": "报告ID",
    "report_name": "报告名称",
    "report_html_length": "报告长度",
    "charts_count": "图表数量",
    "chart_count": "图表数量",
    "chart_types": "图表类型",
    # 数据挖掘
    "n_clusters": "聚类数",
    "silhouette_score": "轮廓系数",
    "noise_count": "噪声点数",
    "noise_percentage": "噪声占比",
    "total_rules": "规则总数",
    "min_support": "最小支持度",
    "min_confidence": "最小置信度",
    "min_lift": "最小提升度",
    "total_patterns": "模式总数",
    "n_sequences": "序列数",
    "params_used": "使用参数",
    "recommended_params": "推荐参数",
    "support_range": "支持度范围",
    "confidence_range": "置信度范围",
    "lift_range": "提升度范围",
    "tid_column": "事务标识列",
    "item_column": "项列",
    # 关联规则数据格式：basket=购物篮格式（双列），binary=自动二值化（0/1矩阵）
    "data_format": "数据格式",
    "auto_params": "是否使用推荐参数",
    # 数据挖掘 sequence 列名
    "seq_id_column": "序列ID列",
    "time_column": "时间列",
    "event_column": "事件列",
    # 数据挖掘 params_used 内嵌字段
    "init": "初始化方式",
    "max_iter": "最大迭代数",
    "n_init": "重复次数",
    "eps": "邻域半径",
    "min_samples": "最小样本数",
    "metric": "距离度量",
    "linkage": "连接方式",
    "max_len": "最大长度",
    "cluster_sizes": "各簇样本数",
    # 特征工程
    "n_features": "原始特征数",
    "n_selected": "选中特征数",
    "encoding_method": "编码方式",
    "scaling_method": "缩放方式",
    "n_components": "降维维度",
    "explained_variance": "解释方差",
    "added_columns": "新增列",
    "removed_columns": "删除列",
    "column_pool_before": "操作前列池",
    "column_pool_after": "操作后列池",
    "before_columns": "操作前列池",
    "after_columns": "操作后列池",
    "target_column": "目标列",
    "feature_columns": "特征列",
    "new_columns_count": "新增列数",
    "total_columns": "总列数",
    "exec_errors_count": "执行错误数",
    "encoded_columns_count": "编码列数",
    "scaled_columns_count": "缩放列数",
    "method": "方法",
    "method_label": "方法标签",
    "selected_features": "选中特征",
    "feature_scores": "特征得分",
    "all_scores": "全部得分",
    "top_k": "保留特征数",
    "total_features": "总特征数",
    "new_features": "新增特征数",
    "excluded_columns": "排除列",
    "excluded_details": "排除详情",
    "target_fill_warnings": "目标列填充警告",
    # 特征工程 config 内嵌字段
    "encoding_map": "编码映射",
    "names": "自定义列名",
    "columns": "列",
    # 机器学习
    "model_name": "模型名称",
    "model_id": "模型ID",
    "algorithm": "算法",
    "task_type": "任务类型",
    "accuracy": "准确率",
    "r2": "R²",
    "f1": "F1",
    "auc": "AUC",
    "metrics": "完整指标",
    "train_rows": "训练行数",
    "test_rows": "测试行数",
    "predict_rows": "预测行数",
    "prediction_rows": "预测行数",
    "cv_folds": "交叉验证折数",
    "test_size": "测试集比例",
    "auto_tune": "自动调参",
    "auto_tune_label": "自动调优",
    "tune_method": "调优方法",
    "best_params": "最优参数",
    "feature_importance": "特征重要性",
    "prediction_file": "预测文件",
    "model_file": "模型文件",
    "test_set_path": "测试集路径",
    "random_seed": "随机种子",
    "predict_dataset_name": "预测数据集名称",
    "predict_dataset_id": "预测数据集ID",
    # ML 旧接口 params 内嵌字段（旧接口删除后老记录仍需展示）
    "features": "特征列",
    "contamination": "异常比例",
    # AI分析
    "question": "问题",
    "context_count": "上下文数量",
    "context_items": "上下文项",
    "start_new_topic": "开启新话题",
    "needs_context": "需要上下文",
    "conversation_id": "会话ID",
    # AI 上下文项内嵌字段
    "ref_id": "引用ID",
    # 异步任务进度
    "current_stage": "当前阶段",
    "current_progress": "当前进度",
    "current_message": "当前消息",
    "progress_history": "进度历史",
    "stage": "阶段",
    "progress": "进度",
    "message": "消息",
    "timestamp": "时间戳",
    # 列结构
    "name": "名称",
    "type": "类型",
    "importance": "重要性",
    # 数据分析章节
    "data_preview": "数据预览",
    "quality": "数据质量",
    "column_info": "列信息",
    "numeric_stats": "数值统计",
    "categorical_stats": "分类统计",
    "charts": "图表分析",
    "sections": "章节",
    "charts_count": "图表数量",
    "report_html_length": "报告长度",
    # ===== v3 新增：ML train/batch_predict result_summary 字段 =====
    "tune_results": "调优结果",
    "split_info": "数据集划分信息",
    "predictions": "预测结果预览",
    "probabilities": "预测概率预览",
    "prediction_count": "预测数量",
    "full_result_saved": "完整结果已保存",
    "train_size": "训练样本数",
    # ===== v3 新增：数据清洗 result_summary 字段 =====
    "audit_report": "审计报告",
    "cleaned_dataset_id": "清洗后数据集ID",
    # ===== v3 新增：特征工程 result_summary 字段（列表本身）=====
    "new_columns": "新增列",
    "exec_errors": "执行错误",
    "encoded_columns": "编码列",
    # ===== v3 新增：通用状态标记 =====
    "success": "是否成功",
    # ===== v3 新增：tune_results 嵌套字段 =====
    "best_score": "最优评分",
    "n_candidates": "候选组合数",
    # ===== v3 新增：split_info 嵌套字段 =====
    "total": "总样本数",
    "trainval": "训练+验证集数",
    "trainval_ratio": "训练+验证集比例",
    "test": "测试集样本数",
    "test_ratio": "测试集比例",
    "test_size_param": "测试集比例参数",
    "description": "说明",
    # ===== v3 新增：audit_report 嵌套字段 =====
    "row_level_diff": "行级差异",
    "column_level_stats": "列级统计",
    "quality_scores": "质量评分",
    "summary": "汇总",
    "marked_columns": "标记列",
    # ===== v3 新增：audit_report.summary 嵌套字段 =====
    "original_cols": "原始列数",
    "cleaned_cols": "清洗后列数",
    "operations_count": "操作数",
    "marked_columns_count": "标记列数",
    # ===== v3 新增：audit_report.column_level_stats 嵌套字段 =====
    "original_missing": "原始缺失数",
    "cleaned_missing": "清洗后缺失数",
    "original_missing_rate": "原始缺失率",
    "cleaned_missing_rate": "清洗后缺失率",
    "original_outliers": "原始异常值数",
    "cleaned_outliers": "清洗后异常值数",
    "original_duplicate": "原始重复数",
    "cleaned_duplicate": "清洗后重复数",
    "data_type": "数据类型",
    # ===== 远程数据源 =====
    "remote_config": "远程数据源配置",
    "is_remote": "数据来源",
    "connection_id": "连接ID",
    "table_name": "表名",
    "use_remote": "使用远程模式",
    # ===== 数据分析报告 =====
    "preview_html": "报告HTML预览",
    "dynamic_data": "图表动态数据",
    # ===== 数据挖掘报告 =====
    "cluster_report": "聚类报告",
    "association_report": "关联规则报告",
    "sequence_report": "序列模式报告",
    "saved": "是否已保存",
    # ===== 数据挖掘报告内嵌字段 =====
    "cluster_stats": "各簇统计",
    "projection_2d": "二维投影",
    "preview_data": "数据预览",
    "quality_assessment": "质量评估",
    "rules": "规则列表",
    "top_patterns": "高频模式",
    "antecedent": "前项",
    "consequent": "后项",
    "support": "支持度",
    "confidence": "置信度",
    "lift": "提升度",
    "features_used": "使用特征",
    "sequence": "序列",
    # ===== 数据治理批量操作对象 =====
    "dataset_names": "数据集名称列表",
    "names_truncated": "名称已截断",
}

# value 需转中文的 key 集合（用 MODULE_LABEL_MAP 转换）
_MODULE_VALUE_KEYS = {"module_source", "source_module", "target_module"}
# value 需转中文的 key 集合（用 ARTIFACT_LABEL_MAP 转换）
_ARTIFACT_VALUE_KEYS = {"artifact_type"}
# value 需转中文的 key 集合（用 OPERATION_LABELS 转换，operation 字段值）
_OPERATION_VALUE_KEYS = {"operation"}

# 特征工程方法值 → 中文（method 字段值）
# 算法名如 xgboost/random_forest/kmeans 等保留英文，仅转换方法类值
METHOD_VALUE_LABELS = {
    # 特征选择方法
    "chi2": "卡方检验",
    "mutual_info": "互信息",
    "pearson": "皮尔逊相关",
    "tree": "树模型",
    "f_classif": "方差分析F检验",
    # 特征构造操作类型
    "arithmetic": "四则运算",
    "polynomial": "多项式",
    "log_transform": "对数变换",
    "binning": "分箱",
    "time_split": "时间拆解",
    "category_cross": "类别交叉",
    "target_encoding": "Target编码",
    # 分箱方法
    "equal_width": "等宽分箱",
    "equal_freq": "等频分箱",
    "kmeans": "KMeans分箱",
    # 编码方式
    "onehot": "独热编码",
    "label": "标签编码",
    "ordinal": "顺序编码",
    "target": "目标编码",
    # 缩放方式
    "standard": "标准化",
    "minmax": "归一化",
    "robust": "鲁棒缩放",
    # 降维方式（pca/tsne 为专有算法名，保留英文）
    # "pca": "主成分分析",
    # "tsne": "t-SNE",
    # 清洗策略
    "mean": "均值填充",
    "median": "中位数填充",
    "mode": "众数填充",
    "drop": "删除",
    "auto_convert": "自动转换",
    "clip": "截断",
    "custom": "自定义",
    "forward_fill": "前向填充",
    "backward_fill": "后向填充",
    "interpolate": "插值",
    # 数据清洗管道步骤（pipeline_order 列表中的字符串值转中文）
    "missing_values": "缺失值处理",
    "type_errors": "类型错误处理",
    "range_errors": "范围错误处理",
    "outliers": "异常值处理",
    "row_duplicates": "行重复值处理",
    "column_duplicates": "列重复值处理",
    # 列操作 action 值（column_ops 的 action 字段）
    "rename": "重命名",
    "delete": "删除",
    # 机器学习任务类型（params/result_summary 中的 task_type 字段值，区别于 task_records.task_type）
    "classification": "分类",
    "regression": "回归",
    "clustering": "聚类",
    "dimensionality_reduction": "降维",
    # 关联规则数据格式值
    "basket": "购物篮格式",
    "binary": "自动二值化",
    # 清洗模式
    "strict": "严格模式",
    "warning": "警告模式",
    "loose": "宽松模式",
    # cleaning mode（分支标识）
    "problem_strategies": "问题清单模式",
    "pipeline": "管道模式",
    "unknown": "未知",
    # 布尔值
    "true": "是",
    "false": "否",
    # 数据分析章节值（sections 字段的值）
    "data_preview": "数据预览",
    "quality": "数据质量",
    "column_info": "列信息",
    "numeric_stats": "数值统计",
    "categorical_stats": "分类统计",
    "charts": "图表分析",
    # type（特征工程 added_columns 列类型推断）
    "numeric": "数值",
    "datetime": "日期时间",
    "string": "字符串",
    # type（AI context_items 类型）
    "dataset": "数据集",
    "operation": "操作记录",
    # ML 调参方法（tune_method 字段值）
    "grid": "网格搜索",
    "random": "随机搜索",
}

# 需要用 METHOD_VALUE_LABELS 转换 value 的 key 集合
# task_type 在 params/result_summary 中是机器学习任务类型（classification/regression），不是 task_records.task_type
# sections 是数据分析报告的章节列表，值需要转中文
# pipeline_order 是数据清洗管道步骤列表，list 中的字符串值需转中文
# data_format 是关联规则数据格式（basket/binary）
# action 是清洗管道 column_ops 的操作类型（rename/delete）
_METHOD_VALUE_KEYS = {"method", "mode", "type", "encoding_method", "scaling_method", "task_type", "sections", "pipeline_order", "data_format", "tune_method", "action"}

# is_remote 的值是布尔（true=远程数据库操作，false=本地操作），需专门转中文
# 不放入通用布尔转换（是/否），避免"数据来源：是"这种不直观展示
_REMOTE_FLAG_VALUE_KEYS = {"is_remote"}

# 算法名 value → 中文（与 algorithm_registry.py 的 label_cn 保持一致）
# 有通用中文名的算法转中文，本身就是英文专有名词的保留英文
ALGORITHM_LABELS = {
    # 监督学习
    "logistic_regression": "逻辑回归",
    "svm": "支持向量机",
    "decision_tree": "决策树",
    "naive_bayes": "朴素贝叶斯",
    "knn": "K近邻",
    "linear_regression": "线性回归",
    "ridge_regression": "岭回归",
    "lasso_regression": "Lasso回归",
    "random_forest": "随机森林",
    "adaboost": "AdaBoost",
    "gbdt": "梯度提升树",
    "xgboost": "XGBoost",
    "lightgbm": "LightGBM",
    "mlp": "多层感知机",
    # 数据挖掘
    "kmeans": "KMeans",
    "dbscan": "DBSCAN",
    "hierarchical": "层次聚类",
    "apriori": "Apriori",
    "fpgrowth": "FP-Growth",
    "prefixspan": "PrefixSpan",
    "gsp": "GSP",
    # ML 旧接口曾用值（旧接口删除后老记录仍需展示）
    "association_rules": "关联规则",
    "isolation_forest": "孤立森林",
}

# value 需用 ALGORITHM_LABELS 转中文的 key 集合
_ALGORITHM_VALUE_KEYS = {"algorithm"}


def get_task_type_label(task_type: str) -> str:
    """获取 task_type 的中文标签，未映射时返回原值"""
    return TASK_TYPE_LABELS.get(task_type, task_type)


def get_operation_label(operation: str) -> str:
    """获取 operation 的中文标签，未映射时返回原值"""
    return OPERATION_LABELS.get(operation, operation) if operation else None


def get_status_label(status: str) -> str:
    """获取 status 的中文标签，未映射时返回原值"""
    return STATUS_LABELS.get(status, status)


def get_failure_category_label(category: str) -> str:
    """获取 failure_category 的中文标签，未映射时返回原值"""
    return FAILURE_CATEGORY_LABELS.get(category, category) if category else None


def get_failure_category_tag_type(category: str) -> str:
    """获取 failure_category 对应的 el-tag type（颜色），未映射时返回 info"""
    return FAILURE_CATEGORY_TAG_TYPE.get(category, "info") if category else "info"


def is_retryable_failure(category: str) -> bool:
    """判断失败分类是否可重试

    param_error / data_error 不可重试（需修改参数或处理数据后重新执行）
    system_error / timeout / network_error / unknown 可重试
    空 category 视为可重试（与 retry_async_task 路由逻辑一致：未分类的失败允许重试）
    """
    if not category:
        return True
    return category in RETRYABLE_FAILURE_CATEGORIES


def get_task_type_tag_type(task_type: str) -> str:
    """获取 task_type 对应的 el-tag type（颜色），未映射时返回空字符串"""
    return TASK_TYPE_TAG_TYPE.get(task_type, "")


def _label_value(key: str, value):
    """对特定 key 的 value 转中文

    - 布尔值统一转为"是"/"否"（auto_params/save/force 等）
    - module_source / source_module / target_module：用 MODULE_LABEL_MAP 转（ml→机器学习）
    - artifact_type：用 ARTIFACT_LABEL_MAP 转（raw_data→原始数据）
    - operation：用 OPERATION_LABELS 转（construct_features→特征构造）
    - method / mode / type / task_type / data_format 等：用 METHOD_VALUE_LABELS 转（chi2→卡方检验、classification→分类、basket→购物篮格式）
    - algorithm：用 ALGORITHM_LABELS 转（random_forest→随机森林，XGBoost 保留英文）
    - 其他 value（文件格式/指标符号/数据列名）保留原值
    """
    # 布尔值统一转为"是"/"否"（注意：必须在 isinstance(value, str) 检查之前处理，因为 bool 是 int 的子类但不是 str）
    if isinstance(value, bool):
        # is_remote 特殊处理：true=远程数据库操作，false=本地操作
        if key in _REMOTE_FLAG_VALUE_KEYS:
            return "远程数据库" if value else "本地数据"
        return "是" if value else "否"
    if not isinstance(value, str):
        return value
    if key in _MODULE_VALUE_KEYS:
        return MODULE_LABEL_MAP.get(value, value)
    if key in _ARTIFACT_VALUE_KEYS:
        return ARTIFACT_LABEL_MAP.get(value, value)
    if key in _OPERATION_VALUE_KEYS:
        return OPERATION_LABELS.get(value, value)
    if key in _METHOD_VALUE_KEYS:
        return METHOD_VALUE_LABELS.get(value, value)
    if key in _ALGORITHM_VALUE_KEYS:
        return ALGORITHM_LABELS.get(value, value)
    return value


def _label_dict_keys(data: dict) -> dict:
    """递归将 dict 的 key 转为纯中文，并对特定 key 的 value 转中文

    规则：
    - key 在 RESULT_KEY_LABELS 中映射为纯中文，否则保留原 key
    - value 中的 dict 递归处理
    - value 中的 list 逐项处理（仅处理 dict 项）
    - module_source/source_module/target_module 的 value 用 MODULE_LABEL_MAP 转中文
    - artifact_type 的 value 用 ARTIFACT_LABEL_MAP 转中文
    - operation 的 value 用 OPERATION_LABELS 转中文
    - task_type 的 value 用 TASK_TYPE_LABELS 转中文
    - method/mode/type 等的 value 用 METHOD_VALUE_LABELS 转中文
    - 其他 value（算法名/文件格式/指标符号/数据列名）保留原值
    """
    if not isinstance(data, dict):
        return data

    result = {}
    for key, value in data.items():
        # key 转纯中文
        labeled_key = RESULT_KEY_LABELS.get(key, key)
        # value 处理
        if isinstance(value, dict):
            result[labeled_key] = _label_dict_keys(value)
        elif isinstance(value, list):
            result[labeled_key] = [
                _label_dict_keys(item) if isinstance(item, dict) else _label_value(key, item)
                for item in value
            ]
        else:
            result[labeled_key] = _label_value(key, value)
    return result


def label_result_summary(summary: dict) -> dict:
    """将 result_summary 的 key 转为纯中文并对特定 value 转中文

    用于前端展示操作详情。输入为 None 时返回空 dict。
    """
    if not summary or not isinstance(summary, dict):
        return {}
    return _label_dict_keys(summary)


def label_params(params: dict) -> dict:
    """将 params 的 key 转为纯中文并对特定 value 转中文

    用于前端展示操作参数。输入为 None 时返回空 dict。
    """
    if not params or not isinstance(params, dict):
        return {}
    return _label_dict_keys(params)


def extract_operation(params: dict) -> str:
    """从 params 中提取 operation 字段

    用于操作历史列表展示"具体操作"二级分类。
    无 operation 时返回 None。
    """
    if not params or not isinstance(params, dict):
        return None
    return params.get("operation")


def build_action_description(task_type: str, operation: str, params: dict,
                             result_summary: dict, status: str,
                             dataset_name: str = None) -> str:
    """根据 task_type + operation + result_summary 拼接操作简述（一句话）

    用于操作历史列表"操作简述"列展示。
    - success 状态：展示动作 + 对象 + 核心结果
    - failed/running/pending 状态：展示动作 + 对象
    - 字段缺失时省略对应部分，不显示 None/0/空
    """
    params = params or {}
    result_summary = result_summary or {}

    # 非 success 状态：展示"模块标签 状态：对象"
    if status and status != "success":
        task_label = TASK_TYPE_LABELS.get(task_type, task_type)
        status_label = STATUS_LABELS.get(status, status)
        obj = (dataset_name or params.get("filename")
               or result_summary.get("dataset_name")
               or result_summary.get("new_dataset_name") or "-")
        return f"{task_label} {status_label}：{obj}"

    # success 状态：按 task_type + operation 拼接
    return _build_success_desc(task_type, operation, params, result_summary, dataset_name)


def _alg_label(alg):
    """算法名转中文（用于简述中的算法名占位符）"""
    if not alg:
        return None
    return ALGORITHM_LABELS.get(alg, alg)


def _mod_label(mod):
    """模块名转中文（用于简述中的模块名占位符）"""
    if not mod:
        return None
    return MODULE_LABEL_MAP.get(mod, mod)


def _build_success_desc(task_type: str, operation: str, params: dict,
                        result_summary: dict, dataset_name: str) -> str:
    """构建 success 状态的操作简述"""
    rs = result_summary
    p = params

    # ===== 文件上传 =====
    if task_type == "upload":
        filename = rs.get("filename") or p.get("filename") or ""
        row, col = rs.get("row_count"), rs.get("column_count")
        base = f"已上传 {filename}" if filename else "已上传文件"
        detail = []
        if row is not None:
            detail.append(f"{row}行")
        if col is not None:
            detail.append(f"{col}列")
        return base + (f"（{'×'.join(detail)}）" if detail else "")

    # ===== 数据治理 =====
    if task_type == "dataset":
        name = rs.get("dataset_name") or dataset_name or ""
        if operation == "soft_delete":
            return f"已移到回收站：{name}" if name else "已移到回收站"
        if operation == "batch_delete":
            n = rs.get("actual_deleted")
            return f"已将 {n} 项移到回收站" if n is not None else "已批量移到回收站"
        if operation == "permanent_delete":
            return f"已永久删除：{name}" if name else "已永久删除"
        if operation == "restore":
            return f"已恢复：{name}" if name else "已恢复数据"
        if operation in ("clear_trash", "clear_all"):
            n = rs.get("cleared_count")
            label = "回收站" if operation == "clear_trash" else "所有数据"
            return f"已清空{label}，共 {n} 项" if n is not None else f"已清空{label}"
        if operation == "edit_meta":
            fields = rs.get("changed_fields")
            fields_str = f"（{fields}）" if fields else ""
            return f"已编辑元数据：{name}{fields_str}" if name else f"已编辑元数据{fields_str}"
        if operation == "import_to_module":
            src = _mod_label(rs.get("source_module") or p.get("source_module"))
            tgt = _mod_label(rs.get("target_module") or p.get("target_module"))
            new_name = rs.get("new_dataset_name") or ""
            if src and tgt and new_name:
                return f"已从{src}导入到{tgt}：{new_name}"
            return "已跨模块导入"

    # ===== 数据清洗 =====
    if task_type == "cleaning":
        if operation == "contract_config":
            n = rs.get("contract_fields")
            return f"已配置契约（{n}个字段）" if n is not None else "已配置契约"
        if operation == "problem_strategy":
            n = rs.get("affected_columns")
            return f"已配置问题清单（涉及{n}列）" if n is not None else "已配置问题清单"
        if operation == "execute_clean":
            orig, audit = rs.get("original_rows"), rs.get("audit_rows")
            if orig is not None and audit is not None:
                return f"清洗完成（{orig}→{audit}行）"
            return "清洗完成"
        if operation == "save_clean_result":
            new_name = rs.get("new_dataset_name") or ""
            orig, cleaned = rs.get("original_rows"), rs.get("cleaned_rows")
            if new_name and orig is not None and cleaned is not None:
                return f"已保存清洗结果：{new_name}（{orig}→{cleaned}行）"
            if new_name:
                return f"已保存清洗结果：{new_name}"
            return "已保存清洗结果"

    # ===== 数据分析 =====
    if task_type == "data_analysis":
        if operation == "generate_report":
            n = rs.get("charts_count")
            return f"已生成报告（{n}个图表）" if n is not None else "已生成报告"
        if operation == "save_report":
            name = rs.get("report_name") or ""
            return f"已保存报告：{name}" if name else "已保存报告"

    # ===== 数据挖掘 =====
    if task_type == "data_mining":
        # 统一处理执行分析和保存到数据管理两种操作
        # save_cluster/save_association/save_sequence 与 cluster/association/sequence 共用简述逻辑
        is_save = operation and operation.startswith("save_")
        if operation in ("cluster", "save_cluster"):
            n = rs.get("n_clusters")
            sil = rs.get("silhouette_score")
            prefix = "已保存聚类结果" if is_save else "聚类完成"
            if n is not None and sil is not None:
                return f"{prefix}（{n}簇，轮廓系数{sil}）"
            if n is not None:
                return f"{prefix}（{n}簇）"
            return prefix
        if operation in ("association", "save_association"):
            n = rs.get("total_rules")
            prefix = "已保存关联规则" if is_save else "关联规则完成"
            return f"{prefix}（{n}条规则）" if n is not None else prefix
        if operation in ("sequence", "save_sequence"):
            n = rs.get("total_patterns")
            prefix = "已保存序列模式" if is_save else "序列模式完成"
            return f"{prefix}（{n}个模式）" if n is not None else prefix

    # ===== 特征工程 =====
    if task_type and task_type.startswith("feature_engineering"):
        if operation == "select_features":
            sel, total = rs.get("n_selected"), rs.get("n_features")
            if sel is not None and total is not None:
                return f"特征选择完成（{sel}/{total}个）"
            return "特征选择完成"
        if operation == "export_selected":
            new_name = rs.get("new_dataset_name") or ""
            return f"已导出特征选择产物：{new_name}" if new_name else "已导出特征选择产物"
        if operation == "construct_features":
            n = rs.get("new_columns_count")
            return f"特征构造完成（新增{n}列）" if n is not None else "特征构造完成"
        if operation == "export_pool":
            new_name = rs.get("new_dataset_name") or ""
            return f"已导出列池产物：{new_name}" if new_name else "已导出列池产物"
        if operation == "encode_features":
            n = rs.get("encoded_columns_count")
            return f"特征编码完成（{n}列）" if n is not None else "特征编码完成"
        if operation == "scale_features":
            n = rs.get("scaled_columns_count")
            return f"特征缩放完成（{n}列）" if n is not None else "特征缩放完成"
        if operation == "reduce_features":
            n = rs.get("n_components")
            return f"特征降维完成（{n}维）" if n is not None else "特征降维完成"

    # ===== 机器学习训练 =====
    if task_type == "ml_training":
        if operation == "train":
            alg = _alg_label(rs.get("algorithm") or p.get("algorithm"))
            acc = rs.get("accuracy")
            if alg and acc is not None:
                return f"训练完成（{alg}，准确率{acc}）"
            if alg:
                return f"训练完成（{alg}）"
            return "训练完成"

    # ===== 机器学习其他操作 =====
    if task_type == "ml":
        if operation == "batch_predict":
            n = rs.get("prediction_rows")
            return f"批量预测完成（{n}行）" if n is not None else "批量预测完成"
        if operation == "test_evaluate":
            acc = rs.get("accuracy")
            return f"测试集评估完成（准确率{acc}）" if acc is not None else "测试集评估完成"
        if operation == "export_report":
            name = rs.get("report_name") or ""
            return f"已导出报告：{name}" if name else "已导出报告"

    # ===== AI 分析 =====
    if task_type == "ai":
        if operation == "ai_chat":
            n = rs.get("context_count")
            return f"AI对话（{n}个上下文）" if n is not None else "AI对话"

    # ===== 兜底：操作标签 + 完成 =====
    op_label = OPERATION_LABELS.get(operation, "")
    task_label = TASK_TYPE_LABELS.get(task_type, task_type)
    if op_label:
        return f"{op_label}完成"
    return f"{task_label}完成"
