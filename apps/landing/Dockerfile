# syntax=docker/dockerfile:1
#
# Landing image. BUILD CONTEXT = REPO ROOT (workspace-aware) so pnpm can resolve
# the workspace + lockfile:
#   docker build -f apps/landing/Dockerfile .
# Multi-arch base images resolve on linux/arm64 (Oracle Ampere A1).

# ---- build stage: compile the Vite app with pnpm ----
FROM node:24-slim AS build
WORKDIR /app

# Use the pnpm version pinned in package.json's "packageManager" via Corepack.
RUN corepack enable

# Copy manifests first so the install layer caches independently of source.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/landing/package.json apps/landing/package.json
COPY packages/design-system/package.json packages/design-system/package.json
COPY packages/notify-client/package.json packages/notify-client/package.json

# Install just the landing app and its workspace dependencies.
RUN pnpm install --frozen-lockfile --filter @portfolio/landing...

# Bring in the sources and build to apps/landing/dist.
COPY apps/landing apps/landing
COPY packages packages
RUN pnpm --filter @portfolio/landing build

# ---- serve stage: static files behind nginx ----
FROM nginx:alpine AS serve
COPY apps/landing/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/landing/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
