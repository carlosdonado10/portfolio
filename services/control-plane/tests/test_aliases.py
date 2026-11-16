import re

from control_plane.aliases import ADJECTIVES, SURNAMES, alias_for


def test_alias_deterministic_and_well_formed():
    assert alias_for("sid-1") == alias_for("sid-1")
    assert re.fullmatch(r"[a-z]+_[a-z]+", alias_for("sid-1"))


def test_alias_lists_are_large_and_lowercase_ascii():
    assert len(ADJECTIVES) >= 30
    assert len(SURNAMES) >= 30
    assert len(set(ADJECTIVES)) == len(ADJECTIVES)
    assert len(set(SURNAMES)) == len(SURNAMES)
    assert all(re.fullmatch(r"[a-z]+", w) for w in (*ADJECTIVES, *SURNAMES))


def test_alias_varies_across_sessions():
    assert len({alias_for(f"sid-{i}") for i in range(50)}) > 10
