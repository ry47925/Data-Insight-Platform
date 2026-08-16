from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import json
from datetime import datetime

import pandas as pd
import numpy as np
from celery.exceptions import SoftTimeLimitExceeded

from app.models import Dataset, User
from app.schemas.dataset import DatasetResponse
from app.services.data_service import DataService
from app.services.storage_manager import storage_manager
from app.utils.security import get_current_user
from app.utils.common import clean_dataset_name, build_product_name, get_dataset_or_404, get_numeric_columns, to_numeric_if_possible, get_root_dataset_id, clear_user_dataset_cache, MODULE_LABEL_MAP, validate_upload_file
from app.utils.task_records import (
    create_task_record, update_task_record, update_task_progress,
    mark_task_running, classify_failure, check_task_queue_capacity
)
from app.services.task_manager import task_manager
from app.utils.db import get_db, SessionLocal
from app.config import settings
import io
import time

router = APIRouter()


# ========== 请求模型 ==========

class ClusterRequest(BaseModel):
    dataset_id: Optional[int] = None  # 本地数据集 ID（与 remote 互斥）
    # 远程数据源配置（与 dataset_id 互斥）
    remote: Optional[Dict[str, Any]] = None  # {"use_remote": True, "connection_id": N, "table_name": "..."}
    algorithm: str = "kmeans"  # kmeans / dbscan / hierarchical
    columns: Optional[List[str]] = None
    # KMeans参数
    n_clusters: Optional[int] = None  # None表示自动推荐
    init: str = "k-means++"
    max_iter: int = 300
    n_init: int = 10
    # DBSCAN参数
    eps: Optional[float] = None  # None表示自动推荐
    min_samples: Optional[int] = None  # None表示自动推荐
    metric: str = "euclidean"
    # 层次聚类参数
    linkage: str = "ward"
    # 通用
    auto_params: bool = True  # 是否自动推荐参数
    save: bool = False  # 是否自动保存结果到数据管理


class AssociationRequest(BaseModel):
    dataset_id: Optional[int] = None  # 本地数据集 ID（与 remote 互斥）
    # 远程数据源配置（与 dataset_id 互斥）
    remote: Optional[Dict[str, Any]] = None  # {"use_remote": True, "connection_id": N, "table_name": "..."}
    algorithm: str = "apriori"  # apriori / fpgrowth
    data_format: str = "basket"  # basket / binary（购物篮格式 / 自动二值化）
    min_support: Optional[float] = None  # None表示自动推荐
    min_confidence: Optional[float] = None  # None表示自动推荐
    min_lift: float = 1.0
    max_len: Optional[int] = None  # 最大项集长度，None 表示不限制（对应前端“最大项集长度”参数）
    item_column: Optional[str] = None
    tid_column: Optional[str] = None
    auto_params: bool = True
    save: bool = False  # 是否自动保存结果到数据管理


class SequenceRequest(BaseModel):
    dataset_id: Optional[int] = None  # 本地数据集 ID（与 remote 互斥）
    # 远程数据源配置（与 dataset_id 互斥）
    remote: Optional[Dict[str, Any]] = None  # {"use_remote": True, "connection_id": N, "table_name": "..."}
    algorithm: str = "prefixspan"  # prefixspan / gsp
    seq_id_column: Optional[str] = None  # 序列ID列（如用户ID），None自动检测
    time_column: Optional[str] = None  # 时间列，None自动检测
    event_column: Optional[str] = None  # 事件列，None自动检测
    min_support: Optional[float] = None  # None表示自动推荐
    max_len: Optional[int] = None  # 最大序列长度，None 使用默认值 10
    auto_params: bool = True
    save: bool = False  # 是否自动保存结果到数据管理


class PrecheckRequest(BaseModel):
    dataset_id: Optional[int] = None  # 本地数据集 ID（与 remote 互斥）
    # 远程数据源配置（与 dataset_id 互斥）
    remote: Optional[Dict[str, Any]] = None  # {"use_remote": True, "connection_id": N, "table_name": "..."}


class RecommendParamsRequest(BaseModel):
    dataset_id: Optional[int] = None  # 本地数据集 ID（与 remote 互斥）
    # 远程数据源配置（与 dataset_id 互斥）
    remote: Optional[Dict[str, Any]] = None  # {"use_remote": True, "connection_id": N, "table_name": "..."}
    algorithm_type: str  # cluster / association / sequence
    algorithm: Optional[str] = None  # 具体算法名
    columns: Optional[List[str]] = None  # 用户选择的特征列（聚类用）


# ========== 数据预处理工具函数 ==========

def _prepare_numeric_data(df: pd.DataFrame, columns: Optional[List[str]] = None):
    """准备数值数据：提取数值列、缺失值均值填充、标准化

    标准化仅用于距离计算，不影响原始数据。

    Returns:
        (data_scaled, numeric_cols) 标准化后的numpy数组和数值列名列表；
        无数值列时返回 (None, [])
    """
    from sklearn.preprocessing import StandardScaler

    all_numeric_cols = get_numeric_columns(df)

    # 使用用户指定的列（过滤掉非数值列），否则使用全部数值列
    if columns and len(columns) > 0:
        numeric_cols = [c for c in columns if c in all_numeric_cols]
    else:
        numeric_cols = all_numeric_cols

    if len(numeric_cols) == 0:
        return None, []

    numeric_df = df[numeric_cols].copy()
    for col in numeric_cols:
        numeric_df[col] = to_numeric_if_possible(numeric_df[col])

    # 缺失值均值填充；全NaN列均值为NaN，再补0
    numeric_df = numeric_df.fillna(numeric_df.mean())
    numeric_df = numeric_df.fillna(0)

    # 标准化（仅用于距离计算）
    scaler = StandardScaler()
    data_scaled = scaler.fit_transform(numeric_df)

    return data_scaled, numeric_cols


def _compute_pca_2d(data_scaled: np.ndarray, labels: np.ndarray, max_points: int = 500) -> List[Dict]:
    """PCA降维到2D，返回投影数据列表

    数据量超过max_points时随机采样，避免前端渲染压力。
    """
    from sklearn.decomposition import PCA

    n_samples = len(data_scaled)
    if n_samples == 0:
        return []

    # 数据量过大时随机采样
    if n_samples > max_points:
        indices = np.random.choice(n_samples, max_points, replace=False)
        data_sample = data_scaled[indices]
        labels_sample = np.array(labels)[indices]
    else:
        data_sample = data_scaled
        labels_sample = np.array(labels)

    # PCA降维到2D；特征不足2维时补零
    if data_sample.shape[1] >= 2:
        pca = PCA(n_components=2)
        projection = pca.fit_transform(data_sample)
    elif data_sample.shape[1] == 1:
        projection = np.column_stack([data_sample, np.zeros(len(data_sample))])
    else:
        return []

    return [
        {
            "x": round(float(projection[i][0]), 4),
            "y": round(float(projection[i][1]), 4),
            "cluster": int(labels_sample[i])
        }
        for i in range(len(projection))
    ]


def _get_data_preview(df: pd.DataFrame, max_rows: int = 20) -> Dict:
    """获取数据预览：返回前max_rows行数据

    远程模式下 DataFrame 中的时间列为 datetime64 类型，to_dict 会产生
    pd.Timestamp / pd.NaT 对象，FastAPI 的 jsonable_encoder 无法序列化 NaT，
    导致 API 返回 500。此处用 json.dumps(default=str) 统一清理不可序列化类型。
    """
    preview_df = df.head(max_rows)
    preview_df = preview_df.replace({np.nan: None, np.inf: None, -np.inf: None})

    # 将 datetime64 列转为字符串，避免 Timestamp/NaT 对象导致 JSON 序列化失败
    for col in preview_df.columns:
        if pd.api.types.is_datetime64_any_dtype(preview_df[col]):
            preview_df[col] = preview_df[col].apply(
                lambda x: x.strftime('%Y-%m-%d %H:%M:%S') if pd.notna(x) else None
            )

    # 双保险：json.dumps(default=str) 将所有不可序列化类型转为字符串
    rows = json.loads(json.dumps(preview_df.to_dict(orient="records"), default=str, ensure_ascii=False))

    return {
        "columns": list(preview_df.columns),
        "rows": rows,
        "total_rows": len(df)
    }


# ========== 参数推荐工具函数 ==========

def _find_knee_point(sorted_values: np.ndarray) -> float:
    """找到排序曲线的拐点（knee point）

    通过计算每个点到首尾连线的距离，取距离最大的点作为拐点。
    """
    if len(sorted_values) < 3:
        return float(sorted_values[-1]) if len(sorted_values) > 0 else 0.0

    first = np.array([0, sorted_values[0]])
    last = np.array([len(sorted_values) - 1, sorted_values[-1]])

    line_vec = last - first
    line_len = np.linalg.norm(line_vec)
    if line_len < 1e-10:
        return float(sorted_values[-1])

    max_dist = 0.0
    knee_idx = len(sorted_values) - 1

    for i in range(len(sorted_values)):
        point = np.array([i, sorted_values[i]])
        dist = abs(np.cross(line_vec, first - point)) / line_len
        if dist > max_dist:
            max_dist = dist
            knee_idx = i

    return float(sorted_values[knee_idx])


def _recommend_n_clusters(df: pd.DataFrame, numeric_cols: List[str]) -> Dict:
    """推荐聚类数：肘部法则+轮廓系数（以轮廓系数为主）

    尝试K=2到min(10, sqrt(行数))：
    - 肘部法则：计算每个K的SSE，用拐点检测找到推荐K
    - 轮廓系数：计算每个K的轮廓系数，取最高值对应的K
    最终推荐以轮廓系数结果为主，肘部法则作为辅助参考。
    """
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    data_scaled, _ = _prepare_numeric_data(df, numeric_cols)
    if data_scaled is None:
        return {"n_clusters": 3, "reason": "无数值列，使用默认K=3"}

    n_samples = len(data_scaled)
    if n_samples < 3:
        return {"n_clusters": 2, "reason": "数据量不足3行，使用K=2"}

    max_k = min(10, int(np.sqrt(n_samples)), n_samples - 1)
    if max_k < 2:
        return {"n_clusters": 2, "reason": "数据量过小，使用K=2"}

    k_range = list(range(2, max_k + 1))
    silhouette_list = []
    sse_list = []

    for k in k_range:
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = kmeans.fit_predict(data_scaled)
        sse_list.append(float(kmeans.inertia_))
        if len(set(labels)) > 1:
            # 样本数过多时采样计算轮廓系数，避免性能问题
            if n_samples > 5000:
                sample_idx = np.random.choice(n_samples, 5000, replace=False)
                silhouette_list.append(silhouette_score(data_scaled[sample_idx], labels[sample_idx]))
            else:
                silhouette_list.append(silhouette_score(data_scaled, labels))
        else:
            silhouette_list.append(-1)

    # 轮廓系数推荐K（主）
    best_k_idx = int(np.argmax(silhouette_list))
    best_k = k_range[best_k_idx]
    best_silhouette = silhouette_list[best_k_idx]

    # 肘部法则推荐K（辅）：在SSE曲线上找拐点
    # _find_knee_point 返回SSE值，需反查对应的K
    sse_array = np.array(sse_list)
    knee_sse = _find_knee_point(sse_array)
    # 找到SSE最接近拐点值的K
    elbow_k = k_range[int(np.argmin(np.abs(sse_array - knee_sse)))]
    elbow_k = int(elbow_k)

    reason = f"轮廓系数分析，K={best_k}时轮廓系数最高({best_silhouette:.4f})"
    if elbow_k != best_k:
        reason += f"；肘部法则推荐K={elbow_k}（辅助参考）"

    return {
        "n_clusters": int(best_k),
        "elbow_k": elbow_k,
        "silhouette_k": int(best_k),
        "silhouette_score": round(float(best_silhouette), 4),
        "reason": reason
    }


