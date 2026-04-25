# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

# SRE Environment Docker image
# Sandbox for agent to SSH into and debug faults

FROM ubuntu:22.04

WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server \
    nginx \
    curl \
    net-tools \
    procps \
    python3 \
    util-linux \
    && rm -rf /var/lib/apt/lists/*

# Create sre user with password 'fix123'
RUN useradd -m -s /bin/bash sre && \
    echo "sre:fix123" | chpasswd && \
    usermod -aG sudo sre

# Configure SSH
RUN mkdir -p /var/run/sshd && \
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin no/' /etc/ssh/sshd_config && \
    sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config

# Create faults directory structure
RUN mkdir -p /faults/inject /faults/verify

# Copy fault injection scripts
COPY faults/scripts/inject/ /faults/inject/

# Create startup script
RUN cat > /startup.sh << 'EOF'
#!/bin/bash
set -e

# Start SSH
/usr/sbin/sshd -D &
SSH_PID=$!

# Start nginx
service nginx start || true

# Signal readiness
touch /tmp/ready

# Wait for SSH to exit
wait $SSH_PID
EOF

RUN chmod +x /startup.sh

# Expose SSH port
EXPOSE 22

# Run startup script
CMD ["/startup.sh"]
