#!/bin/bash
# Ansible Container Entrypoint
# Sets up SSH keys with proper permissions on container start

set -e

# Copy SSH keys from mounted volume to writable location
if [ -d "/tmp/host-ssh" ]; then
    echo "Setting up SSH keys..."
    mkdir -p /root/.ssh
    cp -r /tmp/host-ssh/* /root/.ssh/ 2>/dev/null || true

    # Set proper permissions
    chmod 700 /root/.ssh
    chmod 600 /root/.ssh/id_* 2>/dev/null || true
    chmod 644 /root/.ssh/*.pub 2>/dev/null || true
    chmod 644 /root/.ssh/known_hosts 2>/dev/null || true
    chmod 644 /root/.ssh/config 2>/dev/null || true

    echo "✓ SSH keys configured with proper permissions"
else
    echo "⚠ Warning: No SSH keys found at /tmp/host-ssh"
fi

# Ensure Ansible vault password file has secure permissions
if [ -f "/ansible/.vault_pass" ]; then
    echo "Setting up vault password file..."
    chmod 600 /ansible/.vault_pass
    echo "✓ Vault password file secured (permissions: 600)"
else
    echo "⚠ Warning: No vault password file found at /ansible/.vault_pass"
    echo "  You will need to use --ask-vault-pass for encrypted vaults"
fi

# Execute the command passed to the container
exec "$@"
