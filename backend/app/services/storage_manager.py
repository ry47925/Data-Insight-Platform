import os
import io
import uuid
from typing import List, BinaryIO, Union, Dict

from app.config import settings


_CONTENT_TYPE_MAP = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".txt": "text/plain",
    # 联系管理员截图上传支持
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _infer_content_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    return _CONTENT_TYPE_MAP.get(ext, "application/octet-stream")


class MinIOStorage:
    def __init__(self):
        self.bucket = settings.MINIO_BUCKET
        self.client = None
        self._init_client()

    def _normalize_object_name(self, object_name: str) -> str:
        """在 MinIO 路径中插入 UUID 中间目录，保证每次保存的物理路径唯一。

        调用方传入的 object_name 保持语义不变（如 uploads/user_1/test.csv），
        存储层自动在文件名前追加 UUID 目录，避免并发写入时发生覆盖。

        例如：
            uploads/user_1/test.csv
            -> uploads/user_1/{uuid}/test.csv

            models/model_x.pkl
            -> models/{uuid}/model_x.pkl

        Args:
            object_name: 调用方传入的期望存储路径

        Returns:
            实际写入 MinIO 的唯一路径
        """
        parts = object_name.split("/")
        unique_id = uuid.uuid4().hex
        if len(parts) <= 1:
            # 没有目录层级，直接在文件名前加 UUID 目录
            return f"{unique_id}/{object_name}"
        directory = "/".join(parts[:-1])
        filename = parts[-1]
        return f"{directory}/{unique_id}/{filename}"

    def _init_client(self):
        from minio import Minio
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE
        )
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def save(self, file_path: str, data: Union[bytes, BinaryIO, str]) -> str:
        if self.client is None:
            raise RuntimeError("MinIO 客户端未初始化")

        # 在物理路径中注入 UUID，防止并发同名写入导致覆盖
        actual_path = self._normalize_object_name(file_path)

        if isinstance(data, str):
            data = data.encode('utf-8')
        if isinstance(data, bytes):
            data = io.BytesIO(data)

        length = len(data.getvalue()) if hasattr(data, 'getvalue') else -1
        content_type = _infer_content_type(actual_path)
        self.client.put_object(self.bucket, actual_path, data, length, content_type=content_type)
        return actual_path

    def save_bytes(self, object_name: str, data_bytes: bytes, inplace: bool = False) -> str:
        if self.client is None:
            raise RuntimeError("MinIO 客户端未初始化")

        # inplace=True 时直接覆盖原文件（用于原地更新场景），否则注入 UUID 防止并发同名写入
        actual_name = object_name if inplace else self._normalize_object_name(object_name)

        data = io.BytesIO(data_bytes)
        length = len(data_bytes)
        content_type = _infer_content_type(actual_name)
        self.client.put_object(self.bucket, actual_name, data, length, content_type=content_type)
        return actual_name

    def read(self, file_path: str) -> bytes:
        if self.client is None:
            raise RuntimeError("MinIO 客户端未初始化")

        response = self.client.get_object(self.bucket, file_path)
        return response.read()

    def get_file_bytes(self, object_name: str) -> bytes:
        if self.client is None:
            raise RuntimeError("MinIO 客户端未初始化")

        response = self.client.get_object(self.bucket, object_name)
        return response.read()

    def delete(self, file_path: str) -> bool:
        if self.client is None:
            return False

        try:
            self.client.remove_object(self.bucket, file_path)
            return True
        except Exception:
            return False

    def list_files(self, prefix: str = "") -> List[Dict]:
        if self.client is None:
            return []

        result = []
        objects = self.client.list_objects(self.bucket, prefix=prefix, recursive=True)
        for obj in objects:
            name = obj.object_name.split("/")[-1] if obj.object_name else obj.object_name
            content_type = obj.content_type if obj.content_type else _infer_content_type(name)

            result.append({
                "name": name,
                "path": obj.object_name,
                "size": obj.size,
                "modified_time": obj.last_modified.isoformat() if obj.last_modified else None,
                "content_type": content_type,
                "storage_type": "minio",
            })

        return result

    def exists(self, file_path: str) -> bool:
        if self.client is None:
            return False

        try:
            self.client.stat_object(self.bucket, file_path)
            return True
        except Exception:
            return False


class StorageManager:
    def __init__(self):
        self._minio_storage = None
        self._init_minio()

    def _init_minio(self):
        try:
            self._minio_storage = MinIOStorage()
            if self._minio_storage.client is None:
                raise RuntimeError("MinIO 客户端初始化失败")
        except Exception as e:
            raise RuntimeError("MinIO 不可用，请先启动 MinIO 服务") from e

    def save(self, file_path: str, data: Union[bytes, BinaryIO, str]) -> str:
        return self._minio_storage.save(file_path, data)

    def save_bytes(self, object_name: str, data_bytes: bytes, inplace: bool = False) -> str:
        return self._minio_storage.save_bytes(object_name, data_bytes, inplace=inplace)

    def read(self, file_path: str) -> bytes:
        return self._minio_storage.read(file_path)

    def get_file_bytes(self, object_name: str) -> bytes:
        return self._minio_storage.get_file_bytes(object_name)

    def delete(self, file_path: str) -> bool:
        return self._minio_storage.delete(file_path)

    def list_files(self, prefix: str = "") -> List[Dict]:
        return self._minio_storage.list_files(prefix)

    def exists(self, file_path: str) -> bool:
        return self._minio_storage.exists(file_path)

    def get_stats(self) -> dict:
        try:
            files = self._minio_storage.list_files("")
            total_size = sum(f.get("size", 0) for f in files)
            return {
                "minio_enabled": True,
                "minio_available": True,
                "storage_type": "minio",
                "bucket": self._minio_storage.bucket,
                "buckets": 1,
                "objects": len(files),
                "total_size_mb": round(total_size / 1024 / 1024, 2)
            }
        except Exception:
            # MinIO 不可达时返回明确的离线状态，避免管理端/概览显示"在线"假象（修复）
            return {
                "minio_enabled": True,
                "minio_available": False,
                "storage_type": "minio",
                "bucket": self._minio_storage.bucket,
                "buckets": 0,
                "objects": 0,
                "total_size_mb": 0,
                "error": "MinIO 不可达"
            }


storage_manager = StorageManager()
