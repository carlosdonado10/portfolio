import logging

from agent.__main__ import heartbeat_message, run


def test_heartbeat_message_numbers_the_beat() -> None:
    assert heartbeat_message(1) == "agent alive — heartbeat #1"
    assert heartbeat_message(42) == "agent alive — heartbeat #42"


def test_run_emits_expected_number_of_beats(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="agent"):
        run(interval=0, max_beats=3)
    beats = [r for r in caplog.records if "heartbeat" in r.getMessage()]
    assert len(beats) == 3
