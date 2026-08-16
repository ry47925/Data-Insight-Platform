"""机器学习算法注册表

集中管理所有支持的算法,包括:
- 算法名称(中英文)
- 支持的任务类型(分类/回归)
- 估算器构造函数(惰性导入,避免启动时加载全部依赖)
- 默认超参数搜索空间(用于 L2/L3 自动调优)
- 调优策略配置(n_iter 按算法特点配置)
- 是否原生支持缺失值(决定预测时是否需要 fillna)
- 大数据适用性(用于预检警告)

新增算法只需在 ALGORITHM_REGISTRY 中添加一条记录,无需改动训练主流程。
"""

from typing import Any, Callable, Dict, List, Optional


def _lazy_logistic_regression(**kwargs):
    from sklearn.linear_model import LogisticRegression
    return LogisticRegression(max_iter=1000, **kwargs)


def _lazy_random_forest_clf(**kwargs):
    from sklearn.ensemble import RandomForestClassifier
    return RandomForestClassifier(n_jobs=-1, **kwargs)


def _lazy_random_forest_reg(**kwargs):
    from sklearn.ensemble import RandomForestRegressor
    return RandomForestRegressor(n_jobs=-1, **kwargs)


def _lazy_svm_clf(**kwargs):
    from sklearn.svm import SVC
    return SVC(probability=True, **kwargs)


def _lazy_svm_reg(**kwargs):
    from sklearn.svm import SVR
    return SVR(**kwargs)


def _lazy_decision_tree_clf(**kwargs):
    from sklearn.tree import DecisionTreeClassifier
    return DecisionTreeClassifier(**kwargs)


def _lazy_decision_tree_reg(**kwargs):
    from sklearn.tree import DecisionTreeRegressor
    return DecisionTreeRegressor(**kwargs)


def _lazy_naive_bayes(**kwargs):
    from sklearn.naive_bayes import GaussianNB
    return GaussianNB(**kwargs)


def _lazy_knn_clf(**kwargs):
    from sklearn.neighbors import KNeighborsClassifier
    return KNeighborsClassifier(n_jobs=-1, **kwargs)


def _lazy_knn_reg(**kwargs):
    from sklearn.neighbors import KNeighborsRegressor
    return KNeighborsRegressor(n_jobs=-1, **kwargs)


def _lazy_linear_regression(**kwargs):
    from sklearn.linear_model import LinearRegression
    return LinearRegression(**kwargs)


def _lazy_ridge(**kwargs):
    from sklearn.linear_model import Ridge
    return Ridge(**kwargs)


def _lazy_lasso(**kwargs):
    from sklearn.linear_model import Lasso
    return Lasso(max_iter=10000, **kwargs)


def _lazy_adaboost_clf(**kwargs):
    from sklearn.ensemble import AdaBoostClassifier
    return AdaBoostClassifier(**kwargs)


def _lazy_adaboost_reg(**kwargs):
    from sklearn.ensemble import AdaBoostRegressor
    return AdaBoostRegressor(**kwargs)


def _lazy_gbdt_clf(**kwargs):
    from sklearn.ensemble import GradientBoostingClassifier
    return GradientBoostingClassifier(**kwargs)


def _lazy_gbdt_reg(**kwargs):
    from sklearn.ensemble import GradientBoostingRegressor
    return GradientBoostingRegressor(**kwargs)


def _lazy_xgboost_clf(**kwargs):
    from xgboost import XGBClassifier
    kwargs.setdefault('eval_metric', 'logloss')
    kwargs.setdefault('n_jobs', -1)
    return XGBClassifier(**kwargs)


def _lazy_xgboost_reg(**kwargs):
    from xgboost import XGBRegressor
    kwargs.setdefault('n_jobs', -1)
    return XGBRegressor(**kwargs)


def _lazy_lightgbm_clf(**kwargs):
    from lightgbm import LGBMClassifier
    kwargs.setdefault('n_jobs', -1)
    kwargs.setdefault('verbose', -1)
    return LGBMClassifier(**kwargs)


def _lazy_lightgbm_reg(**kwargs):
    from lightgbm import LGBMRegressor
    kwargs.setdefault('n_jobs', -1)
    kwargs.setdefault('verbose', -1)
    return LGBMRegressor(**kwargs)


def _lazy_mlp_clf(**kwargs):
    from sklearn.neural_network import MLPClassifier
    # max_iter=200 + early_stopping 防止训练超时卡死系统(原 max_iter=500 无早停)
    # early_stopping=True:验证集连续 n_iter_no_change 轮无提升则提前终止
    kwargs.setdefault('max_iter', 200)
    kwargs.setdefault('early_stopping', True)
    kwargs.setdefault('n_iter_no_change', 10)
    return MLPClassifier(**kwargs)


