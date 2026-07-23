# 0001 — Vite (`react-ts`) over Create React App for the landing app

- **Status:** Accepted
- **Date:** 2026-07-23
- **Deciders:** Owner + WS-P0.1
- **Decision ref:** D1

## Context

The landing app (`apps/landing`) needs a React + TypeScript build toolchain. The
two obvious candidates are Create React App (CRA) and Vite's `react-ts` template.

## Decision

Use **Vite** with the `react-ts` template.

## Rationale

- **CRA is deprecated.** The React team stopped recommending CRA in 2025 and it
  is effectively unmaintained. It pulls a large, dated dependency tree.
- **Toolchain friction.** CRA (react-scripts / webpack 4-era tooling) interacts
  poorly with recent Node LTS releases and with pnpm's strict, symlinked
  `node_modules` layout — the exact combination this repo standardizes on
  (Node 24 + pnpm, see [0003](0003-node-and-python-version-pins.md)).
- **Vite fits the workspace.** Fast dev server (native ESM + esbuild), first-class
  TypeScript, trivial static build (`dist/`) that drops cleanly into an
  `nginx:alpine` production image (see
  [0004](0004-docker-compose-topology-and-socket-isolation.md)).

## Consequences

- Dev server via `vite` (`pnpm --filter @portfolio/landing dev`), production build
  via `vite build` → `dist/`.
- Config lives in `vite.config.ts`; no `react-scripts` eject path to worry about.
- If a future app needs SSR/routing beyond a static landing page, revisit with a
  framework (e.g. Next/Remix) rather than reaching back to CRA.
