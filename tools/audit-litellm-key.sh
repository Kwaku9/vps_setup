#!/bin/sh
# audit-litellm-key.sh — audit every consumer of the LiteLLM master key.
#
# Origin: copied verbatim from /root/keyaudit.sh on alpine-vps, committed 2026-08-11.
#
# What it does: resolves the current master key and the salt key from the running
# litellm container's env, then walks every place a key could be hiding —
# container envs (open-webui, session-recall-mcp, telegram-gateway, fabric-api),
# the openwebui.config table in Postgres, and on-disk ingestion scripts — and
# finally probes LiteLLM itself to confirm the old key is rejected (401) and the
# new one accepted (200).
#
# Why it matters: it matches consumers by key VALUE (comparing truncated md5
# hashes), not by key NAME. A hand-written list of "places to update" always
# misses something — an env var named OPENAI_API_KEY, a row buried in the
# openwebui config JSON, a literal pasted into a script. Hashing the value and
# comparing catches those regardless of what they are called.
#
# Safety: prints truncated md5 hashes only, never a plaintext key. Keep it that
# way — do not add an echo of $NEW or $OLD.
#
# Usage: run on the VPS as root:  sh tools/audit-litellm-key.sh
# Audit every consumer of the LiteLLM master key. Hashes only, no plaintext.
set -u
NEW=$(podman inspect litellm --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^LITELLM_MASTER_KEY=//p' | head -1)
OLD=$(podman inspect litellm --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^LITELLM_SALT_KEY=//p'   | head -1)
NH=$(printf '%s' "$NEW" | md5sum | cut -c1-16)
OH=$(printf '%s' "$OLD" | md5sum | cut -c1-16)
echo "NEW key md5 = $NH   (expected everywhere)"
echo "OLD key md5 = $OH   (expected ONLY as the salt)"
echo
chk() { # name, value
  v=$(printf '%s' "$2" | md5sum | cut -c1-16)
  if   [ -z "$2" ];        then echo "  ----  $1: (empty/absent)"
  elif [ "$v" = "$NH" ];   then echo "  OK    $1"
  elif [ "$v" = "$OH" ];   then echo "  STALE $1  <-- still the OLD key"
  else                          echo "  ????  $1: md5=$v (neither)"; fi
}
echo "--- container envs"
chk "litellm LITELLM_MASTER_KEY" "$NEW"
chk "open-webui OPENAI_API_KEYS" "$(podman inspect open-webui --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | sed -n 's/^OPENAI_API_KEYS=//p' | head -1)"
chk "open-webui OPENAI_API_KEY " "$(podman inspect open-webui --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | sed -n 's/^OPENAI_API_KEY=//p' | head -1)"
for c in session-recall-mcp telegram-gateway fabric-api; do
  podman inspect "$c" >/dev/null 2>&1 || continue
  v=$(podman inspect "$c" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -nE 's/^(LITELLM_KEY|LITELLM_API_KEY|OPENAI_API_KEY)=//p' | head -1)
  chk "$c" "$v"
done
echo "--- openwebui DB config (ALL rows whose value hashes to a known key)"
podman exec -i postgres psql -U postgres -d enterprise -tAc \
  "SELECT key || '|' || substr(md5(trim(both '\"' from value::text)),1,16) FROM openwebui.config WHERE value::text <> 'null'" 2>/dev/null \
| while IFS='|' read -r k v; do
    [ "$v" = "$NH" ] && echo "  OK    owui.$k"
    [ "$v" = "$OH" ] && echo "  STALE owui.$k  <-- still the OLD key"
  done
echo "--- on-disk scripts"
for f in /opt/compose/session-ingestion/classify-sessions.py /opt/compose/session-ingestion/daily-ingest.sh; do
  [ -f "$f" ] || continue
  if grep -qF "$NEW" "$f" 2>/dev/null; then echo "  OK    $f"
  elif grep -qF "$OLD" "$f" 2>/dev/null; then echo "  STALE $f  <-- still the OLD key"
  else echo "  ----  $f (no literal key; reads from env)"; fi
done
echo "--- functional: old key must be rejected, new accepted"
echo "  old -> HTTP $(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $OLD" http://127.0.0.1:4000/v1/models)  (want 401)"
echo "  new -> HTTP $(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $NEW" http://127.0.0.1:4000/v1/models)  (want 200)"
