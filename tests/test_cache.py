"""Tests für modules/cache.py: SQLite-Cache, Einstellungen und Schema-Migration (temporäre Datenbank)."""

import sqlite3
from datetime import timedelta

import pytest

from modules import cache as cache_module
from modules.cache import CACHE_EXPIRY_HOURS, LOCAL_USER_ID, CacheManager


@pytest.fixture
def cache(tmp_path):
    return CacheManager(db_path=str(tmp_path / "cache.db"))


def test_wetter_roundtrip(cache):
    assert cache.get_weather(47.99, 7.85, "2026-06-01") is None
    cache.set_weather(47.99, 7.85, "2026-06-01", {"total_sunshine_hours": 9.5})
    assert cache.get_weather(47.99, 7.85, "2026-06-01") == {"total_sunshine_hours": 9.5}
    assert cache.get_weather(47.99, 7.85, "2026-06-02") is None  # anderes Datum


def test_reisezeit_roundtrip(cache):
    cache.set_directions(47.0, 8.0, 47.5, 8.5, "driving", "2026-06-01", 1800)
    assert cache.get_directions(47.0, 8.0, 47.5, 8.5, "driving", "2026-06-01") == 1800
    assert cache.get_directions(47.0, 8.0, 47.5, 8.5, "walking", "2026-06-01") is None


def test_eintraege_laufen_nach_der_cachezeit_ab(cache, monkeypatch):
    cache.set_weather(1.0, 2.0, "2026-06-01", {"x": 1})
    spaeter = cache_module._utcnow() + timedelta(hours=CACHE_EXPIRY_HOURS + 1)
    monkeypatch.setattr(cache_module, "_utcnow", lambda: spaeter)
    assert cache.get_weather(1.0, 2.0, "2026-06-01") is None


def test_cleanup_entfernt_nur_abgelaufene_eintraege(cache, monkeypatch):
    cache.set_weather(1.0, 2.0, "2026-06-01", {"alt": True})
    spaeter = cache_module._utcnow() + timedelta(hours=CACHE_EXPIRY_HOURS + 1)
    monkeypatch.setattr(cache_module, "_utcnow", lambda: spaeter)
    cache.set_weather(3.0, 4.0, "2026-06-01", {"neu": True})
    cache.cleanup_expired()
    with sqlite3.connect(cache.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM weather_cache").fetchone()[0] == 1


def test_einstellungen_werden_gespeichert_und_teilweise_aktualisiert(cache):
    assert cache.get_user_preferences(LOCAL_USER_ID) is None
    cache.set_user_preferences(
        LOCAL_USER_ID, last_place_name="Freiburg", last_place_id="1", last_place_lat=47.99,
        last_place_lng=7.85, last_travel_time=1.5, last_travel_mode="driving",
        last_only_cities=True, last_max_results=60, last_date_iso="2026-06-01",
        last_no_precipitation_only=False,
    )
    cache.set_user_preferences(LOCAL_USER_ID, last_travel_time=2.0)  # nur ein Feld ändern
    prefs = cache.get_user_preferences(LOCAL_USER_ID)
    assert prefs["last_place_name"] == "Freiburg"
    assert prefs["last_travel_time"] == 2.0
    assert prefs["last_only_cities"] == 1
    assert prefs["last_no_precipitation_only"] == 0


def test_nearby_cache_behaelt_hoechstens_zehn_eintraege(cache):
    for i in range(15):
        cache.set_nearby_candidates(47.0 + i, 8.0, "driving", True, 60, 3600, [{"name": f"Ort{i}"}])
    with sqlite3.connect(cache.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM nearby_cache").fetchone()[0] == 10
    assert cache.get_nearby_candidates(47.0 + 14, 8.0, "driving", True, 60, 3600) == [{"name": "Ort14"}]
    assert cache.get_nearby_candidates(47.0, 8.0, "driving", True, 60, 3600) is None  # verdrängt


def test_neue_datenbank_hat_user_id_spalte(cache):
    with sqlite3.connect(cache.db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(user_preferences)")}
    assert "user_id" in columns and "google_user_id" not in columns


def _legacy_db(path, rows):
    """Legt eine Datenbank im alten Schema (Spalte google_user_id, ohne neuere Spalten) an."""
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE user_preferences (google_user_id TEXT PRIMARY KEY, last_place_name TEXT, "
            "last_place_id TEXT, last_place_lat REAL, last_place_lng REAL, last_travel_time REAL, "
            "last_travel_mode TEXT, updated_at TEXT NOT NULL)"
        )
        conn.executemany(
            "INSERT INTO user_preferences (google_user_id, last_place_name, updated_at) VALUES (?, ?, ?)",
            rows,
        )


def test_migration_benennt_spalte_um_und_behaelt_lokalen_nutzer(tmp_path):
    path = str(tmp_path / "alt.db")
    _legacy_db(path, [(LOCAL_USER_ID, "Konstanz", "2026-06-01T10:00:00")])
    cache = CacheManager(db_path=path)
    assert cache.get_user_preferences(LOCAL_USER_ID)["last_place_name"] == "Konstanz"


def test_migration_entfernt_fremde_google_ids(tmp_path):
    path = str(tmp_path / "alt.db")
    _legacy_db(path, [("123456789012345678901", "Ulm", "2026-05-01T10:00:00")])
    CacheManager(db_path=path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM user_preferences").fetchone()[0] == 0


def test_migration_ist_idempotent(tmp_path):
    path = str(tmp_path / "alt.db")
    _legacy_db(path, [(LOCAL_USER_ID, "Konstanz", "2026-06-01T10:00:00")])
    CacheManager(db_path=path)
    cache = CacheManager(db_path=path)  # zweiter Start: nichts darf kaputtgehen
    assert cache.get_user_preferences(LOCAL_USER_ID)["last_place_name"] == "Konstanz"
