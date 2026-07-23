# 0003 — Node and Python version pins

- **Status:** Accepted
- **Date:** 2026-07-23
- **Deciders:** Owner + WS-P0.1
- **Decision refs:** D3, D4

## Context

Every later workstream builds on these two runtimes. Unpinned versions cause
"works on my machine" drift between the dev box, the Oracle VM, and CI.

## Decision

- **Node: 24 (current LTS, "Krypton").** Pinned three ways:
  - `.nvmrc` = `24` (for `nvm use`),
  - `engines.node` in the root `package.json`,
  - `packageManager: pnpm@<version>` so Corepack provisions the exact pnpm.
- **Python: 3.13.** Pinned two ways:
  - `.python-version` = `3.13`,
  - `requires-python = ">=3.13"` in the workspace `pyproject.toml` files.

## Rationale

- Node 24 is the current LTS and matches the installed `v24.14.0`.
- Python 3.13 is stable and broadly supported by mid-2026. **uv provisions the
  pinned interpreter regardless of the host's system Python** (the host here runs
  3.14), so the pin is authoritative and reproducible.
- Volta was considered for Node pinning but skipped — `.nvmrc` + `engines` +
  Corepack cover it without another tool to install on the VM.

## Consequences

- `uv sync` resolves and installs CPython 3.13 into `.venv` even on a 3.14 host.
- If ML libraries in a later workstream lag on 3.13, the owner may drop to 3.12;
  change `.python-version` and `requires-python` together.
