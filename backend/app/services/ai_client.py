"""共享 LLM 客户端提供者

分析对话(AIService)与数据问答(AIQAService)共用的 LLM 客户端/模型名/配置管理。
把原本散布在两个服务里的客户端构建与缓存逻辑收敛到此处，避免重复。
"""
from typing import Dict, Optional

from openai import OpenAI

from app.config import settings
from app.models import AIConfig


class LLMClientProvider:
    """懒加载的 LLM 客户端提供者

    持有 db（用于在无系统 API Key 时回退读取数据库里的 AI 配置），负责创建并
    缓存 OpenAI 兼容客户端，并输出当前生效的模型名。两个服务各组合一个实例即可复用。

    Args:
        db: 数据库会话（可选，无系统 API Key 时用于读取 AIConfig）
    """

    def __init__(self, db=None):
        self.db = db
        self._clients = None
        self._default_client = None

    # ---- 缓存管理 ----

    def reset(self) -> None:
        """清空客户端缓存（保存/切换 AI 配置后调用，下次按需重建）"""
        self._clients = None
        self._default_client = None

    # ---- 配置读取 / 客户端构建（内部复用） ----

    def _get_active_config(self) -> Optional[AIConfig]:
        """获取当前激活的 AI 配置"""
        try:
            if self.db is None:
                return None
            return self.db.query(AIConfig).filter(AIConfig.is_active.is_(True)).first()
        except Exception:
            return None

    def _create_client_from_config(self, config: Optional[AIConfig]) -> Optional[OpenAI]:
        """根据配置创建 OpenAI 兼容客户端"""
        if not config or not config.api_key:
            return None
        base_url = config.base_url
        if not base_url:
            if config.provider == "deepseek":
                base_url = "https://api.deepseek.com"
            elif config.provider == "openai":
                base_url = None
        try:
            if base_url:
                return OpenAI(api_key=config.api_key, base_url=base_url)
            return OpenAI(api_key=config.api_key)
        except Exception:
            return None

    # ---- 对外能力 ----

    def get_clients(self) -> Dict[str, OpenAI]:
        """懒加载 AI 客户端：优先使用系统 API Key，否则回退到数据库配置"""
        if self._clients is None:
            self._clients = {}
            self._default_client = None
            if settings.OPENAI_API_KEY:
                try:
                    kwargs = {"api_key": settings.OPENAI_API_KEY}
                    if settings.OPENAI_API_BASE:
                        kwargs["base_url"] = settings.OPENAI_API_BASE
                    client = OpenAI(**kwargs)
                    self._clients["openai"] = client
                    self._default_client = "openai"
                except Exception:
                    pass
            else:
                db_config = self._get_active_config()
                if db_config:
                    try:
                        client = self._create_client_from_config(db_config)
                        if client:
                            self._clients[db_config.provider] = client
                            self._default_client = db_config.provider
                    except Exception:
                        pass
        return self._clients

    @property
    def default_client(self) -> Optional[str]:
        """当前默认客户端的 key（"openai" 或数据库配置的 provider）"""
        self.get_clients()
        return self._default_client

    def get_default_client(self) -> Optional[OpenAI]:
        """获取当前默认的 OpenAI 客户端（未配置 API Key 时返回 None）"""
        return self.get_clients().get(self.default_client)

    def get_model_name(self) -> str:
        """返回当前生效的模型名（与默认 provider 匹配，逻辑与原 AIService 一致）"""
        if settings.OPENAI_API_KEY and settings.OPENAI_MODEL:
            return settings.OPENAI_MODEL
        self.get_clients()
        config = self._get_active_config()
        if config and config.model:
            return config.model
        return "gpt-3.5-turbo" if self.default_client == "openai" else "deepseek-chat"