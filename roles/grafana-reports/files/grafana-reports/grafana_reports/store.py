from __future__ import annotations
import boto3, hashlib, json, logging, os, re
from pathlib import Path
from grafana_reports.config import Settings

log = logging.getLogger("grafana_reports.store")

_RID_RE = re.compile(r"^[0-9a-f]{64}$")

class Store:
    def __init__(self, settings: Settings):
        self._s = settings
        self._dir = Path(os.environ.get("LOCAL_DIR", "/app/renders"))
        self._dir.mkdir(parents=True, exist_ok=True)
        self._s3 = None

    def _png(self, rid: str) -> Path:
        if not _RID_RE.match(rid):
            raise KeyError(rid)
        return self._dir / f"{rid}.png"

    def _client(self):
        if self._s3 is None:
            self._s3 = boto3.client("s3", region_name=self._s.s3_region)
        return self._s3

    def _key(self, rid: str) -> str:
        if not _RID_RE.match(rid):
            raise KeyError(rid)
        return f"{self._s.s3_prefix}/{rid}.png"

    def save(self, png: bytes, meta: dict) -> str:
        rid = hashlib.sha256(png).hexdigest()
        self._png(rid).write_bytes(png)
        (self._dir / f"{rid}.json").write_text(json.dumps(meta))
        if self._s.s3_bucket:
            try:
                self._client().put_object(Bucket=self._s.s3_bucket, Key=self._key(rid),
                                          Body=png, ContentType="image/png")
            except Exception:
                log.warning("S3 upload failed for %s; serving local render only", rid)
        return rid

    def get(self, report_id: str) -> bytes:
        p = self._png(report_id)
        if not p.exists():
            raise KeyError(report_id)
        return p.read_bytes()

    def exists(self, report_id: str) -> bool:
        if not _RID_RE.match(report_id):
            return False
        return self._png(report_id).exists()

    def presign(self, report_id: str, ttl: int | None = None) -> str | None:
        if not self._s.s3_bucket:
            return None
        return self._client().generate_presigned_url(
            "get_object",
            Params={"Bucket": self._s.s3_bucket, "Key": self._key(report_id)},
            ExpiresIn=ttl or self._s.presign_ttl,
        )
