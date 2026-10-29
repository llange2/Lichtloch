"""
weather.py – Open-Meteo API Wrapper für stündliche Wetterdaten.

Abgefragt werden:
  - cloud_cover (Bewölkung in % pro Stunde)
  - is_day (Tageslicht-Flag pro Stunde)
  - sunshine_duration (Sekunden pro Stunde, nur zur Information)
  - precipitation (mm pro Stunde)
  - temperature_2m (Grad Celsius pro Stunde)

Berechnet werden (auf Basis der Bewölkung; 50 % Bewölkung = 50 % Sonne):
  - Sonnenstunden = Summe von (1 − Bewölkung) über alle Tageslicht-Stunden
  - mittlere Bewölkung über die Tageslicht-Stunden
  - Längste klare Phase (zusammenhängende Tageslicht-Stunden mit ≤ 50 % Bewölkung)
  - Gesamtniederschlag (mm)
  - Durchschnittstemperatur (Grad Celsius)

Hintergrund: Früher zählte jede Stunde mit mehr als 0 s Sonnenschein als volle
Sonnenstunde (103 s Sonne = 1 h). Dadurch erschienen überwiegend bewölkte Orte als
„sonnig“. Die Modellgröße sunshine_duration und die Bewölkung stimmen außerdem nicht
immer überein; deshalb bestimmt die Bewölkung das Ranking.
"""

import logging
import time
from typing import Any, Optional

import requests

from modules import USER_AGENT

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT = 15
HOURLY_VARS = "cloud_cover,sunshine_duration,precipitation,temperature_2m,is_day"
MAX_ATTEMPTS = 3

# Eine Stunde zählt zur „längsten klaren Phase“, wenn die Bewölkung höchstens so hoch ist.
CLEAR_HOUR_MAX_CLOUD = 50.0


class WeatherError(Exception):
    """Fehler beim Abruf von Open-Meteo."""
    pass


