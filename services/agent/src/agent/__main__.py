"""Agent entrypoint — emits a heartbeat until interrupted.

Scaffold scope (WS-P0.1): a liveness loop proving the agent runs under uv (native
dev) and inside its container. The real work — reading intents from Supabase and
bringing the ML app stacks up/down via the bind-mounted Docker socket — lands in
WS3. This module deliberately depends on the standard library only.
"""

from __future__ import annotations

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("agent")

HEARTBEAT_INTERVAL_SECONDS = 30.0


def heartbeat_message(beat: int) -> str:
    """Format the log line for a given heartbeat number."""
    return f"agent alive — heartbeat #{beat}"


def run(
    interval: float = HEARTBEAT_INTERVAL_SECONDS,
    max_beats: int | None = None,
) -> None:
    """Emit heartbeats forever (``max_beats=None``) or a bounded number.

    ``max_beats`` bounds the loop so it is testable; production runs unbounded.
    """
    import time

    beat = 0
    while True:
        beat += 1
        logger.info(heartbeat_message(beat))
        if max_beats is not None and beat >= max_beats:
            return
        time.sleep(interval)


if __name__ == "__main__":  # pragma: no cover
    try:
        run()
    except KeyboardInterrupt:
        logger.info("agent shutting down")
