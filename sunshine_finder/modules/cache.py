"""
cache.py – SQLite-Cache-Logik für API-Ergebnisse und Nutzereinstellungen.

Zwei Tabellen:
  - directions_cache / weather_cache: API-Ergebnisse mit 24h Ablaufzeit
  - user_preferences: Einstellungen des lokalen Nutzers (Schlüssel LOCAL_USER_ID)
"""

import sqlite3
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Cache-Ablaufzeit in Stunden
CACHE_EXPIRY_HOURS = 24
WEATHER_CACHE_SCHEMA_VERSION = 3
# Version der Kandidatenlisten (2 = auf Reisezeit-Bänder verteilt, mit duration_sec)
NEARBY_CACHE_SCHEMA_VERSION = 2

# Die App hat keinen Login: alle Einstellungen gehören dem lokalen Nutzer.
LOCAL_USER_ID = "local"


def _get_db_path() -> str:
    """Gibt den Pfad zur Cache-Datenbank zurück (neben der EXE bzw. im Quellverzeichnis)."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "cache.db")


def _utcnow() -> datetime:
    """Aktuelle UTC-Zeit ohne Zeitzone (so ist sie in der Datenbank gespeichert)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_cache_key(*args: Any) -> str:
    """Erzeugt einen deterministischen Hash-Schlüssel aus den übergebenen Werten."""
    raw = json.dumps(args, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CacheManager:
    """Verwaltet den SQLite-Cache und die Nutzereinstellungen."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or _get_db_path()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Erstellt alle benötigten Tabellen, falls sie noch nicht existieren."""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS directions_cache (
                    cache_key   TEXT PRIMARY KEY,
                    data        TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS weather_cache (
                    cache_key   TEXT PRIMARY KEY,
                    data        TEXT NOT NULL,
                    created_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_preferences (
                    user_id             TEXT PRIMARY KEY,
                    last_place_name     TEXT,
                    last_place_id       TEXT,
                    last_place_lat      REAL,
                    last_place_lng      REAL,
                    last_travel_time    REAL,
                    last_travel_mode    TEXT,
                    last_only_cities    INTEGER,
                    last_max_results    INTEGER,
                    last_date_iso       TEXT,
                    updated_at          TEXT NOT NULL
                );
            """)
            # nearby_cache wird separat erstellt (ALTER TABLE wäre nötig für
            # ältere DBs ohne die Tabelle)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS nearby_cache (
                    cache_key   TEXT PRIMARY KEY,
                    data        TEXT NOT NULL,
                    last_used   TEXT NOT NULL
                )
            """)
            self._migrate_legacy_user_id_column(conn)
            self._ensure_user_preferences_columns(conn)
        logger.debug("Datenbank initialisiert: %s", self.db_path)

    @staticmethod
    def _migrate_legacy_user_id_column(conn: sqlite3.Connection) -> None:
        """
        Schema-Migration älterer Datenbanken: die Spalte hieß früher `google_user_id`
        (Zeit mit Google-Login). Sie wird umbenannt; Zeilen mit einer fremden ID sind seit
        dem Wegfall des Logins nicht mehr erreichbar und werden entfernt.
        """
        columns = {row[1] for row in conn.execute("PRAGMA table_info(user_preferences)")}
        if "google_user_id" in columns and "user_id" not in columns:
            conn.execute("ALTER TABLE user_preferences RENAME COLUMN google_user_id TO user_id")
            conn.execute("DELETE FROM user_preferences WHERE user_id != ?", (LOCAL_USER_ID,))

    def _ensure_user_preferences_columns(self, conn: sqlite3.Connection) -> None:
        """Stellt sicher, dass neue Einstellungs-Spalten in älteren DBs existieren."""
        existing_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(user_preferences)").fetchall()
        }
        required_columns = {
            "last_only_cities": "INTEGER",
            "last_max_results": "INTEGER",
            "last_date_iso": "TEXT",
            "last_no_precipitation_only": "INTEGER",
        }
        for column_name, column_type in required_columns.items():
            if column_name not in existing_columns:
                conn.execute(
                    f"ALTER TABLE user_preferences ADD COLUMN {column_name} {column_type}"
                )

    # ------------------------------------------------------------------ #
    # Directions-Cache                                                     #
    # ------------------------------------------------------------------ #

    def get_directions(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        mode: str,
        date_str: str,
    ) -> Optional[int]:
        """
        Gibt gecachte Reisezeit in Sekunden zurück oder None bei Cache-Miss.
        """
        key = _make_cache_key("directions", origin_lat, origin_lng,
                               dest_lat, dest_lng, mode, date_str)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data, created_at FROM directions_cache WHERE cache_key = ?",
                (key,)
            ).fetchone()
        if row is None:
            return None
        if _is_expired(row["created_at"]):
            self._delete_directions(key)
            return None
        return json.loads(row["data"])

    def set_directions(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        mode: str,
        date_str: str,
        duration_seconds: int,
    ) -> None:
        """Speichert Reisezeit-Ergebnis im Cache."""
        key = _make_cache_key("directions", origin_lat, origin_lng,
                               dest_lat, dest_lng, mode, date_str)
        now = _utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO directions_cache (cache_key, data, created_at) VALUES (?, ?, ?)",
                (key, json.dumps(duration_seconds), now)
            )

    def _delete_directions(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM directions_cache WHERE cache_key = ?", (key,))

    # ------------------------------------------------------------------ #
    # Wetter-Cache                                                         #
    # ------------------------------------------------------------------ #

    def get_weather(
        self,
        lat: float,
        lng: float,
        date_str: str,
    ) -> Optional[dict]:
        """Gibt gecachte Wetterdaten zurück oder None bei Cache-Miss."""
        # Versionierter Schlüssel, damit alte Cache-Schemas (z. B. ohne Temperatur)
        # nicht weiterverwendet werden.
        key = _make_cache_key(
            "weather",
            WEATHER_CACHE_SCHEMA_VERSION,
            lat,
            lng,
            date_str,
        )
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data, created_at FROM weather_cache WHERE cache_key = ?",
                (key,)
            ).fetchone()
        if row is None:
            return None
        if _is_expired(row["created_at"]):
            self._delete_weather(key)
            return None
        return json.loads(row["data"])

    def set_weather(
        self,
        lat: float,
        lng: float,
        date_str: str,
        weather_data: dict,
    ) -> None:
        """Speichert Wetterdaten im Cache."""
        key = _make_cache_key(
            "weather",
            WEATHER_CACHE_SCHEMA_VERSION,
            lat,
            lng,
            date_str,
        )
        now = _utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO weather_cache (cache_key, data, created_at) VALUES (?, ?, ?)",
                (key, json.dumps(weather_data, ensure_ascii=False), now)
            )

    def _delete_weather(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM weather_cache WHERE cache_key = ?", (key,))

    # ------------------------------------------------------------------ #
    # Nutzereinstellungen                                                  #
    # ------------------------------------------------------------------ #

    def get_user_preferences(self, user_id: str) -> Optional[dict]:
        """Gibt gespeicherte Nutzereinstellungen zurück oder None."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM user_preferences WHERE user_id = ?",
                    (user_id,)
                ).fetchone()
            if row is None:
                return None
            return dict(row)
        except sqlite3.Error as exc:
            logger.warning(
                "Nutzereinstellungen konnten nicht geladen werden (%s). Verwende Defaults.",
                exc,
            )
            return None

    def set_user_preferences(
        self,
        user_id: str,
        last_place_name: Optional[str] = None,
        last_place_id: Optional[str] = None,
        last_place_lat: Optional[float] = None,
        last_place_lng: Optional[float] = None,
        last_travel_time: Optional[float] = None,
        last_travel_mode: Optional[str] = None,
        last_only_cities: Optional[bool] = None,
        last_max_results: Optional[int] = None,
        last_date_iso: Optional[str] = None,
        last_no_precipitation_only: Optional[bool] = None,
    ) -> None:
        """Speichert oder aktualisiert Nutzereinstellungen."""
        now = _utcnow().isoformat()
        only_cities_int = None if last_only_cities is None else int(last_only_cities)
        no_precip_int = None if last_no_precipitation_only is None else int(last_no_precipitation_only)

        try:
            with self._connect() as conn:
                # Bestehende Werte laden, damit keine Felder überschrieben werden
                existing = conn.execute(
                    "SELECT * FROM user_preferences WHERE user_id = ?",
                    (user_id,)
                ).fetchone()

                if existing:
                    # Nur übergebene Werte aktualisieren
                    conn.execute("""
                        UPDATE user_preferences SET
                            last_place_name            = COALESCE(?, last_place_name),
                            last_place_id              = COALESCE(?, last_place_id),
                            last_place_lat             = COALESCE(?, last_place_lat),
                            last_place_lng             = COALESCE(?, last_place_lng),
                            last_travel_time           = COALESCE(?, last_travel_time),
                            last_travel_mode           = COALESCE(?, last_travel_mode),
                            last_only_cities           = COALESCE(?, last_only_cities),
                            last_max_results           = COALESCE(?, last_max_results),
                            last_date_iso              = COALESCE(?, last_date_iso),
                            last_no_precipitation_only = COALESCE(?, last_no_precipitation_only),
                            updated_at                 = ?
                        WHERE user_id = ?
                    """, (
                        last_place_name,
                        last_place_id,
                        last_place_lat,
                        last_place_lng,
                        last_travel_time,
                        last_travel_mode,
                        only_cities_int,
                        last_max_results,
                        last_date_iso,
                        no_precip_int,
                        now,
                        user_id,
                    ))
                else:
                    conn.execute("""
                        INSERT INTO user_preferences
                            (user_id, last_place_name, last_place_id,
                             last_place_lat, last_place_lng, last_travel_time,
                             last_travel_mode, last_only_cities, last_max_results,
                             last_date_iso, last_no_precipitation_only, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        user_id,
                        last_place_name,
                        last_place_id,
                        last_place_lat,
                        last_place_lng,
                        last_travel_time,
                        last_travel_mode,
                        only_cities_int,
                        last_max_results,
                        last_date_iso,
                        no_precip_int,
                        now,
                    ))
        except sqlite3.Error as exc:
            logger.warning("Nutzereinstellungen konnten nicht gespeichert werden: %s", exc)

    # ------------------------------------------------------------------ #
    # Nearby-Kandidaten-Cache (max. 10 Einträge, LRU-Eviction)           #
    # ------------------------------------------------------------------ #

    def get_nearby_candidates(
        self,
        origin_lat: float,
        origin_lng: float,
        mode: str,
        only_cities: bool,
        max_results: int,
        max_duration_sec: int,
    ) -> Optional[list]:
        """Gibt gecachte Kandidatenliste zurück oder None bei Cache-Miss."""
        key = _make_cache_key(
            "nearby", NEARBY_CACHE_SCHEMA_VERSION, origin_lat, origin_lng,
            mode, only_cities, max_results, max_duration_sec,
        )
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM nearby_cache WHERE cache_key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            # last_used aktualisieren (LRU-Zugriff)
            conn.execute(
                "UPDATE nearby_cache SET last_used = ? WHERE cache_key = ?",
                (_utcnow().isoformat(), key),
            )
        return json.loads(row["data"])

    def set_nearby_candidates(
        self,
        origin_lat: float,
        origin_lng: float,
        mode: str,
        only_cities: bool,
        max_results: int,
        max_duration_sec: int,
        candidates: list,
    ) -> None:
        """Speichert Kandidatenliste im Cache (max. 10 Einträge, LRU-Eviction)."""
        key = _make_cache_key(
            "nearby", NEARBY_CACHE_SCHEMA_VERSION, origin_lat, origin_lng,
            mode, only_cities, max_results, max_duration_sec,
        )
        now = _utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO nearby_cache (cache_key, data, last_used) VALUES (?, ?, ?)",
                (key, json.dumps(candidates, ensure_ascii=False), now),
            )
            # Älteste Einträge entfernen, wenn mehr als 10 vorhanden
            count = conn.execute("SELECT COUNT(*) FROM nearby_cache").fetchone()[0]
            if count > 10:
                conn.execute(
                    "DELETE FROM nearby_cache WHERE cache_key IN "
                    "(SELECT cache_key FROM nearby_cache ORDER BY last_used ASC LIMIT ?)",
                    (count - 10,),
                )
        logger.debug("Nearby-Cache gespeichert: %s (Einträge gesamt: %d)", key[:12], min(count, 10))

    # ------------------------------------------------------------------ #
    # Hilfsmethoden                                                        #
    # ------------------------------------------------------------------ #

    def cleanup_expired(self) -> None:
        """Entfernt abgelaufene Cache-Einträge aus allen Tabellen."""
        cutoff = (_utcnow() - timedelta(hours=CACHE_EXPIRY_HOURS)).isoformat()
        with self._connect() as conn:
            conn.execute("DELETE FROM directions_cache WHERE created_at < ?", (cutoff,))
            conn.execute("DELETE FROM weather_cache WHERE created_at < ?", (cutoff,))
        logger.info("Abgelaufene Cache-Einträge gelöscht (älter als %s).", cutoff)


def _is_expired(created_at_iso: str) -> bool:
    """Prüft, ob ein Cache-Eintrag älter als CACHE_EXPIRY_HOURS ist."""
    try:
        created = datetime.fromisoformat(created_at_iso)
        return _utcnow() - created > timedelta(hours=CACHE_EXPIRY_HOURS)
    except ValueError:
        return True
