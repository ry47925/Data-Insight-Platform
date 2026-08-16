"""数据源密码加密工具

使用 Fernet 对称加密（cryptography 库），密钥持久化存储在数据库 app_config 表。
首次启动时自动生成密钥并写入数据库，后续启动从数据库读取。
不依赖环境变量，服务重启/容器重建不丢失。

安全机制：
- 密钥一旦生成，永不再生（即使 app_config 记录被意外删除，也不应生成新密钥，
  否则已有加密数据将无法解密）
- 解密失败时返回清晰错误信息，而不是让调用方崩溃
"""
from cryptography.fernet import Fernet, InvalidToken
import logging

logger = logging.getLogger(__name__)

# 数据库中的配置 key
_CONFIG_KEY = "data_source_encryption_key"

_fernet = None


def _get_fernet():
    """懒加载 Fernet 实例，确保首次调用时已从 DB 获取密钥

    支持并发安全：若首次生成密钥时因主键冲突失败，自动回退查询已有密钥。
    """
    global _fernet
    if _fernet is not None:
        return _fernet

    from app.utils.db import SessionLocal
    from app.models import AppConfig

    db = SessionLocal()
    try:
        config = db.query(AppConfig).filter(AppConfig.key == _CONFIG_KEY).first()
        if config:
            key = config.value
        else:
            # 首次启动：生成密钥并写入数据库
            # 安全检查：确认没有已加密的数据才生成新密钥
            _ensure_no_existing_encrypted_data(db)
            key = Fernet.generate_key().decode()
            db.add(AppConfig(key=_CONFIG_KEY, value=key))
            try:
                db.commit()
                logger.info("加密密钥已生成并持久化到数据库")
            except Exception:
                # 并发场景：其他进程已先写入，回滚后重新查询已有密钥
                db.rollback()
                config = db.query(AppConfig).filter(AppConfig.key == _CONFIG_KEY).first()
                if config:
                    key = config.value
                    logger.info("并发场景：使用其他进程生成的加密密钥")
                else:
                    raise RuntimeError("加密密钥初始化失败：无法写入或读取 app_config 表") from None
    finally:
        db.rollback()
        db.close()

    _fernet = Fernet(key.encode())
    return _fernet


def _ensure_no_existing_encrypted_data(db):
    """安全检查：如果已有加密数据但密钥丢失，拒绝生成新密钥（防止数据永久无法解密）"""
    from app.models import DataSourceConnection
    count = db.query(DataSourceConnection).count()
    if count > 0:
        raise RuntimeError(
            f"检测到 {count} 条已有数据源连接，但加密密钥丢失。"
            f"为防止已有密码永久无法解密，拒绝生成新密钥。"
            f"请从备份恢复 app_config 表中的加密密钥后重试。"
        )


def encrypt_password(plain: str) -> str:
    """加密密码"""
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_password(cipher: str) -> str:
    """解密密码。解密失败时抛出 InvalidTokenError（含中文提示）"""
    try:
        return _get_fernet().decrypt(cipher.encode()).decode()
    except InvalidToken:
        raise InvalidTokenError(
            "密码解密失败：加密密钥不匹配，密文可能由其他密钥加密。"
            "请删除该数据源后重新创建。"
        ) from None


class InvalidTokenError(Exception):
    """解密失败异常（密钥不匹配）"""
    pass
