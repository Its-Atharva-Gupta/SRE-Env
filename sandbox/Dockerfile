# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# Sandbox Container for SRE Agents
# This container simulates a broken Linux server that agents SSH into to diagnose faults.
# Includes sshd, nginx, and fault injection scripts.

FROM ubuntu:22.04

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server \
    openssh-client \
    nginx \
    curl \
    wget \
    net-tools \
    procps \
    python3 \
    python3-pip \
    util-linux \
    cron \
    sudo \
    vim-tiny \
    less \
    grep \
    sed \
    gawk \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Create sre user with password 'fix123' and sudo access
RUN useradd -m -s /bin/bash sre && \
    echo "sre:fix123" | chpasswd && \
    usermod -aG sudo sre && \
    echo "sre ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Configure SSH for password authentication
RUN mkdir -p /var/run/sshd && \
    mkdir -p /home/sre/.ssh && \
    chown -R sre:sre /home/sre/.ssh && \
    chmod 700 /home/sre/.ssh && \
    # Enable password authentication
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
    sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
    # Disable root login
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin no/' /etc/ssh/sshd_config && \
    sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config && \
    # Generate host keys if missing
    ssh-keygen -A

# Ensure nginx is properly configured
RUN mkdir -p /var/www/html && \
    echo "<!DOCTYPE html><html><body>OK</body></html>" > /var/www/html/index.html && \
    chown -R www-data:www-data /var/www/html && \
    # Ensure nginx user exists
    id www-data || useradd -r -s /bin/false www-data

# Create fault injection scripts directory
RUN mkdir -p /faults/inject /faults/verify

# Copy fault injection scripts from build context
COPY faults/scripts/inject/ /faults/inject/
RUN chmod +x /faults/inject/*.sh

# Create startup script that initializes the sandbox
RUN cat > /startup.sh << 'STARTUP_EOF'
#!/bin/bash
set -e

echo "=== SRE Sandbox Startup ==="

# Ensure /var/run directories exist
mkdir -p /var/run/sshd
mkdir -p /var/run/nginx

# Start SSH daemon in background
echo "Starting SSH daemon..."
/usr/sbin/sshd -D &
SSH_PID=$!

# Start nginx (allow failure in case of config issues)
echo "Starting nginx..."
service nginx start || true

# Start cron daemon (for cron-related faults)
echo "Starting cron daemon..."
service cron start || true

# Signal that container is ready for agent connection
echo "Container ready"
touch /tmp/ready

# Keep container running while waiting for signals
trap "kill $SSH_PID 2>/dev/null || true" SIGTERM SIGINT
wait $SSH_PID || true
STARTUP_EOF

RUN chmod +x /startup.sh

# Expose SSH port
EXPOSE 22

# Health check: verify SSH is responding
HEALTHCHECK --interval=10s --timeout=3s --start-period=2s --retries=3 \
    CMD test -f /tmp/ready || exit 1

# Run startup script on container start
CMD ["/startup.sh"]
