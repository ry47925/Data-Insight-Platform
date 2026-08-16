from pydantic import BaseModel, Field, ConfigDict, field_serializer, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta

from app.config import dataset_color


def _format_shanghai(dt: datetime) -> Optional[str]:
    """将数据库中存储的 UTC naive datetime 转换为上海时区 ISO 字符串"""
    if dt is None:
        return None
    # Docker 容器时区为 UTC，数据库中 naive datetime 实际表示 UTC 时间
    dt_utc = dt.replace(tzinfo=timezone.utc)
    dt_shanghai = dt_utc.astimezone(timezone(timedelta(hours=8)))
    return dt_shanghai.isoformat()


class DatasetCreate(BaseModel):
    """数据集创建schema"""
    name: str
    connection_id: Optional[int] = None
    table_name: Optional[str] = None
    file_path: Optional[str] = None
    module_source: Optional[str] = None
    module_label: Optional[str] = None
    algorithm: Optional[str] = None
    parent_id: Optional[int] = None
    root_dataset_id: Optional[int] = None
    tags: Optional[str] = None
    remarks: Optional[str] = None
    artifact_type: Optional[str] = None
    report_content: Optional[str] = None


class DatasetUpdate(BaseModel):
    """数据集更新schema"""
    name: Optional[str] = None
    tags: Optional[str] = None
    remarks: Optional[str] = None


class DatasetResponse(BaseModel):
    """数据集响应schema"""
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    name: str
    user_id: Optional[int] = None
    connection_id: Optional[int] = None
    table_name: Optional[str] = None
    data_schema: Optional[Dict] = Field(None, alias="schema")
    file_path: Optional[str] = None
    row_count: Optional[int] = None
    file_size: Optional[int] = Field(None, alias="size")  # 文件大小（字节），前端用 row.size 访问
    module_source: Optional[str] = None
    module_label: Optional[str] = None
    algorithm: Optional[str] = None
    parent_id: Optional[int] = None
    root_dataset_id: Optional[int] = None
    tags: Optional[str] = None
    remarks: Optional[str] = None
    artifact_type: Optional[str] = None
    report_content: Optional[str] = None
    status: Optional[str] = "active"
    deleted_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    color: Optional[str] = None  # 按 dataset_id 派生的固定颜色（方案 A，零存储）

    @field_serializer('created_at', 'deleted_at')
    def serialize_datetime(self, dt: datetime) -> Optional[str]:
        return _format_shanghai(dt)

    @model_validator(mode='after')
    def _fill_dataset_color(self) -> "DatasetResponse":
        """自动按 dataset_id 派生颜色，所有返回数据集的接口统一带 color 字段"""
        if self.color is None:
            self.color = dataset_color(self.id)
        return self


class DatasetDataResponse(BaseModel):
    """数据集数据响应schema"""
    columns: List[str]
    data: List[Dict[str, Any]]
    total_rows: int
    page: int = 1
    page_size: int = 100


class DataStatisticsResponse(BaseModel):
    """数据统计响应schema"""
    row_count: int
    column_count: int
    missing_values: Dict[str, int]
    duplicate_rows: int
    statistics: Dict[str, Any]
