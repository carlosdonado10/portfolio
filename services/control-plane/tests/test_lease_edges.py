import json
from dataclasses import replace

import pytest
from control_plane.lease import (
    Activity,
    AdminClearQueue,
    AdminForceStop,
    Broadcast,
    Email,
    EmailAttached,
    LeaseConfig,
    LeaveQueue,
    Notify,
    Observed,
    Rejected,
    Seen,
    SetDesired,
    StartRequested,
    State,
    Tick,
    decide,
)
from orch_common.wire import StackStatus

CFG = LeaseConfig()


def run(state, *events):
    effects = []
    for event in events:
        t = decide(state, event, CFG)
        state = t.state
        effects.extend(t.effects)
    return state, effects


def kinds(effects, cls=Notify):
    return [(e.sid, e.kind) for e in effects if isinstance(e, cls)]


def ready(state, stack, now):
    return Observed(stack, StackStatus.READY, state.generation, now)


def ready_a(**kw):
    s, _ = run(State(), StartRequested("A", "a", 0, **kw))
    s, _ = run(s, ready(s, "a", 0))
    return s


def test_idle_holder_forfeits_when_someone_queued():
    s = ready_a()
    s, _ = run(s, StartRequested("B", "b", 10, has_email=True))
    s, fx = run(s, Tick(180))
    assert s.lease.grace_deadline == 360
    assert ("A", "grace_started") in kinds(fx)


def test_idle_holder_kept_when_queue_empty():
    s, _ = run(ready_a(), Tick(5000))
    assert s.lease.grace_deadline is None


def test_activity_resets_idle():
    s, _ = run(ready_a(), StartRequested("B", "b", 10, has_email=True), Activity("A", 170))
    s, _ = run(s, Tick(200))
    assert len(s.queue) == 1
    assert s.lease.grace_deadline is None


def test_seen_does_not_count_as_holder_activity():
    s, _ = run(ready_a(), StartRequested("B", "b", 10), Seen("A", 170), Seen("B", 170))
    assert s.lease.last_activity == 0
    assert s.queue[0].last_seen == 170
    s, _ = run(s, Tick(180))
    assert s.lease.grace_deadline == 360


def test_activity_updates_queued_last_seen():
    s, _ = run(ready_a(), StartRequested("B", "b", 10), Activity("B", 50))
    assert s.queue[0].last_seen == 50


def test_unknown_sid_events_are_noops():
    s, _ = run(ready_a(), StartRequested("B", "b", 10))
    for ev in (Activity("Z", 5), Seen("Z", 5), EmailAttached("Z", 5)):
        t = decide(s, ev, CFG)
        assert t.state == s
        assert t.effects == ()


def test_email_attached_to_holder_and_queued():
    s, _ = run(ready_a(), StartRequested("B", "b", 10))
    s, _ = run(s, EmailAttached("A", 11), EmailAttached("B", 12))
    assert s.lease.has_email
    assert s.queue[0].has_email


def test_grace_cancelled_when_queue_empties():
    s, _ = run(ready_a(), StartRequested("B", "b", 10), Activity("A", 889), Seen("B", 890))
    s, _ = run(s, Tick(900))
    assert s.lease.grace_deadline == 1080
    s, fx = run(s, Tick(1011))
    assert s.queue == ()
    assert s.lease.grace_deadline is None
    assert ("A", "grace_cancelled") in kinds(fx)
    assert s.lease.sid == "A"


def test_presence_drop_and_grace_deadline_same_tick_cancels_not_evicts():
    s, _ = run(ready_a(), StartRequested("B", "b", 10), Activity("A", 889), Seen("B", 890))
    s, _ = run(s, Tick(900))
    assert s.lease.grace_deadline == 1080
    s, fx = run(s, Tick(1080))
    assert s.queue == ()
    assert s.lease.sid == "A"
    assert s.lease.grace_deadline is None
    assert ("A", "grace_cancelled") in kinds(fx)
    assert ("A", "evicted") not in kinds(fx)
    assert not [e for e in fx if isinstance(e, SetDesired)]


def test_presence_drop_without_email():
    s, _ = run(ready_a(), StartRequested("B", "b", 0))
    s, fx = run(s, Tick(120))
    assert len(s.queue) == 1
    s, fx = run(s, Tick(121))
    assert s.queue == ()
    assert Broadcast("queue_changed") in fx


def test_presence_kept_with_email():
    s, _ = run(ready_a(), StartRequested("B", "b", 0, has_email=True))
    s, _ = run(s, Tick(10_000))
    assert len(s.queue) == 1