def _recommend_dbscan_params(df: pd.DataFrame, numeric_cols: List[str]) -> Dict:
    """推荐DBSCAN参数：k-距离图找eps，数据量决定min_samples"""
    from sklearn.neighbors import NearestNeighbors

    data_scaled, _ = _prepare_numeric_data(df, numeric_cols)
    if data_scaled is None:
        return {"eps": 0.5, "min_samples": 5, "reason": "无数值列，使用默认参数"}

    n_samples = len(data_scaled)
    n_features = data_scaled.shape[1]

    if n_samples < 5:
        return {"eps": 0.5, "min_samples": 2, "reason": f"数据量过少({n_samples}行)，使用保守参数"}

    if n_features == 1:
        std_val = float(np.std(data_scaled))
        eps = max(0.5, std_val * 1.5)
        # min_samples 至少为 2：=1 时每个点都是核心点，几乎全部聚为一簇，推荐参数失真
        min_samples = max(2, min(3, n_samples // 5))
        return {"eps": round(eps, 4), "min_samples": min_samples, "reason": f"单特征数据，eps基于标准差计算"}

    if n_samples < 100:
        min_samples = 3
    elif n_samples <= 1000:
        min_samples = 5
    else:
        min_samples = 10

    k = min(min_samples, n_samples - 1)
    try:
        nn = NearestNeighbors(n_neighbors=k)
        nn.fit(data_scaled)
        distances, _ = nn.kneighbors(data_scaled)
        k_distances = np.sort(distances[:, k - 1])

        eps = _find_knee_point(k_distances)
        if eps <= 0:
            eps = float(np.median(k_distances))
    except Exception:
        eps = float(np.median(data_scaled.std(axis=0))) * 2

    return {
        "eps": round(float(eps), 4),
        "min_samples": min_samples,
        "reason": f"k-距离图分析(k={k})，eps={eps:.4f}为拐点；min_samples={min_samples}（数据量{n_samples}行）"
    }


def _recommend_association_params(n_transactions: int) -> Dict:
    """推荐关联规则参数：根据数据量推荐min_support和min_confidence"""
    if n_transactions < 100:
        min_support = 0.2
        min_confidence = 0.8
        reason = f"数据量{n_transactions}行(<100)"
    elif n_transactions <= 1000:
        min_support = 0.1
        min_confidence = 0.7
        reason = f"数据量{n_transactions}行(100-1000)"
    else:
        min_support = 0.05
        min_confidence = 0.6
        reason = f"数据量{n_transactions}行(>1000)"

    return {
        "min_support": min_support,
        "min_confidence": min_confidence,
        "reason": reason
    }


def _recommend_sequence_params(n_sequences: int) -> Dict:
    """推荐序列模式参数：根据序列数推荐min_support"""
    if n_sequences < 50:
        min_support = 0.3
        reason = f"序列数{n_sequences}(<50)"
    elif n_sequences <= 500:
        min_support = 0.1
        reason = f"序列数{n_sequences}(50-500)"
    else:
        min_support = 0.05
        reason = f"序列数{n_sequences}(>500)"

    return {
        "min_support": min_support,
        "reason": reason
    }


# ========== 序列模式算法实现 ==========

def _project(sequences: List[List], prefix_item) -> List[List]:
    """PrefixSpan投影：找到prefix_item在每个序列中首次出现位置后的后缀"""
    projected = []
    for seq in sequences:
        for i, item in enumerate(seq):
            if item == prefix_item:
                projected.append(seq[i + 1:])
                break
    return projected


def _prefix_span_recursive(sequences: List[List], prefix: List, min_count: int,
                           n_sequences: int, max_len: int) -> List[Dict]:
    """PrefixSpan递归挖掘：在投影数据库中找频繁项并递归投影"""
    if not sequences or len(prefix) >= max_len:
        return []

    # 统计投影数据库中各项的支持度（每个序列中每项只算一次）
    freq_items = {}
    for seq in sequences:
        for item in set(seq):
            freq_items[item] = freq_items.get(item, 0) + 1
    freq_items = {k: v for k, v in freq_items.items() if v >= min_count}

    results = []
    for item in sorted(freq_items.keys()):
        new_prefix = prefix + [item]
        count = freq_items[item]
        results.append({"sequence": new_prefix, "support": round(count / n_sequences, 4)})
        # 递归：以new_prefix投影
        projected = _project(sequences, item)
        results.extend(_prefix_span_recursive(projected, new_prefix, min_count, n_sequences, max_len))

    return results


def _prefix_span(sequences: List[List], min_support: float, max_len: int = 10) -> List[Dict]:
    """PrefixSpan算法实现

    sequences: 事件序列列表（每个内部列表是一个事件序列）
    min_support: 最小支持度比例（0-1）
    """
    n_sequences = len(sequences)
    if n_sequences == 0:
        return []

    min_count = max(1, int(n_sequences * min_support))

    # 找所有频繁1-项
    freq_items = {}
    for seq in sequences:
        for item in set(seq):
            freq_items[item] = freq_items.get(item, 0) + 1
    freq_items = {k: v for k, v in freq_items.items() if v >= min_count}

    results = []
    for item in sorted(freq_items.keys()):
        count = freq_items[item]
        results.append({"sequence": [item], "support": round(count / n_sequences, 4)})
        projected = _project(sequences, item)
        results.extend(_prefix_span_recursive(projected, [item], min_count, n_sequences, max_len))

    return results


def _is_subsequence(candidate: List, sequence: List) -> bool:
    """检查candidate是否是sequence的子序列（保持顺序）"""
    it = iter(sequence)
    return all(item in it for item in candidate)


def _generate_candidates(prev_seqs: List[tuple], freq_items: List) -> List[tuple]:
    """GSP候选生成：将每个频繁(k-1)-序列与每个频繁1-项拼接成k-候选"""
    candidates = set()
    for seq in prev_seqs:
        for item in freq_items:
            new_seq = tuple(list(seq) + [item])
            candidates.add(new_seq)
    return list(candidates)


def _gsp(sequences: List[List], min_support: float, max_len: int = 10) -> List[Dict]:
    """GSP算法实现（逐层搜索）

    sequences: 事件序列列表
    min_support: 最小支持度比例（0-1）
    max_len: 最大序列长度，默认 10（由下方 while 循环的 k <= max_len 限制逐层深度）
    """
    n_sequences = len(sequences)
    if n_sequences == 0:
        return []

    min_count = max(1, int(n_sequences * min_support))

    # 第1层：频繁1-项
    item_counts = {}
    for seq in sequences:
        for item in set(seq):
            item_counts[item] = item_counts.get(item, 0) + 1
    freq_items = {k: v for k, v in item_counts.items() if v >= min_count}

    results = [{"sequence": [item], "support": round(count / n_sequences, 4)}
               for item, count in sorted(freq_items.items())]

    # 第k层：基于上一层生成候选，计数，筛选
    k = 2
    prev_seqs = [(item,) for item in freq_items]
    freq_items_list = list(freq_items.keys())

    while prev_seqs and k <= max_len:
        candidates = _generate_candidates(prev_seqs, freq_items_list)
        candidate_counts = {}
        for seq in sequences:
            for cand in candidates:
                if _is_subsequence(list(cand), seq):
                    candidate_counts[cand] = candidate_counts.get(cand, 0) + 1

        freq_k = {c: count for c, count in candidate_counts.items() if count >= min_count}
        results.extend([{"sequence": list(c), "support": round(count / n_sequences, 4)}
                        for c, count in sorted(freq_k.items())])
        prev_seqs = list(freq_k.keys())
        k += 1

    return results


# ========== 列检测工具函数 ==========

def _detect_datetime_columns(df: pd.DataFrame) -> List[str]:
    """检测datetime类型的列，包括可解析为时间的字符串列"""
    dt_cols = []
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            dt_cols.append(col)
        elif pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col]):
            # 对字符串列尝试转换，前100个非空值有超过80%能成功解析就算时间列
            non_null = df[col].dropna().head(100)
            if len(non_null) >= 3:
                try:
                    parsed = pd.to_datetime(non_null, errors='coerce')
                    success_rate = parsed.notna().sum() / len(non_null)
                    if success_rate >= 0.8:
                        dt_cols.append(col)
                except Exception:
                    pass
    return dt_cols


def _detect_id_columns(df: pd.DataFrame) -> List[str]:
    """检测ID列：列名包含id/user/transaction等关键词（不区分大小写）"""
    id_keywords = ["id", "user", "transaction", "session", "order"]
    id_cols = []
    for col in df.columns:
        col_lower = str(col).lower()
        if any(kw in col_lower for kw in id_keywords):
            id_cols.append(col)
    return id_cols


def _detect_sequence_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    """自动检测序列模式所需的三列：序列ID、时间、事件

    检测逻辑：
    - 时间列：datetime类型列或可解析为时间的字符串列
    - 序列ID列：列名包含id/user/transaction等关键词（基于关键词，可能检测不到，需用户手动选择）
    - 事件列：第一个非数值、非时间、非ID的类别列

    注意：序列ID列检测依赖列名关键词，命中率较低，通常需要用户手动指定。
    """
    dt_cols = _detect_datetime_columns(df)
    id_cols = _detect_id_columns(df)
    numeric_cols = get_numeric_columns(df)

    time_col = dt_cols[0] if dt_cols else None
    seq_id_col = id_cols[0] if id_cols else None

    # 事件列：非数值、非时间、非ID的第一个类别列
    event_col = None
    for col in df.columns:
        if col in numeric_cols or col in dt_cols or col in id_cols:
            continue
        event_col = col
        break

    return {
        "seq_id_column": seq_id_col,
        "time_column": time_col,
        "event_column": event_col
    }


def _validate_cluster_params(df: pd.DataFrame, columns: List[str]) -> List[str]:
    """校验聚类参数，返回数值列列表或抛出错误"""
    if not columns:
        raise HTTPException(status_code=400, detail="请选择至少一列特征列")
    
    # 检查列是否存在
    missing_cols = [c for c in columns if c not in df.columns]
    if missing_cols:
        raise HTTPException(status_code=400, detail=f"列不存在: {', '.join(missing_cols)}")
    
    # 检查是否为数值列
    numeric_cols = get_numeric_columns(df)
    non_numeric = [c for c in columns if c not in numeric_cols]
    if non_numeric:
        raise HTTPException(
            status_code=400,
            detail=f"聚类分析需要数值列，以下列不是数值类型: {', '.join(non_numeric)}。"
                   f"可选数值列: {', '.join(numeric_cols) if numeric_cols else '无'}"
        )
    
    if len(df) < 3:
        raise HTTPException(status_code=400, detail="数据行数不足，至少需要3行进行聚类")
    
    return [c for c in columns if c in numeric_cols]


def _validate_association_params(df: pd.DataFrame, data_format: str, tid_column: Optional[str], item_column: Optional[str]) -> None:
    """校验关联规则参数
    data_format: basket（购物篮格式，需要tid和item列）/ binary（自动二值化，不需要选列）
    """
    if data_format == "basket":
        # 购物篮格式：必须有事务列和项列
        if not tid_column:
            raise HTTPException(status_code=400, detail="请选择事务标识列")
        if not item_column:
            raise HTTPException(status_code=400, detail="请选择项列")
        
        # 检查列是否存在
        missing_cols = []
        if tid_column not in df.columns:
            missing_cols.append(tid_column)
        if item_column not in df.columns:
            missing_cols.append(item_column)
        if missing_cols:
            raise HTTPException(status_code=400, detail=f"列不存在: {', '.join(missing_cols)}")
        
        if tid_column == item_column:
            raise HTTPException(status_code=400, detail="事务标识列和项列不能是同一列")
    
    if len(df) < 2:
        raise HTTPException(status_code=400, detail="数据行数不足，至少需要2行进行关联规则挖掘")


def _validate_sequence_params(df: pd.DataFrame, seq_id_column: str, time_column: str, event_column: str) -> None:
    """校验序列模式参数"""
    if not seq_id_column:
        raise HTTPException(status_code=400, detail="请选择序列ID列")
    if not time_column:
        raise HTTPException(status_code=400, detail="请选择时间列")
    if not event_column:
        raise HTTPException(status_code=400, detail="请选择事件列")
    
    # 检查列是否存在
    missing_cols = []
    if seq_id_column not in df.columns:
        missing_cols.append(seq_id_column)
    if time_column not in df.columns:
        missing_cols.append(time_column)
    if event_column not in df.columns:
        missing_cols.append(event_column)
    if missing_cols:
        raise HTTPException(status_code=400, detail=f"列不存在: {', '.join(missing_cols)}")
    
    # 检查时间列是否可排序
    try:
        pd.to_datetime(df[time_column], errors='raise')
    except Exception:
        # 不是datetime格式，但只要可排序即可，给出警告而非错误
        pass
    
    if len(df) < 2:
        raise HTTPException(status_code=400, detail="数据行数不足，至少需要2行进行序列模式挖掘")


# ========== API 端点 ==========

