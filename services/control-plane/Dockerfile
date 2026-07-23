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
COPY services/control-plane services/control-plane
COPY services/agent services/agent

# Install only the control-plane package's environment (agent code not installed).
RUN uv sync --frozen --package control-plane

EXPOSE 8000
CMD ["uv", "run", "--frozen", "--package", "control-plane", \
     "uvicorn", "control_plane.app:app", "--host", "0.0.0.0", "--port", "8000"]