def test_failed_boot_notifies_emails_and_promotes():
    s, _ = run(State(), StartRequested("A", "a", 0, has_email=True), StartRequested("B", "b", 1))
    s, fx = run(s, Observed("a", StackStatus.FAILED, s.generation, 5, error="boom"))
    assert Notify("A", "stack_failed", {"error": "boom"}) in fx
    assert Email("A", "stack_failed", "a") in fx
    assert s.lease.sid == "B"
    assert SetDesired("b", 2) in fx
    assert s.status == StackStatus.STARTING


def test_failed_without_email_or_queue_releases():
    s, _ = run(State(), StartRequested("A", "a", 0))
    s, fx = run(s, Observed("a", StackStatus.FAILED, s.generation, 5, error="boom"))
    assert not [e for e in fx if isinstance(e, Email)]
    assert s.lease is None
    assert SetDesired(None, 2) in fx


def test_failed_with_same_stack_queued_restarts_not_transfers():
    s, _ = run(State(), StartRequested("A", "a", 0), StartRequested("B", "a", 1))
    s, fx = run(s, Observed("a", StackStatus.FAILED, s.generation, 5, error="x"))
    assert s.lease.sid == "B"
    assert SetDesired("a", 2) in fx
    assert s.status == StackStatus.STARTING


def test_failed_stale_or_wrong_stack_ignored():
    s, _ = run(State(), StartRequested("A", "a", 0))
    for ev in (
        Observed("a", StackStatus.FAILED, 99, 5),
        Observed("zzz", StackStatus.FAILED, s.generation, 5),
    ):
        assert decide(s, ev, CFG).state == s
    assert decide(State(), Observed("a", StackStatus.FAILED, 0, 5), CFG).state == State()


def test_switch_keeps_remaining_window():
    s = ready_a()
    gen = s.generation
    s, fx = run(s, StartRequested("A", "b", 600))
    assert s.status == StackStatus.STARTING
    assert s.generation == gen + 1
    assert s.lease.stack_id == "b"
    assert s.lease.window_remaining_s == 300
    assert s.lease.window_ends_at is None
    assert SetDesired("b", gen + 1) in fx
    assert ("A", "stack_starting") in kinds(fx)
    assert Broadcast("queue_changed") in fx
    s, _ = run(s, ready(s, "b", 700))
    assert s.status == StackStatus.READY
    assert s.lease.window_ends_at == 1000


def test_switch_while_starting_keeps_frozen_window():
    s, _ = run(State(), StartRequested("A", "a", 0))
    s, _ = run(s, StartRequested("A", "b", 5))
    assert s.lease.window_remaining_s == 900
    assert s.lease.stack_id == "b"


def test_switch_during_grace_rejected_409():
    s, _ = run(ready_a(), StartRequested("B", "b", 10, has_email=True), Tick(900))
    with pytest.raises(Rejected) as ei:
        decide(s, StartRequested("A", "c", 950), CFG)
    assert ei.value.status == 409
    assert "waiting" in ei.value.reason


def test_no_grace_while_starting():
    s = ready_a()
    s, _ = run(s, StartRequested("A", "b", 600), StartRequested("B", "c", 610, has_email=True))
    s, fx = run(s, Tick(950))
    assert len(s.queue) == 1
    assert s.status == StackStatus.STARTING
    assert s.lease.grace_deadline is None
    assert ("A", "grace_started") not in kinds(fx)


def test_admin_force_stop_promotes():
    s, _ = run(ready_a(), StartRequested("B", "b", 10))
    s, fx = run(s, AdminForceStop(20))
    assert kinds(fx)[0] == ("A", "evicted")
    assert s.lease.sid == "B"
    assert SetDesired("b", 2) in fx


def test_admin_force_stop_without_lease_is_noop():
    t = decide(State(), AdminForceStop(1), CFG)
    assert t.state == State()
    assert t.effects == ()


def test_admin_clear_queue():
    s, _ = run(ready_a(), StartRequested("B", "b", 10), StartRequested("C", "c", 11))
    s, fx = run(s, AdminClearQueue(20))
    assert s.queue == ()
    assert ("B", "queue_changed") in kinds(fx)[-3:]
    assert ("C", "queue_changed") in kinds(fx)[-3:]
    assert Broadcast("queue_changed") in fx
    assert s.lease.sid == "A"


def test_admin_clear_queue_empty_is_noop():
    s = ready_a()
    t = decide(s, AdminClearQueue(1), CFG)
    assert t.state == s
    assert t.effects == ()


# -- leave the queue (I1) ----------------------------------------------------


def test_leave_queue_removes_entry_and_notifies():
    s, _ = run(State(), StartRequested("A", "a", 0), StartRequested("B", "b", 1))
    s, fx = run(s, LeaveQueue("B", 2))
    assert s.queue == ()
    assert ("B", "queue_changed") in kinds(fx)
    assert Broadcast() in fx
    assert s.lease.sid == "A"


