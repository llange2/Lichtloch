"""Tests für modules/weather.py: Bewölkungs-Kennzahlen und der Abruf bei Open-Meteo."""

import pytest
import requests

from modules import USER_AGENT, weather
from modules.weather import WeatherResult, _calculate_weather_stats, _num, fetch_weather

TAG = [0] * 6 + [1] * 12 + [0] * 6  # is_day: 12 Stunden Tageslicht


def stats(cloud, is_day=TAG, sunshine=None, rain=None, temp=None):
    hours = len(cloud)
    return _calculate_weather_stats(
        cloud,
        sunshine if sunshine is not None else [0] * hours,
        rain if rain is not None else [0] * hours,
        temp if temp is not None else [10] * hours,
        is_day,
    )


def test_klarer_himmel_zaehlt_alle_tageslichtstunden():
    result = stats([0] * 24)
    assert result.total_sunshine_hours == 12.0
    assert result.avg_cloud_pct == 0.0
    assert result.longest_sunshine_period_hours == 12.0


def test_halbe_bewoelkung_ergibt_halbe_sonnenstunden():
    result = stats([50] * 24)
    assert result.total_sunshine_hours == 6.0
    assert result.avg_cloud_pct == 50.0
    assert result.longest_sunshine_period_hours == 12.0  # 50 % zählt noch als klar


def test_ueber_50_prozent_gibt_keine_klare_phase():
    result = stats([51] * 24)
    assert result.longest_sunshine_period_hours == 0.0


def test_laengste_klare_phase_ist_zusammenhaengend():
    cloud = [100] * 24
    for hour in (7, 8, 9, 13, 14):  # 3 h und 2 h am Stück
        cloud[hour] = 0
    assert stats(cloud).longest_sunshine_period_hours == 3.0


def test_fehlende_werte_zaehlen_als_bedeckt():
    result = stats([None] * 24)
    assert result.total_sunshine_hours == 0.0
    assert result.avg_cloud_pct == 100.0


def test_werte_ausserhalb_0_bis_100_werden_begrenzt():
    result = stats([-20] * 12 + [250] * 12)
    assert all(0 <= value <= 100 for value in result.hourly_cloud_pct)


def test_polarnacht_bewertet_alle_stunden():
    result = stats([0] * 24, is_day=[0] * 24)
    assert result.total_sunshine_hours == 24.0


def test_kuerzere_is_day_liste_gilt_als_tag():
    result = stats([0] * 24, is_day=[1] * 10)
    assert result.total_sunshine_hours == 24.0


def test_niederschlag_summe_und_temperatur_mittel():
    result = stats([0] * 24, rain=[0.25] * 24, temp=[8] * 12 + [12] * 12)
    assert result.total_precipitation_mm == 6.0
    assert result.avg_temperature_c == 10.0


def test_gemessene_sonnenscheindauer_in_stunden():
    result = stats([0] * 24, sunshine=[1800] * 24)
    assert result.measured_sunshine_hours == 12.0


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, 0.0), ("3.5", 3.5), ("abc", 0.0), (7, 7.0)],
)
def test_num(value, expected):
    assert _num(value) == expected


def test_weather_result_roundtrip():
    original = stats([20] * 24, sunshine=[900] * 24, rain=[0.1] * 24)
    clone = WeatherResult.from_dict(original.to_dict())
    assert clone.to_dict() == original.to_dict()


# --------------------------------------------------------------------------- #
# fetch_weather (ohne Netzwerk)                                                #
# --------------------------------------------------------------------------- #

class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(weather.time, "sleep", lambda _seconds: None)


def hourly_payload():
    return {"hourly": {
        "cloud_cover": [0] * 24,
        "sunshine_duration": [3600] * 24,
        "precipitation": [0] * 24,
        "temperature_2m": [15] * 24,
        "is_day": TAG,
    }}


def test_fetch_weather_erfolg_sendet_user_agent(monkeypatch):
    seen = {}

    def fake_get(url, params, timeout, headers):
        seen.update(url=url, params=params, headers=headers)
        return FakeResponse(200, hourly_payload())

    monkeypatch.setattr(weather.requests, "get", fake_get)
    result = fetch_weather(47.99, 7.85, "2026-06-01")
    assert result is not None and result.total_sunshine_hours == 12.0
    assert seen["headers"]["User-Agent"] == USER_AGENT
    assert seen["params"]["start_date"] == seen["params"]["end_date"] == "2026-06-01"


def test_fetch_weather_wiederholt_bei_server_fehler_und_gibt_dann_auf(monkeypatch):
    calls = []

    def fake_get(*args, **kwargs):
        calls.append(1)
        return FakeResponse(503)

    monkeypatch.setattr(weather.requests, "get", fake_get)
    assert fetch_weather(0, 0, "2026-06-01") is None
    assert len(calls) == weather.MAX_ATTEMPTS


def test_fetch_weather_ohne_bewoelkungsdaten_gibt_none(monkeypatch):
    monkeypatch.setattr(
        weather.requests, "get", lambda *a, **k: FakeResponse(200, {"hourly": {"cloud_cover": []}})
    )
    assert fetch_weather(0, 0, "2026-06-01") is None


def test_stundentemperatur_gerundet_und_unbekannt_bleibt_none():
    temp = [10.04] * 23 + [None]
    result = stats([0] * 24, temp=temp)
    assert result.hourly_temperature_c[0] == 10.0
    assert result.hourly_temperature_c[23] is None  # unbekannt, nicht 0
    assert len(result.hourly_temperature_c) == 24


def test_altdaten_ohne_stundentemperatur_werden_toleriert():
    d = stats([0] * 24).to_dict()
    del d["hourly_temperature_c"]
    assert WeatherResult.from_dict(d).hourly_temperature_c == []
