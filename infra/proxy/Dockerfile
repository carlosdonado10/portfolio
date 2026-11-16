# syntax=docker/dockerfile:1
#
# Gateway image: builds the lab UI, then serves it behind nginx. BUILD CONTEXT =
# REPO ROOT (the pnpm workspace is needed to build apps/lab + notify-client):
#   docker build -f infra/proxy/Dockerfile .

FROM node:24-slim AS lab
WORKDIR /repo
# Corepack reads the pnpm version from "packageManager" in the root package.json.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/lab/package.json apps/lab/package.json
COPY packages/notify-client/package.json packages/notify-client/package.json
RUN corepack enable && pnpm install --frozen-lockfile
COPY apps/lab apps/lab
COPY packages/notify-client packages/notify-client
RUN pnpm --filter @portfolio/lab build

FROM nginx:1.27-alpine
COPY --from=lab /repo/apps/lab/dist /usr/share/nginx/html/lab
COPY infra/proxy/nginx.conf /etc/nginx/nginx.conf
COPY infra/proxy/snippets/ /etc/nginx/snippets/
# Generated per-project routes are mounted here by docker-compose.yml.
RUN mkdir -p /etc/nginx/generated
EXPOSE 80
