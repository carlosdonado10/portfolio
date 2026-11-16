# syntax=docker/dockerfile:1
#
# Lab image. BUILD CONTEXT = REPO ROOT (workspace-aware) so pnpm can resolve
# the workspace + lockfile:
#   docker build -f apps/lab/Dockerfile .
# Multi-arch base images resolve on linux/arm64 (Oracle Ampere A1).

# ---- build stage: compile the Vite app with pnpm ----
FROM node:24-slim AS build
WORKDIR /app

# Use the pnpm version pinned in package.json's "packageManager" via Corepack.
RUN corepack enable

# Copy manifests first so the install layer caches independently of source.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/lab/package.json apps/lab/package.json
COPY packages/notify-client/package.json packages/notify-client/package.json

# Install just the lab app and its workspace dependencies.
RUN pnpm install --frozen-lockfile --filter @portfolio/lab...

# Bring in the sources and build to apps/lab/dist.
COPY apps/lab apps/lab
COPY packages packages
RUN pnpm --filter @portfolio/lab build

# ---- serve stage: static files behind nginx ----
FROM nginx:alpine AS serve
COPY apps/lab/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/lab/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
