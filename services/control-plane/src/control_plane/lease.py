"""Pure lease / queue / grace state machine.

No I/O, no clock reads, no randomness: time arrives on events as ``now``. The
service layer persists ``State`` and executes the returned effects.
"""

import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from orch_common.wire import StackStatus

from control_plane.aliases import alias_for


@dataclass(frozen=True)
class LeaseConfig:
    window_s: float = 900
    grace_s: float = 180
    idle_s: float = 180
    presence_s: float = 120


@dataclass(frozen=True)
class Lease:
    sid: str
    alias: str
    stack_id: str
    has_email: bool
    # Frozen remainder while the stack is not ready; spent once ready.
    window_remaining_s: float
    # Set only while the stack is ready.
    window_ends_at: float | None
    last_activity: float
    grace_deadline: float | None


@dataclass(frozen=True)
class QueueEntry:
    sid: str
    alias: str
    stack_id: str
    has_email: bool
    enqueued_at: float
    last_seen: float


@dataclass(frozen=True)
class State:
    lease: Lease | None = None
    status: StackStatus = StackStatus.STOPPED
    queue: tuple[QueueEntry, ...] = ()
    generation: int = 0

    def to_json(self) -> str:
        data = asdict(self)
        data["status"] = self.status.value
        return json.dumps(data)

    @classmethod
    def from_json(cls, s: str) -> "State":
        data = json.loads(s)
        lease = data["lease"]
        return cls(
            lease=Lease(**lease) if lease is not None else None,
            status=StackStatus(data["status"]),
            queue=tuple(QueueEntry(**q) for q in data["queue"]),
            generation=data["generation"],
        )


@dataclass(frozen=True)
class StartRequested:
    sid: str
    stack_id: str
    now: float
    has_email: bool = False


@dataclass(frozen=True)
class StopRequested:
    sid: str
    now: float


@dataclass(frozen=True)
class Observed:
    stack_id: str
    status: StackStatus
    generation: int
    now: float
    error: str | None = None


@dataclass(frozen=True)
class Activity:
    sid: str
    now: float


@dataclass(frozen=True)
class Seen:
    """SSE heartbeat or connection."""

    sid: str
    now: float


@dataclass(frozen=True)
class EmailAttached:
    sid: str
    now: float


@dataclass(frozen=True)
class Tick:
    now: float


@dataclass(frozen=True)
class AdminForceStop:
    now: float


@dataclass(frozen=True)
class AdminClearQueue:
    now: float


Event = (
    StartRequested
    | StopRequested
    | Observed
    | Activity
    | Seen
    | EmailAttached
    | Tick
    | AdminForceStop
    | AdminClearQueue
)


@dataclass(frozen=True)
class SetDesired:
    stack_id: str | None
    generation: int


@dataclass(frozen=True)
class Notify:
    sid: str
    kind: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Broadcast:
    kind: str = "queue_changed"


@dataclass(frozen=True)
class Email:
    sid: str
    kind: str
    stack_id: str


Effect = SetDesired | Notify | Broadcast | Email


@dataclass(frozen=True)
class Transition:
    state: State
    effects: tuple[Effect, ...] = ()


class Rejected(Exception):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


def decide(state: State, event: Event, cfg: LeaseConfig) -> Transition:
    if isinstance(event, StartRequested):
        t = _start_requested(state, event, cfg)
    elif isinstance(event, StopRequested):
        t = _stop_requested(state, event, cfg)
    elif isinstance(event, Observed):
        t = _observed(state, event)
    elif isinstance(event, Tick):
        t = _tick(state, event, cfg)
    else:
        # Activity, Seen, EmailAttached, AdminForceStop, AdminClearQueue:
        # rules land with the idle/presence/admin work.
        t = Transition(state, ())
    return _evaluate_contention(t, event.now, cfg)


def _start_requested(state: State, ev: StartRequested, cfg: LeaseConfig) -> Transition:
    lease = state.lease
    if lease is None:
        generation = state.generation + 1
        new_lease = Lease(
            sid=ev.sid,
            alias=alias_for(ev.sid),
            stack_id=ev.stack_id,
            has_email=ev.has_email,
            window_remaining_s=cfg.window_s,
            window_ends_at=None,
            last_activity=ev.now,
            grace_deadline=None,
        )
        new = replace(state, lease=new_lease, status=StackStatus.STARTING, generation=generation)
        return Transition(
            new,
            (
                SetDesired(ev.stack_id, generation),
                Notify(ev.sid, "stack_starting"),
                Broadcast(),
            ),
        )
    if lease.sid == ev.sid:
        # Same stack is a no-op; switching projects is handled separately.
        return Transition(state, ())
    entry = QueueEntry(
        sid=ev.sid,
        alias=alias_for(ev.sid),
        stack_id=ev.stack_id,
        has_email=ev.has_email,
        enqueued_at=ev.now,
        last_seen=ev.now,
    )
    queue = list(state.queue)
    for i, existing in enumerate(queue):
        if existing.sid == ev.sid:
            queue[i] = replace(
                existing,
                stack_id=ev.stack_id,
                has_email=existing.has_email or ev.has_email,
            )
            break
    else:
        queue.append(entry)
    return Transition(
        replace(state, queue=tuple(queue)),
        (Notify(ev.sid, "queue_changed"), Broadcast()),
    )


