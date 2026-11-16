from orch_common.wire import DesiredState, ObservedState, StackStatus


def test_wire_roundtrip() -> None:
    o = ObservedState(stack_id="demo", status=StackStatus.READY, generation=3, at=1.5)
    assert ObservedState.model_validate_json(o.model_dump_json()) == o
    assert o.status == "ready"


def test_desired_state() -> None:
    d = DesiredState(active=None, generation=0)
    assert DesiredState.model_validate(d.model_dump()) == d
