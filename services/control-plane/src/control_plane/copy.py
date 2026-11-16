"""Human copy for notifications and emails.

Every body explains the engineering reason: the box has 2 CPUs so one project
runs at a time, started is not ready, and turns are time-boxed with a handoff
warning when someone is waiting. Project names are always passed in.
"""

from typing import Any

from control_plane.lease import LeaseConfig

DEFAULT_CFG = LeaseConfig()


def _mins(seconds: float) -> str:
    m = max(1, round(seconds / 60))
    return f"{m} minute" + ("" if m == 1 else "s")


def notification(
    kind: str, stack_name: str, data: dict[str, Any], cfg: LeaseConfig = DEFAULT_CFG
) -> dict[str, str]:
    window, grace = _mins(cfg.window_s), _mins(cfg.grace_s)
    table = {
        "queue_changed": (
            "The queue changed",
            "This lab has 2 CPUs, so only one project can run at a time and visitors "
            "take turns in order. Your place in line updated.",
        ),
        "your_turn": (
            f"It's your turn: {stack_name}",
            f"The machine has 2 CPUs, so {stack_name} gets it to itself for a {window} "
            f"turn. The clock starts when the project is ready, not when it begins booting.",
        ),
        "stack_starting": (
            f"{stack_name} is starting",
            f"{stack_name} is booting now. Starting is not the same as ready: heavy ML "
            f"stacks can take a while on 2 CPUs. We will tell you the moment it is up.",
        ),
        "stack_ready": (
            f"{stack_name} is ready",
            f"{stack_name} passed its health check. Your {window} turn starts now and "
            f"is protected: nobody can take the machine while it runs.",
        ),
        "grace_started": (
            f"Handoff in {grace}: {stack_name}",
            f"Someone is waiting and your turn on {stack_name} is up, so you have a "
            f"{grace} handoff warning before it stops. One project at a time keeps each "
            f"demo fast on 2 CPUs.",
        ),
        "grace_cancelled": (
            f"Handoff cancelled: {stack_name}",
            f"Nobody is waiting any more, so {stack_name} keeps running. Turns only end "
            f"when someone else needs the 2 CPUs.",
        ),
        "evicted": (
            f"Your turn on {stack_name} ended",
            f"{stack_name} was stopped to hand the machine to the next visitor. With "
            f"2 CPUs only one project runs at a time. You can rejoin the queue anytime.",
        ),
        "stack_failed": (
            f"{stack_name} failed to start",
            f"{stack_name} did not become healthy in time and was shut down so the next "
            f"visitor is not blocked. A recorded demo is available instead.",
        ),
    }
    title, body = table[kind]
    return {"title": title, "body": body}


def email(kind: str, stack_name: str, link: str, cfg: LeaseConfig = DEFAULT_CFG) -> tuple[str, str]:
    window = _mins(cfg.window_s)
    table = {
        "your_turn": (
            f"Your turn: {stack_name}",
            f"It's your turn. {stack_name} is starting now. The machine has 2 CPUs, so "
            f"one project runs at a time, and your {window} turn starts once it is "
            f"ready. Open it here: {link}",
        ),
        "stack_ready": (
            f"{stack_name} is ready",
            f"{stack_name} is up and your {window} turn has started. It was not ready "
            f"until its health check passed. Open it here: {link}",
        ),
        "stack_failed": (
            f"{stack_name} failed to start",
            f"{stack_name} did not become healthy, so it was stopped to keep the queue "
            f"moving on a 2 CPU machine. The project page has the recorded demo: {link}",
        ),
    }
    return table[kind]