def _stop_requested(state: State, ev: StopRequested, cfg: LeaseConfig) -> Transition:
    if state.lease is None or state.lease.sid != ev.sid:
        raise Rejected(
            403,
            "Only the visitor whose turn it is can stop the project, because "
            "stopping it ends their protected session. Everyone else can "
            "join the queue instead.",
        )
    return _promote(state, ev.now, cfg)


def _observed(state: State, ev: Observed) -> Transition:
    if ev.generation != state.generation:
        return Transition(state, ())
    lease = state.lease
    if ev.status == StackStatus.READY:
        # Only the STARTING -> READY edge starts the window; repeat reports
        # (agent restart, health recovery) must not extend it.
        if lease is None or lease.stack_id != ev.stack_id or state.status != StackStatus.STARTING:
            return Transition(state, ())
        new_lease = replace(
            lease,
            window_ends_at=ev.now + lease.window_remaining_s,
            last_activity=ev.now,
        )
        effects: list[Effect] = [Notify(lease.sid, "stack_ready")]
        if lease.has_email:
            effects.append(Email(lease.sid, "stack_ready", lease.stack_id))
        return Transition(replace(state, lease=new_lease, status=StackStatus.READY), tuple(effects))
    if ev.status == StackStatus.STOPPED and lease is None:
        return Transition(replace(state, status=StackStatus.STOPPED), ())
    # FAILED handling is added with the failure rules.
    return Transition(state, ())


def _tick(state: State, ev: Tick, cfg: LeaseConfig) -> Transition:
    lease = state.lease
    if lease is not None and lease.grace_deadline is not None and ev.now >= lease.grace_deadline:
        promoted = _promote(state, ev.now, cfg)
        return Transition(promoted.state, (Notify(lease.sid, "evicted"), *promoted.effects))
    return Transition(state, ())


def _promote(state: State, now: float, cfg: LeaseConfig) -> Transition:
    """Release the current lease and hand the box to the head of the queue."""
    if not state.queue:
        generation = state.generation + 1
        return Transition(
            replace(state, lease=None, generation=generation),
            (SetDesired(None, generation), Broadcast()),
        )
    head, rest = state.queue[0], state.queue[1:]
    same_stack_ready = (
        state.lease is not None
        and head.stack_id == state.lease.stack_id
        and state.status == StackStatus.READY
    )
    lease = Lease(
        sid=head.sid,
        alias=head.alias,
        stack_id=head.stack_id,
        has_email=head.has_email,
        window_remaining_s=cfg.window_s,
        window_ends_at=now + cfg.window_s if same_stack_ready else None,
        last_activity=now,
        grace_deadline=None,
    )
    if same_stack_ready:
        return Transition(
            replace(state, lease=lease, queue=rest),
            (
                Notify(head.sid, "your_turn"),
                Notify(head.sid, "stack_ready"),
                Broadcast(),
            ),
        )
    generation = state.generation + 1
    effects: list[Effect] = [
        SetDesired(head.stack_id, generation),
        Notify(head.sid, "your_turn"),
        Notify(head.sid, "stack_starting"),
    ]
    if head.has_email:
        effects.append(Email(head.sid, "your_turn", head.stack_id))
    effects.append(Broadcast())
    return Transition(
        replace(
            state,
            lease=lease,
            queue=rest,
            status=StackStatus.STARTING,
            generation=generation,
        ),
        tuple(effects),
    )


def _evaluate_contention(t: Transition, now: float, cfg: LeaseConfig) -> Transition:
    state, lease = t.state, t.state.lease
    if (
        lease is None
        or not state.queue
        or state.status != StackStatus.READY
        or lease.grace_deadline is not None
        or lease.window_ends_at is None
        or now < lease.window_ends_at
    ):
        return t
    deadline = now + cfg.grace_s
    return Transition(
        replace(state, lease=replace(lease, grace_deadline=deadline)),
        (*t.effects, Notify(lease.sid, "grace_started", {"deadline": deadline})),
    )
