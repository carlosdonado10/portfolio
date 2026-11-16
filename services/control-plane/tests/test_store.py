from control_plane.lease import LeaseConfig, StartRequested, State, decide
from control_plane.store import Store


def test_store_state_roundtrip(tmp_path):
    store = Store(tmp_path / "o.sqlite")
    assert store.load_state() == State()
    state = decide(State(), StartRequested("s1", "a", 0.0), LeaseConfig()).state
    store.save_state(state)
    store.save_state(state)
    assert Store(tmp_path / "o.sqlite").load_state() == state


def test_store_email(tmp_path):
    store = Store(tmp_path / "o.sqlite")
    store.ensure_session("s1", "1.2.3.4")
    assert store.get_email("s1") is None
    store.set_email("s1", "a@b.co")
    assert store.get_email("s1") == "a@b.co"
    store.ensure_session("s1", "9.9.9.9")  # idempotent: keeps email and first ip
    assert store.get_email("s1") == "a@b.co"
    assert store.get_email("nobody") is None


def test_store_sessions_and_visits(tmp_path):
    store = Store(tmp_path / "o.sqlite")
    store.ensure_session("s1", "1.2.3.4")
    store.log_visit("s1", "/lab/p/a", 5.0)
    [row] = store.list_sessions()
    assert row["sid"] == "s1"
    assert row["ip"] == "1.2.3.4"
    assert row["visits"] == [{"path": "/lab/p/a", "at": 5.0}]
