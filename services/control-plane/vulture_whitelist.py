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
