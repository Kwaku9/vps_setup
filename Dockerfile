# Lightweight Ansible Container for Alpine Podman Enterprise Stack
# Optimized for minimal size and all required dependencies

FROM python:3.12-alpine

# Metadata
LABEL maintainer="vps-setup"
LABEL description="Ansible container for Alpine Linux Podman deployments"
LABEL version="2.1"

# Install system dependencies and build tools
RUN apk add --no-cache \
    openssh-client \
    sshpass \
    git \
    rsync \
    bash \
    curl \
    ca-certificates \
    gcc \
    musl-dev \
    python3-dev \
    libffi-dev \
    && rm -rf /var/cache/apk/*

# Install Ansible and required Python packages (latest stable versions)
RUN pip install --no-cache-dir \
    ansible==13.2.0 \
    ansible-core>=2.20 \
    ansible-lint \
    jinja2 \
    netaddr \
    paramiko \
    passlib \
    && rm -rf /root/.cache/pip

# Set up working directory
WORKDIR /ansible

# Copy Ansible configuration and requirements
COPY ansible.cfg .
COPY requirements.yml .

# Install required Ansible collections
RUN ansible-galaxy collection install -r requirements.yml

# Copy playbook files
COPY *.yml ./
COPY *.j2 ./

# Copy inventory directory
COPY inventory ./inventory

# Create SSH directory
RUN mkdir -p /root/.ssh && \
    chmod 700 /root/.ssh

# Set environment variables
ENV ANSIBLE_HOST_KEY_CHECKING=False \
    ANSIBLE_RETRY_FILES_ENABLED=False \
    ANSIBLE_STDOUT_CALLBACK=default \
    ANSIBLE_CALLBACK_RESULT_FORMAT=yaml \
    ANSIBLE_FORCE_COLOR=true \
    PYTHONUNBUFFERED=1

# Copy entrypoint script
COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Use entrypoint to set up SSH keys on container start
ENTRYPOINT ["/entrypoint.sh"]

# Default to bash shell with help message
CMD ["/bin/bash", "-c", "echo -e '\\n\\033[1;36m=== Ansible Container Ready! ===\\033[0m\\n\\n\\033[1mCommon Commands:\\033[0m\\n  ansible-playbook -i hosts site.yml\\n  ansible-playbook -i hosts site.yml --tags \"base,podman\"\\n  ansible-playbook -i hosts site.yml --ask-vault-pass\\n  ansible -i hosts alpine_servers -m ping\\n  ansible-vault view vault.yml\\n  ansible-galaxy collection list\\n\\n\\033[1mMounted Directories:\\033[0m\\n  /ansible - Playbooks and configs\\n  /mnt/c/Users/swirl/VScdeProjects - VSCode projects\\n  /mnt/c/Users/swirl/PycharmProjects - PyCharm projects\\n\\n\\033[1mInteractive Shell:\\033[0m\\n  docker exec -it ansible-deployment bash\\n'"]
