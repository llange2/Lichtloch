"""Tests für modules/osm_api.py: Entfernungen, Ortsauswahl und Kandidatenpool (ohne Netzwerk)."""

import pytest

from modules import USER_AGENT, osm_api
from modules.osm_api import (
    POOL_SIZE,
    _build_candidate_pool,
    _estimate_seconds,
    _haversine_m,
    _overpass_query,
    _spread,
    select_spread,
)


def test_haversine_ein_breitengrad_sind_rund_111_km():
    assert _haversine_m(0, 0, 1, 0) == pytest.approx(111_195, rel=1e-3)


def test_haversine_gleicher_punkt_ist_null():
    assert _haversine_m(47.99, 7.85, 47.99, 7.85) == 0


def test_haversine_freiburg_basel():
    # Luftlinie Freiburg i. Br. – Basel ca. 55 km
    assert _haversine_m(47.9990, 7.8421, 47.5596, 7.5886) == pytest.approx(55_000, rel=0.05)


def ort(i, duration=0):
    return {"lat": 47.0 + i * 0.05, "lng": 8.0 + i * 0.05, "duration_sec": duration, "name": f"Ort{i}"}


def test_spread_waehlt_die_entferntesten_orte():
    places = [{"lat": 0.0, "lng": float(lng), "duration_sec": 0} for lng in range(11)]
    picked = _spread(places, 2)
    assert sorted(p["lng"] for p in picked) == [0.0, 10.0]


def test_spread_beachtet_bereits_gewaehlte_orte():
    places = [{"lat": 0.0, "lng": float(lng), "duration_sec": 0} for lng in range(11)]
    picked = _spread(places, 1, chosen=[places[0]])
    assert picked == [places[10]]


def test_spread_mehr_gewuenscht_als_vorhanden():
    places = [ort(i) for i in range(3)]
    assert len(_spread(places, 10)) == 3


def test_select_spread_unter_dem_limit_gibt_alle_zurueck():
    places = [ort(i, i * 60) for i in range(5)]
    assert select_spread(places, 10, 3600) == places


def test_select_spread_verteilt_gleichmaessig_auf_die_baender():
    # 30 Orte, 0 bis 58 min; Limit 60 min → Bänder 0–20, 20–40, 40–60 min
    places = [ort(i, i * 120) for i in range(30)]
    chosen = select_spread(places, 9, 3600)
    assert len(chosen) == 9
    bands = [min(2, int(p["duration_sec"] // 1200)) for p in chosen]
    assert [bands.count(b) for b in range(3)] == [3, 3, 3]


def test_select_spread_fuellt_ungenutzte_quote_ohne_doppelte_auf():
    # Das mittlere Band ist leer; trotzdem müssen 9 verschiedene Orte herauskommen.
    places = [ort(i, i * 100) for i in range(12)] + [ort(100 + i, 2500 + i * 100) for i in range(12)]
    chosen = select_spread(places, 9, 3600)
    assert len(chosen) == 9
    assert len({p["name"] for p in chosen}) == 9


def test_overpass_query_enthaelt_nur_die_gewuenschten_ortsarten():
    nur_staedte = _overpass_query(47.0, 8.0, 40_000, only_cities=True)
    assert '"place"="city"' in nur_staedte and '"place"="town"' in nur_staedte
    assert "village" not in nur_staedte and "suburb" not in nur_staedte
    assert "(around:40000,47.0,8.0)" in nur_staedte

    alle = _overpass_query(47.0, 8.0, 40_000, only_cities=False)
    assert '"place"="village"' in alle and '"place"="suburb"' in alle


def test_estimate_seconds_nutzt_geschwindigkeit_des_verkehrsmittels():
    origin = (47.0, 8.0)
    dest = {"lat": 47.5, "lng": 8.0}
    auto = _estimate_seconds(origin, dest, "driving")
    zu_fuss = _estimate_seconds(origin, dest, "walking")
    assert 0 < auto < zu_fuss
    assert _estimate_seconds(origin, dest, "unbekannt") == auto  # Fallback: Auto


class TestKandidatenpool:
    ORIGIN = (47.99, 7.85)

    @staticmethod
    def node(i, name, lat, lon):
        return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": {"name": name}}

    def test_ort_als_knoten_und_flaeche_wird_zusammengefasst(self):
        elements = [
            {"type": "way", "id": 2, "center": {"lat": 47.995, "lon": 7.855}, "tags": {"name": "Freiburg"}},
            self.node(1, "Freiburg", 47.99, 7.85),
        ]
        pool = _build_candidate_pool(elements, *self.ORIGIN, max_distance_m=50_000)
        assert [p["place_id"] for p in pool] == ["osm_node_1"]  # der nähere Treffer bleibt

    def test_gleicher_name_weit_entfernt_bleibt_erhalten(self):
        elements = [self.node(1, "Neudorf", 47.99, 7.85), self.node(2, "Neudorf", 48.30, 7.85)]
        assert len(_build_candidate_pool(elements, *self.ORIGIN, max_distance_m=100_000)) == 2

    def test_filtert_zu_weit_entfernte_namenlose_und_ortlose_elemente(self):
        elements = [
            self.node(1, "Zu weit", 50.0, 7.85),
            {"type": "node", "id": 2, "lat": 47.99, "lon": 7.86, "tags": {}},
            {"type": "way", "id": 3, "tags": {"name": "Ohne Mitte"}},
            self.node(4, "Passt", 48.0, 7.9),
        ]
        pool = _build_candidate_pool(elements, *self.ORIGIN, max_distance_m=50_000)
        assert [p["name"] for p in pool] == ["Passt"]

    def test_pool_ist_nach_entfernung_sortiert(self):
        elements = [self.node(1, "Fern", 48.2, 7.85), self.node(2, "Nah", 48.0, 7.85)]
        pool = _build_candidate_pool(elements, *self.ORIGIN, max_distance_m=100_000)
        assert [p["name"] for p in pool] == ["Nah", "Fern"]

    def test_pool_wird_auf_pool_size_ausgedünnt(self):
        elements = [self.node(i, f"Ort{i}", 47.0 + i * 0.001, 8.0) for i in range(POOL_SIZE * 2)]
        # 0,001° ≈ 111 m: die Namen sind verschieden, also greift nur die Ausdünnung
        pool = _build_candidate_pool(elements, 47.0, 8.0, max_distance_m=300_000)
        assert len(pool) == POOL_SIZE


def test_overpass_und_osrm_nutzen_den_gemeinsamen_user_agent():
    assert osm_api._OSM_HEADERS["User-Agent"] == USER_AGENT


def test_alle_dienste_laufen_ueber_https():
    urls = [osm_api.GEOCODING_URL, osm_api.OSRM_ROUTE_URL, osm_api.OSRM_TABLE_URL, *osm_api.OVERPASS_URLS]
    assert all(url.startswith("https://") for url in urls)