def test_leave_queue_when_not_queued_is_noop():
    s, _ = run(State(), StartRequested("A", "a", 0))
    t = decide(s, LeaveQueue("Z", 2), CFG)
    assert t.state == s
    assert t.effects == ()
    # The holder is not queued either: leaving never stops their stack.
    t = decide(s, LeaveQueue("A", 2), CFG)
    assert t.state == s
    assert t.effects == ()


def test_leave_queue_cancels_grace_when_last_waiter_leaves():
    s, _ = run(State(), StartRequested("A", "a", 0))
    s, _ = run(s, ready(s, "a", 0), StartRequested("B", "b", 1, has_email=True), Tick(900))
    assert s.lease.grace_deadline is not None
    s, fx = run(s, LeaveQueue("B", 901))
    assert s.lease.grace_deadline is None
    assert ("A", "grace_cancelled") in kinds(fx)


# -- same-stack promote emails stack_ready (I2) ------------------------------


def test_same_stack_promote_emails_stack_ready_to_emailed_head():
    s, _ = run(State(), StartRequested("A", "a", 0))
    s, _ = run(s, ready(s, "a", 0), StartRequested("B", "a", 1, has_email=True), Tick(900))
    s, fx = run(s, Tick(1080))
    assert Email("B", "stack_ready", "a") in fx


def test_same_stack_promote_without_email_sends_none():
    s, _ = run(State(), StartRequested("A", "a", 0))
    s, _ = run(s, ready(s, "a", 0), StartRequested("B", "a", 1), Tick(900))
    s, fx = run(s, Tick(1080))
    assert [e for e in fx if isinstance(e, Email)] == []


# -- boot watchdog (I4b) -----------------------------------------------------

WATCHDOG = LeaseConfig(boot_watchdog_s=100)


def test_starting_since_set_on_start_switch_and_promote():
    s, _ = run(State(), StartRequested("A", "a", 5))
    assert s.lease.starting_since == 5
    s, _ = run(s, ready(s, "a", 6), StartRequested("A", "b", 7))
    assert s.lease.starting_since == 7
    s, _ = run(s, StartRequested("B", "c", 8, has_email=True), ready(s, "b", 9), Tick(9 + 900))
    s, _ = run(s, Tick(9 + 900 + 180))
    assert s.lease.sid == "B"
    assert s.status == StackStatus.STARTING
    assert s.lease.starting_since == 9 + 900 + 180


def test_watchdog_fails_stuck_boot_and_promotes():
    s = decide(State(), StartRequested("A", "a", 0, has_email=True), WATCHDOG).state
    s = decide(s, StartRequested("B", "b", 1), WATCHDOG).state
    t = decide(s, Tick(100), WATCHDOG)
    assert t.state.lease.sid == "A"  # not yet: strictly more than the limit
    t = decide(s, Tick(101), WATCHDOG)
    assert t.state.lease.sid == "B"
    assert t.state.status == StackStatus.STARTING
    failed = [e for e in t.effects if isinstance(e, Notify) and e.kind == "stack_failed"]
    assert failed == [
        Notify("A", "stack_failed", {"error": "no ready report from the agent in 100 s"})
    ]
    assert Email("A", "stack_failed", "a") in t.effects
    assert SetDesired("b", t.state.generation) in t.effects


def test_watchdog_releases_when_nobody_waits():
    s = decide(State(), StartRequested("A", "a", 0), WATCHDOG).state
    t = decide(s, Tick(200), WATCHDOG)
    assert t.state.lease is None
    assert SetDesired(None, t.state.generation) in t.effects


def test_watchdog_ignores_ready_stacks():
    s = decide(State(), StartRequested("A", "a", 0), WATCHDOG).state
    s = decide(s, ready(s, "a", 50), WATCHDOG).state
    t = decide(s, Tick(10_000), WATCHDOG)
    assert t.state.lease.sid == "A"
    assert t.state.status == StackStatus.READY


def test_watchdog_skips_lease_without_starting_since():
    s = decide(State(), StartRequested("A", "a", 0), WATCHDOG).state
    s = State(lease=replace(s.lease, starting_since=None), status=s.status, generation=1)
    assert decide(s, Tick(10_000), WATCHDOG).state == s


def test_old_snapshot_without_starting_since_loads():
    s, _ = run(State(), StartRequested("A", "a", 0))
    data = json.loads(s.to_json())
    del data["lease"]["starting_since"]
    loaded = State.from_json(json.dumps(data))
    assert loaded.lease.starting_since is None
    assert loaded.lease.sid == "A"
