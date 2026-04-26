ARG BASE_IMAGE=ghcr.io/meta-pytorch/openenv-base:latest
FROM ${BASE_IMAGE} AS builder

WORKDIR /app

ARG BUILD_MODE=in-repo

COPY . /app/env

WORKDIR /app/env

RUN if ! command -v uv >/dev/null 2>&1; then \
        curl -LsSf https://astral.sh/uv/install.sh | sh && \
        mv /root/.local/bin/uv /usr/local/bin/uv && \
        mv /root/.local/bin/uvx /usr/local/bin/uvx; \
    fi

RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -f uv.lock ]; then \
        uv sync --frozen --no-install-project --no-editable; \
    else \
        uv sync --no-install-project --no-editable; \
    fi

RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -f uv.lock ]; then \
        uv sync --frozen --no-editable; \
    else \
        uv sync --no-editable; \
    fi

FROM ${BASE_IMAGE}

WORKDIR /app

# Install system tools needed for fault simulation
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    curl \
    procps \
    net-tools \
    sudo \
    && rm -rf /var/lib/apt/lists/*

# Create sre user for sandboxed command execution
RUN useradd -m -s /bin/bash sre && \
    echo "sre ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Set up nginx with default config
RUN mkdir -p /var/log/nginx /var/www/html && \
    echo '<!DOCTYPE html><html><body>OK</body></html>' > /var/www/html/index.html

# Back up nginx configs so restore.sh can always restore them
RUN cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak && \
    cp /etc/nginx/sites-enabled/default /etc/nginx/sites-enabled/default.bak 2>/dev/null || true

# Copy the virtual environment from builder
COPY --from=builder /app/env/.venv /app/.venv

# Copy the environment code
COPY --from=builder /app/env /app/env

# Copy all scripts
COPY scripts/ /app/env/scripts/
RUN chmod +x /app/env/scripts/restore.sh /app/env/scripts/inject/*.sh

# Start nginx before the server
COPY server/startup.sh /startup.sh
RUN chmod +x /startup.sh

# Set PATH to use the virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Set PYTHONPATH so imports work correctly
ENV PYTHONPATH="/app/env:$PYTHONPATH"

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:7860/health || exit 1

CMD ["/startup.sh"]
