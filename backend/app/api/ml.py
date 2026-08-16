from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Body
from fastapi.responses import StreamingResponse
from urllib.parse import quote
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from app.models import Dataset, User
from app.schemas.dataset import DatasetResponse
from app.services.data_service import DataService
from app.utils.db import get_db, SessionLocal
from app.utils.security import get_current_user
from app.utils.common import clean_dataset_name, build_product_name, safe_value, clear_user_dataset_cache, MODULE_LABEL_MAP, validate_upload_file
from app.utils.task_records import (
    create_task_record, update_task_record, update_task_progress,
    mark_task_running, classify_failure, check_task_queue_capacity
)
from app.services.storage_manager import storage_manager
from app.services.task_manager import task_manager
from app.services.algorithm_registry import (
    ALGORITHM_REGISTRY, build_estimator, get_default_param_grid,
    get_search_config, native_nan_support, format_algorithm_field
)
from app.config import settings
from celery.exceptions import SoftTimeLimitExceeded
import os
import re
import io
import json
import time
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

SHANGHAI_TZ = timezone(timedelta(hours=8))

router = APIRouter()


def _coerce_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """将 object 类型列中超过 50% 可转为数值的列转换为数值类型

    远程模式下 SQLAlchemy 返回的数据未做类型转换，数值列可能被加载为 object 类型，
    导致 select_dtypes(include=[np.number]) 漏掉数值列，进而影响特征选择和模型训练。
    与 feature_engineering.py 中的 _coerce_numeric_columns 逻辑保持一致。
    """
    for col in df.columns:
        if df[col].dtype == 'object':
            converted = pd.to_numeric(df[col], errors='coerce')
            if converted.notna().sum() > len(df[col]) * 0.5:
                df[col] = converted
    return df


# 验证数据来源是否属于ML模块
def validate_ml_data_source(db: Session, dataset_id: int, user_id: int) -> Dataset:
    """验证数据集来源是否可用于预测（ML原始数据或预测数据）"""
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.user_id == user_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")
    # 支持 ML 原始数据 和 预测数据
    valid_types = ["raw_data", "predict_data"]
    if dataset.artifact_type not in valid_types:
        raise HTTPException(status_code=403, detail="只能使用原始数据或预测数据进行分析")
    return dataset


def cascade_delete_ml_testset(dataset_record: Dataset):
    """级联删除 ML 模型关联的测试集文件

    模型 pkl 文件保存在 dataset.file_path,测试集 CSV 路径保存在 pkl 内部的
    'test_set_path' 字段。删除模型时必须同步删除测试集文件,避免孤儿文件。

    用于:
    - 用户端永久删除模型记录
    - 管理端永久删除模型记录
    - 管理端存储批量删除模型文件

    Args:
        dataset_record: artifact_type="ml_model" 的 Dataset 记录
    """
    if not dataset_record or dataset_record.artifact_type != "ml_model":
        return
    if not dataset_record.file_path:
        return
    try:
        import joblib as _joblib
        model_bytes = storage_manager.get_file_bytes(dataset_record.file_path)
        model_data = _joblib.load(io.BytesIO(model_bytes))
        test_set_path = model_data.get('test_set_path')
        if test_set_path:
            try:
                storage_manager.delete(test_set_path)
            except Exception:
                # 测试集文件可能已被管理员单独删除,忽略错误
                pass
    except Exception:
        # 模型 pkl 可能已损坏或被单独删除,忽略错误(主文件删除流程会继续)
        pass


def find_ml_model_by_testset_path(db: Session, test_set_path: str):
    """根据测试集文件路径反查关联的 ML 模型记录

    用于管理员端存储删除保护:删除 testset_xxx.csv 前先检查是否有关联模型,
    若有则提示用户该文件关联模型,删除后该模型将无法进行测试集评估。

    Returns:
        关联的 Dataset 记录列表(artifact_type="ml_model"),空列表表示无关联
    """
    # 测试集路径保存在 pkl 内部,无法用 SQL 直接查询,
    # 遍历所有 ml_model 记录,加载 pkl 检查 test_set_path 是否匹配
    # 为避免性能问题,仅检查文件名包含 'testset' 的路径
    if not test_set_path or 'testset' not in test_set_path:
        return []

    candidates = db.query(Dataset).filter(
        Dataset.artifact_type == "ml_model",
        Dataset.file_path.isnot(None)
    ).all()

    matched = []
    import joblib as _joblib
    for record in candidates:
        try:
            model_bytes = storage_manager.get_file_bytes(record.file_path)
            model_data = _joblib.load(io.BytesIO(model_bytes))
            if model_data.get('test_set_path') == test_set_path:
                matched.append(record)
        except Exception:
            continue
    return matched


# 旧版算法请求模型（仅用于 random-forest/linear-regression/dbscan/apriori 等旧版接口）
# 新版统一训练接口 /train-supervised 直接接收 dict 配置,不使用此模型
class MLRequestBody(BaseModel):
    dataset_id: int
    target_column: Optional[str] = None
    features: Optional[str] = None
    eps: Optional[float] = None
    min_samples: Optional[int] = None
    min_support: Optional[float] = None
    min_confidence: Optional[float] = None


