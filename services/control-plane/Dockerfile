# syntax=docker/dockerfile:1
#
# Control-plane image (web-facing FastAPI). BUILD CONTEXT = REPO ROOT so uv can
# resolve the workspace + shared lockfile:
#   docker build -f services/control-plane/Dockerfile .
#
# SECURITY: this image and its compose service NEVER mount the Docker socket.
# Multi-arch base + pinned uv resolve on linux/arm64 (Oracle Ampere A1).

FROM python:3.13-slim
WORKDIR /app

# Pinned uv binary (matches the dev toolchain).
COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Workspace resolution needs the root manifest, the lockfile, and every member.
COPY pyproject.toml uv.lock .python-version ./
COPY services/common services/common
COPY services/control-plane services/control-plane
COPY services/agent services/agent

# Install only the control-plane package's environment (agent code not installed).
RUN uv sync --frozen --no-dev --package control-plane

# Non-root runtime user; /data holds the SQLite file (mount a volume here).
RUN useradd --system --uid 10001 --no-create-home orch \
    && mkdir /data \
    && chown orch:orch /data
USER orch

# 8000 public (proxied by nginx), 8001 agent API (orch-internal only).
EXPOSE 8000 8001
# uv is build-time only: running it as non-root would write its cache/venv.
CMD ["/app/.venv/bin/python", "-m", "control_plane.main"]
