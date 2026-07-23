"""Control-plane FastAPI application.

Scaffold scope (WS-P0.1): a single liveness endpoint proving the service runs
under uv (native dev) and inside its container. Intents/auth/state wiring against
managed Supabase lands in later workstreams.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="Portfolio Control Plane", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Returns ``{"status": "ok"}`` when the API is up."""
    return {"status": "ok"}
