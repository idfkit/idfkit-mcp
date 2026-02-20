FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1
WORKDIR /app

COPY pyproject.toml uv.lock README.md /app/
COPY src /app/src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime-base

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    IDFKIT_MCP_TRANSPORT=streamable-http \
    IDFKIT_MCP_HOST=0.0.0.0 \
    IDFKIT_MCP_PORT=8000

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENTRYPOINT ["idfkit-mcp"]

FROM runtime-base AS sim

USER root
ARG ENERGYPLUS_TARBALL_URL
ARG ENERGYPLUS_TARBALL_SHA256

RUN test -n "$ENERGYPLUS_TARBALL_URL" || (echo "ENERGYPLUS_TARBALL_URL is required for sim target" && exit 1)

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates wget libx11-6 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN wget -O /tmp/energyplus.tar.gz "$ENERGYPLUS_TARBALL_URL" \
    && if [ -n "$ENERGYPLUS_TARBALL_SHA256" ]; then echo "$ENERGYPLUS_TARBALL_SHA256  /tmp/energyplus.tar.gz" | sha256sum -c -; fi \
    && mkdir -p /opt/EnergyPlus \
    && tar -xzf /tmp/energyplus.tar.gz -C /opt/EnergyPlus --strip-components=1 \
    && rm -f /tmp/energyplus.tar.gz \
    && test -x /opt/EnergyPlus/energyplus \
    && /opt/EnergyPlus/energyplus --version >/dev/null \
    && chown -R appuser:appuser /opt/EnergyPlus

ENV ENERGYPLUS_DIR=/opt/EnergyPlus \
    PATH="/opt/EnergyPlus:${PATH}"

USER appuser

FROM runtime-base AS runtime
