from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass
class Settings:
    grafana_url: str
    grafana_sa_token: str
    auth_token: str
    s3_bucket: str | None
    s3_prefix: str
    s3_region: str
    presign_ttl: int
    litellm_url: str | None
    litellm_model: str
    litellm_key: str | None
    catalog_path: str
    refresh_interval: int
    default_width: int
    default_height: int
    render_timeout: int
    fuzzy_threshold: float

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            grafana_url=os.environ.get("GRAFANA_URL", "http://metrics-pod:3000"),
            grafana_sa_token=os.environ.get("GRAFANA_SA_TOKEN", ""),
            auth_token=os.environ.get("AUTH_TOKEN", ""),
            s3_bucket=os.environ.get("S3_BUCKET") or None,
            s3_prefix=os.environ.get("S3_PREFIX", "reports"),
            s3_region=os.environ.get("S3_REGION", "us-east-1"),
            presign_ttl=int(os.environ.get("PRESIGN_TTL", "3600")),
            litellm_url=os.environ.get("LITELLM_URL") or None,
            litellm_model=os.environ.get("LITELLM_MODEL", "gpt-4o-mini"),
            litellm_key=os.environ.get("LITELLM_KEY") or None,
            catalog_path=os.environ.get("CATALOG_PATH", "/app/catalog.yml"),
            refresh_interval=int(os.environ.get("REFRESH_INTERVAL", "900")),
            default_width=int(os.environ.get("DEFAULT_WIDTH", "1000")),
            default_height=int(os.environ.get("DEFAULT_HEIGHT", "500")),
            render_timeout=int(os.environ.get("RENDER_TIMEOUT", "15")),
            fuzzy_threshold=float(os.environ.get("FUZZY_THRESHOLD", "70")),
        )
