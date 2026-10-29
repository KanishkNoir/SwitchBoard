import os
from dataclasses import dataclass, field


def _load_dotenv(path: str = ".env") -> None:
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except FileNotFoundError:
        pass


_load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes")


@dataclass
class Settings:
    db_path: str = field(default_factory=lambda: os.environ.get("SWITCHBOARD_DB", "switchboard.db"))
    ui_token: str = field(default_factory=lambda: os.environ.get("SWITCHBOARD_UI_TOKEN", ""))
    baseten_api_key: str = field(default_factory=lambda: os.environ.get("BASETEN_API_KEY", ""))
    baseten_base_url: str = field(default_factory=lambda: os.environ.get("BASETEN_BASE_URL", "https://inference.baseten.co/v1"))
    baseten_model_id: str = field(default_factory=lambda: os.environ.get("BASETEN_MODEL_ID", "meta-models/muse-spark-open-1026"))
    modal_chat_url: str = field(default_factory=lambda: os.environ.get("MODAL_CHAT_URL", ""))
    modal_chat_model: str = field(default_factory=lambda: os.environ.get("MODAL_CHAT_MODEL", "meta-models/Muse-Spark-Open-816B-A42B"))
    modal_proxy_token_id: str = field(default_factory=lambda: os.environ.get("MODAL_PROXY_TOKEN_ID", ""))
    modal_proxy_token_secret: str = field(default_factory=lambda: os.environ.get("MODAL_PROXY_TOKEN_SECRET", ""))
    modal_routing_affinity_key: str = field(default_factory=lambda: os.environ.get("MODAL_ROUTING_AFFINITY_KEY", ""))
    reasoning_provider: str = field(default_factory=lambda: os.environ.get("SWITCHBOARD_REASONING_PROVIDER", "modal"))
    meta_api_key: str = field(default_factory=lambda: os.environ.get("META_API_KEY", ""))
    meta_base_url: str = field(default_factory=lambda: os.environ.get("META_BASE_URL", "https://api.meta.ai/v1"))
    meta_model: str = field(default_factory=lambda: os.environ.get("META_MODEL", "muse-spark-1.3"))
    meta_image_model: str = field(default_factory=lambda: os.environ.get("META_IMAGE_MODEL", "muse-image-1.0"))
    meta_segmentation_model: str = field(default_factory=lambda: os.environ.get("META_SEGMENTATION_MODEL", "sam-3.1"))
    modal_segmentation_url: str = field(default_factory=lambda: os.environ.get("MODAL_SEGMENTATION_URL", ""))
    modal_image_url: str = field(default_factory=lambda: os.environ.get("MODAL_IMAGE_URL", ""))
    modal_t2_url: str = field(default_factory=lambda: os.environ.get("MODAL_T2_URL", ""))
    enable_t3: bool = field(default_factory=lambda: _bool("SWITCHBOARD_ENABLE_T3"))
    enable_segmentation: bool = field(default_factory=lambda: _bool("SWITCHBOARD_ENABLE_SEGMENTATION"))
    enable_image: bool = field(default_factory=lambda: _bool("SWITCHBOARD_ENABLE_IMAGE"))
    t1_threshold: float = 0.35
    policy_version: str = "v0.2.1"
    # Categories/classes that can never be auto-answered in v1 (LLD 7.2).
    locked_categories: tuple = ("payments", "deletion", "messaging_new_recipient")
    locked_context_flags: tuple = ("money_movement", "deletion", "new_recipient", "irreversible_external")


settings = Settings()