def _lazy_mlp_reg(**kwargs):
    from sklearn.neural_network import MLPRegressor
    kwargs.setdefault('max_iter', 200)
    kwargs.setdefault('early_stopping', True)
    kwargs.setdefault('n_iter_no_change', 10)
    return MLPRegressor(**kwargs)


# 算法注册表
# 字段说明:
#   label_cn:        中文名称,用于前端展示和产物 algorithm 字段
#   task_types:      支持的任务类型,["classification"] / ["regression"] / ["classification", "regression"]
#   estimator_fn:    估算器构造函数(惰性导入),调用时传入 random_state 和其它超参
#   default_params:  默认超参数(直接训练时使用)
#   param_grid:      超参数搜索空间(自动调优时使用)
#   search_strategy: 推荐搜索策略,"grid"(网格) / "random"(随机)
#   n_iter:          随机搜索迭代次数(仅 search_strategy="random" 时生效)
#   native_nan:      是否原生支持缺失值,True 表示预测时不需要 fillna
#   large_data_ok:   大数据(>1万行)是否适用,False 表示预检应给出警告
#   slow_warning_rows: 触发慢警告的行数阈值,None 表示不警告
ALGORITHM_REGISTRY: Dict[str, Dict[str, Any]] = {
    # ===== 监督学习 - 分类算法 =====
    "logistic_regression": {
        "label_cn": "逻辑回归",
        "task_types": ["classification"],
        "estimator_fn": _lazy_logistic_regression,
        "default_params": {},
        "param_grid": {"C": [0.01, 0.1, 1, 10, 100], "solver": ["lbfgs", "liblinear"]},
        "search_strategy": "grid",
        "n_iter": 10,
        "native_nan": False,
        "large_data_ok": True,
        "slow_warning_rows": None,
    },
    "svm": {
        "label_cn": "支持向量机",
        "task_types": ["classification", "regression"],
        "estimator_fn": None,  # 分类/回归分别构造,见 build_estimator
        "default_params": {},
        "param_grid": {"C": [0.1, 1, 10], "kernel": ["linear", "rbf"], "gamma": ["scale", "auto"]},
        "search_strategy": "random",
        "n_iter": 10,
        "native_nan": False,
        "large_data_ok": False,
        "slow_warning_rows": 10000,
    },
    "decision_tree": {
        "label_cn": "决策树",
        "task_types": ["classification", "regression"],
        "estimator_fn": None,  # 分类/回归分别构造
        "default_params": {},
        "param_grid": {"max_depth": [3, 5, 10, None], "min_samples_split": [2, 5, 10]},
        "search_strategy": "grid",
        "n_iter": 10,
        "native_nan": False,
        "large_data_ok": True,
        "slow_warning_rows": None,
    },
    "naive_bayes": {
        "label_cn": "朴素贝叶斯",
        "task_types": ["classification"],
        "estimator_fn": _lazy_naive_bayes,
        "default_params": {},
        "param_grid": {"var_smoothing": [1e-9, 1e-8, 1e-7, 1e-6]},
        "search_strategy": "grid",
        "n_iter": 4,
        "native_nan": False,
        "large_data_ok": True,
        "slow_warning_rows": None,
    },
    "knn": {
        "label_cn": "K近邻",
        "task_types": ["classification", "regression"],
        "estimator_fn": None,  # 分类/回归分别构造
        "default_params": {"n_neighbors": 5},
        "param_grid": {"n_neighbors": [3, 5, 7, 11, 15], "weights": ["uniform", "distance"]},
        "search_strategy": "grid",
        "n_iter": 10,
        "native_nan": False,
        "large_data_ok": False,
        "slow_warning_rows": 10000,
    },

    # ===== 监督学习 - 回归算法 =====
    "linear_regression": {
        "label_cn": "线性回归",
        "task_types": ["regression"],
        "estimator_fn": _lazy_linear_regression,
        "default_params": {},
        "param_grid": {},  # 简单线性回归无超参
        "search_strategy": "grid",
        "n_iter": 0,
        "native_nan": False,
        "large_data_ok": True,
        "slow_warning_rows": None,
    },
    "ridge_regression": {
        "label_cn": "岭回归",
        "task_types": ["regression"],
        "estimator_fn": _lazy_ridge,
        "default_params": {},
        "param_grid": {"alpha": [0.01, 0.1, 1, 10, 100]},
        "search_strategy": "grid",
        "n_iter": 5,
        "native_nan": False,
        "large_data_ok": True,
        "slow_warning_rows": None,
    },
    "lasso_regression": {
        "label_cn": "Lasso回归",
        "task_types": ["regression"],
        "estimator_fn": _lazy_lasso,
        "default_params": {},
        "param_grid": {"alpha": [0.01, 0.1, 1, 10, 100]},
        "search_strategy": "grid",
        "n_iter": 5,
        "native_nan": False,
        "large_data_ok": True,
        "slow_warning_rows": None,
    },

    # ===== 集成学习 =====
    "random_forest": {
        "label_cn": "随机森林",
        "task_types": ["classification", "regression"],
        "estimator_fn": None,  # 分类/回归分别构造
        "default_params": {},
        "param_grid": {"n_estimators": [50, 100, 200], "max_depth": [3, 5, 10, None], "min_samples_split": [2, 5, 10]},
        "search_strategy": "random",
        "n_iter": 20,
        "native_nan": False,
        "large_data_ok": True,
        "slow_warning_rows": None,
    },
    "adaboost": {
        "label_cn": "AdaBoost",
        "task_types": ["classification", "regression"],
        "estimator_fn": None,
        "default_params": {},
        "param_grid": {"n_estimators": [50, 100, 200], "learning_rate": [0.01, 0.1, 1.0]},
        "search_strategy": "random",
        "n_iter": 15,
        "native_nan": False,
        "large_data_ok": True,
        "slow_warning_rows": None,
    },
    "gbdt": {
        "label_cn": "梯度提升树",
        "task_types": ["classification", "regression"],
        "estimator_fn": None,
        "default_params": {},
        "param_grid": {"n_estimators": [50, 100, 200], "max_depth": [3, 5, 7], "learning_rate": [0.01, 0.1, 0.2]},
        "search_strategy": "random",
        "n_iter": 20,
        "native_nan": False,
        "large_data_ok": True,
        "slow_warning_rows": 50000,
    },
    "xgboost": {
        "label_cn": "XGBoost",
        "task_types": ["classification", "regression"],
        "estimator_fn": None,
        "default_params": {},
        "param_grid": {"n_estimators": [50, 100, 200], "max_depth": [3, 5, 7], "learning_rate": [0.01, 0.1, 0.2]},
        "search_strategy": "random",
        "n_iter": 20,
        "native_nan": True,
        "large_data_ok": True,
        "slow_warning_rows": None,
    },
    "lightgbm": {
        "label_cn": "LightGBM",
        "task_types": ["classification", "regression"],
        "estimator_fn": None,
        "default_params": {},
        "param_grid": {"n_estimators": [50, 100, 200], "num_leaves": [31, 63, 127], "learning_rate": [0.01, 0.1, 0.2]},
        "search_strategy": "random",
        "n_iter": 20,
        "native_nan": True,
        "large_data_ok": True,
        "slow_warning_rows": None,
    },

    # ===== 基于神经网络的深度学习 =====
    "mlp": {
        "label_cn": "多层感知机",
        "task_types": ["classification", "regression"],
        "estimator_fn": None,
        "default_params": {"hidden_layer_sizes": (64, 32)},
        "param_grid": {"hidden_layer_sizes": [(32,), (64,), (64, 32), (128, 64)], "alpha": [0.0001, 0.001, 0.01]},
        "search_strategy": "random",
        "n_iter": 10,
        "native_nan": False,
        "large_data_ok": True,
        "slow_warning_rows": 50000,
    },
}