# 获取ML模块专用的原始数据列表
@router.get("/raw-data", response_model=list[DatasetResponse])
async def get_ml_raw_data(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取ML模块专用的原始数据列表（仅返回 module_source=ml 且 artifact_type=raw_data 的数据）"""
    datasets = db.query(Dataset).filter(
        Dataset.module_source == "ml",
        Dataset.artifact_type == "raw_data",
        Dataset.user_id == current_user.id,
        Dataset.status == "active"
    ).all()
    return datasets


# ==================== 文件上传接口 ====================

@router.post("/upload", response_model=DatasetResponse)
async def ml_upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """上传文件到ML模块，artifact_type=raw_data, module_source=ml"""
    import time as _time
    start_time = _time.time()
    validate_upload_file(file)

    # 同名区分
    name = clean_dataset_name(file.filename)

    # 埋点：创建上传任务记录
    task_record = create_task_record(
        db=db,
        task_type="upload",
        user_id=current_user.id,
        params={"filename": name, "module_source": "ml", "artifact_type": "raw_data"}
    )

    # 保存文件到 MinIO
    object_name = f"ml/user_{current_user.id}/{name}"
    content = await file.read()
    file_path = storage_manager.save_bytes(object_name, content)

    # 解析数据结构
    data_service = DataService(db)
    try:
        df = data_service._load_from_file(file_path)
        schema = data_service.get_schema(df)
        row_count = len(df)
        data_preview = data_service.get_sample_data(df, 10)
    except Exception as e:
        storage_manager.delete(file_path)
        execution_time = int((_time.time() - start_time) * 1000)
        update_task_record(
            db=db, record_id=task_record.id, status="failed",
            error_message=str(e), execution_time=execution_time,
            failure_category="data_error"
        )
        raise HTTPException(status_code=400, detail=f"无法解析文件: {str(e)}")

    # 创建数据集记录（ML模块来源，原始数据）
    file_size = len(content)
    new_dataset = Dataset(
        name=name,
        file_path=file_path,
        file_size=file_size,
        schema=schema,
        row_count=row_count,
        data_preview=str(data_preview[:5]),
        module_source="ml",
        module_label=MODULE_LABEL_MAP.get("ml", "机器学习"),
        artifact_type="raw_data",
        user_id=current_user.id
    )
    db.add(new_dataset)
    db.commit()
    db.refresh(new_dataset)

    execution_time = int((_time.time() - start_time) * 1000)
    update_task_record(
        db=db, record_id=task_record.id, status="success",
        dataset_id=new_dataset.id,
        result_summary={
            "dataset_name": new_dataset.name,
            "row_count": new_dataset.row_count,
            "column_count": len(df.columns),
            "file_size": new_dataset.file_size
        },
        execution_time=execution_time
    )

    clear_user_dataset_cache(current_user.id)

    # 触发 ClickHouse 副本同步（raw_data 且行数达阈值时在任务内同步；失败不影响上传）
    from app.services.clickhouse_service import trigger_sync
    trigger_sync(new_dataset.id)

    return new_dataset
@router.get("/chart-export/{dataset_id}")
async def chart_export(
    dataset_id: int,
    chart_type: str = Query("histogram", description="图表类型: histogram/scatter/line"),
    column: str = Query(None, description="主列名"),
    y_column: str = Query(None, description="Y轴列名（散点图需要）"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """导出PNG图表 - 仅支持ML模块的原始数据"""
    # 验证数据来源
    validate_ml_data_source(db, dataset_id, current_user.id)

    data_service = DataService(db)
    try:
        df = data_service.load_dataset(dataset_id)

        fig, ax = plt.subplots(figsize=(10, 6))

        if chart_type == "histogram":
            col = column if column else df.select_dtypes(include=['number']).columns[0]
            ax.hist(df[col].dropna(), bins=30, color='steelblue', edgecolor='white', alpha=0.8)
            ax.set_title(f"柱状图 - {col}", fontsize=14, fontweight='bold')
            ax.set_xlabel(col)
            ax.set_ylabel("频数")
        elif chart_type == "scatter":
            col_x = column if column else df.select_dtypes(include=['number']).columns[0]
            col_y = y_column if y_column else df.select_dtypes(include=['number']).columns[-1]
            ax.scatter(df[col_x], df[col_y], alpha=0.6, c='steelblue', edgecolors='white')
            ax.set_title(f"散点图 - {col_x} vs {col_y}", fontsize=14, fontweight='bold')
            ax.set_xlabel(col_x)
            ax.set_ylabel(col_y)
        elif chart_type == "line":
            col = column if column else df.select_dtypes(include=['number']).columns[0]
            ax.plot(df[col].dropna().values, color='steelblue', linewidth=1.5)
            ax.set_title(f"折线图 - {col}", fontsize=14, fontweight='bold')
            ax.set_xlabel("索引")
            ax.set_ylabel(col)

        ax.grid(True, alpha=0.3)
        plt.tight_layout()

        img_buffer = io.BytesIO()
        fig.savefig(img_buffer, format='png', dpi=100, bbox_inches='tight')
        plt.close(fig)
        img_buffer.seek(0)

        return StreamingResponse(
            iter([img_buffer.getvalue()]),
            media_type="image/png",
            headers={"Content-Disposition": f"attachment; filename=chart_{dataset_id}.png"}
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== 新版核心接口:预检/特征推荐/训练/预测/评估/导出 ====================

# 预检缓存 TTL(秒),与特征工程保持一致
_PRECHECK_CACHE_TTL = 300


def _ml_precheck_cache_key(user_id: int, dataset_id: int) -> str:
    """生成 ML 预检缓存键"""
    return f"ml:precheck:user:{user_id}:dataset:{dataset_id}"


def _clear_ml_precheck_cache(user_id: int, dataset_id: int):
    """清理 ML 预检缓存(切换数据集时由前端主动调用)"""
    from app.services.cache_manager import cache_manager
    cache_manager.delete(_ml_precheck_cache_key(user_id, dataset_id))


@router.post("/precheck")
async def precheck_ml_data(body: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """机器学习训练前数据预检

    切换数据集时由前端自动调用,检查数据质量并给出算法推荐。
    结果缓存到 Redis 5 分钟,与特征工程预检保持一致。

    检查项分三级:
    - errors(阻断):行数过少/无有效特征列/目标列全 NaN/分类任务类别数<2/回归目标列无法转数值
    - warnings(警告):分类任务某类样本<5/特征列<3/缺失值比例>30%/存在常量列/高基数分类列未编码/SVM/KNN 大数据慢警告
    - info(提示):行数>1万将异步执行/行数>10万训练时长提示/特征数>500建议降维
    """
    from app.services.cache_manager import cache_manager

    dataset_id = body.get("dataset_id")
    remote_config = body.get("remote")
    is_remote = remote_config and remote_config.get("use_remote")

    if not dataset_id and not is_remote:
        raise HTTPException(status_code=400, detail="请提供 dataset_id 或 remote 参数")

    # 本地模式：命中缓存直接返回；远程模式不缓存（无 dataset_id）
    if not is_remote:
        cache_key = _ml_precheck_cache_key(current_user.id, dataset_id)
        cached = cache_manager.get(cache_key)
        if cached:
            return cached

    # 统一加载数据（本地或远程）
    data_service = DataService(db)
    try:
        df, dataset = data_service.load_module_data(
            dataset_id=dataset_id,
            remote_config=remote_config,
            user_id=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"加载数据失败: {e}")

    # 本地模式验证数据来源
    if not is_remote and dataset:
        validate_ml_data_source(db, dataset_id, current_user.id)

    row_count = len(df)
    col_count = len(df.columns)
    numeric_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    categorical_cols = [c for c in df.columns if c not in numeric_cols]

    # 缺失值统计
    missing_total = int(df.isna().sum().sum())
    missing_rate = float(missing_total / (row_count * col_count)) if row_count * col_count > 0 else 0.0

    # 常量列检测(唯一值数<=1)
    constant_cols = [c for c in df.columns if df[c].nunique() <= 1]

    # 高基数分类列(非数值列唯一值>100)
    high_cardinality_cols = [c for c in categorical_cols if df[c].nunique() > 100]

    errors = []
    warnings = []
    infos = []

    # ===== 阻断错误 =====
    if row_count < 10:
        errors.append({
            "code": "TOO_FEW_ROWS",
            "message": f"数据仅 {row_count} 行,机器学习训练至少需要 10 行数据"
        })

    if len(numeric_cols) == 0 and len(categorical_cols) <= 1:
        errors.append({
            "code": "NO_FEATURE_COLUMNS",
            "message": "数据集没有可用的特征列(至少需要 1 个数值列或 2 个以上分类列)"
        })

    # ===== 警告 =====
    if missing_rate > 0.3:
        warnings.append({
            "code": "HIGH_MISSING",
            "message": f"数据缺失率达 {missing_rate*100:.1f}%,建议先进行数据清洗"
        })

    if constant_cols:
        warnings.append({
            "code": "CONSTANT_COLUMNS",
            "message": f"存在 {len(constant_cols)} 个常量列(无信息量): {', '.join(constant_cols[:5])}{'...' if len(constant_cols) > 5 else ''}"
        })

    if high_cardinality_cols:
        warnings.append({
            "code": "HIGH_CARDINALITY",
            "message": f"存在高基数分类列(唯一值>100),训练前建议编码: {', '.join(high_cardinality_cols[:3])}{'...' if len(high_cardinality_cols) > 3 else ''}"
        })

    if len(numeric_cols) < 3 and len(categorical_cols) == 0:
        warnings.append({
            "code": "TOO_FEW_FEATURES",
            "message": f"仅 {len(numeric_cols)} 个数值特征列,模型表现可能受限"
        })

    # 分类列做回归任务的潜在风险预警
    # 数值列但唯一值很少(2-20)的分类型目标,做回归时R²可能为负
    classification_like_numeric = [
        c for c in numeric_cols
        if 2 <= df[c].nunique() <= 20
    ]
    if classification_like_numeric:
        warnings.append({
            "code": "CLASSIFICATION_AS_REGRESSION",
            "message": f"以下数值列唯一值较少({', '.join(classification_like_numeric[:3])}),"
                       f"若作为回归目标R²可能为负,建议改用分类任务"
        })

    if row_count > 50000:
        warnings.append({
            "code": "LARGE_DATASET",
            "message": f"数据量较大({row_count} 行),训练时间可能较长,建议使用随机森林/XGBoost/LightGBM"
        })

    # ===== 信息 =====
    if row_count >= 10000:
        infos.append({
            "code": "ASYNC_TRIGGER",
            "message": f"数据量 {row_count} 行,将自动异步执行(≥1万行)"
        })

    if col_count > 500:
        infos.append({
            "code": "HIGH_DIMENSIONAL",
            "message": f"特征维度较高({col_count} 列),建议先进行特征选择或降维"
        })

    # ===== 算法推荐(按任务类型分组,标注推荐度评分和原因) =====
    # 推荐度评分(score, 0-100):
    #   80-100:强烈推荐(数据量/特征匹配,训练效率高)
    #   60-79:推荐(可用,但有更优选择)
    #   1-59:不推荐(可用但有明显劣势,选中时前端提示)
    _ALGO_RECOMMEND_REASONS = {
        "logistic_regression": "线性分类模型,训练快,可解释性强,适合作为分类基线模型和小数据集",
        "svm": "在高维空间找最优分界,小数据集表现好,需要标准化",
        "decision_tree": "树形规则结构,可解释性极强,能处理非线性,适合作为基线模型",
        "naive_bayes": "基于贝叶斯定理,训练极快,适合文本分类和小数据集",
        "knn": "基于距离的惰性学习,无需训练过程,需要标准化",
        "linear_regression": "最简单的回归模型,速度快可解释,作为回归基线模型",
        "ridge_regression": "带 L2 正则化的线性回归,能抑制多重共线性,适合高维数据",
        "lasso_regression": "带 L1 正则化的线性回归,能进行特征选择,适合稀疏特征",
        "random_forest": "集成多棵决策树,精度高抗过拟合,能处理非线性,工业界常用",
        "adaboost": "串行训练弱分类器,关注难分样本,适合二分类",
        "gbdt": "串行训练决策树拟合残差,精度高,大数据集建议用 XGBoost/LightGBM",
        "xgboost": "工业界首选集成算法,训练快精度高,支持原生缺失值处理",
        "lightgbm": "基于直方图算法训练极快,内存占用低,适合大数据集",
        "mlp": "全连接神经网络,能拟合复杂非线性关系,需要充足数据",
    }
    algorithm_recommendations = {
        "classification": [],
        "regression": []
    }
    for algo_id, reg in ALGORITHM_REGISTRY.items():
        for task_type in reg["task_types"]:
            recommended = True
            reason = ""
            score = 70  # 基础推荐度

            # 大数据慢算法:大幅降分并给出原因和预计时间
            if not reg["large_data_ok"] and row_count > reg.get("slow_warning_rows", 10000):
                if algo_id == "svm":
                    estimated_minutes = round((row_count / 10000) ** 2 * 0.5, 1)
                    reason = f"数据量 {row_count} 行,SVM 训练复杂度 O(n²)~O(n³),预计训练约 {estimated_minutes} 分钟,建议改用随机森林/XGBoost"
                elif algo_id == "knn":
                    estimated_minutes = round(row_count / 10000 * 2, 1)
                    reason = f"数据量 {row_count} 行,KNN 预测时需计算全量距离,预计较慢,建议改用随机森林/XGBoost"
                else:
                    estimated_minutes = round(row_count / 10000 * 5, 1)
                    reason = f"数据量 {row_count} 行,预计训练约 {estimated_minutes} 分钟"
                recommended = False
                score = 25
            # GBDT 在大数据上较慢
            elif algo_id == "gbdt" and row_count > reg.get("slow_warning_rows", 50000):
                estimated_minutes = round(row_count / 10000 * 3, 1)
                reason = f"数据量 {row_count} 行,GBDT 串行训练较慢,预计约 {estimated_minutes} 分钟,建议改用 XGBoost/LightGBM"
                recommended = False
                score = 35
            # MLP 在大数据上慢
            elif algo_id == "mlp" and row_count > reg.get("slow_warning_rows", 50000):
                estimated_minutes = round(row_count / 10000 * 8, 1)
                reason = f"数据量 {row_count} 行,MLP 神经网络训练较慢,预计约 {estimated_minutes} 分钟"
                recommended = False
                score = 30
            else:
                # 推荐算法:根据数据规模调整推荐度
                base_reason = _ALGO_RECOMMEND_REASONS.get(algo_id, "适合当前数据规模")

                if row_count >= 10000:
                    # 大数据集:树模型/集成模型加分,线性模型略降
                    if algo_id in ["random_forest", "xgboost", "lightgbm"]:
                        score = 92
                        reason = f"{base_reason};当前数据量 {row_count} 行,大数据集表现稳定"
                    elif algo_id in ["logistic_regression", "linear_regression", "ridge_regression", "lasso_regression"]:
                        score = 75
                        reason = f"{base_reason};当前数据量 {row_count} 行,线性模型训练快但可能欠拟合"
                    elif algo_id in ["decision_tree", "naive_bayes"]:
                        score = 68
                        reason = f"{base_reason};当前数据量 {row_count} 行,简单模型精度可能不足"
                    else:
                        score = 70
                        reason = base_reason
                elif row_count < 100:
                    # 小数据集:简单模型加分,复杂模型降分
                    if algo_id in ["logistic_regression", "decision_tree", "naive_bayes", "linear_regression"]:
                        score = 88
                        reason = f"{base_reason};当前数据量仅 {row_count} 行,简单模型更不易过拟合"
                    elif algo_id in ["ridge_regression", "lasso_regression"]:
                        score = 82
                        reason = f"{base_reason};当前数据量仅 {row_count} 行,正则化防止过拟合"
                    elif algo_id in ["mlp", "gbdt", "xgboost", "lightgbm"]:
                        score = 55
                        reason = f"{base_reason};当前数据量仅 {row_count} 行,深度模型/集成模型可能过拟合,建议先用简单模型"
                        recommended = False
                    else:
                        score = 65
                        reason = base_reason
                else:
                    # 中等数据集(100-10000):都适用,按算法特性细分评分
                    if algo_id in ["xgboost", "lightgbm"]:
                        # 工业首选:训练快+原生缺失值+精度高
                        score = 88
                        reason = f"{base_reason};当前数据量 {row_count} 行,工业首选算法,训练快精度高"
                    elif algo_id == "random_forest":
                        # 精度高抗过拟合,但训练稍慢于XGBoost/LightGBM
                        score = 85
                        reason = f"{base_reason};当前数据量 {row_count} 行,精度高抗过拟合"
                    elif algo_id == "gbdt":
                        # 精度高但串行训练较慢
                        score = 82
                        reason = f"{base_reason};当前数据量 {row_count} 行,精度高但串行训练较慢"
                    elif algo_id in ["logistic_regression", "linear_regression", "decision_tree"]:
                        # 可作为基线模型
                        score = 78
                        reason = f"{base_reason};当前数据量 {row_count} 行,可作为基线模型"
                    else:
                        score = 72
                        reason = base_reason

            reason_type = "warning" if not recommended else "info"

            algorithm_recommendations[task_type].append({
                "algorithm": algo_id,
                "label_cn": reg["label_cn"],
                "task_type": task_type,
                "recommended": recommended,
                "score": score,  # 推荐度评分 0-100
                "reason": reason,
                "reason_type": reason_type,  # info(推荐) / warning(不推荐)
                "native_nan": reg["native_nan"]
            })

    # 每个任务类型的算法按推荐度降序排序(方便前端取最高分算法)
    algorithm_recommendations["classification"].sort(key=lambda x: x["score"], reverse=True)
    algorithm_recommendations["regression"].sort(key=lambda x: x["score"], reverse=True)

    # ===== 目标列推荐(评估每列适合分类还是回归) =====
    # 判断逻辑:
    # - 数值列 & 唯一值>10 & 非高基数:推荐回归
    # - 数值列 & 2<=唯一值<=10:推荐分类(也可回归但不推荐)
    # - 分类列 & 2<=唯一值<=20:推荐分类
    # - 分类列 & 唯一值>20:都不推荐(高基数,需先编码)
    # - 唯一值<2:都不推荐(常量列无信息)
    # - 缺失率>50%:都不推荐
    target_column_recommendations = []
    for col in df.columns:
        col_data = df[col]
        col_unique = col_data.nunique()
        col_is_numeric = pd.api.types.is_numeric_dtype(col_data)
        col_missing_rate = float(col_data.isna().sum() / row_count) if row_count > 0 else 0.0

        recommend_cls = False
        recommend_reg = False
        reason = ""

        if col_unique < 2:
            reason = f"唯一值仅 {col_unique} 个,无法作为目标列(常量列无预测价值)"
        elif col_missing_rate > 0.5:
            reason = f"缺失率 {col_missing_rate*100:.0f}%,数据不足无法作为目标列"
        elif col_is_numeric and col_unique > 10:
            # 数值列且高唯一值:推荐回归
            recommend_reg = True
            if col_unique > 100:
                reason = f"数值列,唯一值 {col_unique} 个,适合回归任务(预测连续数值)"
            else:
                reason = f"数值列,唯一值 {col_unique} 个,适合回归任务"
            # 如果唯一值较少(如11-20),也可勉强分类但不推荐
            if col_unique <= 20:
                reason += f";也可做分类(类别数 {col_unique} 偏多,建议优先回归)"
        elif col_is_numeric and 2 <= col_unique <= 10:
            # 数值列且唯一值少:推荐分类
            recommend_cls = True
            reason = f"数值列,唯一值 {col_unique} 个,适合分类任务(类别数适中)"
            if col_unique == 2:
                reason += "(二分类)"
            # 也可回归但不推荐
            reason += f";回归也可用但目标值仅 {col_unique} 种,意义不大"
        elif not col_is_numeric and 2 <= col_unique <= 20:
            # 分类列且类别数适中:推荐分类
            recommend_cls = True
            if col_unique == 2:
                reason = f"分类列,唯一值 {col_unique} 个,适合二分类任务"
            else:
                reason = f"分类列,唯一值 {col_unique} 个,适合分类任务"
        elif not col_is_numeric and col_unique > 20:
            # 高基数分类列:都不推荐
            reason = f"分类列但唯一值 {col_unique} 个过多,需先编码才能使用,不推荐直接作为目标列"
        else:
            reason = f"唯一值 {col_unique} 个,不建议作为目标列"

        target_column_recommendations.append({
            "column": col,
            "is_numeric": col_is_numeric,
            "unique_values": int(col_unique),
            "missing_rate": round(col_missing_rate, 4),
            "recommend_classification": recommend_cls,
            "recommend_regression": recommend_reg,
            "reason": reason
        })

    result = {
        "data_profile": {
            "row_count": row_count,
            "col_count": col_count,
            "numeric_count": len(numeric_cols),
            "categorical_count": len(categorical_cols),
            "numeric_columns": numeric_cols,
            "categorical_columns": categorical_cols,
            "missing_total": missing_total,
            "missing_rate": round(missing_rate, 4),
            "constant_columns": constant_cols,
            "high_cardinality_columns": high_cardinality_cols
        },
        "checks": {
            "errors": errors,
            "warnings": warnings,
            "infos": infos
        },
        "algorithm_recommendations": algorithm_recommendations,
        "target_column_recommendations": target_column_recommendations,
        "can_train": len(errors) == 0
    }

    # 本地模式缓存 5 分钟，远程模式不缓存
    if not is_remote:
        cache_manager.set(cache_key, result, ttl=_PRECHECK_CACHE_TTL)
    return result


# 特征列推荐缓存 TTL
_FEATURE_REC_CACHE_TTL = 300


def _feature_rec_cache_key(user_id: int, dataset_id: int, target_col: str) -> str:
    return f"ml:featrec:user:{user_id}:dataset:{dataset_id}:target:{target_col}"


@router.post("/recommend-features")
async def recommend_features(body: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """特征列智能推荐

    根据目标列的类型,计算每个特征列与目标列的关联度,返回按关联度排序的推荐列表。
    前端选择目标列后自动调用,默认勾选关联度高的特征列。

    关联度计算方法:
    - 数值特征 vs 数值目标(回归):Pearson 相关系数绝对值
    - 数值特征 vs 分类目标(分类):ANOVA F 值归一化
    - 分类特征 vs 分类目标(分类):卡方统计量归一化
    - 分类特征 vs 数值目标(回归):分类特征 one-hot 后与目标的最大相关系数
    """
    from app.services.cache_manager import cache_manager
    from sklearn.feature_selection import f_classif, f_regression, chi2
    from sklearn.preprocessing import LabelEncoder, OneHotEncoder
    import numpy as np

    dataset_id = body.get("dataset_id")
    remote_config = body.get("remote")
    is_remote = remote_config and remote_config.get("use_remote")
    target_column = body.get("target_column")
    if (not dataset_id and not is_remote) or not target_column:
        raise HTTPException(status_code=400, detail="请提供 dataset_id（或 remote）和 target_column")

    # 本地模式：命中缓存直接返回；远程模式不缓存
    if not is_remote:
        cache_key = _feature_rec_cache_key(current_user.id, dataset_id, target_column)
        cached = cache_manager.get(cache_key)
        if cached:
            return cached

    # 统一加载数据（本地或远程）
    data_service = DataService(db)
    try:
        df, dataset = data_service.load_module_data(
            dataset_id=dataset_id,
            remote_config=remote_config,
            user_id=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"加载数据失败: {e}")

    # 本地模式验证数据来源
    if not is_remote and dataset:
        validate_ml_data_source(db, dataset_id, current_user.id)

    if target_column not in df.columns:
        raise HTTPException(status_code=400, detail=f"目标列 {target_column} 不存在")

    # 判断任务类型:数值列且唯一值>10 为回归,否则为分类
    target_series = df[target_column]
    is_target_numeric = pd.api.types.is_numeric_dtype(target_series)
    target_unique = target_series.nunique()
    is_regression = is_target_numeric and target_unique > 10
    task_type = "regression" if is_regression else "classification"

    # 候选特征列:排除目标列、常量列
    candidate_cols = [c for c in df.columns if c != target_column and df[c].nunique() > 1]
    feature_scores = []

    # 准备目标值
    if is_regression:
        y = pd.to_numeric(target_series, errors='coerce').fillna(target_series.median() if is_target_numeric else 0)
    else:
        # 分类任务:LabelEncoder 编码目标
        le = LabelEncoder()
        # 处理 NaN:填充为 'missing' 字符串
        y_series = target_series.fillna('missing').astype(str)
        y = le.fit_transform(y_series)

    for col in candidate_cols:
        col_data = df[col]
        is_numeric_col = pd.api.types.is_numeric_dtype(col_data)

        score = 0.0
        recommend_reason = ""

        try:
            if is_numeric_col and is_regression:
                # 数值特征 vs 数值目标:Pearson 相关系数
                x = pd.to_numeric(col_data, errors='coerce')
                valid_mask = ~(x.isna() | pd.Series(y).isna())
                if valid_mask.sum() > 5:
                    corr = x[valid_mask].corr(pd.Series(y)[valid_mask])
                    score = abs(corr) if not pd.isna(corr) else 0.0
                    recommend_reason = f"Pearson 相关系数 {corr:.3f}"
                else:
                    score = 0.0
                    recommend_reason = "有效数据不足"

            elif is_numeric_col and not is_regression:
                # 数值特征 vs 分类目标:ANOVA F 值
                x = pd.to_numeric(col_data, errors='coerce').fillna(0)
                valid_mask = ~pd.Series(y).isna()
                if valid_mask.sum() > 5 and len(np.unique(y[valid_mask])) > 1:
                    f_values, _ = f_classif(x.values.reshape(-1, 1)[valid_mask], y[valid_mask])
                    score = float(f_values[0]) if not pd.isna(f_values[0]) else 0.0
                    # 归一化到 0-1(F 值越大关联越强,用 1/(1+exp(-x)) 归一化)
                    score = 1 / (1 + np.exp(-score / 10))
                    recommend_reason = f"ANOVA F 值归一化 {score:.3f}"
                else:
                    score = 0.0
                    recommend_reason = "有效数据不足或目标列仅一类"

            elif not is_numeric_col and not is_regression:
                # 分类特征 vs 分类目标:卡方检验
                x_str = col_data.fillna('missing').astype(str)
                valid_mask = ~pd.Series(y).isna()
                if valid_mask.sum() > 5 and len(np.unique(y[valid_mask])) > 1:
                    # 构造列联表
                    contingency = pd.crosstab(x_str[valid_mask], y[valid_mask])
                    if contingency.size > 1:
                        # sklearn 的 chi2(X, y) 要求 (n_samples, n_features) 特征矩阵，
                        # 不能用列联表计数矩阵，否则报 "y should be a 1d array" 并被吞掉导致推荐恒为0。
                        # 分类特征 vs 分类目标应使用卡方独立性检验（修复）
                        from scipy.stats import chi2_contingency
                        chi2_val, _, _, _ = chi2_contingency(contingency.values)
                        # 归一化卡方值
                        score = 1 / (1 + np.exp(-chi2_val / 100))
                        recommend_reason = f"卡方统计量归一化 {score:.3f}"
                    else:
                        score = 0.0
                        recommend_reason = "列联表退化"
                else:
                    score = 0.0
                    recommend_reason = "有效数据不足"

            elif not is_numeric_col and is_regression:
                # 分类特征 vs 数值目标:one-hot 后计算最大相关系数
                x_str = col_data.fillna('missing').astype(str)
                # 高基数分类列(>20 唯一值)跳过,避免维度爆炸
                if x_str.nunique() > 20:
                    score = 0.0
                    recommend_reason = f"高基数分类列(唯一值 {x_str.nunique()}),建议先编码"
                else:
                    # 简化:用每组的均值与全局均值的差异作为评分
                    grouped = pd.DataFrame({'x': x_str, 'y': pd.Series(y)}).dropna()
                    if len(grouped) > 5 and grouped['x'].nunique() > 1:
                        group_means = grouped.groupby('x')['y'].mean()
                        global_mean = grouped['y'].mean()
                        # 组间方差占总方差的比例(类似 eta squared)
                        ss_between = sum(len(grouped[grouped['x']==g]) * (m - global_mean)**2 for g, m in group_means.items())
                        ss_total = ((grouped['y'] - global_mean)**2).sum()
                        score = float(ss_between / ss_total) if ss_total > 0 else 0.0
                        recommend_reason = f"组间方差占比 {score:.3f}"
                    else:
                        score = 0.0
                        recommend_reason = "有效数据不足"

        except Exception as e:
            score = 0.0
            recommend_reason = f"计算失败: {str(e)[:50]}"

        # 推荐阈值:关联度 > 0.1 默认勾选
        # 低于阈值不自动勾选,但补充明确原因让用户理解为什么不勾选
        # 显式转 Python bool：score 可能为 numpy 标量，直接比较返回 numpy.bool_ 无法被 JSON 序列化
        should_select = bool(score >= 0.1)
        if not should_select and not recommend_reason.startswith("计算失败"):
            # 在原评分原因基础上追加"未自动勾选"说明
            if "有效数据不足" in recommend_reason or "目标列仅一类" in recommend_reason or "列联表退化" in recommend_reason:
                recommend_reason = f"{recommend_reason}(无法计算有效关联度,不自动勾选,可手动选择)"
            elif "高基数分类列" in recommend_reason:
                recommend_reason = f"{recommend_reason}(建议先编码再使用,不自动勾选)"
            else:
                recommend_reason = f"{recommend_reason};评分 {score:.3f} 低于阈值 0.1,关联度较弱不自动勾选(可手动选择)"

        feature_scores.append({
            "column": col,
            "score": float(round(float(score), 4)),
            "is_numeric": bool(is_numeric_col),
            "should_select": should_select,
            "reason": recommend_reason,
            "unique_values": int(col_data.nunique())
        })

    # 按评分降序排序
    feature_scores.sort(key=lambda x: x["score"], reverse=True)

    result = {
        "target_column": target_column,
        "task_type": task_type,
        "target_unique_values": int(target_unique),
        "feature_recommendations": feature_scores,
        "recommended_count": sum(1 for f in feature_scores if f["should_select"])
    }

    # 本地模式缓存，远程模式不缓存
    if not is_remote:
        cache_manager.set(cache_key, result, ttl=_FEATURE_REC_CACHE_TTL)
    return result


@router.post("/train-supervised")
async def train_supervised_model(config: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """训练有监督学习模型（分类/回归），支持自动调优

    智能异步执行（≥1万行异步，<1万行同步，Celery 不可用且≥1万行报503不降级）：
    - 数据集 ≥ 1万行：通过 task_manager.run_task 异步提交，立即返回 task_id
    - 数据集 < 1万行：同步执行，直接返回训练结果
    - Celery 不可用且 ≥ 1万行：返回 HTTP 503，不降级到同步

    训练核心逻辑见 _execute_training，4阶段进度上报到 task_records.result_summary：
    数据加载与预处理(20%) → 模型训练中(50%) → 模型评估中(80%) → 保存结果(100%)

    Args:
        config: {
            "dataset_id": 数据集ID,
            "target_column": 目标列名,
            "feature_columns": 特征列名列表(可选,不传则默认使用除目标列外的全部列),
            "task_type": "classification"|"regression",
            "algorithm": 共14种,详见 algorithm_registry.py:
                分类11个: logistic_regression/svm/decision_tree/naive_bayes/knn/
                         random_forest/adaboost/gbdt/xgboost/lightgbm/mlp
                回归12个: svm/decision_tree/knn/linear_regression/ridge_regression/
                          lasso_regression/random_forest/adaboost/gbdt/xgboost/lightgbm/mlp,
            "test_size": 测试集比例 (默认0.2),
            "cv_folds": 交叉验证折数 (默认5),
            "auto_tune": true|false (是否自动调优),
            "tune_method": "grid"|"random" (调优方法，当前实现未包含 bayesian),
            "hyperparams": 超参数搜索空间(可选,不传则用算法注册表默认搜索空间),
            "random_seed": 随机种子 (默认42)
        }
    """
    dataset_id = config.get("dataset_id")
    remote_config = config.get("remote")
    is_remote = remote_config and remote_config.get("use_remote")
    target_column = config.get("target_column")
    feature_columns = config.get("feature_columns", [])
    task_type = config.get("task_type", "classification")
    algorithm = config.get("algorithm", "random_forest")
    test_size = config.get("test_size", 0.2)
    cv_folds = config.get("cv_folds", 5)
    auto_tune = config.get("auto_tune", False)
    tune_method = config.get("tune_method", "random")
    # 提前提取重试/任务记录所需参数（此前缺失导致 create_task_record 引用未定义变量抛 NameError）
    hyperparams = config.get("hyperparams", {})
    random_seed = config.get("random_seed", 42)

    if (not dataset_id and not is_remote) or not target_column:
        raise HTTPException(status_code=400, detail="请指定 dataset_id（或 remote）和 target_column")

    # 统一加载数据获取数据集信息和行数（远程模式需加载数据获取行数）
    data_service = DataService(db)
    try:
        df_preview, original_dataset = data_service.load_module_data(
            dataset_id=dataset_id,
            remote_config=remote_config,
            user_id=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 本地模式验证数据来源
    if not is_remote and original_dataset:
        validate_ml_data_source(db, dataset_id, current_user.id)

    # 数据集名称（远程模式使用表名）
    if is_remote:
        dataset_name = remote_config.get("table_name", "远程表")
        row_count = len(df_preview)
    else:
        dataset_name = original_dataset.name if original_dataset else "数据集"
        row_count = original_dataset.row_count or 0

    # 埋点：创建任务记录（status=running）
    # task_type="ml_training" 与 retry_task 注册表键匹配，便于失败后手动重试时查找处理函数
    start_time = time.time()
    task_record = create_task_record(
        db=db,
        task_type="ml_training",
        user_id=current_user.id,
        dataset_id=dataset_id,  # 远程模式下为 None
        params={
            "operation": "train",
            "dataset_name": dataset_name,
            "is_remote": is_remote,
            "remote_config": remote_config if is_remote else None,
            "algorithm": algorithm,
            "params": {
                "target_column": target_column,
                "feature_columns": feature_columns,
                "task_type": task_type,
                "test_size": test_size,
                "cv_folds": cv_folds,
                "auto_tune": auto_tune,
                "tune_method": tune_method,
                # 重试时需恢复随机种子与自定义超参，否则结果不可复现、调参空间丢失（修复）
                "random_seed": random_seed,
                "hyperparams": hyperparams
            }
        }
    )

    ASYNC_THRESHOLD = settings.ASYNC_THRESHOLD

    # 智能异步分发：远程模式强制同步；本地模式 ≥1万行异步
    if not is_remote and row_count >= ASYNC_THRESHOLD:
        # 业务代码不降级：Celery 不可用时直接报 503，不静默回退到同步
        if not task_manager.is_async_available():
            execution_time = int((time.time() - start_time) * 1000)
            update_task_record(
                db=db,
                record_id=task_record.id,
                status="failed",
                error_message="Celery 不可用，无法处理大数据集（≥1万行），请启动 Celery 服务或使用小数据集",
                execution_time=execution_time,
                failure_category="system_error"
            )
            raise HTTPException(
                status_code=503,
                detail="Celery 不可用，无法处理大数据集（≥1万行），请启动 Celery 服务或使用小数据集"
            )

        # 任务排队机制：检查用户队列容量，决定立即执行还是进入等待队列
        # check_task_queue_capacity 会在总上限超限时抛 HTTPException(429)
        try:
            can_run_now, queue_msg = check_task_queue_capacity(
                db, current_user.id, exclude_task_id=task_record.id
            )
        except HTTPException as queue_err:
            # 总上限超限（running+pending >= 7），标记失败并返回 429
            execution_time = int((time.time() - start_time) * 1000)
            update_task_record(
                db=db,
                record_id=task_record.id,
                status="failed",
                error_message=str(queue_err.detail),
                execution_time=execution_time,
                failure_category="param_error"
            )
            raise queue_err

        if can_run_now:
            # 立即执行：提交到 Celery 队列
            task_result = task_manager.run_task(
                _execute_training,
                task_record_id=task_record.id,
                user_id=current_user.id,
                dataset_id=dataset_id,
                config=config,
                remote_config=remote_config if is_remote else None,
                no_degrade=True
            )
            # 写入 celery_task_id，供后续取消任务时反查
            celery_task_id = task_result.get("task_id")
            if celery_task_id:
                mark_task_running(db, task_record.id, celery_task_id=celery_task_id)
            return {
                "task_record_id": task_record.id,
                "task_id": celery_task_id,
                "status": "running",
                "message": "模型训练任务已提交，请在右上角任务面板查看进度",
                "row_count": row_count
            }
        else:
            # 进入等待队列：不提交 Celery，由调度器自动激活
            # create_task_record 默认创建 running 状态，这里改为 pending
            task_record.status = "pending"
            db.commit()
            return {
                "task_record_id": task_record.id,
                "task_id": None,
                "status": "pending",
                "message": f"任务已进入等待队列（{queue_msg}），将在前面任务完成后自动执行",
                "row_count": row_count
            }

    # 小数据集或远程模式：同步执行，直接返回训练结果
    return _execute_training(
        task_record_id=task_record.id,
        user_id=current_user.id,
        dataset_id=dataset_id,
        config=config,
        remote_config=remote_config if is_remote else None
    )


@task_manager.register_task
def _execute_training(task_record_id: int, user_id: int, dataset_id: int, config: dict, remote_config: dict = None):
    """ML 训练核心执行函数（同步/异步共用入口）

    通过 SessionLocal 创建独立 db 会话：
    - 同步调用时与 FastAPI 的 db 隔离，避免长事务占用请求连接
    - 异步调用时（Celery Worker 进程）必须新建 session，因为无法访问 FastAPI 请求上下文

    4阶段进度上报到 task_records.result_summary：
    - 数据加载与预处理(20%)：加载数据、缺失值处理、目标列编码、数据集划分
    - 模型训练中(50%)：Pipeline 构建、超参调优或直接训练
    - 模型评估中(80%)：测试集预测、分类/回归指标计算、交叉验证
    - 保存结果(100%)：模型持久化到 MinIO、产物记录到数据库

    Args:
        task_record_id: 任务记录ID（入口已创建）
        user_id: 用户ID
        dataset_id: 数据集ID（远程模式为 None）
        config: 训练配置（与 train_supervised_model 接口入参一致）
        remote_config: 远程数据源配置（可选）

    Returns:
        训练结果字典（与原同步接口返回结构保持一致）
    """
    from sklearn.model_selection import (
        train_test_split, cross_val_score, StratifiedKFold, KFold
    )
    from sklearn.preprocessing import StandardScaler, LabelEncoder
    from sklearn.pipeline import Pipeline
    from sklearn.model_selection import GridSearchCV, RandomizedSearchCV
    import joblib

    # Celery Worker 是独立进程，必须新建 db 会话，不能复用 FastAPI 请求作用域的 db
    db = SessionLocal()
    start_time = time.time()

    try:
        # ===== 阶段1：数据加载与预处理（20%） =====
        update_task_progress(db, task_record_id, "数据加载与预处理", 20, "正在加载和预处理数据")

        target_column = config.get("target_column")
        feature_columns = config.get("feature_columns", [])
        task_type = config.get("task_type", "classification")
        algorithm = config.get("algorithm", "random_forest")
        test_size = config.get("test_size", 0.2)
        cv_folds = config.get("cv_folds", 5)
        auto_tune = config.get("auto_tune", False)
        tune_method = config.get("tune_method", "random")
        hyperparams = config.get("hyperparams", {})
        random_seed = config.get("random_seed", 42)

        is_remote = remote_config and remote_config.get("use_remote")

        # 统一加载数据（本地或远程）
        data_service = DataService(db)
        df, original_dataset = data_service.load_module_data(
            dataset_id=dataset_id,
            remote_config=remote_config,
            user_id=user_id
        )
        # 远程模式下数值列可能被加载为 object 类型，先做类型转换
        # 确保 select_dtypes(include=[np.number]) 和 fillna(numeric_only=True) 正确识别数值列
        df = _coerce_numeric_columns(df)

        # 数据集名称（远程模式使用表名）
        if is_remote:
            dataset_name = remote_config.get("table_name", "remote_table")
            safe_dataset_id = remote_config.get("table_name", "remote")
        else:
            dataset_name = original_dataset.name if original_dataset else "数据集"
            safe_dataset_id = str(dataset_id)

        if target_column not in df.columns:
            raise ValueError(f"目标列 '{target_column}' 不存在")

        if not feature_columns:
            feature_columns = [c for c in df.columns if c != target_column]
        else:
            missing = [c for c in feature_columns if c not in df.columns]
            if missing:
                raise ValueError(f"特征列不存在: {missing}")
            # 目标列不能被当作特征列：手动勾选目标列或切换目标列后残留的旧目标列
            # 都会造成数据泄露（模型用"答案预测答案"，指标虚高）（修复）
            if target_column in feature_columns:
                feature_columns = [c for c in feature_columns if c != target_column]

        X = df[feature_columns].copy()
        y_raw = df[target_column]

        # datetime 列处理:转换为 timestamp（int64），避免 numpy DTypePromotionError
        # datetime64 列无法与 float64 混合参与矩阵运算，转为数值后可正常训练
        for col in X.select_dtypes(include=['datetime64', 'datetime']).columns:
            X[col] = pd.to_numeric(X[col], errors='coerce')

        # 缺失值处理:按算法是否原生支持 NaN 决定策略
        # 原生支持(XGBoost/LightGBM):仅做类型转换,保留 NaN(让算法自行处理)
        # 不原生支持:均值填充数值列 -> object 列强转数值 -> 0 填充残余
        # 低基数字符串分类列先做 LabelEncoder：直接强转数值会整列 NaN，
        # 导致特征信息全部丢失（修复，编码器存入模型供预测/评估复用）
        feature_encoders = {}
        for col in X.select_dtypes(include=['object', 'category']).columns:
            nunique = X[col].nunique(dropna=True)
            if 1 < nunique <= 50:
                le = LabelEncoder()
                mask = X[col].notna()
                le.fit(X[col][mask].astype(str))
                X.loc[mask, col] = le.transform(X[col][mask].astype(str))
                X[col] = pd.to_numeric(X[col], errors='coerce')
                feature_encoders[col] = le
            else:
                X[col] = pd.to_numeric(X[col], errors='coerce')

        if not native_nan_support(algorithm):
            X = X.fillna(X.mean(numeric_only=True))
            X = X.fillna(0)

        # 目标列编码：分类任务对所有类型列统一做 LabelEncoder
        # 必须对所有分类目标列编码,不能只处理 object/category 列:
        # XGBoost/LightGBM 要求标签从 0 开始连续,数值型分类列(如 [1,2,3,4,5])
        # 不编码会报 "Invalid classes inferred from unique values of `y`"
        label_encoder = None
        if task_type == "classification":
            # 目标列缺失值拦截：NaN 经 astype(str) 会被编码为 "nan" 类别污染模型（修复）
            if y_raw.isna().any():
                nan_count = int(y_raw.isna().sum())
                raise ValueError(f"目标列 '{target_column}' 包含 {nan_count} 个缺失值，分类任务不支持缺失目标值，请先清洗数据")
            label_encoder = LabelEncoder()
            # 强制转字符串后编码,保证所有分类列(数值/字符串/类别)都映射为 [0, n-1]
            y = label_encoder.fit_transform(y_raw.astype(str))
            # 分类任务校验：至少 2 个类别，每类至少 2 个样本
            unique_classes = len(np.unique(y))
            if unique_classes < 2:
                raise ValueError(f"目标列 '{target_column}' 分类数过少（{unique_classes}类），无法用于分类任务")
            class_counts = pd.Series(y).value_counts()
            if class_counts.min() < 2:
                rare_class = class_counts.idxmin()
                raise ValueError(f"目标列 '{target_column}' 中类别 {rare_class} 仅有 {class_counts.min()} 个样本，分类任务需要每类至少2个样本")
        else:
            y = pd.to_numeric(y_raw, errors='coerce')
            if y.isna().any():
                raise ValueError(f"目标列 '{target_column}' 包含非数值内容，无法用于回归任务")

        # 划分训练/测试集（train_test_split 是训练内部细节，不单独上报进度）
        # 测试集完全独立，不参与训练和调参，用于最终评估
        if task_type == "classification":
            X_trainval, X_test, y_trainval, y_test = train_test_split(
                X, y, test_size=test_size, random_state=random_seed, stratify=y
            )
            # 稀有类别样本数不足折数时自动降低交叉验证折数，避免 StratifiedKFold 崩溃（修复）
            # 必须基于训练/验证集(y_trainval)计数：train_test_split 会从每类分走样本到测试集，
            # 若按全量 y 判断降折，训练集内稀有类别样本数可能仍 < 折数
            trainval_class_counts = pd.Series(y_trainval).value_counts()
            if int(trainval_class_counts.min()) < cv_folds:
                cv_folds = max(2, int(trainval_class_counts.min()))
            cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=random_seed)
        else:
            X_trainval, X_test, y_trainval, y_test = train_test_split(
                X, y, test_size=test_size, random_state=random_seed
            )
            cv = KFold(n_splits=cv_folds, shuffle=True, random_state=random_seed)

        X_train, y_train = X_trainval, y_trainval

        # ===== 阶段2：模型训练中（50%） =====
        update_task_progress(db, task_record_id, "模型训练中", 50, f"正在训练 {algorithm} 模型")

        # 通过算法注册表构造估算器(支持 14 种算法,详见 algorithm_registry.py)
        base_model = build_estimator(algorithm, task_type, random_seed=random_seed)

        # 构建 Pipeline：XGBoost/LightGBM 原生支持 NaN，若再套 StandardScaler，
        # scaler 对含 NaN 的列求 mean/std 会把整列污染为 NaN（连非缺失值也被破坏），
        # 故原生支持 NaN 的算法跳过标准化步骤，其余算法保留
        if native_nan_support(algorithm):
            pipeline = Pipeline([
                ('model', base_model)
            ])
        else:
            pipeline = Pipeline([
                ('scaler', StandardScaler()),
                ('model', base_model)
            ])

        # 超参数调优
        best_params = {}
        tune_results = None
        # auto_tune=True 但用户未指定 hyperparams 时,从注册表取默认搜索空间
        if auto_tune and not hyperparams:
            hyperparams = get_default_param_grid(algorithm)

        if auto_tune and hyperparams:
            # Pipeline 参数需加 'model__' 前缀
            param_grid = {f'model__{k}': v for k, v in hyperparams.items()}

            # 搜索策略:优先遵循用户显式指定,其次用注册表推荐的策略
            search_config = get_search_config(algorithm, user_tune_method=tune_method)
            strategy = search_config["strategy"]
            n_iter = search_config["n_iter"]

            if strategy == "grid" or not n_iter:
                search = GridSearchCV(
                    pipeline, param_grid, cv=cv, scoring='f1_weighted' if task_type == 'classification' else 'r2',
                    n_jobs=-1, refit=True
                )
            else:
                search = RandomizedSearchCV(
                    pipeline, param_grid, n_iter=n_iter, cv=cv,
                    scoring='f1_weighted' if task_type == 'classification' else 'r2',
                    n_jobs=-1, refit=True, random_state=random_seed
                )

            search.fit(X_train, y_train)
            pipeline = search.best_estimator_
            best_params = {k.replace('model__', ''): v for k, v in search.best_params_.items()}
            tune_results = {
                "best_score": float(search.best_score_),
                "best_params": best_params,
                "method": strategy,
                "n_candidates": len(search.cv_results_['params'])
            }
        else:
            pipeline.fit(X_train, y_train)

        # ===== 阶段3：模型评估中（80%） =====
        update_task_progress(db, task_record_id, "模型评估中", 80, "正在评估模型性能")

        # 测试集评估（测试集完全独立，未参与训练和调参）
        y_pred = pipeline.predict(X_test)
        metrics = {}

        if task_type == "classification":
            from sklearn.metrics import (
                accuracy_score, precision_score, recall_score, f1_score,
                classification_report, confusion_matrix, roc_auc_score
            )
            metrics['accuracy'] = float(accuracy_score(y_test, y_pred))
            metrics['precision'] = float(precision_score(y_test, y_pred, average='weighted', zero_division=0))
            metrics['recall'] = float(recall_score(y_test, y_pred, average='weighted', zero_division=0))
            metrics['f1'] = float(f1_score(y_test, y_pred, average='weighted', zero_division=0))
            # 二分类任务额外计算 ROC AUC
            try:
                if len(np.unique(y)) == 2 and hasattr(pipeline, 'predict_proba'):
                    y_proba = pipeline.predict_proba(X_test)[:, 1]
                    metrics['roc_auc'] = float(roc_auc_score(y_test, y_proba))
            except Exception:
                pass
        else:
            from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error
            metrics['r2'] = float(r2_score(y_test, y_pred))
            metrics['mse'] = float(mean_squared_error(y_test, y_pred))
            metrics['rmse'] = float(np.sqrt(metrics['mse']))
            metrics['mae'] = float(mean_absolute_error(y_test, y_pred))

        # 交叉验证评分（在训练+验证集上做 CV，反映模型稳定性）
        cv_scores = cross_val_score(
            pipeline, X_train, y_train, cv=cv,
            scoring='f1_weighted' if task_type == 'classification' else 'r2',
            n_jobs=-1
        )
        metrics['cv_mean'] = float(cv_scores.mean())
        metrics['cv_std'] = float(cv_scores.std())
        metrics['cv_scores'] = cv_scores.tolist()

        # 特征重要性（从 Pipeline 末端的模型提取）
        feature_importance = {}
        try:
            classifier = pipeline.named_steps['model']
            if hasattr(classifier, 'feature_importances_'):
                importance = classifier.feature_importances_
            elif hasattr(classifier, 'coef_'):
                importance = np.abs(classifier.coef_).flatten()
            else:
                importance = np.zeros(len(feature_columns))

            feature_importance = {
                feature_columns[i]: float(importance[i])
                for i in range(len(feature_columns))
            }
        except Exception:
            pass

        # ===== 阶段4：保存结果（100%） =====
        update_task_progress(db, task_record_id, "保存结果", 100, "正在保存模型和结果")

        # 模型与测试集持久化到 MinIO
        # 时间戳格式与其它模块产物保持一致: YYYY-MM-DD HH-MM-SS
        timestamp = datetime.now(SHANGHAI_TZ).strftime('%Y-%m-%d %H-%M-%S')
        model_object_name = f"models/model_{algorithm}_{safe_dataset_id}_{timestamp}.pkl"
        testset_object_name = f"models/testset_{algorithm}_{safe_dataset_id}_{timestamp}.csv"

        # 测试集单独保存，支持后续独立评估使用
        df_test = pd.DataFrame(X_test, columns=feature_columns)
        # 分类任务测试集保存原始标签（而非 LabelEncoder 编码值），
        # 使后续评估时"真实值 vs 预测值"能展示原始类别，且无需反向编码
        if label_encoder is not None:
            df_test[target_column] = label_encoder.inverse_transform(y_test.astype(int))
        else:
            df_test[target_column] = y_test
        csv_buf = io.StringIO()
        df_test.to_csv(csv_buf, index=False, encoding='utf-8-sig')
        csv_bytes = csv_buf.getvalue().encode('utf-8-sig')
        actual_testset_path = storage_manager.save_bytes(testset_object_name, csv_bytes)

        # 数据集划分统计
        total_samples = len(X)
        trainval_size = len(X_trainval)
        test_size_count = len(X_test)
        split_info = {
            "total": total_samples,
            "trainval": trainval_size,
            "trainval_ratio": round(trainval_size / total_samples, 4),
            "test": test_size_count,
            "test_ratio": round(test_size_count / total_samples, 4),
            "cv_folds": cv_folds,
            "test_size_param": test_size,
            "description": "训练+验证集用于模型训练和交叉验证调参，测试集完全独立用于最终评估"
        }

        # 调优方法中文名(用于报告展示)
        tune_method_name = {
            'grid': '网格搜索(穷尽)',
            'random': '随机搜索(快速)'
        }

        # 模型 joblib 序列化
        model_buf = io.BytesIO()
        joblib.dump({
            'pipeline': pipeline,
            'label_encoder': label_encoder,
            'feature_encoders': feature_encoders,
            'feature_columns': feature_columns,
            'algorithm': algorithm,
            'task_type': task_type,
            'target_column': target_column,
            'metrics': metrics,
            'test_set_path': actual_testset_path,
            'split_info': split_info
        }, model_buf)
        model_buf.seek(0)
        model_bytes = model_buf.read()
        actual_model_path = storage_manager.save_bytes(model_object_name, model_bytes)
        model_file_size = len(model_bytes)

        # 保存为 ML 产物到数据库
        # algorithm 字段使用中文显示(如"随机森林（分类）"),便于数据管理直接展示
        # 命名方案：产物保留源名（去扩展名 + 真实内容后缀 .pkl，与存储格式一致），不拼算法名/时间戳，靠 #id/颜色区分
        model_name = build_product_name(dataset_name, "pkl")
        algorithm_display = format_algorithm_field(algorithm, task_type)
        # 远程模式：parent_id 为 None（无父数据集）
        parent_id = None if is_remote else dataset_id
        model_record = Dataset(
            name=model_name,
            file_path=actual_model_path,
            file_size=model_file_size,
            module_source="ml",
            module_label=MODULE_LABEL_MAP.get("ml", "机器学习"),
            algorithm=algorithm_display,
            parent_id=parent_id,
            artifact_type="ml_model",
            row_count=len(X_train) + len(X_test),
            user_id=user_id,
            # 远程来源血缘字段
            connection_id=remote_config.get("connection_id") if is_remote else None,
            table_name=remote_config.get("table_name") if is_remote else None,
            root_connection_id=remote_config.get("connection_id") if is_remote else None,
            source_type="derived",
            report_content=json.dumps({
                "model_info": {
                    "model_name": model_name,
                    "algorithm": algorithm,
                    "task_type": task_type,
                    "target_column": target_column,
                    "feature_count": len(feature_columns),
                    "feature_columns": feature_columns,
                    "created_at": timestamp
                },
                "training_params": {
                    "test_size": test_size,
                    "cv_folds": cv_folds,
                    "auto_tune": auto_tune,
                    "tune_method": tune_method,
                    "hyperparams": hyperparams,
                    "random_seed": random_seed
                },
                "performance_metrics": metrics,
                "dataset_split": split_info,
                "feature_importance": feature_importance,
                "best_params": best_params,
                "tune_results": tune_results
            }, ensure_ascii=False, default=str)
        )
        db.add(model_record)
        db.commit()
        db.refresh(model_record)

        clear_user_dataset_cache(user_id)
        # 训练完成清理预检缓存(数据集已被使用,缓存无需保留)；远程模式跳过
        if not is_remote:
            _clear_ml_precheck_cache(user_id, dataset_id)

        # 埋点：更新任务记录为成功
        execution_time = int((time.time() - start_time) * 1000)
        # 特征重要性 Top 5（按重要性降序，便于操作历史快速查看关键特征）
        top5_importance = sorted(
            [{"name": k, "importance": v} for k, v in feature_importance.items()],
            key=lambda x: x["importance"], reverse=True
        )[:5] if feature_importance else []
        update_task_record(
            db=db,
            record_id=task_record_id,
            status="success",
            dataset_id=model_record.id,
            result_summary={
                "operation": "train",
                "model_name": model_name,
                "algorithm": algorithm,  # 保留英文算法名（专有名词）
                "task_type": task_type,  # 存英文（classification/regression），由 _label_value 转中文
                "accuracy": metrics.get("accuracy") or metrics.get("r2"),
                "metrics": metrics,
                "train_rows": len(X_train),
                "test_rows": len(X_test),
                "cv_folds": cv_folds,
                "test_size": test_size,
                "auto_tune": auto_tune,
                "tune_method": tune_method if auto_tune else None,
                "best_params": best_params if auto_tune else None,
                "feature_importance": feature_importance,  # 完整特征重要性，非仅Top5
                "model_file": actual_model_path,
                # 以下字段为补充，使异步 result_summary 与同步 return 字段一致
                "tune_results": tune_results,
                "feature_columns": feature_columns,
                "split_info": split_info,
                "random_seed": random_seed,
                "model_id": model_record.id,
                "train_size": len(X_train),
            },
            execution_time=execution_time
        )

        return {
            "model_id": model_record.id,
            "model_name": model_name,
            "model_path": actual_model_path,
            "algorithm": algorithm,
            "task_type": task_type,
            "metrics": metrics,
            "feature_importance": feature_importance,
            "best_params": best_params,
            "tune_results": tune_results,
            "feature_columns": feature_columns,
            "split_info": split_info,
            "train_size": len(X_train),
            "test_size": len(X_test),
            "random_seed": random_seed
        }
    except SoftTimeLimitExceeded:
        # 软超时：Celery soft_time_limit 触发，需在硬超时前更新数据库状态
        execution_time = int((time.time() - start_time) * 1000)
        try:
            update_task_record(
                db=db,
                record_id=task_record_id,
                status="failed",
                error_message=f"训练执行超时（超过 {settings.CELERY_TASK_SOFT_TIME_LIMIT} 秒），已自动终止",
                execution_time=execution_time,
                failure_category="timeout"
            )
        except Exception:
            pass
        raise
    except Exception as e:
        # 异常时更新任务记录为 failed（含失败分类，便于前端展示和重试控制）
        execution_time = int((time.time() - start_time) * 1000)
        try:
            update_task_record(
                db=db,
                record_id=task_record_id,
                status="failed",
                error_message=str(e),
                execution_time=execution_time,
                failure_category=classify_failure(e)
            )
        except Exception:
            # 更新任务记录失败时不掩盖原异常
            pass
        raise
    finally:
        # 无论同步还是异步，都关闭独立创建的 db 会话
        db.close()


# 注册到 retry_task 任务注册表，支持失败后手动重试时通过 task_type 查找原任务处理函数
task_manager.register_task_handler("ml_training", _execute_training)


@task_manager.register_task
def _execute_batch_predict(task_record_id: int, user_id: int, model_id: int, predict_dataset_id: int, remote_config: dict = None):
    """批量预测核心执行函数（同步/异步共用入口）

    通过 SessionLocal 创建独立 db 会话：
    - 同步调用时与 FastAPI 的 db 隔离，避免长事务占用请求连接
    - 异步调用时（Celery Worker 进程）必须新建 session，因为无法访问 FastAPI 请求上下文

    6阶段进度上报到 task_records.result_summary：
    - 加载模型(10%)：从 MinIO 加载模型 pkl 文件
    - 加载预测数据(20%)：加载数据集
    - 特征检查(30%)：校验特征列完整性和数据类型
    - 执行预测(60%)：模型预测 + 概率计算
    - 结果汇总(80%)：预测完成，汇总结果
    - 保存结果(100%)：预测结果持久化到 MinIO + 数据库

    Args:
        task_record_id: 任务记录ID（入口已创建）
        user_id: 用户ID
        model_id: 已训练模型的ID
        predict_dataset_id: 待预测的数据集ID（远程模式为 None）
        remote_config: 远程数据源配置（可选）

    Returns:
        预测结果字典（与原同步接口返回结构保持一致）
    """
    import joblib

    # Celery Worker 是独立进程，必须新建 db 会话，不能复用 FastAPI 请求作用域的 db
    db = SessionLocal()
    start_time = time.time()

    try:
        # ===== 阶段1：加载模型（10%） =====
        update_task_progress(db, task_record_id, "加载模型", 10, "正在加载模型文件")

        model_record = db.query(Dataset).filter(Dataset.id == model_id, Dataset.user_id == user_id).first()
        if not model_record:
            raise ValueError(f"模型 {model_id} 不存在")
        if model_record.artifact_type != "ml_model":
            raise ValueError("该记录不是模型")
        if not model_record.file_path:
            raise ValueError("模型文件不存在")

        model_bytes = storage_manager.get_file_bytes(model_record.file_path)
        model_data = joblib.load(io.BytesIO(model_bytes))
        pipeline = model_data['pipeline']
        feature_columns = model_data['feature_columns']
        label_encoder = model_data.get('label_encoder')
        target_column = model_data.get('target_column')
        task_type = model_data.get('task_type')
        # 模型算法名（用于操作历史展示，保留英文专有名词）
        model_algorithm = model_data.get('algorithm', '')
        # 训练时保存的低基数分类特征列编码器（旧模型无此字段时为空，保持向后兼容）
        feature_encoders = model_data.get('feature_encoders', {}) or {}

        # ===== 阶段2：加载预测数据（20%） =====
        update_task_progress(db, task_record_id, "加载预测数据", 20, "正在加载预测数据")

        is_remote = remote_config and remote_config.get("use_remote")

        # 统一加载数据（本地或远程）
        data_service = DataService(db)
        df, predict_dataset = data_service.load_module_data(
            dataset_id=predict_dataset_id,
            remote_config=remote_config,
            user_id=user_id
        )
        # 远程模式下数值列可能被加载为 object 类型，先做类型转换
        df = _coerce_numeric_columns(df)

        # 数据集名称（远程模式使用表名）
        if is_remote:
            predict_dataset_name = remote_config.get("table_name", "远程表")
        else:
            predict_dataset_name = predict_dataset.name if predict_dataset else "数据集"

        # ===== 阶段3：特征检查（30%） =====
        update_task_progress(db, task_record_id, "特征检查", 30, "正在检查特征列完整性和数据类型")

        # 检查特征列是否齐全(区分部分缺失/全部缺失,给出精确提示)
        missing = [c for c in feature_columns if c not in df.columns]
        if missing:
            if len(missing) == len(feature_columns):
                # 全部特征列都缺失
                execution_time = int((time.time() - start_time) * 1000)
                update_task_record(
                    db=db, record_id=task_record_id, status="failed",
                    error_message=f"预测数据未包含任何模型所需特征列。模型需要: {feature_columns}；数据集实际列: {list(df.columns)}",
                    execution_time=execution_time,
                    failure_category="param_error"
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"预测数据未包含任何模型所需特征列。模型需要: {feature_columns}；数据集实际列: {list(df.columns)}"
                )
            else:
                # 部分缺失
                existing = [c for c in feature_columns if c in df.columns]
                execution_time = int((time.time() - start_time) * 1000)
                update_task_record(
                    db=db, record_id=task_record_id, status="failed",
                    error_message=f"预测数据缺少 {len(missing)}/{len(feature_columns)} 个特征列。缺少: {missing}；已有: {existing}",
                    execution_time=execution_time,
                    failure_category="param_error"
                )
                raise HTTPException(
                    status_code=400,
                    detail=f"预测数据缺少 {len(missing)}/{len(feature_columns)} 个特征列。缺少: {missing}；已有: {existing}"
                )

        # 空数据检查(避免 sklearn 抛出难以理解的堆栈异常)
        if len(df) == 0:
            execution_time = int((time.time() - start_time) * 1000)
            update_task_record(
                db=db, record_id=task_record_id, status="failed",
                error_message="预测数据为空(0行),无法执行预测。请检查数据文件是否包含有效数据行",
                execution_time=execution_time,
                failure_category="data_error"
            )
            raise HTTPException(
                status_code=400,
                detail=f"预测数据为空(0行),无法执行预测。请检查数据文件是否包含有效数据行"
            )

        # 检查特征列数据类型是否与训练时一致(数值型/分类型)
        # 如果训练时是数值型,预测数据是分类型(字符串),to_numeric 会转 NaN,导致预测异常
        type_warnings = []
        critical_type_errors = []
        for col in feature_columns:
            col_data = df[col]
            # 列中非空值
            non_null = col_data.dropna()
            if len(non_null) == 0:
                type_warnings.append(f"特征列 '{col}' 全为空值")
            elif non_null.dtype == 'object' or str(non_null.dtype).startswith('str') or str(non_null.dtype).startswith('string'):
                # 字符串列(object/string),检查是否能完全转为数值
                # 该列训练时若是低基数分类特征（有编码器），字符串类别是合法的，走编码转换而非报错
                trained_categorical = col in feature_encoders
                if not trained_categorical:
                    # 用 errors='coerce' 转换后看 NaN 占比,判断是否为真正的分类型列
                    converted = pd.to_numeric(non_null, errors='coerce')
                    nan_ratio = converted.isna().sum() / len(converted)
                    if nan_ratio > 0.5:
                        # 超过50%无法转换,视为严重类型错误(分类型数据用于数值模型)
                        critical_type_errors.append(
                            f"特征列 '{col}' 为分类型(字符串),无法转为数值,转换失败率 {nan_ratio*100:.0f}%。"
                            f"模型训练时该列为数值型,请检查数据格式"
                        )
                    elif nan_ratio > 0:
                        # 部分无法转换,记录警告
                        type_warnings.append(f"特征列 '{col}' 部分值为字符串类型,已自动转换(失败率 {nan_ratio*100:.0f}%)")

        # 严重类型错误直接阻断(避免预测结果异常)
        if critical_type_errors:
            execution_time = int((time.time() - start_time) * 1000)
            update_task_record(
                db=db, record_id=task_record_id, status="failed",
                error_message=f"特征列数据类型错误: {'; '.join(critical_type_errors)}",
                execution_time=execution_time,
                failure_category="data_error"
            )
            raise HTTPException(
                status_code=400,
                detail=f"特征列数据类型错误: {'; '.join(critical_type_errors)}"
            )

        # ===== 阶段4：执行预测（60%） =====
        update_task_progress(db, task_record_id, "执行预测", 60, "正在执行模型预测")

        X = df[feature_columns].copy()
        # datetime 列处理:转换为 timestamp，与训练时保持一致
        for col in X.select_dtypes(include=['datetime64', 'datetime']).columns:
            X[col] = pd.to_numeric(X[col], errors='coerce')
        # 低基数分类特征列：用训练时保存的编码器转换（与训练预处理保持一致），
        # 未见过的类别映射为 NaN 交给缺失值策略处理，避免 transform 抛错（修复）
        for col in X.select_dtypes(include=['object', 'category']).columns:
            le = feature_encoders.get(col)
            if le is not None:
                mask = X[col].notna()
                if mask.any():
                    try:
                        X.loc[mask, col] = le.transform(X[col][mask].astype(str))
                    except ValueError:
                        # 存在训练时未见过的类别：逐个转换，未知类别置 NaN
                        X.loc[mask, col] = [
                            le.transform([str(v)])[0] if str(v) in le.classes_ else np.nan
                            for v in X.loc[mask, col]
                        ]
                X[col] = pd.to_numeric(X[col], errors='coerce')
            else:
                X[col] = pd.to_numeric(X[col], errors='coerce')
        # 缺失值处理:与训练时保持一致,按算法是否原生支持 NaN 决定策略
        # 原生支持(XGBoost/LightGBM)保留 NaN,其他算法均值/0 填充
        model_algo = model_data.get('algorithm', '')
        if not native_nan_support(model_algo):
            X = X.fillna(X.mean(numeric_only=True))
            X = X.fillna(0)

        # 预测
        predictions = pipeline.predict(X)

        # 反编码（分类任务）
        if label_encoder is not None:
            predictions = label_encoder.inverse_transform(predictions)

        # 预测概率（分类任务）
        probabilities = None
        if task_type == "classification" and hasattr(pipeline, 'predict_proba'):
            try:
                proba = pipeline.predict_proba(X)
                probabilities = proba.tolist()
            except Exception:
                pass

        # ===== 阶段5：结果汇总（80%） =====
        update_task_progress(db, task_record_id, "结果汇总", 80, "预测完成，正在汇总结果")

        # ===== 阶段6：保存结果（100%） =====
        update_task_progress(db, task_record_id, "保存结果", 100, "正在保存预测结果")

        # 生成预测结果文件
        df_result = df.copy()
        df_result[f'{target_column}_predicted'] = predictions
        if probabilities is not None:
            for i, cls in enumerate(pipeline.classes_):
                class_name = label_encoder.inverse_transform([cls])[0] if label_encoder else str(cls)
                df_result[f'{target_column}_proba_{class_name}'] = [p[i] for p in probabilities]

        # 保存预测结果到 MinIO
        if is_remote:
            base = predict_dataset_name
            parent_id = None
        else:
            base = predict_dataset.name
            parent_id = predict_dataset_id
        # 命名方案：产物保留源名（去扩展名 + 真实内容后缀 .csv），不拼 _predicted_/时间戳，靠 #id/颜色区分
        result_filename = build_product_name(base, "csv")
        csv_buffer = io.StringIO()
        df_result.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
        csv_content = csv_buffer.getvalue().encode('utf-8')
        object_name = f"ml/user_{user_id}/{result_filename}"
        result_path = storage_manager.save_bytes(object_name, csv_content)

        result_file_size = len(csv_content)

        # 构建算法描述字段
        if is_remote:
            predict_source_desc = f"远程表: {predict_dataset_name}"
        else:
            predict_source_desc = f"原始数据: {predict_dataset_name}"

        result_record = Dataset(
            name=result_filename,
            file_path=result_path,
            file_size=result_file_size,
            # 批量预测是机器学习模块的内部功能，导航栏无独立入口，统一归到 ml 大类
            module_source="ml",
            module_label=MODULE_LABEL_MAP.get("ml", "机器学习"),
            algorithm=f"{model_record.algorithm or '机器学习模型'}（模型: {model_record.name}）→ 预测{predict_source_desc}",
            parent_id=parent_id,
            artifact_type="ml_prediction",
            row_count=len(predictions),
            user_id=user_id,
            # 远程来源血缘字段
            connection_id=remote_config.get("connection_id") if is_remote else None,
            table_name=remote_config.get("table_name") if is_remote else None,
            root_connection_id=remote_config.get("connection_id") if is_remote else None,
            source_type="derived",
        )
        db.add(result_record)
        db.commit()
        db.refresh(result_record)

        clear_user_dataset_cache(user_id)

        # 更新任务记录为成功
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db,
            record_id=task_record_id,
            status="success",
            dataset_id=result_record.id,
            result_summary={
                "operation": "batch_predict",
                "prediction_rows": len(predictions),
                "prediction_count": len(predictions),
                "prediction_file": result_path,
                "model_name": model_record.name,
                "algorithm": model_algorithm,
                "new_dataset_id": result_record.id,
                "new_dataset_name": result_record.name,
                # 补充预览数据（前100条），避免完整数据撑爆 JSON 字段
                "predictions": predictions[:100].tolist() if hasattr(predictions, 'tolist') else list(predictions[:100]),
                "probabilities": probabilities[:100] if probabilities is not None else None,
                "row_count": len(predictions),
                "warnings": type_warnings if type_warnings else None,
                "full_result_saved": True,  # 标记完整结果已保存到数据集
            },
            execution_time=execution_time
        )

        return {
            "result_id": result_record.id,
            "result_name": result_filename,
            "predictions": predictions.tolist(),
            "probabilities": probabilities,
            "row_count": len(predictions),
            "warnings": type_warnings if type_warnings else None
        }

    except HTTPException:
        # 参数/数据校验失败，task_record 已在内部更新为 failed，直接传播异常
        # 同步调用时 FastAPI 会将 HTTPException 转为对应 HTTP 状态码
        # 异步调用时 Celery 会记录任务失败，前端通过轮询 task_record 看到 failed 状态
        raise
    except SoftTimeLimitExceeded:
        # 软超时：Celery soft_time_limit 触发，需在硬超时前更新数据库状态
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db, record_id=task_record_id, status="failed",
            error_message=f"批量预测超时（超过 {settings.CELERY_TASK_SOFT_TIME_LIMIT} 秒），已自动终止",
            execution_time=execution_time,
            failure_category="timeout"
        )
        raise
    except Exception as e:
        # 未预期的系统异常（模型加载失败、预测异常、文件保存失败等）
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db, record_id=task_record_id, status="failed",
            error_message=f"批量预测失败: {str(e)}",
            execution_time=execution_time,
            failure_category=classify_failure(e)
        )
        raise
    finally:
        # Celery Worker 是独立进程，必须显式关闭 db 会话，避免连接泄漏
        db.close()


# 注册到 retry_task 任务注册表，支持失败后手动重试时通过 task_type 查找原任务处理函数
# batch_predict 的 task_type="ml"，与训练的 "ml_training" 区分
task_manager.register_task_handler("ml", _execute_batch_predict)


@router.post("/batch-predict/{model_id}")
async def batch_predict(model_id: int, body: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """批量预测：使用已保存的模型对新数据进行预测

    智能异步：≥1万行异步提交（Celery 不可用且≥1万行报503不降级），<1万行同步执行
    远程模式强制同步执行

    Args:
        model_id: 已训练模型的ID
        body: {
            "dataset_id": 待预测的数据集ID（必须是ML模块的原始数据 raw_data 或预测数据 predict_data）,
            "remote": 远程数据源配置（与 dataset_id 互斥）
        }
    """
    # 查询模型记录（快速校验，不加载模型文件，避免大数据集时阻塞）
    model_record = db.query(Dataset).filter(Dataset.id == model_id, Dataset.user_id == current_user.id).first()
    if not model_record:
        raise HTTPException(status_code=404, detail="模型不存在")
    if model_record.artifact_type != "ml_model":
        raise HTTPException(status_code=400, detail="该记录不是模型")
    if not model_record.file_path:
        raise HTTPException(status_code=404, detail="模型文件不存在")

    # 查询预测数据集
    predict_dataset_id = body.get("dataset_id")
    remote_config = body.get("remote")
    is_remote = remote_config and remote_config.get("use_remote")

    if not predict_dataset_id and not is_remote:
        raise HTTPException(status_code=400, detail="请提供 dataset_id 或 remote 参数")

    # 数据集名称和行数（远程模式需加载数据获取）
    if is_remote:
        data_service = DataService(db)
        try:
            df_preview, _ = data_service.load_module_data(
                dataset_id=None,
                remote_config=remote_config,
                user_id=current_user.id
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        predict_dataset_name = remote_config.get("table_name", "远程表")
        row_count = len(df_preview)
        predict_dataset = None
    else:
        predict_dataset = validate_ml_data_source(db, predict_dataset_id, current_user.id)
        predict_dataset_name = predict_dataset.name
        row_count = predict_dataset.row_count or 0

    # 创建任务记录
    start_time = time.time()
    task_record = create_task_record(
        db=db,
        task_type="ml",
        user_id=current_user.id,
        dataset_id=predict_dataset_id,  # 远程模式下为 None
        params={
            "operation": "batch_predict",
            "model_name": model_record.name,
            "model_id": model_id,
            "predict_dataset_name": predict_dataset_name,
            "predict_dataset_id": predict_dataset_id,
            "is_remote": is_remote,
            "remote_config": remote_config if is_remote else None,
        }
    )

    # 智能异步分发：远程模式强制同步；本地模式 ≥1万行异步
    if not is_remote and row_count >= settings.ASYNC_THRESHOLD:
        # 业务代码不降级：Celery 不可用时直接报 503，不静默回退到同步
        if not task_manager.is_async_available():
            execution_time = int((time.time() - start_time) * 1000)
            update_task_record(
                db=db, record_id=task_record.id, status="failed",
                error_message="Celery 不可用，无法处理大数据集批量预测，请启动 Celery 服务或使用小数据集",
                execution_time=execution_time,
                failure_category="system_error"
            )
            raise HTTPException(
                status_code=503,
                detail="Celery 不可用，无法处理大数据集批量预测，请启动 Celery 服务或使用小数据集"
            )

        # 任务排队机制：检查用户队列容量，决定立即执行还是进入等待队列
        try:
            can_run_now, queue_msg = check_task_queue_capacity(
                db, current_user.id, exclude_task_id=task_record.id
            )
        except HTTPException as queue_err:
            execution_time = int((time.time() - start_time) * 1000)
            update_task_record(
                db=db, record_id=task_record.id, status="failed",
                error_message=str(queue_err.detail),
                execution_time=execution_time,
                failure_category="param_error"
            )
            raise queue_err

        if can_run_now:
            # 立即执行：提交到 Celery 队列
            task_result = task_manager.run_task(
                _execute_batch_predict,
                task_record_id=task_record.id,
                user_id=current_user.id,
                model_id=model_id,
                predict_dataset_id=predict_dataset_id,
                remote_config=remote_config if is_remote else None,
                no_degrade=True
            )
            celery_task_id = task_result.get("task_id")
            if celery_task_id:
                mark_task_running(db, task_record.id, celery_task_id=celery_task_id)
            return {
                "task_record_id": task_record.id,
                "task_id": celery_task_id,
                "status": "running",
                "message": "批量预测任务已提交，请在右上角任务面板查看进度",
                "row_count": row_count
            }
        else:
            # 进入等待队列：不提交 Celery，由调度器自动激活
            task_record.status = "pending"
            db.commit()
            return {
                "task_record_id": task_record.id,
                "task_id": None,
                "status": "pending",
                "message": f"批量预测任务已进入等待队列（{queue_msg}），将在前面任务完成后自动执行",
                "row_count": row_count
            }

    # 同步执行（小数据集或远程模式）
    return _execute_batch_predict(
        task_record_id=task_record.id,
        user_id=current_user.id,
        model_id=model_id,
        predict_dataset_id=predict_dataset_id,
        remote_config=remote_config if is_remote else None
    )


@router.get("/model-list/{dataset_id}")
async def list_models(
    dataset_id: int,
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(50, ge=1, le=200, description="每页数量，最大200"),
    paginated: bool = Query(False, description="是否返回分页结构（true=分页字典，false=列表，兼容旧前端）"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """列出某个数据集训练的所有模型

    - dataset_id=0：远程模式，返回该用户的远程训练模型（parent_id 为空）
    - paginated=false（默认）：返回列表（兼容旧前端）
    - paginated=true：返回 {models, total, page, page_size, total_pages}
    """
    # 先查总数，再分页查询
    if dataset_id == 0:
        # 远程模式：远程训练模型无父数据集（parent_id=None），全部列出
        base_query = db.query(Dataset).filter(
            Dataset.parent_id.is_(None),
            Dataset.artifact_type == "ml_model",
            Dataset.user_id == current_user.id
        )
    else:
        base_query = db.query(Dataset).filter(
            Dataset.parent_id == dataset_id,
            Dataset.artifact_type == "ml_model",
            Dataset.user_id == current_user.id
        )
    total = base_query.count()
    start = (page - 1) * page_size
    models = base_query.order_by(Dataset.created_at.desc()).offset(start).limit(page_size).all()

    result = []
    for m in models:
        metrics = {}
        feature_columns = []
        target_column = None
        task_type = None
        # 安全解析 report_content：优先取 performance_metrics（新格式），兼容旧格式 metrics
        if m.report_content:
            try:
                parsed = json.loads(m.report_content)
                if isinstance(parsed, dict):
                    if isinstance(parsed.get("performance_metrics"), dict):
                        metrics = parsed["performance_metrics"]
                    elif isinstance(parsed.get("metrics"), dict):
                        metrics = parsed["metrics"]
                    # 提取模型信息(特征列/目标列/任务类型)供前端批量预测使用
                    model_info = parsed.get("model_info") or parsed.get("model_metadata") or {}
                    if isinstance(model_info, dict):
                        feature_columns = model_info.get("feature_columns") or []
                        target_column = model_info.get("target_column")
                        task_type = model_info.get("task_type")
            except (json.JSONDecodeError, TypeError):
                metrics = {}
        result.append({
            "id": m.id,
            "name": m.name,
            "algorithm": m.algorithm,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "metrics": metrics,
            "feature_columns": feature_columns,
            "target_column": target_column,
            "task_type": task_type
        })

    if paginated:
        return {
            "models": result,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size)
        }
    else:
        # 兼容旧前端：返回列表
        return result


@router.get("/models/{model_id}/export")
async def export_model(model_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """导出模型文件（pkl格式）

    下载已训练的模型文件，包含pipeline、标签编码器、特征列等完整信息
    """
    model_record = db.query(Dataset).filter(Dataset.id == model_id, Dataset.user_id == current_user.id).first()
    if not model_record:
        raise HTTPException(status_code=404, detail="模型不存在")
    if model_record.artifact_type != "ml_model":
        raise HTTPException(status_code=400, detail="该记录不是模型")

    if not model_record.file_path:
        raise HTTPException(status_code=404, detail="模型文件不存在")

    model_bytes = storage_manager.get_file_bytes(model_record.file_path)
    # 下载名与前端展示名一致（源名 + 真实 .pkl 后缀），避免暴露内部存储路径
    filename = build_product_name(model_record.name, "pkl")
    return StreamingResponse(
        iter([model_bytes]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}
    )


@router.get("/reports/{report_id}")
async def get_model_report(report_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """获取模型报告详细内容

    用于数据管理中查看ml_model或ml_report类型的报告内容，
    返回解析后的报告结构供前端展示
    """
    record = db.query(Dataset).filter(Dataset.id == report_id, Dataset.user_id == current_user.id).first()
    if not record:
        raise HTTPException(status_code=404, detail="记录不存在")

    # ml_report 类型：直接返回 report_content JSON
    if record.artifact_type == "ml_report":
        report_data = {}
        if record.report_content:
            try:
                report_data = json.loads(record.report_content)
            except (json.JSONDecodeError, TypeError):
                report_data = {}
        return {
            "id": record.id,
            "name": record.name,
            "algorithm": record.algorithm,
            "module_label": record.module_label,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "parent_id": record.parent_id,
            "report": report_data
        }

    # ml_model 类型：从数据库 report_content 字段读取报告
    if record.artifact_type == "ml_model":
        report_data = {}
        if record.report_content:
            try:
                report_data = json.loads(record.report_content)
            except (json.JSONDecodeError, TypeError):
                report_data = {}
        return {
            "id": record.id,
            "name": record.name,
            "algorithm": record.algorithm,
            "module_label": record.module_label,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "parent_id": record.parent_id,
            "report": report_data
        }

    raise HTTPException(status_code=400, detail="该记录不是模型报告或模型")


@router.post("/models/{model_id}/test-evaluate")
async def test_set_evaluate(model_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """测试集独立评估（期末考试）

    使用完全独立的测试集对模型进行最终评估，对比真实值与预测值，
    返回完整的性能指标和预测结果(per_sample_info 列表)。
    改进：
    - 分类任务：反编码真实值和预测值；每条样本含 correct 字段(布尔)供前端展示
    - 回归任务：每条样本含 abs_error(绝对误差)和 rel_error(相对误差百分比)
    """
    import joblib
    import numpy as np
    import pandas as pd

    model_record = db.query(Dataset).filter(Dataset.id == model_id, Dataset.user_id == current_user.id).first()
    if not model_record:
        raise HTTPException(status_code=404, detail="模型不存在")
    if model_record.artifact_type != "ml_model":
        raise HTTPException(status_code=400, detail="该记录不是模型")

    if not model_record.file_path:
        raise HTTPException(status_code=404, detail="模型文件不存在")

    model_bytes = storage_manager.get_file_bytes(model_record.file_path)
    model_data = joblib.load(io.BytesIO(model_bytes))
    pipeline = model_data['pipeline']
    feature_columns = model_data['feature_columns']
    label_encoder = model_data.get('label_encoder')
    target_column = model_data.get('target_column')
    task_type = model_data.get('task_type')
    test_set_path = model_data.get('test_set_path')
    # 模型算法名（用于操作历史展示）
    model_algorithm = model_data.get('algorithm', '')

    if not test_set_path:
        raise HTTPException(status_code=400, detail="测试集数据不存在")

    # 埋点：创建任务记录（status=running）
    # test_set_evaluate 是只读评估，不产生新数据集，task_type="ml" + operation="test_evaluate"
    start_time = time.time()
    task_record = create_task_record(
        db=db,
        task_type="ml",
        user_id=current_user.id,
        dataset_id=model_id,
        params={
            "operation": "test_evaluate",
            "model_name": model_record.name,
            "model_id": model_id,
            "algorithm": model_algorithm,
        }
    )

    try:
        testset_bytes = storage_manager.get_file_bytes(test_set_path)
        df_test = pd.read_csv(io.BytesIO(testset_bytes))
        X_test = df_test[feature_columns].copy()
        y_true_raw = df_test[target_column].values

        # 数据预处理:必须与训练时保持一致,否则 StandardScaler 会对字符串列报错
        # 训练时:不原生支持 NaN 的算法用均值/0 填充 + object 列强转数值;原生支持的算法仅做类型转换
        model_algo = model_data.get('algorithm', '')
        if not native_nan_support(model_algo):
            X_test = X_test.fillna(X_test.mean(numeric_only=True))
            for col in X_test.select_dtypes(include=['object']).columns:
                X_test[col] = pd.to_numeric(X_test[col], errors='coerce')
            X_test = X_test.fillna(0)
        else:
            for col in X_test.select_dtypes(include=['object']).columns:
                X_test[col] = pd.to_numeric(X_test[col], errors='coerce')

        y_pred_raw = pipeline.predict(X_test)

        # 反编码：分类任务把数值预测转回原始标签
        y_true_display = y_true_raw
        y_pred_display = y_pred_raw
        if task_type == "classification" and label_encoder is not None:
            try:
                # 将原始字符串转回编码形式后比较
                y_true_encoded = label_encoder.transform(y_true_raw.astype(str))
                y_pred_decoded = label_encoder.inverse_transform(y_pred_raw.astype(int))
                y_true_display = label_encoder.inverse_transform(y_true_encoded)
                y_pred_display = y_pred_decoded
            except Exception:
                y_true_display = y_true_raw
                y_pred_display = y_pred_raw

        # 计算每条样本的"正确性"和误差，供前端展示
        per_sample_info = []
        n = len(y_true_display)
        if task_type == "classification":
            for i in range(n):
                correct = str(y_true_display[i]) == str(y_pred_display[i])
                per_sample_info.append({
                    "y_true": safe_value(y_true_display[i]),
                    "y_pred": safe_value(y_pred_display[i]),
                    "correct": bool(correct)
                })
        else:
            y_true_arr = np.asarray(y_true_raw, dtype=float)
            y_pred_arr = np.asarray(y_pred_raw, dtype=float)
            for i in range(n):
                err = float(y_pred_arr[i] - y_true_arr[i])
                abs_err = abs(err)
                rel_err = (abs_err / abs(y_true_arr[i])) if y_true_arr[i] != 0 else 0
                per_sample_info.append({
                    "y_true": safe_value(y_true_arr[i]),
                    "y_pred": safe_value(y_pred_arr[i]),
                    "abs_error": round(abs_err, 4),
                    "rel_error": round(rel_err * 100, 2)
                })

        metrics = {}
        if task_type == "classification":
            from sklearn.metrics import (
                accuracy_score, precision_score, recall_score, f1_score,
                classification_report, confusion_matrix, roc_auc_score
            )
            # 分类任务：用字符串比较计算指标
            y_true_str = np.asarray([str(v) for v in y_true_display])
            y_pred_str = np.asarray([str(v) for v in y_pred_display])
            try:
                metrics['accuracy'] = float(accuracy_score(y_true_str, y_pred_str))
                metrics['precision'] = float(precision_score(y_true_str, y_pred_str, average='weighted', zero_division=0))
                metrics['recall'] = float(recall_score(y_true_str, y_pred_str, average='weighted', zero_division=0))
                metrics['f1'] = float(f1_score(y_true_str, y_pred_str, average='weighted', zero_division=0))
                metrics['classification_report'] = classification_report(y_true_str, y_pred_str, output_dict=True, zero_division=0)
            except Exception as e:
                metrics['accuracy'] = float(accuracy_score(y_true_raw, y_pred_raw))
            # 混淆矩阵
            try:
                labels = sorted(set(list(y_true_str)) + list(y_pred_str))
                cm = confusion_matrix(y_true_str, y_pred_str, labels=labels)
                metrics['confusion_matrix'] = cm.tolist()
                metrics['confusion_labels'] = [str(l) for l in labels]
            except Exception:
                pass
            try:
                if len(np.unique(y_true_raw)) == 2 and hasattr(pipeline, 'predict_proba'):
                    y_proba = pipeline.predict_proba(X_test)[:, 1]
                    metrics['roc_auc'] = float(roc_auc_score(y_true_raw, y_proba))
            except Exception:
                pass
        else:
            from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error
            try:
                metrics['r2'] = float(r2_score(y_true_raw, y_pred_raw))
            except Exception:
                metrics['r2'] = 0.0
            metrics['mse'] = float(mean_squared_error(y_true_raw, y_pred_raw))
            metrics['rmse'] = float(np.sqrt(metrics['mse']))
            metrics['mae'] = float(mean_absolute_error(y_true_raw, y_pred_raw))
            # 相对误差百分比
            y_arr = np.asarray(y_true_raw, dtype=float)
            mask = y_arr != 0
            if mask.any():
                mape = float(np.mean(np.abs((y_arr[mask] - y_pred_raw[mask]) / y_arr[mask])) * 100)
            else:
                mape = 0.0
            metrics['mape'] = round(mape, 2)

        # 埋点：更新任务记录为成功
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db,
            record_id=task_record.id,
            status="success",
            result_summary={
                "operation": "test_evaluate",
                "model_name": model_record.name,
                "algorithm": model_algorithm,
                "task_type": task_type,  # 存英文（classification/regression），由 _label_value 转中文
                "test_rows": n,
                "accuracy": metrics.get("accuracy") or metrics.get("r2"),
                "metrics": metrics,
            },
            execution_time=execution_time
        )

        return {
                "model_id": model_id,
                "task_type": task_type,
                "target_column": target_column,
                "test_size": n,
                "metrics": metrics,
                "samples": per_sample_info
            }
    except Exception as e:
        # 失败时回滚未提交的数据库变更，避免连接残留（符合 project 约束：rollback before close）
        db.rollback()
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db,
            record_id=task_record.id,
            status="failed",
            error_message=str(e),
            execution_time=execution_time,
            failure_category=classify_failure(e)
        )
        raise HTTPException(status_code=500, detail=f"测试集评估失败: {e}")


@router.post("/models/{model_id}/export-report")
async def export_model_report(model_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """导出模型报告到数据管理

    在数据管理中生成一条模型报告记录，包含：
    - 模型基本信息、训练参数、性能评估指标、特征重要性等完整报告内容
    """
    import joblib
    from datetime import datetime as dt_local

    model_record = db.query(Dataset).filter(Dataset.id == model_id, Dataset.user_id == current_user.id).first()
    if not model_record:
        raise HTTPException(status_code=404, detail="模型不存在")
    if model_record.artifact_type != "ml_model":
        raise HTTPException(status_code=400, detail="该记录不是模型")

    if not model_record.file_path:
        raise HTTPException(status_code=404, detail="模型文件不存在")

    # 解析现有报告内容
    report_data = {}
    if model_record.report_content:
        try:
            report_data = json.loads(model_record.report_content)
        except (json.JSONDecodeError, TypeError):
            report_data = {}

    # 加载模型获取更多信息
    model_bytes = storage_manager.get_file_bytes(model_record.file_path)
    model_data = joblib.load(io.BytesIO(model_bytes))
    algorithm = model_data.get('algorithm', '')
    task_type = model_data.get('task_type', '')
    target_column = model_data.get('target_column', '')
    feature_columns = model_data.get('feature_columns', [])
    metrics = model_data.get('metrics', {})
    split_info = model_data.get('split_info', {})
    test_set_path = model_data.get('test_set_path', '')

    # 埋点：创建任务记录（status=running）
    # export_model_report 导出报告到数据管理，task_type="ml" + operation="export_report"
    start_time = time.time()
    task_record = create_task_record(
        db=db,
        task_type="ml",
        user_id=current_user.id,
        dataset_id=model_id,
        params={
            "operation": "export_report",
            "model_name": model_record.name,
            "model_id": model_id,
            "algorithm": algorithm,
        }
    )

    # 构建完整报告
    full_report = {
        "report_type": "ml_model_report",
        "model_info": {
            "model_id": model_id,
            "model_name": model_record.name,
            "algorithm": algorithm,
            "task_type": task_type,
            "target_column": target_column,
            "feature_count": len(feature_columns),
            "feature_columns": feature_columns,
            "created_at": model_record.created_at.isoformat() if model_record.created_at else None
        },
        "training_params": report_data.get("train_params", {}),
        "best_params": report_data.get("best_params", {}),
        "tune_results": report_data.get("tune_results"),
        "performance_metrics": metrics,
        "feature_importance": report_data.get("feature_importance", {}),
        "dataset_split": split_info,
        "model_path": model_record.file_path,
        "test_set_path": test_set_path
    }

    # 生成报告记录
    # 命名方案：产物保留源名（基于模型名去扩展名 + .html），不拼"模型报告_"/算法/时间戳，靠 #id/颜色区分
    report_name = build_product_name(model_record.name, "html")
    report_record = Dataset(
        name=report_name,
        file_path=model_record.file_path,
        module_source="ml",
        module_label=MODULE_LABEL_MAP.get("ml", "机器学习"),
        algorithm=f"{algorithm} 模型报告",
        parent_id=model_record.parent_id,
        artifact_type="ml_report",
        report_content=json.dumps(full_report, ensure_ascii=False, default=str),
        user_id=current_user.id
    )

    db.add(report_record)
    db.commit()
    db.refresh(report_record)

    clear_user_dataset_cache(current_user.id)

    # 埋点：更新任务记录为成功
    execution_time = int((time.time() - start_time) * 1000)
    update_task_record(
        db=db,
        record_id=task_record.id,
        status="success",
        dataset_id=report_record.id,
        result_summary={
            "operation": "export_report",
            "model_name": model_record.name,
            "algorithm": algorithm,
            "report_id": report_record.id,
            "report_name": report_record.name,
            "new_dataset_id": report_record.id,
            "new_dataset_name": report_record.name,
        },
        execution_time=execution_time
    )

    return {
        "report_id": report_record.id,
        "report_name": report_name,
        "message": "模型报告已导出到数据管理"
    }
