from __future__ import annotations
import hashlib, json, os, re
from pathlib import Path
from grafana_reports.config import Settings

_RID_RE = re.compile(r"^[0-9a-f]{64}$")

class Store:
    def __init__(self, settings: Settings):
        self._s = settings
        self._dir = Path(os.environ.get("LOCAL_DIR", "/app/renders"))
        self._dir.mkdir(parents=True, exist_ok=True)

    def _png(self, rid: str) -> Path:
        if not _RID_RE.match(rid):
            raise KeyError(rid)
        return self._dir / f"{rid}.png"

    def save(self, png: bytes, meta: dict) -> str:
        rid = hashlib.sha256(png).hexdigest()
        self._png(rid).write_bytes(png)
        (self._dir / f"{rid}.json").write_text(json.dumps(meta))
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
        return None  # implemented in Task 8
