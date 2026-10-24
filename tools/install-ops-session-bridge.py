#!/usr/bin/env python3
"""Privileged bootstrap for the single OPS bridge service.

Run via sudo/pkexec, pipe the derived bridge token on stdin. No plaintext token
is written to disk. User-owned script and isolated venv must already be installed.
Subsequent updates can use ops-workstation.yml with become enabled.
"""
import argparse
import os
import pwd
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True, help='Tailnet HTTPS origin, including port')
    url = parser.parse_args().url.rstrip('/')
    from urllib.parse import urlsplit
    endpoint = urlsplit(url)
    if endpoint.scheme != 'https' or not endpoint.hostname or endpoint.path or endpoint.query or endpoint.fragment or endpoint.username or '\n' in url:
        raise SystemExit('Expected an HTTPS origin without a path or credentials.')
    if os.geteuid() != 0:
        raise SystemExit("Run this installer with sudo or pkexec.")
    uid = int(os.environ.get("PKEXEC_UID") or os.environ.get("SUDO_UID") or "0")
    if uid == 0:
        raise SystemExit("Invoke from the desktop account through sudo/pkexec; the bridge must not run as root.")
    account = pwd.getpwuid(uid)
    home = account.pw_dir
    python = Path(home) / ".local/share/ops-session-bridge/venv/bin/python"
    observer = Path(home) / ".local/bin/ops-session-bridge.py"
    if not python.is_file() or not observer.is_file():
        raise SystemExit("Install the user-owned observer and venv first.")
    token = sys.stdin.buffer.read(256).strip()
    if len(token) != 64 or any(c not in b"0123456789abcdef" for c in token):
        raise SystemExit("Expected the 64-character derived bridge token on stdin.")
    directory = Path("/etc/credstore.encrypted")
    directory.mkdir(mode=0o700, exist_ok=True)
    temporary = directory / "ops-session-token.new"
    subprocess.run(["systemd-creds", "--with-key=tpm2", "--name=ops-session-token",
                    "encrypt", "-", str(temporary)], input=token, check=True)
    temporary.chmod(0o600)
    temporary.replace(directory / "ops-session-token")
    template = Path(__file__).parents[1] / "roles/workstation/templates/systemd/ops-session-bridge.service"
    unit = template.read_text().replace("{{ ops_bridge_user }}", account.pw_name)
    unit = unit.replace("{{ ops_bridge_home }}", home)
    unit = unit.replace("{{ ops_bridge_url }}", url)
    destination = Path("/etc/systemd/system/ops-session-bridge.service")
    destination.write_text(unit)
    destination.chmod(0o644)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", "ops-session-bridge.service"], check=True)
    subprocess.run(["systemctl", "restart", "ops-session-bridge.service"], check=True)
    print("TPM-sealed OPS bridge installed, enabled, and running as " + account.pw_name)


if __name__ == "__main__":
    main()
