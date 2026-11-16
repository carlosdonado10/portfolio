"""Internal agent API (port 8001, reachable only on the private network).

The agent long-polls for desired state and reports observed state.
"""

import time
from collections.abc import Callable

from fastapi import FastAPI, Response
from orch_common.wire import DesiredState, ObservedState

from control_plane.engine import Engine
from control_plane.lease import Observed

POLL_TIMEOUT_S = 25.0


def create_agent_app(
    engine: Engine,
    clock: Callable[[], float] = time.time,
    poll_timeout: float = POLL_TIMEOUT_S,
) -> FastAPI:
    app = FastAPI(title="Portfolio Control Plane (agent)", version="0.1.0")

    @app.get("/agent/desired")
    async def desired(after_generation: int) -> DesiredState:
        return await engine.wait_desired(after_generation, poll_timeout)

    @app.post("/agent/observed", status_code=204)
    async def observed(body: ObservedState) -> Response:
        # Server time, not the agent's `at`. STOPPED with nothing desired has no
        # stack; the lease machine only compares stack_id on READY/FAILED.
        await engine.dispatch(
            Observed(body.stack_id or "", body.status, body.generation, clock(), body.error)
        )
        return Response(status_code=204)

    return app
