#!/bin/sh
# Owner-run, ON THE BOX: issue a virtual key for the VPS LiteLLM's calls to
# Stack B, put it in the vault, and deploy the litellm config. The key never
# touches argv or the terminal: it goes LiteLLM -> /dev/shm -> vault helper.
#
#   sh /workspace/vscode-projects/vps_setup/tools/stack-b/connect-vps-litellm.sh
#
# Why a virtual key and not Stack B's master key: both gateways share one key
# store, so a key minted here is valid on Stack B, scoped to the three aliases,
# revocable from either side, and shows up by alias in the ledger.
set -eu
cd /workspace/vscode-projects/vps_setup
M=$(podman exec litellm sh -c 'echo $LITELLM_MASTER_KEY')
# A previous partial run may have minted the alias already: retire it first so
# the vault ends up holding the one key that exists.
podman exec -i litellm python3 - "$M" <<'PY'
import json,sys,urllib.request
req=urllib.request.Request("http://127.0.0.1:4000/key/delete",data=json.dumps({"key_aliases":["vps-litellm-to-stack-b"]}).encode(),headers={"Authorization":"Bearer "+sys.argv[1],"content-type":"application/json"})
try: urllib.request.urlopen(req,timeout=30)
except Exception: pass
PY
KEY=$(podman exec -i litellm python3 - "$M" <<'PY'
import json,sys,urllib.request
req=urllib.request.Request("http://127.0.0.1:4000/key/generate",data=json.dumps({"models":["cand-a","cand-b","cand-b-fallback"],"key_alias":"vps-litellm-to-stack-b","metadata":{"purpose":"VPS LiteLLM upstream credential for Stack B"}}).encode(),headers={"Authorization":"Bearer "+sys.argv[1],"content-type":"application/json"})
print(json.load(urllib.request.urlopen(req,timeout=30))["key"])
PY
)
[ -n "$KEY" ] || { echo "ABORT: no key minted"; exit 1; }
echo "virtual key vps-litellm-to-stack-b issued"
# The vault helper runs inside the ansible-deployment container and reads
# /dev/shm/newkey-value THERE (its /dev/shm is not the host's). Hand the value
# over on stdin; it is never an argument.
printf '%s' "$KEY" | podman exec -i ansible-deployment sh -c 'umask 077; cat > /dev/shm/newkey-value'
unset KEY
podman exec -w /ansible ansible-deployment sh tools/vault/vault_add_key.sh stack_b_gateway_key
podman exec ansible-deployment rm -f /dev/shm/newkey-value
echo "vault updated; deploying litellm"
podman exec -w /ansible ansible-deployment ansible-playbook -i inventory/hosts site.yml --tags litellm > /var/log/litellm-stack-b-connect.log 2>&1
grep -A2 "PLAY RECAP" /var/log/litellm-stack-b-connect.log | tail -2
sleep 15
M=$(podman exec litellm sh -c 'echo $LITELLM_MASTER_KEY')
podman exec -i litellm python3 - "$M" <<'PY'
import json,sys,urllib.request
h={"Authorization":"Bearer "+sys.argv[1],"content-type":"application/json"}
ids=[m["id"] for m in json.load(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:4000/v1/models",headers=h),timeout=30))["data"]]
print("stack-b models listed:", sorted(i for i in ids if i.startswith("stack-b/")))
def chat(model):
    req=urllib.request.Request("http://127.0.0.1:4000/v1/chat/completions",data=json.dumps({"model":model,"max_tokens":6,"temperature":0,"messages":[{"role":"user","content":"Reply with exactly: READY"}]}).encode(),headers=h)
    try: return urllib.request.urlopen(req,timeout=180).status
    except urllib.error.HTTPError as e: return e.code
print("stack-b/cand-b completion ->", chat("stack-b/cand-b"), "(expect 200)")
print("control stack-b/does-not-exist ->", chat("stack-b/does-not-exist"), "(expect 400 or 404)")
PY
