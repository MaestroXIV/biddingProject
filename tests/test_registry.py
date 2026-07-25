"""Registry persistence for user-added events (SPEC 7.6)."""
import importlib


def test_register_roundtrip(tmp_path, monkeypatch):
    import registry
    importlib.reload(registry)
    monkeypatch.setattr(registry, "USER_REGISTRY", tmp_path / "tournaments.json")

    t = registry.Tournament(
        key="test25", site="WBF",
        base="http://example.org/Asp/", tournid=9999,
        name="Test Cup 2025", year=2025, series="Test")
    registry.register(t)

    # persisted to disk and merged into the live table
    assert registry.USER_REGISTRY.exists()
    assert registry.TOURNAMENTS["test25"].tournid == 9999
    # re-loading from disk yields the same event
    reloaded = registry._load_user()
    assert reloaded["test25"].name == "Test Cup 2025"


def test_builtins_present():
    import registry
    importlib.reload(registry)
    assert "riga" in registry.TOURNAMENTS
    assert registry.TOURNAMENTS["riga"].tournid == 2620
