# syntax=docker/dockerfile:1
#
# Agent image (privileged control-tier component). BUILD CONTEXT = REPO ROOT so
# uv can resolve the workspace + shared lockfile:
#   docker build -f services/agent/Dockerfile .
#
# The Docker socket is NOT baked into this image — it is bind-mounted at RUN time
# by docker-compose.yml (the only service granted the socket). Multi-arch base +
# pinned uv resolve on linux/arm64 (Oracle Ampere A1).

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

# Install only the agent package's environment (stdlib-only for now).
RUN uv sync --frozen --package agent

CMD ["uv", "run", "--frozen", "--package", "agent", "python", "-m", "agent"]