@router.get("/raw-data", response_model=list[DatasetResponse])
async def get_mining_raw_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取数据挖掘模块专用的原始数据列表（仅返回 module_source=data_mining 且 artifact_type=raw_data 的数据）"""
    datasets = db.query(Dataset).filter(
        Dataset.module_source == "data_mining",
        Dataset.artifact_type == "raw_data",
        Dataset.user_id == current_user.id,
        Dataset.status == "active"
    ).all()
    return datasets


@router.post("/upload", response_model=DatasetResponse)
async def mining_upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """上传文件到数据挖掘模块，artifact_type=raw_data, module_source=data_mining"""
    import time as _time
    start_time = _time.time()
    validate_upload_file(file)

    name = clean_dataset_name(file.filename)

    # 埋点：创建上传任务记录
    task_record = create_task_record(
        db=db,
        task_type="upload",
        user_id=current_user.id,
        params={"filename": name, "module_source": "data_mining", "artifact_type": "raw_data"}
    )

    content = await file.read()

    object_name = f"uploads/user_{current_user.id}/{name}"
    file_path = storage_manager.save_bytes(object_name, content)

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

    file_size = len(content)
    new_dataset = Dataset(
        name=name,
        file_path=file_path,
        file_size=file_size,
        schema=schema,
        row_count=row_count,
        data_preview=str(data_preview[:5]),
        module_source="data_mining",
        module_label=MODULE_LABEL_MAP.get("data_mining", "数据挖掘"),
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


@router.post("/precheck")
async def precheck_data(
    body: PrecheckRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """预检数据并推荐算法（支持本地数据集和远程数据库）"""
    dataset_id = body.dataset_id
    remote_config = body.remote

    if not dataset_id and not (remote_config and remote_config.get("use_remote")):
        raise HTTPException(status_code=400, detail="缺少 dataset_id 或 remote 参数")

    # 统一数据加载（本地数据集或远程数据库）
    data_service = DataService(db)
    try:
        df, dataset = data_service.load_module_data(
            dataset_id=dataset_id,
            remote_config=remote_config,
            user_id=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    is_remote = remote_config and remote_config.get("use_remote")

    # 本地数据集模式：验证来源
    if not is_remote and dataset:
        if dataset.module_source != "data_mining" or dataset.artifact_type != "raw_data":
            raise HTTPException(status_code=403, detail="只能使用数据挖掘模块的原始数据")

    row_count = len(df)
    col_count = len(df.columns)

    # 数值列
    numeric_cols = get_numeric_columns(df)
    numeric_count = len(numeric_cols)

    # 时间列
    dt_cols = _detect_datetime_columns(df)
    has_datetime = len(dt_cols) > 0

    # ID列
    id_cols = _detect_id_columns(df)
    has_id_column = len(id_cols) > 0

    # 类别列：非数值、非时间的列
    categorical_cols = [c for c in df.columns
                        if c not in numeric_cols and c not in dt_cols]
    categorical_count = len(categorical_cols)

    # 缺失值统计
    missing_count = int(df.isna().sum().sum())
    total_cells = row_count * col_count
    missing_percentage = round(missing_count / total_cells * 100, 2) if total_cells > 0 else 0.0

    # 唯一值统计
    unique_stats = {}
    for col in df.columns:
        unique_stats[col] = int(df[col].nunique())

    # 异常值比例（IQR方法，仅数值列）
    outlier_cells = 0
    checked_cells = 0
    for col in numeric_cols:
        col_data = to_numeric_if_possible(df[col]).dropna()
        if len(col_data) == 0:
            continue
        q1 = col_data.quantile(0.25)
        q3 = col_data.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            checked_cells += len(col_data)
            continue
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        outliers = int(((col_data < lower) | (col_data > upper)).sum())
        outlier_cells += outliers
        checked_cells += len(col_data)
    outlier_percentage = round(outlier_cells / checked_cells * 100, 2) if checked_cells > 0 else 0.0

    # 预检结果
    errors = []
    warnings = []
    info = []

    # 阻断性错误：与 _execute_cluster 的最小样本数（3）保持一致
    if row_count < 3:
        errors.append({
            "code": "TOO_FEW_ROWS",
            "message": f"数据仅{row_count}行，聚类/关联规则分析至少需要3行",
            "level": "error"
        })
    if numeric_count < 1:
        errors.append({
            "code": "NO_NUMERIC_COLUMNS",
            "message": "数据集中无数值列，无法进行聚类分析",
            "level": "error"
        })

    # 警告
    if missing_percentage > 30:
        warnings.append({
            "code": "HIGH_MISSING",
            "message": f"缺失值比例{missing_percentage}%较高，可能影响分析结果",
            "level": "warning"
        })
    if outlier_percentage > 10:
        warnings.append({
            "code": "HIGH_OUTLIERS",
            "message": f"异常值比例{outlier_percentage}%较高，建议预处理",
            "level": "warning"
        })
    if col_count > 50:
        warnings.append({
            "code": "HIGH_DIMENSIONAL",
            "message": f"列数{col_count}较多，可能影响性能",
            "level": "warning"
        })
    # 关联规则相关警告：类别列唯一值过多
    for col in categorical_cols:
        if unique_stats.get(col, 0) > 100:
            warnings.append({
                "code": "HIGH_CARDINALITY",
                "message": f"类别列'{col}'唯一值{unique_stats[col]}个过多，关联规则可能产生大量项集",
                "level": "warning"
            })
            break

    # 提示信息
    if row_count > 10000:
        if is_remote:
            # 远程模式强制同步执行，不提示"将自动异步"（避免误导用户）
            info.append({
                "code": "LARGE_DATASET",
                "message": f"数据量超过1万行，远程模式将同步执行，大表处理可能耗时较长",
                "level": "info"
            })
        else:
            info.append({
                "code": "LARGE_DATASET",
                "message": "数据量超过1万行，将自动异步处理（可在右上角任务面板查看进度）",
                "level": "info"
            })

    # 算法推荐（包含具体算法的推荐状态）
    recommendations = {}

    # 聚类推荐：为每个具体算法添加推荐状态
    cluster_algo_details = []
    if numeric_count >= 2 and row_count >= 5:
        # KMeans：始终推荐，适用于大多数数据
        cluster_algo_details.append({
            "name": "kmeans",
            "display_name": "KMeans",
            "recommended": True,
            "reason": "经典聚类算法，适用性广"
        })
        # 层次聚类：数据量适中时推荐
        if row_count <= 2000:
            cluster_algo_details.append({
                "name": "hierarchical",
                "display_name": "层次聚类",
                "recommended": True,
                "reason": "数据量适中，层次结构清晰"
            })
        else:
            cluster_algo_details.append({
                "name": "hierarchical",
                "display_name": "层次聚类",
                "recommended": False,
                "reason": "数据量较大，层次聚类性能较差"
            })
        # DBSCAN：数据量较大或密度不均匀时推荐
        if row_count >= 50 or numeric_count >= 3:
            cluster_algo_details.append({
                "name": "dbscan",
                "display_name": "DBSCAN",
                "recommended": True,
                "reason": "适用于发现任意形状的簇"
            })
        else:
            cluster_algo_details.append({
                "name": "dbscan",
                "display_name": "DBSCAN",
                "recommended": False,
                "reason": "数据量较小或维度单一，DBSCAN效果可能不佳"
            })
    recommendations["cluster"] = {
        "recommended": len([a for a in cluster_algo_details if a["recommended"]]) > 0,
        "can_execute": numeric_count >= 1 and row_count >= 3,
        "block_reason": "" if (numeric_count >= 1 and row_count >= 3) else (
            "无数值列，无法进行聚类" if numeric_count < 1 else
            "数据行数不足，至少需要3行"
        ),
        "algorithms": [a["name"] for a in cluster_algo_details],
        "algorithm_details": cluster_algo_details,
        "reason": f"{numeric_count}个数值列，数据量{row_count}行，适合聚类分析" if cluster_algo_details else "数值列不足或数据量过小，不适合聚类分析"
    }

    # 关联规则推荐
    assoc_algo_details = []
    # 只要有至少1个类别列且行数足够，就可以做关联规则
    # 购物篮格式需要1个类别列（商品项）+ 1个事务ID列，自动二值化不需要选列
    if categorical_count >= 1 and row_count >= 5:
        assoc_algo_details.append({
            "name": "apriori",
            "display_name": "Apriori",
            "recommended": True,
            "reason": "经典关联规则算法，易于理解"
        })
        assoc_algo_details.append({
            "name": "fpgrowth",
            "display_name": "FP-Growth",
            "recommended": True,
            "reason": "数据量较大时效率更高" if row_count >= 500 else "高效的频繁模式增长算法"
        })
    recommendations["association"] = {
        "recommended": len([a for a in assoc_algo_details if a["recommended"]]) > 0,
        "can_execute": row_count >= 2 and len(df.columns) >= 1,
        "block_reason": "" if (row_count >= 2 and len(df.columns) >= 1) else (
            "无有效列，无法进行关联规则挖掘" if len(df.columns) < 1 else
            "数据行数不足，至少需要2行"
        ),
        "algorithms": [a["name"] for a in assoc_algo_details],
        "algorithm_details": assoc_algo_details,
        "reason": f"检测到{categorical_count}个类别列，适合关联规则挖掘（建议使用购物篮格式）" if assoc_algo_details else "类别列不足，不适合关联规则挖掘"
    }

    # 序列模式推荐：只需检测到时间列即可推荐，具体ID列和事件列由用户选择
    seq_algo_details = []
    if has_datetime and row_count >= 5:
        seq_algo_details.append({
            "name": "prefixspan",
            "display_name": "PrefixSpan",
            "recommended": True,
            "reason": "高效的序列模式挖掘算法"
        })
        seq_algo_details.append({
            "name": "gsp",
            "display_name": "GSP",
            "recommended": True,
            "reason": "经典的逐层搜索算法，结果稳定、易于理解"
        })
    # 序列模式可执行条件：检测到时间列 + 有可作为事件列的类别列 + 行数>=2
    has_event_candidate = categorical_count > 0
    recommendations["sequence"] = {
        "recommended": len([a for a in seq_algo_details if a["recommended"]]) > 0,
        "can_execute": has_datetime and has_event_candidate and row_count >= 2,
        "block_reason": "" if (has_datetime and has_event_candidate and row_count >= 2) else (
            "未检测到时间列，无法进行序列模式挖掘" if not has_datetime else
            "未检测到可作为事件列的类别列" if not has_event_candidate else
            "数据行数不足，至少需要2行"
        ),
        "algorithms": [a["name"] for a in seq_algo_details],
        "algorithm_details": seq_algo_details,
        "reason": "检测到时间列，可进行序列模式挖掘，请选择序列ID列和事件列" if seq_algo_details else "未检测到时间列，不适合序列模式挖掘"
    }

    return {
        "data_profile": {
            "row_count": row_count,
            "col_count": col_count,
            "numeric_columns": numeric_cols,
            "numeric_count": numeric_count,
            "categorical_columns": categorical_cols,
            "categorical_count": categorical_count,
            "missing_count": missing_count,
            "missing_percentage": missing_percentage,
            "has_datetime": has_datetime,
            "datetime_columns": dt_cols,
            "has_id_column": has_id_column,
            "id_columns": id_cols,
            "unique_stats": unique_stats
        },
        "checks": {
            "errors": errors,
            "warnings": warnings,
            "info": info
        },
        "recommendations": recommendations
    }


@router.post("/recommend-params")
async def recommend_params(
    body: RecommendParamsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """根据算法类型推荐参数（支持本地数据集和远程数据库）"""
    dataset_id = body.dataset_id
    remote_config = body.remote

    if not dataset_id and not (remote_config and remote_config.get("use_remote")):
        raise HTTPException(status_code=400, detail="缺少 dataset_id 或 remote 参数")

    # 统一数据加载（本地数据集或远程数据库）
    data_service = DataService(db)
    try:
        df, dataset = data_service.load_module_data(
            dataset_id=dataset_id,
            remote_config=remote_config,
            user_id=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    is_remote = remote_config and remote_config.get("use_remote")

    # 本地数据集模式：验证来源
    if not is_remote and dataset:
        if dataset.module_source != "data_mining" or dataset.artifact_type != "raw_data":
            raise HTTPException(status_code=403, detail="只能使用数据挖掘模块的原始数据")

    algorithm_type = body.algorithm_type
    # algorithm为None时取默认算法
    algorithm = body.algorithm
    if algorithm is None:
        algorithm = {"cluster": "kmeans", "association": "apriori", "sequence": "prefixspan"}.get(algorithm_type)

    if algorithm_type == "cluster":
        all_numeric_cols = get_numeric_columns(df)
        # 优先使用用户传入的列，过滤非数值列；未传则使用全部数值列
        if body.columns and len(body.columns) > 0:
            numeric_cols = [c for c in body.columns if c in all_numeric_cols]
            if len(numeric_cols) == 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"所选特征列中无数值列，可选数值列: {', '.join(all_numeric_cols)}"
                )
        else:
            numeric_cols = all_numeric_cols

        if algorithm == "kmeans":
            rec = _recommend_n_clusters(df, numeric_cols)
            return {
                "algorithm_type": "cluster",
                "algorithm": "kmeans",
                "recommended_params": rec,
                "columns_used": numeric_cols,
                "param_ranges": {
                    "n_clusters": {"min": 2, "max": 10, "default": 3},
                    "init": {"options": ["k-means++", "random"], "default": "k-means++"},
                    "max_iter": {"min": 100, "max": 1000, "default": 300},
                    "n_init": {"min": 1, "max": 50, "default": 10}
                }
            }
        elif algorithm == "dbscan":
            rec = _recommend_dbscan_params(df, numeric_cols)
            return {
                "algorithm_type": "cluster",
                "algorithm": "dbscan",
                "recommended_params": rec,
                "columns_used": numeric_cols,
                "param_ranges": {
                    "eps": {"min": 0.01, "max": 10.0, "default": 0.5},
                    "min_samples": {"min": 1, "max": 50, "default": 5},
                    "metric": {"options": ["euclidean", "manhattan", "cosine"], "default": "euclidean"}
                }
            }
        elif algorithm == "hierarchical":
            rec = _recommend_n_clusters(df, numeric_cols)
            return {
                "algorithm_type": "cluster",
                "algorithm": "hierarchical",
                "recommended_params": rec,
                "columns_used": numeric_cols,
                "param_ranges": {
                    "n_clusters": {"min": 2, "max": 10, "default": 3},
                    "linkage": {"options": ["ward", "complete", "average", "single"], "default": "ward"}
                }
            }
        else:
            raise HTTPException(status_code=400, detail=f"不支持的聚类算法: {algorithm}")

    elif algorithm_type == "association":
        # 交易数：本接口未接收 format/tid_column（前端推荐请求不传），无法区分购物篮格式，
        # 按行数估算；实际执行时 _execute_association 会按唯一 tid 数准确计算
        n_transactions = len(df)
        rec = _recommend_association_params(n_transactions)
        return {
            "algorithm_type": "association",
            "algorithm": algorithm or "apriori",
            "recommended_params": rec,
            "param_ranges": {
                "min_support": {"min": 0.01, "max": 1.0, "default": 0.1},
                "min_confidence": {"min": 0.1, "max": 1.0, "default": 0.7},
                "min_lift": {"min": 0.0, "max": 10.0, "default": 1.0},
                "max_len": {"min": 1, "max": 10, "default": None}
            }
        }

    elif algorithm_type == "sequence":
        detected = _detect_sequence_columns(df)
        seq_id_col = detected["seq_id_column"]
        if seq_id_col:
            n_sequences = df[seq_id_col].nunique()
        else:
            n_sequences = len(df)
        rec = _recommend_sequence_params(n_sequences)
        return {
            "algorithm_type": "sequence",
            "algorithm": algorithm or "prefixspan",
            "recommended_params": rec,
            "param_ranges": {
                "min_support": {"min": 0.01, "max": 1.0, "default": 0.1},
                "max_len": {"min": 1, "max": 20, "default": 10}
            }
        }

    else:
        raise HTTPException(status_code=400, detail=f"不支持的算法类型: {algorithm_type}")


@task_manager.register_task
def _execute_cluster(task_record_id: int, user_id: int, dataset_id: int, config: dict,
                     df=None, is_remote: bool = False, remote_config: dict = None):
    """聚类分析核心执行函数（同步/异步共用入口）

    通过 SessionLocal 创建独立 db 会话：
    - 同步调用时与 FastAPI 的 db 隔离，避免长事务占用请求连接
    - 异步调用时（Celery Worker 进程）必须新建 session，因为无法访问 FastAPI 请求上下文

    4阶段进度上报到 task_records.result_summary：
    - 数据加载与预处理(20%)：加载数据集、参数校验、数值数据准备
    - 聚类分析中(50%)：执行聚类算法、计算轮廓系数
    - 结果汇总与质量评估(80%)：生成聚类报告与质量评估
    - 保存结果(100%)：保存聚类结果到 MinIO + 数据库

    Args:
        task_record_id: 任务记录ID（入口已创建）
        user_id: 用户ID
        dataset_id: 数据集ID（远程模式下可为 None）
        config: ClusterRequest 的 dict 表示，包含 algorithm/columns/save/auto_params 等参数
        df: 预加载的 DataFrame（远程模式下由调用方传入）
        is_remote: 是否为远程数据源
        remote_config: 远程数据源配置

    Returns:
        聚类结果字典（与原同步接口返回结构保持一致）
    """
    from sklearn.cluster import KMeans, DBSCAN, AgglomerativeClustering
    from sklearn.metrics import silhouette_score

    # Celery Worker 是独立进程，必须新建 db 会话，不能复用 FastAPI 请求作用域的 db
    db = SessionLocal()
    start_time = time.time()

    try:
        # ===== 阶段1：数据加载与预处理（20%） =====
        update_task_progress(db, task_record_id, "数据加载与预处理", 20, "正在加载数据")

        # 从 config 提取参数（config 是原 ClusterRequest 的 dict 表示）
        algorithm = config.get("algorithm", "kmeans").lower()
        columns = config.get("columns")
        save = config.get("save", False)
        auto_params = config.get("auto_params", True)
        # KMeans 参数
        n_clusters_cfg = config.get("n_clusters")
        init = config.get("init", "k-means++")
        max_iter = config.get("max_iter", 300)
        n_init = config.get("n_init", 10)
        # DBSCAN 参数
        eps_cfg = config.get("eps")
        min_samples_cfg = config.get("min_samples")
        metric = config.get("metric", "euclidean")
        # 层次聚类参数
        linkage = config.get("linkage", "ward")

        # 获取数据集（远程模式下 df 已由调用方预加载）
        if df is None:
            original_dataset = db.query(Dataset).filter(
                Dataset.id == dataset_id, Dataset.user_id == user_id, Dataset.status == "active"
            ).first()
            if not original_dataset:
                raise ValueError(f"数据集 {dataset_id} 不存在")

            data_service = DataService(db)
            df = data_service.load_dataset(dataset_id)
        else:
            original_dataset = None
            data_service = DataService(db)

        # 聚类需要至少3个样本，否则无法形成有效簇
        if len(df) < 3:
            raise HTTPException(status_code=400, detail="聚类分析需要至少3个样本")

        # 参数校验
        numeric_cols = _validate_cluster_params(df, columns)

        # 准备数值数据
        data_scaled, _ = _prepare_numeric_data(df, columns)
        if data_scaled is None or len(numeric_cols) == 0:
            raise HTTPException(status_code=400, detail="数据集中没有数值列可用于聚类")

        # ===== 阶段2：聚类分析中（50%） =====
        update_task_progress(db, task_record_id, "聚类分析中", 50, f"正在执行 {algorithm} 聚类")

        recommended_params = {}
        params_used = {}

        # 根据算法执行聚类
        if algorithm == "kmeans":
            # 参数推荐
            rec = _recommend_n_clusters(df, numeric_cols)
            recommended_params = rec

            # 确定实际使用的n_clusters
            if auto_params or n_clusters_cfg is None:
                n_clusters = rec["n_clusters"]
            else:
                n_clusters = n_clusters_cfg

            if n_clusters >= len(df):
                n_clusters = max(2, len(df) - 1)

            params_used = {
                "n_clusters": n_clusters,
                "init": init,
                "max_iter": max_iter,
                "n_init": n_init
            }

            kmeans = KMeans(
                n_clusters=n_clusters,
                init=init,
                max_iter=max_iter,
                n_init=n_init,
                random_state=42
            )
            cluster_labels = kmeans.fit_predict(data_scaled)

            # 轮廓系数：簇数>1且簇数<样本数时计算
            n_unique = len(set(cluster_labels))
            if 1 < n_unique < len(data_scaled):
                silhouette = float(silhouette_score(data_scaled, cluster_labels))
            else:
                silhouette = None

            noise_count = 0
            noise_percentage = 0.0

        elif algorithm == "dbscan":
            # 参数推荐
            rec = _recommend_dbscan_params(df, numeric_cols)
            recommended_params = rec

            # 确定实际使用的参数
            if auto_params or eps_cfg is None:
                eps = rec["eps"]
            else:
                eps = eps_cfg
            if auto_params or min_samples_cfg is None:
                min_samples = rec["min_samples"]
            else:
                min_samples = min_samples_cfg

            params_used = {
                "eps": eps,
                "min_samples": min_samples,
                "metric": metric
            }

            dbscan = DBSCAN(
                eps=eps,
                min_samples=min_samples,
                metric=metric
            )
            cluster_labels = dbscan.fit_predict(data_scaled)

            # DBSCAN不计算轮廓系数（可能有噪声点）
            silhouette = None

            # 噪声点统计
            noise_count = int((cluster_labels == -1).sum())
            noise_percentage = round(noise_count / len(cluster_labels) * 100, 2) if len(cluster_labels) > 0 else 0.0

        elif algorithm == "hierarchical":
            # 参数推荐
            rec = _recommend_n_clusters(df, numeric_cols)
            recommended_params = rec

            # 确定实际使用的n_clusters
            if auto_params or n_clusters_cfg is None:
                n_clusters = rec["n_clusters"]
            else:
                n_clusters = n_clusters_cfg

            if n_clusters >= len(df):
                n_clusters = max(2, len(df) - 1)

            params_used = {
                "n_clusters": n_clusters,
                "linkage": linkage
            }

            # ward linkage要求欧式距离
            agg = AgglomerativeClustering(
                n_clusters=n_clusters,
                linkage=linkage
            )
            cluster_labels = agg.fit_predict(data_scaled)

            # 轮廓系数
            n_unique = len(set(cluster_labels))
            if 1 < n_unique < len(data_scaled):
                silhouette = float(silhouette_score(data_scaled, cluster_labels))
            else:
                silhouette = None

            noise_count = 0
            noise_percentage = 0.0

        else:
            raise HTTPException(status_code=400, detail=f"不支持的聚类算法: {algorithm}")

        # 将聚类结果添加到原数据
        result_df = df.copy()
        result_df['cluster'] = cluster_labels

        # PCA降维数据
        projection_2d = _compute_pca_2d(data_scaled, cluster_labels)

        # 簇统计
        n_clusters_actual = len(set(cluster_labels.tolist()) - {-1})
        cluster_stats = []
        unique_labels = sorted(set(cluster_labels.tolist()))
        for label in unique_labels:
            count = int((cluster_labels == label).sum())
            cluster_stats.append({
                "cluster": int(label),
                "count": count,
                "percentage": round(count / len(cluster_labels) * 100, 2) if len(cluster_labels) > 0 else 0.0
            })

        new_dataset = None
        result_path = None
        result_name = None

        # ===== 阶段3：结果汇总与质量评估（80%） =====
        update_task_progress(db, task_record_id, "结果汇总与质量评估", 80, "正在生成聚类报告与质量评估")

        # ===== 阶段4：保存结果（100%） =====
        update_task_progress(db, task_record_id, "保存结果", 100, "正在保存聚类结果")

        if save:
            # 保存结果CSV到MinIO
            # 命名方案：产物保留源名（去原扩展名 + 真实内容后缀 .csv），不拼算法/时间戳，靠 #id/颜色区分
            if is_remote:
                source_name = (remote_config or {}).get("table_name", "remote_table")
                result_name = build_product_name(source_name, "csv")
            else:
                result_name = build_product_name(original_dataset.name, "csv")
            csv_buffer = io.StringIO()
            result_df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
            csv_content = csv_buffer.getvalue().encode('utf-8')

            object_name = f"data_mining/user_{user_id}/{result_name}"
            result_path = storage_manager.save_bytes(object_name, csv_content)

            # 创建Dataset记录
            file_size = len(csv_content)
            schema = data_service.get_schema(result_df)
            silhouette_text = f"{round(silhouette, 4)}" if silhouette is not None else "-"
            if algorithm == "dbscan":
                algo_text = f"DBSCAN聚类 | eps={eps} | min_samples={min_samples} | 簇数={n_clusters_actual} | 噪声占比={noise_percentage}%"
            else:
                algo_text = f"{algorithm}聚类 | 簇数={n_clusters_actual} | 轮廓系数={silhouette_text}"

            if is_remote:
                parent_id = None
                root_id = None
            else:
                parent_id = original_dataset.id
                root_id = get_root_dataset_id(db, original_dataset)
            # 复用已有 report_content 字段保存聚类统计报告，便于 AI 对话上下文直接读取，无需改表结构
            cluster_report = {
                "algorithm": algorithm,
                "n_clusters": n_clusters_actual,
                "silhouette": round(silhouette, 4) if silhouette is not None else None,
                "noise_count": noise_count,
                "noise_percentage": noise_percentage,
                "cluster_stats": cluster_stats,
                "params_used": params_used,
                "recommended_params": recommended_params,
                "columns": columns
            }
            new_dataset = Dataset(
                name=result_name,
                file_path=result_path,
                file_size=file_size,
                schema=schema,
                row_count=len(result_df),
                data_preview=str(result_df.head(5).to_dict()),
                module_source="data_mining",
                module_label=MODULE_LABEL_MAP.get("data_mining", "数据挖掘"),
                artifact_type="cluster_result",
                algorithm=algo_text,
                parent_id=parent_id,
                root_dataset_id=root_id,
                user_id=user_id,
                report_content=json.dumps(cluster_report, ensure_ascii=False),
                # 远程来源血缘字段
                connection_id=(remote_config or {}).get("connection_id") if is_remote else None,
                table_name=(remote_config or {}).get("table_name") if is_remote else None,
                root_connection_id=(remote_config or {}).get("connection_id") if is_remote else None,
                source_type="derived" if is_remote else None
            )
            db.add(new_dataset)
            db.commit()
            db.refresh(new_dataset)

            clear_user_dataset_cache(user_id)

        # 质量评估（在更新任务记录前计算，便于写入 result_summary 供异步轮询前端提取）
        quality_assessment = []
        if silhouette is not None and silhouette < 0.3:
            quality_assessment.append({
                "level": "warning",
                "code": "LOW_SILHOUETTE",
                "message": f"轮廓系数{silhouette:.4f}较低（<0.3），聚类质量可能不佳，建议调整参数或尝试其他算法"
            })
        if noise_percentage > 50:
            quality_assessment.append({
                "level": "warning",
                "code": "HIGH_NOISE",
                "message": f"噪声点占比{noise_percentage}%较高（>50%），建议调整邻域半径或最小样本数参数"
            })
        if n_clusters_actual == 1:
            quality_assessment.append({
                "level": "warning",
                "code": "SINGLE_CLUSTER",
                "message": "所有样本被归为同一簇，聚类效果不明显"
            })

        # 构建完整的 cluster_report（与同步返回一致，异步路径下写入 result_summary 供前端轮询提取）
        cluster_report = {
            "algorithm": algorithm,
            "n_clusters": n_clusters_actual,
            "silhouette_score": round(silhouette, 4) if silhouette is not None else None,
            "features_used": numeric_cols,
            "cluster_stats": cluster_stats,
            "noise_count": noise_count,
            "noise_percentage": noise_percentage,
            "params_used": params_used,
            "recommended_params": recommended_params,
            "auto_params": auto_params,
            "projection_2d": projection_2d,
            "preview_data": _get_data_preview(result_df),
            "quality_assessment": quality_assessment
        }

        # 更新任务记录为成功
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db,
            record_id=task_record_id,
            status="success",
            dataset_id=new_dataset.id if new_dataset else None,
            result_summary={
                "operation": "save_cluster" if save else "cluster",
                "new_dataset_id": new_dataset.id if new_dataset else None,
                "new_dataset_name": result_name,
                "saved": save,
                "dataset_id": new_dataset.id if new_dataset else None,
                "cluster_report": cluster_report,
                # 保留摘要字段（操作历史列表展示用）
                "algorithm": algorithm,
                "n_clusters": n_clusters_actual,
                "silhouette_score": round(silhouette, 4) if silhouette is not None else None,
                "noise_count": noise_count,
                "noise_percentage": noise_percentage,
                "params_used": params_used,
                "recommended_params": recommended_params
            },
            execution_time=execution_time
        )

        return {
            "dataset_id": new_dataset.id if new_dataset else None,
            "file_path": result_path,
            "saved": save,
            "cluster_report": cluster_report
        }

    except HTTPException as he:
        # 参数/数据校验失败：_validate_* 抛出的 HTTPException 内部未更新 task_record，此处统一更新
        # 内部主动抛出的 HTTPException 同样由此处统一处理，error_message 使用 HTTPException.detail 保持准确
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db, record_id=task_record_id, status="failed",
            error_message=str(he.detail) if he.detail else "参数校验失败",
            execution_time=execution_time, failure_category="param_error"
        )
        raise
    except SoftTimeLimitExceeded:
        # 软超时：Celery soft_time_limit 触发，需在硬超时前更新数据库状态
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db, record_id=task_record_id, status="failed",
            error_message=f"聚类分析任务超时（超过 {settings.CELERY_TASK_SOFT_TIME_LIMIT} 秒），已自动终止",
            execution_time=execution_time,
            failure_category="timeout"
        )
        raise
    except Exception as e:
        # 未预期的系统异常（数据加载失败、算法执行异常、文件保存失败等）
        import traceback
        traceback.print_exc()
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db, record_id=task_record_id, status="failed",
            error_message=f"聚类分析失败: {str(e)}",
            execution_time=execution_time,
            failure_category=classify_failure(e)
        )
        raise
    finally:
        # Celery Worker 是独立进程，必须显式关闭 db 会话，避免连接泄漏
        db.close()


@router.post("/cluster")
async def cluster_analysis(
    body: ClusterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """聚类分析接口：支持KMeans、DBSCAN、层次聚类（支持本地数据集和远程数据库）

    智能异步：≥1万行异步提交（Celery 不可用且≥1万行报503不降级），<1万行同步执行
    远程模式：强制同步执行
    """
    dataset_id = body.dataset_id
    remote_config = body.remote

    if not dataset_id and not (remote_config and remote_config.get("use_remote")):
        raise HTTPException(status_code=400, detail="缺少 dataset_id 或 remote 参数")

    # 统一数据加载（本地数据集或远程数据库）—— 用于获取数据集信息和行数判断
    data_service = DataService(db)
    try:
        df, dataset = data_service.load_module_data(
            dataset_id=dataset_id,
            remote_config=remote_config,
            user_id=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    is_remote = remote_config and remote_config.get("use_remote")

    # 本地数据集模式：验证来源
    if not is_remote and dataset:
        if dataset.module_source != "data_mining" or dataset.artifact_type != "raw_data":
            raise HTTPException(status_code=403, detail="只能使用数据挖掘模块的原始数据")

    # 获取数据集名称（用于任务记录）
    if is_remote:
        dataset_name = remote_config.get("table_name", "远程表")
    else:
        dataset_name = dataset.name

    # 确定行数
    row_count = len(df) if is_remote else (dataset.row_count or 0)

    # 创建任务记录
    # 根据 body.save 区分执行分析/保存到数据管理，用于操作历史 operation_label 展示
    start_time = time.time()
    cluster_advanced_params = {}
    if body.algorithm == "kmeans":
        cluster_advanced_params = {
            "n_clusters": body.n_clusters,
            "init": body.init,
            "max_iter": body.max_iter,
            "n_init": body.n_init,
        }
    elif body.algorithm == "dbscan":
        cluster_advanced_params = {
            "eps": body.eps,
            "min_samples": body.min_samples,
            "metric": body.metric,
        }
    elif body.algorithm == "hierarchical":
        cluster_advanced_params = {
            "n_clusters": body.n_clusters,
            "linkage": body.linkage,
        }

    task_record = create_task_record(
        db=db,
        task_type="data_mining",
        user_id=current_user.id,
        dataset_id=dataset_id,  # 远程模式下为 None
        params={
            "dataset_name": dataset_name,
            "is_remote": is_remote,
            "remote_config": remote_config if is_remote else None,
            "operation": "save_cluster" if body.save else "cluster",
            "algorithm": body.algorithm,
            "columns": body.columns,
            "auto_params": body.auto_params,
            # 完整配置：供任务调度器激活 pending 任务 / 失败重试时重建执行参数（修复）
            "config": body.dict(),
            # 高级参数：仅记录当前算法相关参数，便于追溯实际执行参数
            **cluster_advanced_params
        }
    )

    # 远程模式：强制同步执行
    if is_remote:
        config = body.dict()
        return _execute_cluster(
            task_record_id=task_record.id,
            user_id=current_user.id,
            dataset_id=dataset_id,
            config=config,
            df=df,
            is_remote=True,
            remote_config=remote_config
        )

    # 智能异步分发：≥1万行异步提交到 Celery，<1万行同步执行
    if row_count >= settings.ASYNC_THRESHOLD:
        # 业务代码不降级：Celery 不可用时直接报 503，不静默回退到同步
        if not task_manager.is_async_available():
            execution_time = int((time.time() - start_time) * 1000)
            update_task_record(
                db=db, record_id=task_record.id, status="failed",
                error_message="Celery 不可用，无法处理大数据集，请启动 Celery 服务或使用小数据集",
                execution_time=execution_time, failure_category="system_error"
            )
            raise HTTPException(
                status_code=503,
                detail="Celery 不可用，无法处理大数据集，请启动 Celery 服务或使用小数据集"
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
            # 立即执行：提交到 Celery 队列，立即返回 task_id 供前端轮询进度
            config = body.dict()
            task_result = task_manager.run_task(
                _execute_cluster,
                task_record_id=task_record.id,
                user_id=current_user.id,
                dataset_id=body.dataset_id,
                config=config,
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
                "message": "聚类分析任务已提交，请在右上角任务面板查看进度",
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
                "message": f"聚类分析任务已进入等待队列（{queue_msg}），将在前面任务完成后自动执行",
                "row_count": row_count
            }

    # 同步执行（本地小数据集）
    config = body.dict()
    return _execute_cluster(
        task_record_id=task_record.id,
        user_id=current_user.id,
        dataset_id=body.dataset_id,
        config=config
    )


@task_manager.register_task
def _execute_association(task_record_id: int, user_id: int, dataset_id: int, config: dict,
                         df=None, is_remote: bool = False, remote_config: dict = None):
    """关联规则挖掘核心执行函数（同步/异步共用入口）

    通过 SessionLocal 创建独立 db 会话：
    - 同步调用时与 FastAPI 的 db 隔离，避免长事务占用请求连接
    - 异步调用时（Celery Worker 进程）必须新建 session，因为无法访问 FastAPI 请求上下文

    4阶段进度上报到 task_records.result_summary：
    - 数据加载与预处理(20%)：加载数据集、参数校验、构建购物篮矩阵
    - 关联规则挖掘中(50%)：计算频繁项集、生成关联规则
    - 结果汇总与质量评估(80%)：生成关联规则报告与质量评估
    - 保存结果(100%)：保存关联规则到 MinIO + 数据库

    Args:
        task_record_id: 任务记录ID（入口已创建）
        user_id: 用户ID
        dataset_id: 数据集ID（远程模式下可为 None）
        config: AssociationRequest 的 dict 表示，包含 algorithm/data_format/min_support 等参数
        df: 预加载的 DataFrame（远程模式下由调用方传入）
        is_remote: 是否为远程数据源
        remote_config: 远程数据源配置

    Returns:
        关联规则结果字典（与原同步接口返回结构保持一致）
    """
    from mlxtend.frequent_patterns import apriori, fpgrowth, association_rules

    # Celery Worker 是独立进程，必须新建 db 会话，不能复用 FastAPI 请求作用域的 db
    db = SessionLocal()
    start_time = time.time()

    try:
        # ===== 阶段1：数据加载与预处理（20%） =====
        update_task_progress(db, task_record_id, "数据加载与预处理", 20, "正在加载数据")

        # 从 config 提取参数（config 是原 AssociationRequest 的 dict 表示）
        algorithm = config.get("algorithm", "apriori").lower()
        data_format = config.get("data_format", "basket")
        tid_column = config.get("tid_column")
        item_column = config.get("item_column")
        min_support_cfg = config.get("min_support")
        min_confidence_cfg = config.get("min_confidence")
        min_lift = config.get("min_lift", 1.0)
        max_len = config.get("max_len")
        auto_params = config.get("auto_params", True)
        save = config.get("save", False)

        # 获取数据集（远程模式下 df 已由调用方预加载）
        if df is None:
            original_dataset = db.query(Dataset).filter(
                Dataset.id == dataset_id, Dataset.user_id == user_id, Dataset.status == "active"
            ).first()
            if not original_dataset:
                raise ValueError(f"数据集 {dataset_id} 不存在")

            data_service = DataService(db)
            df = data_service.load_dataset(dataset_id)
        else:
            original_dataset = None
            data_service = DataService(db)

        # 参数校验
        _validate_association_params(df, data_format, tid_column, item_column)

        # 构建购物篮矩阵
        if data_format == "basket" and tid_column and item_column:
            # 构建购物篮数据（交易ID为行，商品为列）
            basket = df.groupby(tid_column)[item_column].apply(list).reset_index()
            all_items = sorted(df[item_column].dropna().unique())

            basket_data = []
            for _, row in basket.iterrows():
                items = set(row[item_column])
                basket_data.append({item: item in items for item in all_items})

            df_encoded = pd.DataFrame(basket_data)
            n_transactions = len(df_encoded)
        else:
            # 自动二值化：数值列用中位数二值化，类别列唯一值<=10用独热编码，>10用频率编码
            df_encoded = df.copy()
            for col in df_encoded.columns:
                if pd.api.types.is_numeric_dtype(df_encoded[col]):
                    median_val = df_encoded[col].median()
                    df_encoded[col] = (df_encoded[col] > median_val).astype(int)
                else:
                    unique_vals = df_encoded[col].dropna().unique()
                    if len(unique_vals) <= 10:
                        for val in unique_vals:
                            df_encoded[f"{col}_{val}"] = (df_encoded[col] == val).astype(int)
                        df_encoded.drop(columns=[col], inplace=True)
                    else:
                        freq_map = df_encoded[col].value_counts(normalize=True).to_dict()
                        df_encoded[col] = df_encoded[col].map(freq_map).fillna(0)

            # 确保所有列为数值类型
            for col in df_encoded.columns:
                df_encoded[col] = pd.to_numeric(df_encoded[col], errors='coerce').fillna(0)
            n_transactions = len(df_encoded)

        # 参数推荐
        rec = _recommend_association_params(n_transactions)
        recommended_params = rec

        # 确定实际使用的参数
        if auto_params or min_support_cfg is None:
            min_support = rec["min_support"]
        else:
            min_support = min_support_cfg
        if auto_params or min_confidence_cfg is None:
            min_confidence = rec["min_confidence"]
        else:
            min_confidence = min_confidence_cfg

        params_used = {
            "min_support": min_support,
            "min_confidence": min_confidence,
            "min_lift": min_lift,
            "max_len": max_len
        }

        # ===== 阶段2：关联规则挖掘中（50%） =====
        update_task_progress(db, task_record_id, "关联规则挖掘中", 50, f"正在执行 {algorithm} 挖掘")

        # 计算频繁项集
        encoded_bool = df_encoded.astype(bool)
        if algorithm == "fpgrowth":
            frequent_itemsets = fpgrowth(
                encoded_bool,
                min_support=min_support,
                use_colnames=True,
                max_len=max_len
            )
        else:
            # 默认使用apriori
            frequent_itemsets = apriori(
                encoded_bool,
                min_support=min_support,
                use_colnames=True,
                max_len=max_len
            )

        if frequent_itemsets.empty:
            raise HTTPException(status_code=400, detail="没有找到满足最小支持度的频繁项集，请降低最小支持度")

        # 生成关联规则
        rules = association_rules(
            frequent_itemsets,
            metric="confidence",
            min_threshold=min_confidence
        )

        # 提取规则列表，过滤min_lift
        rules_list = []
        for _, rule in rules.iterrows():
            lift = float(rule['lift'])
            if lift < min_lift:
                continue
            antecedent = list(rule['antecedents'])
            consequent = list(rule['consequents'])
            rules_list.append({
                "antecedent": antecedent,
                "consequent": consequent,
                "support": round(float(rule['support']), 4),
                "confidence": round(float(rule['confidence']), 4),
                "lift": round(lift, 4)
            })

        # 按lift降序排序，取前50条
        rules_list.sort(key=lambda x: x['lift'], reverse=True)
        rules_list = rules_list[:50]

        new_dataset = None
        result_path = None
        result_name = None

        # ===== 阶段3：结果汇总与质量评估（80%） =====
        update_task_progress(db, task_record_id, "结果汇总与质量评估", 80, "正在生成关联规则报告与质量评估")

        # ===== 阶段4：保存结果（100%） =====
        update_task_progress(db, task_record_id, "保存结果", 100, "正在保存关联规则结果")

        if save:
            # 保存JSON到MinIO
            # 命名方案：产物保留源名（去原扩展名 + 真实内容后缀 .json），不拼算法/时间戳，靠 #id/颜色区分
            if is_remote:
                source_name = (remote_config or {}).get("table_name", "remote_table")
                result_name = build_product_name(source_name, "json")
            else:
                result_name = build_product_name(original_dataset.name, "json")

            result_data = json.dumps({
                "rules": rules_list,
                "parameters": {
                    "algorithm": algorithm,
                    "min_support": min_support,
                    "min_confidence": min_confidence,
                    "min_lift": min_lift,
                    "max_len": max_len,
                    "total_rules_found": len(rules_list),
                    "n_transactions": n_transactions,
                    "recommended_params": recommended_params
                }
            }, ensure_ascii=False, indent=2).encode('utf-8')

            object_name = f"data_mining/user_{user_id}/{result_name}"
            result_path = storage_manager.save_bytes(object_name, result_data)

            # 创建Dataset记录
            file_size = len(result_data)
            algo_text = f"{algorithm}关联规则 | 最小支持度={min_support} | 最小置信度={min_confidence} | 规则数={len(rules_list)}"
            if is_remote:
                parent_id = None
                root_id = None
            else:
                parent_id = original_dataset.id
                root_id = get_root_dataset_id(db, original_dataset)
            # 复用 report_content 字段保存关联规则摘要报告，便于 AI 对话上下文直接读取，无需改表结构
            rules_report = {
                "algorithm": algorithm,
                "total_rules": len(rules_list),
                "top_rules": rules_list[:10],
                "support_range": [min(r['support'] for r in rules_list), max(r['support'] for r in rules_list)] if rules_list else [None, None],
                "confidence_range": [min(r['confidence'] for r in rules_list), max(r['confidence'] for r in rules_list)] if rules_list else [None, None],
                "lift_range": [min(r['lift'] for r in rules_list), max(r['lift'] for r in rules_list)] if rules_list else [None, None],
                "parameters": {
                    "min_support": min_support,
                    "min_confidence": min_confidence,
                    "min_lift": min_lift,
                    "max_len": max_len,
                    "n_transactions": n_transactions
                }
            }
            new_dataset = Dataset(
                name=result_name,
                file_path=result_path,
                file_size=file_size,
                schema={"type": "json"},
                row_count=len(rules_list),
                data_preview=str(rules_list[:5]),
                module_source="data_mining",
                module_label=MODULE_LABEL_MAP.get("data_mining", "数据挖掘"),
                artifact_type="association_rules",
                algorithm=algo_text,
                parent_id=parent_id,
                root_dataset_id=root_id,
                user_id=user_id,
                report_content=json.dumps(rules_report, ensure_ascii=False),
                # 远程来源血缘字段
                connection_id=(remote_config or {}).get("connection_id") if is_remote else None,
                table_name=(remote_config or {}).get("table_name") if is_remote else None,
                root_connection_id=(remote_config or {}).get("connection_id") if is_remote else None,
                source_type="derived" if is_remote else None
            )
            db.add(new_dataset)
            db.commit()
            db.refresh(new_dataset)

            clear_user_dataset_cache(user_id)

        # 质量评估（在更新任务记录前计算，便于写入 result_summary 供异步轮询前端提取）
        quality_assessment = []

        # 自动二值化模式下，所有规则置信度都是1时给出警告
        if data_format == "binary" and len(rules_list) > 0:
            all_confidence_one = all(round(r['confidence'], 4) >= 0.9999 for r in rules_list)
            if all_confidence_one:
                quality_assessment.append({
                    "level": "warning",
                    "code": "BINARY_FORMAT_LOW_VALUE",
                    "message": "当前使用自动二值化模式，所有规则置信度均为100%，多为数据结构性关联，业务价值有限。建议使用购物篮格式并指定事务列和项列。"
                })

        if len(rules_list) == 0:
            # 分析0规则的原因
            if not frequent_itemsets.empty:
                # 有频繁项集但没有规则：检查lift分布
                all_rules = association_rules(frequent_itemsets, metric="confidence", min_threshold=0)
                if not all_rules.empty:
                    max_lift = float(all_rules['lift'].max())
                    if max_lift < min_lift:
                        # 所有规则的lift都低于阈值
                        if max_lift < 1.0:
                            quality_assessment.append({
                                "level": "warning",
                                "code": "NO_RULES_NEGATIVE_CORRELATION",
                                "message": f"未找到满足条件的关联规则。所有规则的提升度均小于1（最高{max_lift:.2f}），"
                                         f"说明项之间为负相关或独立，没有有价值的关联。建议更换数据或调整数据格式。"
                            })
                        else:
                            quality_assessment.append({
                                "level": "warning",
                                "code": "NO_RULES_LIFT_TOO_HIGH",
                                "message": f"未找到满足条件的关联规则。最高提升度为{max_lift:.2f}，"
                                         f"低于设置的最小提升度{min_lift}。建议降低最小提升度（如{max_lift:.2f}以下）。"
                            })
                    else:
                        quality_assessment.append({
                            "level": "warning",
                            "code": "NO_RULES",
                            "message": "未找到满足条件的关联规则，建议调低最小支持度或最小置信度"
                        })
                else:
                    quality_assessment.append({
                        "level": "warning",
                        "code": "NO_RULES",
                        "message": "未找到满足条件的关联规则，建议调低最小支持度或最小置信度"
                    })
            else:
                quality_assessment.append({
                    "level": "warning",
                    "code": "NO_RULES",
                    "message": "未找到满足条件的关联规则，建议调低最小支持度或最小置信度"
                })
        elif len(rules_list) > 50:
            quality_assessment.append({
                "level": "info",
                "code": "TOO_MANY_RULES",
                "message": f"生成了{len(rules_list)}条规则，数量较多，建议提高最小支持度或最小置信度"
            })

        # 构建完整的 association_report（与同步返回一致，异步路径下写入 result_summary 供前端轮询提取）
        association_report = {
            "algorithm": algorithm,
            "min_support": min_support,
            "min_confidence": min_confidence,
            "min_lift": min_lift,
            "total_rules": len(rules_list),
            "rules": rules_list,
            "params_used": params_used,
            "recommended_params": recommended_params,
            "auto_params": auto_params,
            "preview_data": _get_data_preview(df),
            "quality_assessment": quality_assessment
        }

        # 更新任务记录为成功
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db,
            record_id=task_record_id,
            status="success",
            dataset_id=new_dataset.id if new_dataset else None,
            result_summary={
                "operation": "save_association" if save else "association",
                "new_dataset_id": new_dataset.id if new_dataset else None,
                "new_dataset_name": result_name,
                "saved": save,
                "dataset_id": new_dataset.id if new_dataset else None,
                "association_report": association_report,
                # 保留摘要字段（操作历史列表展示用）
                "algorithm": algorithm,
                "min_support": min_support,
                "min_confidence": min_confidence,
                "min_lift": min_lift,
                "total_rules": len(rules_list),
                "support_range": [min(r['support'] for r in rules_list), max(r['support'] for r in rules_list)] if rules_list else [None, None],
                "confidence_range": [min(r['confidence'] for r in rules_list), max(r['confidence'] for r in rules_list)] if rules_list else [None, None],
                "lift_range": [min(r['lift'] for r in rules_list), max(r['lift'] for r in rules_list)] if rules_list else [None, None],
                "params_used": params_used,
                "recommended_params": recommended_params
            },
            execution_time=execution_time
        )

        return {
            "dataset_id": new_dataset.id if new_dataset else None,
            "file_path": result_path,
            "saved": save,
            "association_report": association_report
        }

    except HTTPException as he:
        # 参数/数据校验失败：_validate_* 抛出的 HTTPException 内部未更新 task_record，此处统一更新
        # 内部主动抛出的 HTTPException 同样由此处统一处理，error_message 使用 HTTPException.detail 保持准确
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db, record_id=task_record_id, status="failed",
            error_message=str(he.detail) if he.detail else "参数校验失败",
            execution_time=execution_time, failure_category="param_error"
        )
        raise
    except SoftTimeLimitExceeded:
        # 软超时：Celery soft_time_limit 触发，需在硬超时前更新数据库状态
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db, record_id=task_record_id, status="failed",
            error_message=f"关联规则挖掘任务超时（超过 {settings.CELERY_TASK_SOFT_TIME_LIMIT} 秒），已自动终止",
            execution_time=execution_time,
            failure_category="timeout"
        )
        raise
    except Exception as e:
        # 未预期的系统异常（数据加载失败、算法执行异常、文件保存失败等）
        import traceback
        traceback.print_exc()
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db, record_id=task_record_id, status="failed",
            error_message=f"关联规则挖掘失败: {str(e)}",
            execution_time=execution_time,
            failure_category=classify_failure(e)
        )
        raise
    finally:
        # Celery Worker 是独立进程，必须显式关闭 db 会话，避免连接泄漏
        db.close()


@router.post("/association")
async def association_rules_mining(
    body: AssociationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """关联规则挖掘接口：支持Apriori和FP-Growth（支持本地数据集和远程数据库）

    智能异步：≥1万行异步提交（Celery 不可用且≥1万行报503不降级），<1万行同步执行
    远程模式：强制同步执行
    """
    dataset_id = body.dataset_id
    remote_config = body.remote

    if not dataset_id and not (remote_config and remote_config.get("use_remote")):
        raise HTTPException(status_code=400, detail="缺少 dataset_id 或 remote 参数")

    # 统一数据加载（本地数据集或远程数据库）
    data_service = DataService(db)
    try:
        df, dataset = data_service.load_module_data(
            dataset_id=dataset_id,
            remote_config=remote_config,
            user_id=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    is_remote = remote_config and remote_config.get("use_remote")

    # 本地数据集模式：验证来源
    if not is_remote and dataset:
        if dataset.module_source != "data_mining" or dataset.artifact_type != "raw_data":
            raise HTTPException(status_code=403, detail="只能使用数据挖掘模块的原始数据")

    # 获取数据集名称（用于任务记录）
    if is_remote:
        dataset_name = remote_config.get("table_name", "远程表")
    else:
        dataset_name = dataset.name

    # 确定行数
    row_count = len(df) if is_remote else (dataset.row_count or 0)

    # 创建任务记录
    start_time = time.time()
    task_record = create_task_record(
        db=db,
        task_type="data_mining",
        user_id=current_user.id,
        dataset_id=dataset_id,  # 远程模式下为 None
        params={
            "dataset_name": dataset_name,
            "is_remote": is_remote,
            "remote_config": remote_config if is_remote else None,
            "operation": "save_association" if body.save else "association",
            "algorithm": body.algorithm,
            "min_support": body.min_support,
            "min_confidence": body.min_confidence,
            "min_lift": body.min_lift,
            # 关联规则数据格式：basket=购物篮格式（事务标识列+项列），binary=自动二值化（0/1矩阵）
            "data_format": body.data_format,
            "item_column": body.item_column,
            "tid_column": body.tid_column,
            # 高级参数：最大项集长度，None 表示不限制
            "max_len": body.max_len,
            "auto_params": body.auto_params,
            # 完整配置：供任务调度器激活 pending 任务 / 失败重试时重建执行参数（修复）
            "config": body.dict()
        }
    )

    # 远程模式：强制同步执行
    if is_remote:
        config = body.dict()
        return _execute_association(
            task_record_id=task_record.id,
            user_id=current_user.id,
            dataset_id=dataset_id,
            config=config,
            df=df,
            is_remote=True,
            remote_config=remote_config
        )

    # 智能异步分发：≥1万行异步提交到 Celery，<1万行同步执行
    if row_count >= settings.ASYNC_THRESHOLD:
        # 业务代码不降级：Celery 不可用时直接报 503，不静默回退到同步
        if not task_manager.is_async_available():
            execution_time = int((time.time() - start_time) * 1000)
            update_task_record(
                db=db, record_id=task_record.id, status="failed",
                error_message="Celery 不可用，无法处理大数据集，请启动 Celery 服务或使用小数据集",
                execution_time=execution_time, failure_category="system_error"
            )
            raise HTTPException(
                status_code=503,
                detail="Celery 不可用，无法处理大数据集，请启动 Celery 服务或使用小数据集"
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
            # 立即执行：提交到 Celery 队列，立即返回 task_id 供前端轮询进度
            config = body.dict()
            task_result = task_manager.run_task(
                _execute_association,
                task_record_id=task_record.id,
                user_id=current_user.id,
                dataset_id=body.dataset_id,
                config=config,
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
                "message": "关联规则挖掘任务已提交，请在右上角任务面板查看进度",
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
                "message": f"关联规则挖掘任务已进入等待队列（{queue_msg}），将在前面任务完成后自动执行",
                "row_count": row_count
            }

    # 同步执行（本地小数据集）
    config = body.dict()
    return _execute_association(
        task_record_id=task_record.id,
        user_id=current_user.id,
        dataset_id=body.dataset_id,
        config=config
    )


@task_manager.register_task
def _execute_sequence(task_record_id: int, user_id: int, dataset_id: int, config: dict,
                      df=None, is_remote: bool = False, remote_config: dict = None):
    """序列模式挖掘核心执行函数（同步/异步共用入口）

    通过 SessionLocal 创建独立 db 会话：
    - 同步调用时与 FastAPI 的 db 隔离，避免长事务占用请求连接
    - 异步调用时（Celery Worker 进程）必须新建 session，因为无法访问 FastAPI 请求上下文

    4阶段进度上报到 task_records.result_summary：
    - 数据加载与预处理(20%)：加载数据集、列检测、参数校验、构建事件序列
    - 序列模式挖掘中(50%)：执行 PrefixSpan/GSP 算法
    - 结果汇总与质量评估(80%)：生成序列模式报告与质量评估
    - 保存结果(100%)：保存序列模式到 MinIO + 数据库

    Args:
        task_record_id: 任务记录ID（入口已创建）
        user_id: 用户ID
        dataset_id: 数据集ID（远程模式下可为 None）
        config: SequenceRequest 的 dict 表示，包含 algorithm/seq_id_column/min_support 等参数
        df: 预加载的 DataFrame（远程模式下由调用方传入）
        is_remote: 是否为远程数据源
        remote_config: 远程数据源配置

    Returns:
        序列模式结果字典（与原同步接口返回结构保持一致）
    """
    # Celery Worker 是独立进程，必须新建 db 会话，不能复用 FastAPI 请求作用域的 db
    db = SessionLocal()
    start_time = time.time()

    try:
        # ===== 阶段1：数据加载与预处理（20%） =====
        update_task_progress(db, task_record_id, "数据加载与预处理", 20, "正在加载数据")

        # 从 config 提取参数（config 是原 SequenceRequest 的 dict 表示）
        algorithm = config.get("algorithm", "prefixspan").lower()
        min_support_cfg = config.get("min_support")
        max_len = config.get("max_len")
        auto_params = config.get("auto_params", True)
        save = config.get("save", False)

        # 获取数据集（远程模式下 df 已由调用方预加载）
        if df is None:
            original_dataset = db.query(Dataset).filter(
                Dataset.id == dataset_id, Dataset.user_id == user_id, Dataset.status == "active"
            ).first()
            if not original_dataset:
                raise ValueError(f"数据集 {dataset_id} 不存在")

            data_service = DataService(db)
            df = data_service.load_dataset(dataset_id)
        else:
            original_dataset = None
            data_service = DataService(db)

        # 确定序列ID列、时间列、事件列
        seq_id_col = config.get("seq_id_column")
        time_col = config.get("time_column")
        event_col = config.get("event_column")

        # 自动检测未指定的列
        if seq_id_col is None or time_col is None or event_col is None:
            detected = _detect_sequence_columns(df)
            if seq_id_col is None:
                seq_id_col = detected["seq_id_column"]
            if time_col is None:
                time_col = detected["time_column"]
            if event_col is None:
                event_col = detected["event_column"]

        # 参数校验
        _validate_sequence_params(df, seq_id_col, time_col, event_col)

        # 构建序列：按seq_id分组，按time排序
        # 时间列若可解析为时间，则用时间语义排序，避免字符串字典序导致
        # '2024-1-10' 排在 '2024-1-2' 之前的事件顺序颠倒
        sort_key_col = time_col
        if not pd.api.types.is_datetime64_any_dtype(df[time_col]):
            parsed_time = pd.to_datetime(df[time_col], errors='coerce')
            if parsed_time.notna().mean() >= 0.8:
                df = df.copy()
                df["__seq_sort_key__"] = parsed_time
                sort_key_col = "__seq_sort_key__"
        df_sorted = df.sort_values(by=[seq_id_col, sort_key_col])
        if sort_key_col != time_col:
            df_sorted = df_sorted.drop(columns=["__seq_sort_key__"])
        # 事件值转为字符串保证一致性
        df_sorted[event_col] = df_sorted[event_col].astype(str)
        sequences = df_sorted.groupby(seq_id_col)[event_col].apply(list).tolist()

        n_sequences = len(sequences)
        if n_sequences == 0:
            raise HTTPException(status_code=400, detail="未构建出任何事件序列")

        # 参数推荐
        rec = _recommend_sequence_params(n_sequences)
        recommended_params = rec

        # 确定实际使用的min_support
        if auto_params or min_support_cfg is None:
            min_support = rec["min_support"]
        else:
            min_support = min_support_cfg

        # 确定最大序列长度：max_len<=0 表示不限制（前端语义"0 表示不限制"），
        # 取最长序列的长度作为上限，避免被截断为默认值 10
        if max_len is None or max_len <= 0:
            seq_max_len = max((len(s) for s in sequences), default=10)
        else:
            seq_max_len = max_len

        params_used = {
            "min_support": min_support,
            "max_len": seq_max_len,
            "seq_id_column": seq_id_col,
            "time_column": time_col,
            "event_column": event_col
        }

        # ===== 阶段2：序列模式挖掘中（50%） =====
        update_task_progress(db, task_record_id, "序列模式挖掘中", 50, f"正在执行 {algorithm} 挖掘")

        # 执行算法
        if algorithm == "gsp":
            patterns = _gsp(sequences, min_support, max_len=seq_max_len)
        else:
            # 默认使用prefixspan
            patterns = _prefix_span(sequences, min_support, max_len=seq_max_len)

        # 按支持度降序排序
        patterns.sort(key=lambda x: x["support"], reverse=True)

        # 限制保存的模式数量，避免文件过大
        total_patterns = len(patterns)
        saved_patterns = patterns[:1000]
        top_patterns = patterns[:20]

        new_dataset = None
        result_path = None
        result_name = None

        # ===== 阶段3：结果汇总与质量评估（80%） =====
        update_task_progress(db, task_record_id, "结果汇总与质量评估", 80, "正在生成序列模式报告与质量评估")

        # ===== 阶段4：保存结果（100%） =====
        update_task_progress(db, task_record_id, "保存结果", 100, "正在保存序列模式结果")

        if save:
            # 保存JSON到MinIO
            # 命名方案：产物保留源名（去原扩展名 + 真实内容后缀 .json），不拼算法/时间戳，靠 #id/颜色区分
            if is_remote:
                source_name = (remote_config or {}).get("table_name", "remote_table")
                result_name = build_product_name(source_name, "json")
            else:
                result_name = build_product_name(original_dataset.name, "json")

            result_data = json.dumps({
                "patterns": saved_patterns,
                "parameters": {
                    "algorithm": algorithm,
                    "min_support": min_support,
                    "max_len": seq_max_len,
                    "total_patterns": total_patterns,
                    "seq_id_column": seq_id_col,
                    "time_column": time_col,
                    "event_column": event_col,
                    "n_sequences": n_sequences,
                    "recommended_params": recommended_params
                }
            }, ensure_ascii=False, indent=2).encode('utf-8')

            object_name = f"data_mining/user_{user_id}/{result_name}"
            result_path = storage_manager.save_bytes(object_name, result_data)

            # 创建Dataset记录
            file_size = len(result_data)
            algo_text = f"{algorithm}序列模式 | 最小支持度={min_support} | 模式数={total_patterns} | 序列数={n_sequences}"
            if is_remote:
                parent_id = None
                root_id = None
            else:
                parent_id = original_dataset.id
                root_id = get_root_dataset_id(db, original_dataset)
            # 复用 report_content 字段保存序列模式摘要报告，便于 AI 对话上下文直接读取，无需改表结构
            patterns_report = {
                "algorithm": algorithm,
                "total_patterns": total_patterns,
                "top_patterns": top_patterns[:10],
                "support_range": [min(p['support'] for p in saved_patterns), max(p['support'] for p in saved_patterns)] if saved_patterns else [None, None],
                "parameters": {
                    "min_support": min_support,
                    "max_len": seq_max_len,
                    "n_sequences": n_sequences,
                    "seq_id_column": seq_id_col,
                    "time_column": time_col,
                    "event_column": event_col
                }
            }
            new_dataset = Dataset(
                name=result_name,
                file_path=result_path,
                file_size=file_size,
                schema={"type": "json"},
                row_count=total_patterns,
                data_preview=str(top_patterns[:5]),
                module_source="data_mining",
                module_label=MODULE_LABEL_MAP.get("data_mining", "数据挖掘"),
                artifact_type="sequential_patterns",
                algorithm=algo_text,
                parent_id=parent_id,
                root_dataset_id=root_id,
                user_id=user_id,
                report_content=json.dumps(patterns_report, ensure_ascii=False),
                # 远程来源血缘字段
                connection_id=(remote_config or {}).get("connection_id") if is_remote else None,
                table_name=(remote_config or {}).get("table_name") if is_remote else None,
                root_connection_id=(remote_config or {}).get("connection_id") if is_remote else None,
                source_type="derived" if is_remote else None
            )
            db.add(new_dataset)
            db.commit()
            db.refresh(new_dataset)

            clear_user_dataset_cache(user_id)

        # 质量评估（在更新任务记录前计算，便于写入 result_summary 供异步轮询前端提取）
        quality_assessment = []
        if total_patterns == 0:
            quality_assessment.append({
                "level": "warning",
                "code": "NO_PATTERNS",
                "message": "未找到满足条件的序列模式，建议调低最小支持度"
            })
        elif total_patterns > 100:
            quality_assessment.append({
                "level": "info",
                "code": "TOO_MANY_PATTERNS",
                "message": f"生成了{total_patterns}个序列模式，数量较多，建议提高最小支持度"
            })

        # 构建完整的 sequence_report（与同步返回一致，异步路径下写入 result_summary 供前端轮询提取）
        sequence_report = {
            "algorithm": algorithm,
            "min_support": min_support,
            "total_patterns": total_patterns,
            "top_patterns": top_patterns,
            "seq_id_column": seq_id_col,
            "time_column": time_col,
            "event_column": event_col,
            "n_sequences": n_sequences,
            "params_used": params_used,
            "recommended_params": recommended_params,
            "auto_params": auto_params,
            "preview_data": _get_data_preview(df),
            "quality_assessment": quality_assessment
        }

        # 更新任务记录为成功
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db,
            record_id=task_record_id,
            status="success",
            dataset_id=new_dataset.id if new_dataset else None,
            result_summary={
                "operation": "save_sequence" if save else "sequence",
                "new_dataset_id": new_dataset.id if new_dataset else None,
                "new_dataset_name": result_name,
                "saved": save,
                "dataset_id": new_dataset.id if new_dataset else None,
                "sequence_report": sequence_report,
                # 保留摘要字段（操作历史列表展示用）
                "algorithm": algorithm,
                "min_support": min_support,
                "total_patterns": total_patterns,
                "support_range": [min(p['support'] for p in saved_patterns), max(p['support'] for p in saved_patterns)] if saved_patterns else [None, None],
                "n_sequences": n_sequences,
                "params_used": params_used,
                "recommended_params": recommended_params
            },
            execution_time=execution_time
        )

        return {
            "dataset_id": new_dataset.id if new_dataset else None,
            "file_path": result_path,
            "saved": save,
            "sequence_report": sequence_report
        }

    except HTTPException as he:
        # 参数/数据校验失败：_validate_* 抛出的 HTTPException 内部未更新 task_record，此处统一更新
        # 内部主动抛出的 HTTPException 同样由此处统一处理，error_message 使用 HTTPException.detail 保持准确
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db, record_id=task_record_id, status="failed",
            error_message=str(he.detail) if he.detail else "参数校验失败",
            execution_time=execution_time, failure_category="param_error"
        )
        raise
    except SoftTimeLimitExceeded:
        # 软超时：Celery soft_time_limit 触发，需在硬超时前更新数据库状态
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db, record_id=task_record_id, status="failed",
            error_message=f"序列模式挖掘任务超时（超过 {settings.CELERY_TASK_SOFT_TIME_LIMIT} 秒），已自动终止",
            execution_time=execution_time,
            failure_category="timeout"
        )
        raise
    except Exception as e:
        # 未预期的系统异常（数据加载失败、算法执行异常、文件保存失败等）
        import traceback
        traceback.print_exc()
        execution_time = int((time.time() - start_time) * 1000)
        update_task_record(
            db=db, record_id=task_record_id, status="failed",
            error_message=f"序列模式挖掘失败: {str(e)}",
            execution_time=execution_time,
            failure_category=classify_failure(e)
        )
        raise
    finally:
        # Celery Worker 是独立进程，必须显式关闭 db 会话，避免连接泄漏
        db.close()


@router.post("/sequence")
async def sequence_pattern_mining(
    body: SequenceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """序列模式挖掘接口：支持PrefixSpan和GSP（支持本地数据集和远程数据库）

    智能异步：≥1万行异步提交（Celery 不可用且≥1万行报503不降级），<1万行同步执行
    远程模式：强制同步执行
    """
    dataset_id = body.dataset_id
    remote_config = body.remote

    if not dataset_id and not (remote_config and remote_config.get("use_remote")):
        raise HTTPException(status_code=400, detail="缺少 dataset_id 或 remote 参数")

    # 统一数据加载（本地数据集或远程数据库）
    data_service = DataService(db)
    try:
        df, dataset = data_service.load_module_data(
            dataset_id=dataset_id,
            remote_config=remote_config,
            user_id=current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    is_remote = remote_config and remote_config.get("use_remote")

    # 本地数据集模式：验证来源
    if not is_remote and dataset:
        if dataset.module_source != "data_mining" or dataset.artifact_type != "raw_data":
            raise HTTPException(status_code=403, detail="只能使用数据挖掘模块的原始数据")

    # 获取数据集名称（用于任务记录）
    if is_remote:
        dataset_name = remote_config.get("table_name", "远程表")
    else:
        dataset_name = dataset.name

    # 确定行数
    row_count = len(df) if is_remote else (dataset.row_count or 0)

    # 创建任务记录
    start_time = time.time()
    task_record = create_task_record(
        db=db,
        task_type="data_mining",
        user_id=current_user.id,
        dataset_id=dataset_id,  # 远程模式下为 None
        params={
            "dataset_name": dataset_name,
            "is_remote": is_remote,
            "remote_config": remote_config if is_remote else None,
            "operation": "save_sequence" if body.save else "sequence",
            "algorithm": body.algorithm,
            "seq_id_column": body.seq_id_column,
            "time_column": body.time_column,
            "event_column": body.event_column,
            "min_support": body.min_support,
            # 高级参数：最大序列长度，None 表示使用默认值 10
            "max_len": body.max_len,
            "auto_params": body.auto_params,
            # 完整配置：供任务调度器激活 pending 任务 / 失败重试时重建执行参数（修复）
            "config": body.dict()
        }
    )

    # 远程模式：强制同步执行
    if is_remote:
        config = body.dict()
        return _execute_sequence(
            task_record_id=task_record.id,
            user_id=current_user.id,
            dataset_id=dataset_id,
            config=config,
            df=df,
            is_remote=True,
            remote_config=remote_config
        )

    # 智能异步分发：≥1万行异步提交到 Celery，<1万行同步执行
    if row_count >= settings.ASYNC_THRESHOLD:
        # 业务代码不降级：Celery 不可用时直接报 503，不静默回退到同步
        if not task_manager.is_async_available():
            execution_time = int((time.time() - start_time) * 1000)
            update_task_record(
                db=db, record_id=task_record.id, status="failed",
                error_message="Celery 不可用，无法处理大数据集，请启动 Celery 服务或使用小数据集",
                execution_time=execution_time, failure_category="system_error"
            )
            raise HTTPException(
                status_code=503,
                detail="Celery 不可用，无法处理大数据集，请启动 Celery 服务或使用小数据集"
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
            # 立即执行：提交到 Celery 队列，立即返回 task_id 供前端轮询进度
            config = body.dict()
            task_result = task_manager.run_task(
                _execute_sequence,
                task_record_id=task_record.id,
                user_id=current_user.id,
                dataset_id=body.dataset_id,
                config=config,
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
                "message": "序列模式挖掘任务已提交，请在右上角任务面板查看进度",
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
                "message": f"序列模式挖掘任务已进入等待队列（{queue_msg}），将在前面任务完成后自动执行",
                "row_count": row_count
            }

    # 同步执行（本地小数据集）
    config = body.dict()
    return _execute_sequence(
        task_record_id=task_record.id,
        user_id=current_user.id,
        dataset_id=body.dataset_id,
        config=config
    )


@router.get("/association/{dataset_id}")
async def get_association_rules(
    dataset_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取关联规则详情（分页）"""
    dataset = get_dataset_or_404(db, dataset_id, current_user.id)
    if dataset.artifact_type != "association_rules":
        raise HTTPException(status_code=400, detail="该数据集不是关联规则类型")

    if not dataset.file_path or not storage_manager.exists(dataset.file_path):
        raise HTTPException(status_code=404, detail="关联规则文件不存在")

    try:
        file_bytes = storage_manager.get_file_bytes(dataset.file_path)
        data = json.loads(file_bytes.decode('utf-8'))

        rules = data.get("rules", [])
        parameters = data.get("parameters", {})

        # 分页
        total = len(rules)
        start = (page - 1) * page_size
        end = start + page_size
        paged_rules = rules[start:end]

        return {
            "rules": paged_rules,
            "parameters": parameters,
            "total": total,
            "page": page,
            "page_size": page_size
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取关联规则失败: {str(e)}")


@router.get("/sequence/{dataset_id}")
async def get_sequence_patterns(
    dataset_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """获取序列模式详情（分页）"""
    dataset = get_dataset_or_404(db, dataset_id, current_user.id)
    if dataset.artifact_type != "sequential_patterns":
        raise HTTPException(status_code=400, detail="该数据集不是序列模式类型")

    if not dataset.file_path or not storage_manager.exists(dataset.file_path):
        raise HTTPException(status_code=404, detail="序列模式文件不存在")

    try:
        file_bytes = storage_manager.get_file_bytes(dataset.file_path)
        data = json.loads(file_bytes.decode('utf-8'))

        patterns = data.get("patterns", [])
        parameters = data.get("parameters", {})

        total = len(patterns)
        start = (page - 1) * page_size
        end = start + page_size
        paged_patterns = patterns[start:end]

        return {
            "patterns": paged_patterns,
            "parameters": parameters,
            "total": total,
            "page": page,
            "page_size": page_size
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取序列模式失败: {str(e)}")


# ====== 任务处理器注册（供任务调度器激活 pending 任务 / 失败重试复用）======

def _dispatch_mining_execution(task_record_id: int, user_id: int, dataset_id: int, config: dict,
                               df=None, is_remote: bool = False, remote_config: dict = None):
    """统一分发：按 config 中的算法类型路由到聚类/关联规则/序列模式执行函数。

    data_mining 三类任务共用 task_type="data_mining"，调度器/重试时通过本函数分发，
    解决此前 pending 任务无法激活、失败任务无法重试的问题（2026-08-15 修复）。
    """
    algorithm = (config or {}).get("algorithm")
    if algorithm in ("kmeans", "dbscan", "hierarchical"):
        return _execute_cluster(task_record_id, user_id, dataset_id, config,
                                df=df, is_remote=is_remote, remote_config=remote_config)
    if algorithm in ("apriori", "fpgrowth"):
        return _execute_association(task_record_id, user_id, dataset_id, config,
                                    df=df, is_remote=is_remote, remote_config=remote_config)
    if algorithm in ("prefixspan", "gsp"):
        return _execute_sequence(task_record_id, user_id, dataset_id, config,
                                 df=df, is_remote=is_remote, remote_config=remote_config)
    raise ValueError(f"未知的挖掘算法类型: {algorithm}")


task_manager.register_task_handler("data_mining", _dispatch_mining_execution)
