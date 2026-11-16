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
from control_plane.store import Store  # noqa: E402

Engine.wait_desired
Engine.run_ticks
Engine.load
Engine.state
Engine.flush
Store.ensure_session
Store.log_visit
Store.list_sessions
Store.set_email
Settings.db_path
Settings.projects_dir
Settings.repos_dir
Settings.include_hidden
Settings.cookie_secret
Settings.cookie_secure
Settings.owner_secret
Settings.resend_api_key
Settings.email_from
Settings.public_base_url

import sqlite3  # noqa: E402

sqlite3.Connection.row_factory
