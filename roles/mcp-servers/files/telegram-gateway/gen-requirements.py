#!/usr/bin/env python3
"""Generate a hash-pinned requirements.txt from uv.lock — offline, no network.

Why this exists: the container build installs deps with pip (not uv), because
uv's bundled DNS resolver hangs on this host's unreachable IPv6 nameserver in the
build sandbox. To keep supply-chain integrity (exact versions + hashes) while
using pip, we transcribe uv.lock's resolved closure into a pip requirements file
with --hash lines. pip then installs with --require-hashes --no-deps.

Regenerate after changing dependencies / re-locking:

    python3 gen-requirements.py    # requires Python 3.11+ (tomllib)

Reads ./uv.lock, writes ./requirements.txt.
"""
from __future__ import annotations

import tomllib

PROJECT = "telegram-gateway"  # the project itself; not a pip-installable dep here


def main() -> None:
    lock = tomllib.load(open("uv.lock", "rb"))
    lines: list[str] = []
    skipped: list[str] = []
    for pkg in lock.get("package", []):
        name = pkg.get("name", "")
        if name == PROJECT:
            continue
        version = pkg.get("version")
        hashes: list[str] = []
        sdist = pkg.get("sdist")
        if isinstance(sdist, dict) and sdist.get("hash"):
            hashes.append(sdist["hash"])
        for wheel in pkg.get("wheels", []):
            if wheel.get("hash"):
                hashes.append(wheel["hash"])
        if not version or not hashes:
            skipped.append(name)
            continue
        req = f"{name}=={version}"
        for h in hashes:
            req += f" \\\n    --hash={h}"
        lines.append(req)
    with open("requirements.txt", "w") as f:
        f.write("\n".join(sorted(lines)) + "\n")
    print(f"wrote {len(lines)} pinned packages; skipped (no hash/version): {skipped}")


if __name__ == "__main__":
    main()
