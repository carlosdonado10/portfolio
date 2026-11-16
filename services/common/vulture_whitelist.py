"""Vulture whitelist: public schema members consumed by later modules/services.

Pydantic fields and framework hooks are read reflectively, so static analysis
sees them as unused.
"""

# ruff: noqa: B018

from orch_common.manifest import Entry, Health, Manifest
from orch_common.wire import DesiredState, ObservedState, StackStatus

Entry.model_config
Entry.service
Entry.port
Health.model_config
Health.interval_s
Manifest.model_config
Manifest.tagline
Manifest.ref
Manifest.entry
Manifest.expected_boot_s
Manifest.demo_url
Manifest._check_id
StackStatus.STOPPED
StackStatus.STARTING
StackStatus.FAILED
DesiredState.active
DesiredState.generation
ObservedState.stack_id
ObservedState.generation
ObservedState.error
ObservedState.at
