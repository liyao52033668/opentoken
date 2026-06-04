# ============================================================
# OpenToken Dockerfile — with Camoufox browser runtime
# ============================================================

# ---- Stage 1: builder ----
FROM python:3.13-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /build

# Copy dependency metadata first for better layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (no dev extras) into a virtualenv
RUN uv sync --frozen --no-dev --no-install-project

# Copy project source and install the project itself
COPY src/ src/
RUN uv sync --frozen --no-dev

# ---- Stage 2: runtime ----
FROM python:3.13-slim AS runtime

# Camoufox (Firefox-based) needs these system libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 \
    libatspi2.0-0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
    libasound2t64 libx11-xcb1 fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Install uv (needed for `uv run` at runtime)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Create non-root user
RUN groupadd -r opentoken && useradd -r -g opentoken -m opentoken

WORKDIR /app

# Copy the virtualenv from builder
COPY --from=builder /build/.venv /app/.venv

# Copy project source and dependency metadata
COPY --from=builder /build/src /app/src
COPY pyproject.toml uv.lock config.yaml ./

# Fetch Camoufox browser runtime into the image
RUN uv run python -m camoufox fetch

# Own everything by opentoken user
RUN chown -R opentoken:opentoken /app

USER opentoken

# Default data/config directory (mount a volume here to persist sessions)
VOLUME ["/app/data"]

EXPOSE 32117

# Health-check: hit the /health endpoint every 30s
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:32117/health')" || exit 1

# Start the gateway server (override host to 0.0.0.0 for container networking)
CMD ["uv", "run", "opentoken", "start", "--host", "0.0.0.0", "--port", "32117"]