class WeatherResult:
    """Enthält die berechneten Wetterwerte für einen Ort und ein Datum."""

    def __init__(
        self,
        total_sunshine_hours: float,
        longest_sunshine_period_hours: float,
        total_precipitation_mm: float,
        avg_temperature_c: float,
        hourly_sunshine_seconds: list[float],
        hourly_precipitation_mm: list[float],
        avg_cloud_pct: float = 100.0,
        measured_sunshine_hours: float = 0.0,
        hourly_cloud_pct: Optional[list[float]] = None,
        hourly_sun_fraction: Optional[list[float]] = None,
        hourly_is_day: Optional[list[int]] = None,
        hourly_temperature_c: Optional[list[Optional[float]]] = None,
    ) -> None:
        # Sonnenstunden = Tageslicht-Stunden gewichtet mit dem klaren Himmel (Bewölkung)
        self.total_sunshine_hours = total_sunshine_hours
        # Längste Phase zusammenhängender Tageslicht-Stunden mit ≤ 50 % Bewölkung
        self.longest_sunshine_period_hours = longest_sunshine_period_hours
        self.total_precipitation_mm = total_precipitation_mm
        self.avg_temperature_c = avg_temperature_c
        self.hourly_sunshine_seconds = hourly_sunshine_seconds
        self.hourly_precipitation_mm = hourly_precipitation_mm
        self.avg_cloud_pct = avg_cloud_pct
        # Vom Wettermodell gemessene direkte Sonnenscheindauer (nur zur Information)
        self.measured_sunshine_hours = measured_sunshine_hours
        self.hourly_cloud_pct = hourly_cloud_pct or []
        self.hourly_sun_fraction = hourly_sun_fraction or []
        self.hourly_is_day = hourly_is_day or []
        # Temperatur je Stunde in °C; None = unbekannt (nicht 0). Leer bei Altdaten.
        self.hourly_temperature_c = hourly_temperature_c or []

    def to_dict(self) -> dict:
        return {
            "total_sunshine_hours": self.total_sunshine_hours,
            "longest_sunshine_period_hours": self.longest_sunshine_period_hours,
            "total_precipitation_mm": self.total_precipitation_mm,
            "avg_temperature_c": self.avg_temperature_c,
            "hourly_sunshine_seconds": self.hourly_sunshine_seconds,
            "hourly_precipitation_mm": self.hourly_precipitation_mm,
            "avg_cloud_pct": self.avg_cloud_pct,
            "measured_sunshine_hours": self.measured_sunshine_hours,
            "hourly_cloud_pct": self.hourly_cloud_pct,
            "hourly_sun_fraction": self.hourly_sun_fraction,
            "hourly_is_day": self.hourly_is_day,
            "hourly_temperature_c": self.hourly_temperature_c,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WeatherResult":
        return cls(
            total_sunshine_hours=d["total_sunshine_hours"],
            longest_sunshine_period_hours=d["longest_sunshine_period_hours"],
            total_precipitation_mm=d["total_precipitation_mm"],
            avg_temperature_c=d.get("avg_temperature_c", 0.0),
            hourly_sunshine_seconds=d["hourly_sunshine_seconds"],
            hourly_precipitation_mm=d["hourly_precipitation_mm"],
            avg_cloud_pct=d.get("avg_cloud_pct", 100.0),
            measured_sunshine_hours=d.get("measured_sunshine_hours", 0.0),
            hourly_cloud_pct=d.get("hourly_cloud_pct"),
            hourly_sun_fraction=d.get("hourly_sun_fraction"),
            hourly_is_day=d.get("hourly_is_day"),
            hourly_temperature_c=d.get("hourly_temperature_c"),
        )


def validate_connection() -> None:
    """
    Testet die Verbindung zu Open-Meteo.

    Raises:
        WeatherError: Falls die API nicht erreichbar ist.
    """
    params = {
        "latitude": 47.0,
        "longitude": 8.0,
        "hourly": "sunshine_duration",
        "forecast_days": 1,
        "timezone": "auto",
    }
    try:
        resp = requests.get(OPEN_METEO_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        logger.info("Open-Meteo Verbindungstest erfolgreich.")
    except requests.RequestException as e:
        logger.error("Open-Meteo nicht erreichbar: %s", e)
        raise WeatherError(
            "Open-Meteo nicht erreichbar. Bitte Internetverbindung prüfen."
        ) from e


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return default if value is None else float(value)
    except (TypeError, ValueError):
        return default


def fetch_weather(lat: float, lng: float, date_str: str) -> Optional[WeatherResult]:
    """
    Ruft stündliche Wetterdaten für einen Ort und ein Datum ab.

    Bei HTTP 429/5xx und Netzwerkfehlern wird bis zu dreimal mit wachsender Pause
    wiederholt (viele Orte werden parallel abgefragt).

    Args:
        lat:      Breitengrad.
        lng:      Längengrad.
        date_str: Datum im Format 'YYYY-MM-DD'.

    Returns:
        WeatherResult oder None bei Fehler.
    """
    params = {
        "latitude": lat,
        "longitude": lng,
        "hourly": HOURLY_VARS,
        "start_date": date_str,
        "end_date": date_str,
        "timezone": "auto",
    }
    data = None
    last_error: Optional[Exception] = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = requests.get(
                OPEN_METEO_URL, params=params, timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = RuntimeError(f"HTTP {resp.status_code}")
                time.sleep(2 * (attempt + 1))
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except (requests.RequestException, ValueError) as e:
            last_error = e
            time.sleep(1 + attempt)
    if data is None:
        logger.warning(
            "Wetterdaten-Abruf fehlgeschlagen für (%.4f, %.4f): %s", lat, lng, last_error
        )
        return None

    try:
        hourly = data.get("hourly", {})
        cloud_raw: list = hourly.get("cloud_cover", [])
        if not cloud_raw:
            logger.warning("Keine Bewölkungsdaten für (%.4f, %.4f).", lat, lng)
            return None
        return _calculate_weather_stats(
            cloud_raw,
            hourly.get("sunshine_duration", []),
            hourly.get("precipitation", []),
            hourly.get("temperature_2m", []),
            hourly.get("is_day", []),
        )
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        logger.warning("Wetterdaten konnten nicht geparst werden: %s", e)
        return None


def _calculate_weather_stats(
    cloud_pct: list,
    sunshine_seconds: list,
    precipitation_mm: list,
    temperature_c: list,
    is_day: list,
) -> WeatherResult:
    """
    Berechnet die Kennzahlen eines Ortes für einen Tag (24 Stundenwerte je Liste).

    Fehlende Bewölkungswerte zählen als vollständig bedeckt (100 %), damit eine
    unbekannte Stunde nie sonnig wirkt. Nachts (is_day = 0) gibt es keine Sonne.
    """
    hours = len(cloud_pct)
    cloud = [min(100.0, max(0.0, _num(v, 100.0))) for v in cloud_pct]
    day_flags = [bool(_num(is_day[i])) if i < len(is_day) else True for i in range(hours)]
    if not any(day_flags):  # Polarnacht: alle Stunden bewerten statt durch 0 zu teilen
        day_flags = [True] * hours

    sun_fraction = [
        round(1.0 - cloud[i] / 100.0, 3) if day_flags[i] else 0.0 for i in range(hours)
    ]
    daylight = [i for i in range(hours) if day_flags[i]]
    avg_cloud = sum(cloud[i] for i in daylight) / len(daylight) if daylight else 100.0

    longest = current = 0
    for i in range(hours):
        if day_flags[i] and cloud[i] <= CLEAR_HOUR_MAX_CLOUD:
            current += 1
            longest = max(longest, current)
        else:
            current = 0

    sunshine = [_num(v) for v in sunshine_seconds]
    precipitation = [_num(v) for v in precipitation_mm]
    temperatures = [_num(v) for v in temperature_c]

    return WeatherResult(
        total_sunshine_hours=round(sum(sun_fraction), 1),
        longest_sunshine_period_hours=float(longest),
        total_precipitation_mm=round(sum(precipitation), 1),
        avg_temperature_c=round(sum(temperatures) / len(temperatures), 1) if temperatures else 0.0,
        hourly_sunshine_seconds=sunshine,
        hourly_precipitation_mm=[round(v, 1) for v in precipitation],
        avg_cloud_pct=round(avg_cloud, 1),
        measured_sunshine_hours=round(sum(sunshine) / 3600.0, 1),
        hourly_cloud_pct=[round(v) for v in cloud],
        hourly_sun_fraction=sun_fraction,
        hourly_is_day=[1 if f else 0 for f in day_flags],
        hourly_temperature_c=[
            None if v is None else round(_num(v), 1) for v in temperature_c
        ],
    )