def build_estimator(algorithm: str, task_type: str, random_seed: int = 42) -> Any:
    """构造算法估算器实例

    Args:
        algorithm: 算法标识符(如 "random_forest")
        task_type: 任务类型("classification" 或 "regression")
        random_seed: 随机种子

    Returns:
        sklearn/xgboost/lightgbm 估算器实例

    Raises:
        ValueError: 算法不支持或任务类型不匹配
    """
    if algorithm not in ALGORITHM_REGISTRY:
        raise ValueError(f"不支持的算法: {algorithm}")

    reg = ALGORITHM_REGISTRY[algorithm]
    if task_type not in reg["task_types"]:
        raise ValueError(f"算法 {reg['label_cn']}({algorithm}) 不支持 {task_type} 任务")

    # 分类/回归分别构造的算法
    if algorithm == "logistic_regression":
        return _lazy_logistic_regression(random_state=random_seed)
    if algorithm == "naive_bayes":
        return _lazy_naive_bayes()
    if algorithm == "linear_regression":
        return _lazy_linear_regression()
    if algorithm == "ridge_regression":
        return _lazy_ridge(random_state=random_seed)
    if algorithm == "lasso_regression":
        return _lazy_lasso(random_state=random_seed)

    if algorithm == "svm":
        if task_type == "classification":
            return _lazy_svm_clf(random_state=random_seed)
        return _lazy_svm_reg()
    if algorithm == "decision_tree":
        if task_type == "classification":
            return _lazy_decision_tree_clf(random_state=random_seed)
        return _lazy_decision_tree_reg(random_state=random_seed)
    if algorithm == "knn":
        if task_type == "classification":
            return _lazy_knn_clf()
        return _lazy_knn_reg()
    if algorithm == "random_forest":
        if task_type == "classification":
            return _lazy_random_forest_clf(random_state=random_seed)
        return _lazy_random_forest_reg(random_state=random_seed)
    if algorithm == "adaboost":
        if task_type == "classification":
            return _lazy_adaboost_clf(random_state=random_seed)
        return _lazy_adaboost_reg(random_state=random_seed)
    if algorithm == "gbdt":
        if task_type == "classification":
            return _lazy_gbdt_clf(random_state=random_seed)
        return _lazy_gbdt_reg(random_state=random_seed)
    if algorithm == "xgboost":
        if task_type == "classification":
            return _lazy_xgboost_clf(random_state=random_seed)
        return _lazy_xgboost_reg(random_state=random_seed)
    if algorithm == "lightgbm":
        if task_type == "classification":
            return _lazy_lightgbm_clf(random_state=random_seed)
        return _lazy_lightgbm_reg(random_state=random_seed)
    if algorithm == "mlp":
        if task_type == "classification":
            return _lazy_mlp_clf(random_state=random_seed)
        return _lazy_mlp_reg(random_state=random_seed)

    raise ValueError(f"算法 {algorithm} 的估算器构造未实现")


