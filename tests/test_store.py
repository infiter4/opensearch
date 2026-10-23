"""Store feature-flag + slug hygiene. Pure/offline — no DB round-trips (live CRUD is a manual
script, kept out of the suite so pytest stays offline and doesn't pollute the DB)."""
from backend import config
from backend.store import db
from backend.store import workspaces as ws


def test_is_enabled_tracks_the_flag(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_DB_URL", None)
    assert db.is_enabled() is False
    monkeypatch.setattr(config, "SUPABASE_DB_URL", "postgresql://u:p@h:5432/db")
    assert db.is_enabled() is True


def test_dsn_is_scrubbed_of_password():
    dsn = "postgresql://postgres.abc:sup3rsecret@aws.pooler.supabase.com:5432/postgres"
    out = db.scrub(f"connect failed for {dsn}")
    assert "sup3rsecret" not in out
    assert "<redacted>" in out


def test_slugify():
    assert ws.slugify("Robotics Q3 2026!") == "robotics-q3-2026"
    assert ws.slugify("") == "workspace"
    assert len(ws.slugify("x" * 200)) <= 48
