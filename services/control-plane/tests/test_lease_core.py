import pytest
from control_plane.aliases import alias_for
from control_plane.lease import (
    Broadcast,
    Email,
    Lease,
    LeaseConfig,
    Notify,
    Observed,
    QueueEntry,
    Rejected,
    SetDesired,
    StartRequested,
    State,
    StopRequested,
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


def test_idle_start_makes_holder_and_sets_desired():
    s, fx = run(State(), StartRequested("A", "a", 0))
    assert s.lease is not None
    assert s.lease.sid == "A"
    assert s.lease.alias == alias_for("A")
    assert s.lease.window_remaining_s == 900
    assert s.status == StackStatus.STARTING
    assert s.generation == 1
    assert SetDesired("a", 1) in fx
    assert ("A", "stack_starting") in kinds(fx)
    assert Broadcast("queue_changed") in fx


def test_second_visitor_queues():
    s, _ = run(State(), StartRequested("A", "a", 0))
    s, fx = run(s, StartRequested("B", "b", 5))
    assert len(s.queue) == 1
    assert s.queue[0].sid == "B"
    assert s.lease.sid == "A"
    assert not [e for e in fx if isinstance(e, SetDesired)]
    assert ("B", "queue_changed") in kinds(fx)
    assert Broadcast("queue_changed") in fx


def test_requeue_updates_stack_not_duplicates():
    s, _ = run(State(), StartRequested("A", "a", 0), StartRequested("B", "b", 5))
    s, _ = run(s, StartRequested("B", "c", 9, has_email=True))
    assert len(s.queue) == 1
    assert s.queue[0].stack_id == "c"
    assert s.queue[0].enqueued_at == 5


def test_holder_same_stack_is_noop():
    s, _ = run(State(), StartRequested("A", "a", 0))
    s2, fx = run(s, StartRequested("A", "a", 3))
    assert s2 == s
    assert fx == []


def test_stale_generation_observed_ignored():
    s, _ = run(State(), StartRequested("A", "a", 0), StartRequested("B", "b", 1))
    s, _ = run(s, ready(s, "a", 10), Tick(910), Tick(1090))
    assert s.generation == 2
    s2, fx = run(s, Observed("a", StackStatus.READY, 1, 2000))
    assert s2.status == StackStatus.STARTING
    assert s2 == s
    assert fx == []


def test_ready_starts_window_from_ready_not_request():
    s, fx = run(State(), StartRequested("A", "a", 0))
    s, fx = run(s, ready(s, "a", 100))
    assert s.status == StackStatus.READY
    assert s.lease.window_ends_at == 1000
    assert s.lease.last_activity == 100
    assert ("A", "stack_ready") in kinds(fx)
    assert not [e for e in fx if isinstance(e, Email)]


def test_ready_emails_holder_with_email():
    s, _ = run(State(), StartRequested("A", "a", 0, has_email=True))
    s, fx = run(s, ready(s, "a", 100))
    assert Email("A", "stack_ready", "a") in fx


def test_observed_for_other_stack_ignored():
    s, _ = run(State(), StartRequested("A", "a", 0))
    s2, fx = run(s, Observed("zzz", StackStatus.READY, s.generation, 5))
    assert s2 == s
    assert fx == []


def test_observed_stopped_with_no_desired_marks_stopped():
    s, _ = run(State(), StartRequested("A", "a", 0))
    s, _ = run(s, ready(s, "a", 1), StopRequested("A", 2))
    assert s.lease is None
    s, _ = run(s, Observed("a", StackStatus.STOPPED, s.generation, 3))
    assert s.status == StackStatus.STOPPED


def test_no_grace_when_queue_empty_even_after_expiry():
    s, _ = run(State(), StartRequested("A", "a", 0))
    s, _ = run(s, ready(s, "a", 0), Tick(5000))
    assert s.lease.grace_deadline is None
    assert s.lease.sid == "A"
    assert s.status == StackStatus.READY


def test_queue_after_expiry_starts_grace_immediately():
    s, _ = run(State(), StartRequested("A", "a", 0))
    s, _ = run(s, ready(s, "a", 0))
    s, fx = run(s, StartRequested("B", "b", 2000))
    assert s.lease.grace_deadline == 2180
    assert Notify("A", "grace_started", {"deadline": 2180}) in fx


def test_queue_before_expiry_grace_at_window_end():
    s, _ = run(State(), StartRequested("A", "a", 0))
    s, _ = run(s, ready(s, "a", 0), StartRequested("B", "b", 100))
    s, fx = run(s, Tick(899))
    assert s.lease.grace_deadline is None
    s, fx = run(s, Tick(900))
    assert s.lease.grace_deadline == 1080
    assert ("A", "grace_started") in kinds(fx)


def test_grace_started_only_once():
    s, _ = run(State(), StartRequested("A", "a", 0))
    s, _ = run(s, ready(s, "a", 0), StartRequested("B", "b", 100), Tick(900))
    s, fx = run(s, Tick(950))
    assert ("A", "grace_started") not in kinds(fx)
    assert s.lease.grace_deadline == 1080


def test_protected_window_never_interrupted():
    s, _ = run(State(), StartRequested("A", "a", 0))
    s, _ = run(s, ready(s, "a", 0), StartRequested("B", "b", 1))
    for t in range(100, 900, 100):
        s, fx = run(s, Tick(t))
        assert not [k for _, k in kinds(fx) if k in ("grace_started", "evicted")]
    assert s.lease.sid == "A"


def test_grace_end_evicts_and_promotes_different_stack():
    s, _ = run(State(), StartRequested("A", "a", 0))
    s, _ = run(s, ready(s, "a", 0), StartRequested("B", "b", 1), Tick(900))
    gen = s.generation
    s, fx = run(s, Tick(1080))
    assert kinds(fx)[0] == ("A", "evicted")
    assert s.lease.sid == "B"
    assert s.queue == ()
    assert SetDesired("b", gen + 1) in fx
    assert s.status == StackStatus.STARTING
    assert s.lease.window_remaining_s == 900
    assert ("B", "your_turn") in kinds(fx)
    assert ("B", "stack_starting") in kinds(fx)
    assert Broadcast("queue_changed") in fx


def test_tick_before_grace_deadline_does_nothing_more():
    s, _ = run(State(), StartRequested("A", "a", 0))
    s, _ = run(s, ready(s, "a", 0), StartRequested("B", "b", 1), Tick(900))
    s2, fx = run(s, Tick(1079))
    assert s2 == s
    assert fx == []


def test_promote_same_stack_transfers_without_restart():
    s, _ = run(State(), StartRequested("A", "a", 0))
    s, _ = run(s, ready(s, "a", 0), StartRequested("B", "a", 1), Tick(900))
    gen = s.generation
    s, fx = run(s, Tick(1080))
    assert s.lease.sid == "B"
    assert s.status == StackStatus.READY
    assert s.generation == gen
    assert not [e for e in fx if isinstance(e, SetDesired)]
    assert s.lease.window_ends_at == 1080 + 900
    assert ("B", "your_turn") in kinds(fx)
    assert ("B", "stack_ready") in kinds(fx)


def test_promote_emailed_head_gets_your_turn_email():
    s, _ = run(State(), StartRequested("A", "a", 0))
    s, _ = run(s, ready(s, "a", 0), StartRequested("B", "b", 1, has_email=True), Tick(900))
    s, fx = run(s, Tick(1080))
    assert Email("B", "your_turn", "b") in fx


def test_non_holder_stop_rejected_403():
    s, _ = run(State(), StartRequested("A", "a", 0))
    with pytest.raises(Rejected) as ei:
        decide(s, StopRequested("B", 1), CFG)
    assert ei.value.status == 403
    assert "turn" in ei.value.reason
    with pytest.raises(Rejected):
        decide(State(), StopRequested("B", 1), CFG)


def test_holder_stop_with_empty_queue_sets_desired_none():
    s, _ = run(State(), StartRequested("A", "a", 0))
    s, fx = run(s, StopRequested("A", 5))
    assert s.lease is None
    assert s.generation == 2
    assert SetDesired(None, 2) in fx
    assert Broadcast("queue_changed") in fx


def test_holder_stop_promotes_next():
    s, _ = run(State(), StartRequested("A", "a", 0), StartRequested("B", "b", 1))
    s, fx = run(s, StopRequested("A", 5))
    assert s.lease.sid == "B"
    assert s.queue == ()
    assert SetDesired("b", 2) in fx


def test_events_deferred_to_task4_are_noops():
    from control_plane.lease import (
        Activity,
        AdminClearQueue,
        AdminForceStop,
        EmailAttached,
        Seen,
    )

    s, _ = run(State(), StartRequested("A", "a", 0))
    for ev in (
        Activity("A", 1),
        Seen("A", 1),
        EmailAttached("A", 1),
        AdminForceStop(1),
        AdminClearQueue(1),
        Observed("a", StackStatus.FAILED, s.generation, 1, error="x"),
    ):
        assert decide(s, ev, CFG).state == s


def test_holder_switch_request_is_noop_for_now():
    s, _ = run(State(), StartRequested("A", "a", 0))
    t = decide(s, StartRequested("A", "b", 1), CFG)
    assert t.state == s
    assert t.effects == ()


def test_state_json_roundtrip():
    s, _ = run(State(), StartRequested("A", "a", 0), StartRequested("B", "b", 1))
    s, _ = run(s, ready(s, "a", 10), Tick(910))
    assert s.lease.grace_deadline is not None
    assert State.from_json(s.to_json()) == s
    assert State.from_json(State().to_json()) == State()
    assert isinstance(State.from_json(s.to_json()).queue, tuple)
    assert State.from_json(s.to_json()).status is StackStatus.READY


def test_dataclasses_are_constructible():
    e = QueueEntry("X", "al", "a", False, 0.0, 0.0)
    lease = Lease("X", "al", "a", False, 900.0, None, 0.0, None)
    assert State(lease=lease, queue=(e,)).queue[0] is e