def get_algorithm_label(algorithm: str) -> str:
    """获取算法的中文名称

    兼容多种格式:
    - 纯算法名: "random_forest"
    - 旧格式(半角括号): "random_forest (classification)"
    - 新格式(全角括号): "随机森林（分类）"
    - 纯中文名: "随机森林"
    """
    if not algorithm:
        return "-"
    # 兼容半角和全角括号,提取括号前的纯名称
    import re
    pure_name = re.split(r'\s*[(（]', algorithm)[0].strip()
    reg = ALGORITHM_REGISTRY.get(pure_name)
    if reg:
        return reg["label_cn"]
    # 可能已经是中文名(如"随机森林"),直接返回
    return pure_name


def format_algorithm_field(algorithm: str, task_type: str) -> str:
    """格式化 algorithm 字段为中文显示

    输出格式: "随机森林（分类）" / "XGBoost（回归）"
    使用全角括号与现有命名风格一致
    """
    label_cn = get_algorithm_label(algorithm)
    task_cn = "分类" if task_type == "classification" else "回归"
    return f"{label_cn}（{task_cn}）"


def get_default_param_grid(algorithm: str) -> Dict[str, list]:
    """获取算法的默认超参数搜索空间"""
    reg = ALGORITHM_REGISTRY.get(algorithm)
    if not reg:
        return {}
    return reg.get("param_grid", {})


def get_search_config(algorithm: str, user_tune_method: Optional[str] = None) -> Dict[str, Any]:
    """获取算法的搜索策略配置

    优先使用算法注册表推荐的策略,用户显式指定时遵循用户选择

    Returns:
        {"strategy": "grid"|"random", "n_iter": int}
    """
    reg = ALGORITHM_REGISTRY.get(algorithm)
    if not reg:
        return {"strategy": "random", "n_iter": 20}

    # 用户指定 grid 就用 grid,指定 random 就用 random
    if user_tune_method == "grid":
        return {"strategy": "grid", "n_iter": 0}
    if user_tune_method == "random":
        return {"strategy": "random", "n_iter": reg.get("n_iter", 20)}

    # 未指定时用算法推荐策略
    return {"strategy": reg.get("search_strategy", "random"), "n_iter": reg.get("n_iter", 20)}


def native_nan_support(algorithm: str) -> bool:
    """算法是否原生支持缺失值(决定预测时是否需要 fillna)"""
    reg = ALGORITHM_REGISTRY.get(algorithm)
    return bool(reg and reg.get("native_nan", False))
