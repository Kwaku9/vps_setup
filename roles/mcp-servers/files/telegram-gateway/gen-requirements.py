#!/usr/bin/env python3
"""How requirements.txt is generated (hash-pinned, with environment markers).

The container build installs deps with pip (not uv): uv runs fine, but we want a
plain pip install so the build needs no uv at runtime, and the image build runs
on enterprise_network (10.89.0.0/24) so DNS resolves and downloads route through
Squid (the default 10.88.0.0/16 build net is firewalled off).

requirements.txt is produced by `uv export` — NOT by hand-parsing uv.lock. An
earlier hand parser dropped the per-package environment markers, which made pip
try to install Windows-only packages (e.g. pywin32) on Linux. `uv export`
preserves markers AND hashes, so pip skips non-matching platforms correctly.

Regenerate after changing/re-locking dependencies (run on enterprise_network so
DNS works), from this directory:

    podman run --rm --network=enterprise_network -v "$PWD":/w -w /w \
      ghcr.io/astral-sh/uv:python3.11-bookworm-slim \
      uv export --frozen --no-dev --no-emit-project \
        --format requirements-txt -o requirements.txt

Then `pip install --require-hashes --no-deps -r requirements.txt` in the Dockerfile
installs the exact locked closure, hash-verified, honoring platform markers.
"""

if __name__ == "__main__":
    print(__doc__)
