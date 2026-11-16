"""Vulture whitelist: lease interface surface consumed by later modules.

The service layer (persistence, effect execution) is built on these names;
static analysis can't see those users yet.
"""

# ruff: noqa: B018

from control_plane.lease import Lease, LeaseConfig, QueueEntry

LeaseConfig.idle_s
LeaseConfig.presence_s
Lease.last_activity
QueueEntry.last_seen

# Consumed by the HTTP/SSE/agent layers (later tasks).
from control_plane.engine import Engine  # noqa: E402
from control_plane.settings import Settings  # noqa: E402

Engine.flush
Settings.repos_dir

import sqlite3  # noqa: E402

sqlite3.Connection.row_factory
