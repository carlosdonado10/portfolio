"""Vulture whitelist: lease interface surface consumed by later modules.

The service layer (persistence, effect execution) and the idle/presence/admin
rules are built on these names; static analysis can't see those users yet.
"""

# ruff: noqa: B018

from control_plane.lease import (
    Activity,
    AdminClearQueue,
    AdminForceStop,
    EmailAttached,
    Lease,
    LeaseConfig,
    QueueEntry,
    Seen,
)

LeaseConfig.idle_s
LeaseConfig.presence_s
Lease.last_activity
QueueEntry.last_seen
Activity.sid
Seen.sid
EmailAttached.sid
AdminForceStop.now
AdminClearQueue.now
