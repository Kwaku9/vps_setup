# Ansible deployment container.
#
# Runs Ansible itself inside a container on the VPS. Mounts the repo at
# /ansible and uses the host's podman socket + SSH keys to act as the
# Ansible controller for the same host. Invoked via
#     podman exec ansible-deployment ansible-playbook -i inventory/hosts site.yml --vault-password-file .vault_pass
#
# Deployed by roles/management/tasks/main.yml.

FROM python:3.12-alpine

# ── OS tooling ─────────────────────────────────────────────────────
# openssh-client / sshpass: Ansible SSH transport
# git / rsync: git ops and synchronize: module
# bash: some tasks assume /bin/bash exists
# jq / bind-tools: debugging from inside the container
RUN apk add --no-cache \
    bash \
    openssh-client \
    sshpass \
    git \
    rsync \
    curl \
    ca-certificates \
    gnupg \
    jq \
    bind-tools \
    postgresql-client

# ── Python packages ────────────────────────────────────────────────
# ansible: full distribution (includes community.general, containers.podman,
#          community.postgresql, etc.)
# cryptography: vault, SSH key handling
# passlib: the `password_hash` filter for crypt()
# jmespath: the `json_query` filter
# netaddr: network-address filters
# requests / kubernetes: modules used by a few roles
RUN pip install --no-cache-dir \
    "ansible>=13.2.0" \
    "ansible-lint" \
    "cryptography>=46.0" \
    "passlib" \
    "jmespath" \
    "netaddr" \
    "requests" \
    "kubernetes"

WORKDIR /ansible

ENV ANSIBLE_HOST_KEY_CHECKING=False \
    ANSIBLE_FORCE_COLOR=true \
    ANSIBLE_RETRY_FILES_ENABLED=False \
    ANSIBLE_CALLBACK_RESULT_FORMAT=yaml \
    ANSIBLE_STDOUT_CALLBACK=default \
    PYTHONUNBUFFERED=1

# Long-running container. Ansible runs via `podman exec`.
CMD ["/bin/bash", "-c", "echo 'ansible-deployment ready'; exec sleep infinity"]
