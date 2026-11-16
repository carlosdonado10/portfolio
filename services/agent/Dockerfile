# syntax=docker/dockerfile:1
#
# Agent image (privileged control-tier component). BUILD CONTEXT = REPO ROOT so
# uv can resolve the workspace + shared lockfile:
#   docker build -f services/agent/Dockerfile .
#
# This container runs as ROOT on purpose: it must read/write the bind-mounted Docker
# socket, and access to that socket is root-equivalent on the host anyway. That is why
# the agent is the only service with the socket and has no inbound network surface.
# The Docker socket is NOT baked into this image — it is bind-mounted at RUN time
# by docker-compose.yml (the only service granted the socket). Multi-arch base +
# pinned uv resolve on linux/arm64 (Oracle Ampere A1).

FROM python:3.13-slim
WORKDIR /app

# Static docker CLI + compose plugin (multi-arch) from the official CLI image; far
# lighter than Debian's docker.io. The agent shells out to `docker compose`.
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker:27-cli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose

# Pinned uv binary (matches the dev toolchain).
COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Workspace resolution needs the root manifest, the lockfile, and every member.
COPY pyproject.toml uv.lock .python-version ./
COPY services/common services/common
COPY services/control-plane services/control-plane
COPY services/agent services/agent

# Install only the agent package's environment.
RUN uv sync --frozen --no-dev --package agent

CMD ["/app/.venv/bin/python", "-m", "agent"]
