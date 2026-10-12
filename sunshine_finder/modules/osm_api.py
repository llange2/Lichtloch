"""
osm_api.py – Ortssuche, Kandidatenorte und Reisezeit ohne Google und ohne API-Key.

  - Ortssuche beim Tippen:    Open-Meteo Geocoding
  - Kandidatenorte:           OpenStreetMap Overpass (mehrere Server werden probiert)
  - Reisezeit (Auto):         OSRM; andere Verkehrsmittel: Luftlinien-Schätzung
"""

import logging
import math
import time
from typing import Optional

import requests

from modules import USER_AGENT

logger = logging.getLogger(__name__)

# Basis-URL der Ortssuche
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
# Öffentliche Overpass-Server sind geteilt und oft überlastet; sie werden der Reihe nach probiert.
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
OVERPASS_ROUNDS = 2          # vollständige Durchläufe über alle Server, bevor aufgegeben wird
OVERPASS_PAUSE_S = 4         # Pause zwischen den Durchläufen
OVERPASS_TIMEOUT = (10, 75)  # Verbindung, Lesen – große Gebiete brauchen 15–25 s
OSRM_ROUTE_URL = "https://router.project-osrm.org/route/v1/driving/{coords}"
OSRM_TABLE_URL = "https://router.project-osrm.org/table/v1/driving/{coords}"
OSRM_CHUNK = 90              # der öffentliche Server erlaubt 100 Koordinaten je Table-Anfrage

MAX_RADIUS_M = 300_000       # begrenzt die Overpass-Abfrage auch bei 12 h Autofahrt
POOL_SIZE = 400              # so viele Kandidaten werden höchstens auf Reisezeit geprüft
DISTANCE_BANDS = 3           # Reisezeit-Bänder, auf die die maximale Ortsanzahl verteilt wird

# Headers für OpenStreetMap-Dienste
_OSM_HEADERS = {"Accept": "*/*", "User-Agent": USER_AGENT}

# Typische Reisegeschwindigkeiten in m/s für Haversine-Schätzung
_SPEEDS_MPS = {
    "driving": 80_000 / 3600,
    "walking": 4_000 / 3600,
    "bicycling": 15_000 / 3600,
    "transit": 35_000 / 3600,
}
_ROUTE_FACTOR = 1.35  # Faktor Luftlinie → Streckendistanz


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Luftlinienabstand in Metern (Haversine-Formel)."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))

def _spread(
    places: list[dict], count: int, chosen: Optional[list[dict]] = None
) -> list[dict]:
    """
    Wählt `count` Orte, die möglichst weit auseinander liegen (Farthest-Point-Sampling,
    optional unter Berücksichtigung bereits gewählter Orte `chosen`).

    Das Wetter ändert sich über die Entfernung langsam; weit verteilte Stichproben
    finden klare Regionen besser als ein enger Haufen direkter Nachbarn.
    """
    anchors = list(chosen or [])
    pool = [p for p in places if not any(p is c for c in anchors)]
    picked: list[dict] = []
    nearest = [
        min((_haversine_m(p["lat"], p["lng"], a["lat"], a["lng"]) for a in anchors),
            default=math.inf)
        for p in pool
    ]
    while pool and len(picked) < count:
        i = max(range(len(pool)), key=lambda j: (nearest[j], -pool[j].get("duration_sec", 0)))
        best = pool.pop(i)
        nearest.pop(i)
        picked.append(best)
        for j, p in enumerate(pool):
            nearest[j] = min(
                nearest[j], _haversine_m(p["lat"], p["lng"], best["lat"], best["lng"])
            )
    return picked


def select_spread(
    in_reach: list[dict], max_places: int, limit_sec: float, bands: int = DISTANCE_BANDS
) -> list[dict]:
    """
    Wählt höchstens `max_places` der erreichbaren Orte so aus, dass jedes Reisezeit-Band
    (z. B. 0–30, 30–60, 60–90 min) vertreten ist und die Orte innerhalb eines Bandes
    weit auseinander liegen. Ungenutzte Quote eines dünn besetzten Bandes wird aus den
    übrigen Orten aufgefüllt.

    Hintergrund: Früher wurden die nächsten Orte zuerst genommen; bei 1,5 h Limit lagen
    alle 60 Ergebnisse 25–39 min entfernt, und eine klare Region in 70 min Entfernung
    wurde nie angeschaut.
    """
    if len(in_reach) <= max_places:
        return list(in_reach)
    width = limit_sec / bands
    groups: list[list[dict]] = [[] for _ in range(bands)]
    for d in in_reach:
        groups[min(bands - 1, int(d["duration_sec"] // width))].append(d)
    quota = max_places // bands
    chosen: list[dict] = []
    for g in groups:
        chosen += _spread(g, quota)
    left = max_places - len(chosen)
    if left > 0:  # Divisionsrest + Quote, die ein dünnes Band nicht nutzen konnte
        chosen += _spread(in_reach, left, chosen)
    return chosen


# HTTP-Timeout in Sekunden
REQUEST_TIMEOUT = 10


class GeoApiError(Exception):
    """Allgemeiner Fehler beim Abruf von Orten oder Reisezeiten."""
    pass


def _overpass_query(lat: float, lng: float, radius: int, only_cities: bool) -> str:
    # Exakte Tag-Vergleiche nutzen den Index und sind deutlich schneller als eine Regex.
    kinds = ("city", "town") if only_cities else ("city", "town", "village", "suburb")
    around = f"(around:{radius},{lat},{lng})"
    parts = "".join(
        f'{el}["place"="{k}"]{around};' for k in kinds for el in ("node", "way")
    )
    return f"[out:json][timeout:60];({parts});out tags center qt;"


def _fetch_overpass(query: str) -> list[dict]:
    """
    Sendet die Abfrage nacheinander an die Overpass-Server (mehrere Durchläufe).

    Raises:
        GeoApiError: Wenn alle Server scheitern; die Meldung nennt je Server den Grund.
    """
    errors: list[str] = []
    for attempt in range(OVERPASS_ROUNDS):
        if attempt:
            time.sleep(OVERPASS_PAUSE_S)
        errors = []
        for url in OVERPASS_URLS:
            host = url.split("//", 1)[1].split("/", 1)[0]
            try:
                resp = requests.post(
                    url, data={"data": query}, headers=_OSM_HEADERS, timeout=OVERPASS_TIMEOUT
                )
                if resp.status_code == 200:
                    body = resp.json()
                    # Ein überlasteter Server antwortet mit 200, einem "remark" und leerer Liste.
                    if body.get("remark"):
                        errors.append(f"{host}: {str(body['remark'])[:80]}")
                    else:
                        return body.get("elements", [])
                else:
                    errors.append(f"{host}: HTTP {resp.status_code}")
            except (requests.RequestException, ValueError) as e:
                errors.append(f"{host}: {e.__class__.__name__}")
            logger.warning("Overpass-Server fehlgeschlagen (%s).", errors[-1])
    raise GeoApiError(
        "Orte konnten nicht von OpenStreetMap geladen werden — " + "; ".join(errors)
        + ". Bitte später erneut versuchen oder die maximale Reisezeit verringern."
    )


def _build_candidate_pool(
    elements: list[dict], lat: float, lng: float, max_distance_m: int
) -> list[dict]:
    """
    Wandelt Overpass-Elemente in Kandidaten um (nach Entfernung sortiert).

    Ein Ort ist oft Knoten und Fläche zugleich: pro Name bleibt der nächste Treffer
    innerhalb von 5 km. Bei mehr als POOL_SIZE Orten wird jeder n-te genommen, damit
    nahe UND ferne Gebiete im Pool bleiben.
    """
    found: list[dict] = []
    for e in elements:
        name = (e.get("tags") or {}).get("name", "")
        if not name:
            continue
        if e.get("type") == "way":
            c = e.get("center") or {}
            e_lat, e_lng = c.get("lat"), c.get("lon")
        else:
            e_lat, e_lng = e.get("lat"), e.get("lon")
        if e_lat is None or e_lng is None:
            continue
        dist_m = _haversine_m(lat, lng, float(e_lat), float(e_lng))
        if dist_m > max_distance_m:
            continue
        found.append({
            "name": name,
            "place_id": f"osm_{e.get('type', '')}_{e.get('id', '')}",
            "lat": float(e_lat),
            "lng": float(e_lng),
            "dist_m": dist_m,
        })
    found.sort(key=lambda p: p["dist_m"])

    kept: dict[str, list[dict]] = {}
    pool: list[dict] = []
    for p in found:
        same = kept.setdefault(p["name"].casefold(), [])
        if any(_haversine_m(q["lat"], q["lng"], p["lat"], p["lng"]) < 5_000 for q in same):
            continue
        same.append(p)
        pool.append(p)

    if len(pool) > POOL_SIZE:
        step = len(pool) / POOL_SIZE
        pool = [pool[int(i * step)] for i in range(POOL_SIZE)]
    return pool


def _estimate_seconds(origin: tuple[float, float], dest: dict, mode: str) -> int:
    dist_m = _haversine_m(origin[0], origin[1], dest["lat"], dest["lng"])
    return int(dist_m * _ROUTE_FACTOR / _SPEEDS_MPS.get(mode, _SPEEDS_MPS["driving"]))


def _travel_seconds(origin: tuple[float, float], dests: list[dict], mode: str) -> list[int]:
    """
    Reisezeit in Sekunden je Ziel. Für "driving" eine OSRM-Table-Anfrage je 90 Orte
    (statt einer Anfrage pro Ort), sonst bzw. als Fallback die Haversine-Schätzung.
    """
    if mode != "driving":
        return [_estimate_seconds(origin, d, mode) for d in dests]

    out: list[int] = []
    for start in range(0, len(dests), OSRM_CHUNK):
        chunk = dests[start:start + OSRM_CHUNK]
        coords = ";".join(
            [f"{origin[1]:.5f},{origin[0]:.5f}"]
            + [f"{d['lng']:.5f},{d['lat']:.5f}" for d in chunk]
        )
        durations = None
        for _attempt in range(2):
            try:
                resp = requests.get(
                    OSRM_TABLE_URL.format(coords=coords),
                    params={"sources": 0, "annotations": "duration"},
                    headers=_OSM_HEADERS, timeout=30,
                )
                if resp.status_code == 200:
                    durations = resp.json()["durations"][0][1:]
                    break
            except (requests.RequestException, ValueError, KeyError, IndexError) as e:
                logger.warning("OSRM-Table fehlgeschlagen: %s", e)
            time.sleep(1)
        for i, d in enumerate(chunk):
            value = durations[i] if durations and i < len(durations) else None
            out.append(int(value) if value is not None else _estimate_seconds(origin, d, mode))
    return out


class GeoApiClient:
    """Kapselt Ortssuche, Kandidatenorte und Reisezeit für die Lichtloch-App."""

    def __init__(self) -> None:
        self._session = requests.Session()

    # ------------------------------------------------------------------ #
    # Ortssuche (Open-Meteo Geocoding, kein API Key nötig)                #
    # ------------------------------------------------------------------ #

    def geocode_location(self, input_text: str) -> list[dict]:
        """
        Liefert Ortsnamen-Vorschläge über die Open-Meteo Geocoding API.

        Kein API Key erforderlich. Gibt lat/lng direkt zurück, sodass
        kein separater Place-Details-Aufruf nötig ist.

        Returns:
            Liste von dicts mit 'description', 'place_id', 'lat', 'lng'.
        """
        if len(input_text) < 3:
            return []

        params = {
            "name": input_text,
            "count": 10,
            "language": "de",
            "format": "json",
        }
        try:
            resp = self._session.get(GEOCODING_URL, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error("Geocoding fehlgeschlagen: %s", e)
            return []

        results = data.get("results") or []
        suggestions = []
        for r in results:
            name = r.get("name", "")
            admin1 = r.get("admin1", "")
            country = r.get("country", "")
            parts = [p for p in [name, admin1, country] if p]
            description = ", ".join(parts)
            suggestions.append({
                "description": description,
                "place_id": str(r.get("id", "")),
                "lat": r.get("latitude", 0.0),
                "lng": r.get("longitude", 0.0),
            })
        return suggestions

    # ------------------------------------------------------------------ #
    # Kandidatenorte (Overpass)                                            #
    # ------------------------------------------------------------------ #

    def nearby_search(
        self,
        lat: float,
        lng: float,
        max_results: int = 60,
        only_cities: bool = True,
        mode: str = "driving",
        max_duration_sec: Optional[int] = None,
    ) -> list[dict]:
        """
        Sucht Städte und Orte in Reichweite von (lat, lng) via Overpass API (OpenStreetMap).

        Ablauf:
          1. Orte im Umkreis laden (höchstens POOL_SIZE, gleichmäßig ausgedünnt).
          2. Reisezeit für alle Kandidaten bestimmen (OSRM-Table bzw. Schätzung).
          3. Orte außerhalb der maximalen Reisezeit verwerfen.
          4. `max_results` Orte auf drei Reisezeit-Bänder verteilen, innerhalb eines
             Bandes möglichst weit auseinander (siehe `select_spread`).

        Args:
            lat, lng:     Zentrum der Suche.
            max_results:  Maximale Anzahl Ergebnisse.
            only_cities:  True → nur city/town; False → auch village/suburb.
            mode:         Verkehrsmittel (driving, walking, bicycling, transit).
            max_duration_sec: Maximale Reisezeit in Sekunden; steuert den Suchradius.

        Returns:
            Liste von dicts mit 'name', 'place_id', 'lat', 'lng', 'duration_sec'.

        Raises:
            GeoApiError: Wenn kein Overpass-Server erreichbar war (mit Details je Server).
        """
        if max_results <= 0:
            return []

        if max_duration_sec is None or max_duration_sec <= 0:
            max_duration_sec = 3600
        speed_mps = _SPEEDS_MPS.get(mode, _SPEEDS_MPS["driving"])
        max_distance_m = int(min(MAX_RADIUS_M, max(1.0, speed_mps * max_duration_sec)))

        elements = _fetch_overpass(_overpass_query(lat, lng, max_distance_m, only_cities))
        pool = _build_candidate_pool(elements, lat, lng, max_distance_m)

        durations = _travel_seconds((lat, lng), pool, mode)
        in_reach: list[dict] = []
        for place, seconds in zip(pool, durations):
            if seconds <= max_duration_sec:
                in_reach.append({**place, "duration_sec": seconds})

        results = [
            {
                "name": p["name"],
                "place_id": p["place_id"],
                "lat": p["lat"],
                "lng": p["lng"],
                "duration_sec": p["duration_sec"],
            }
            for p in select_spread(in_reach, max_results, max_duration_sec)
        ]
        logger.info(
            "Kandidaten (Overpass): %d im Pool, %d in Reichweite, %d ausgewählt "
            "(max_distance=%dm, mode=%s).",
            len(pool), len(in_reach), len(results), max_distance_m, mode,
        )
        return results

    # ------------------------------------------------------------------ #
    # Reisezeit (OSRM)                                                      #
    # ------------------------------------------------------------------ #

    def get_travel_duration(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        mode: str,
        departure_unix: int,
    ) -> Optional[int]:
        """
        Gibt die Reisezeit in Sekunden zurück.

        Für "driving" wird OSRM (OpenStreetMap Routing Machine) verwendet.
        Für alle anderen Modi wird eine Haversine-basierte Schätzung berechnet.

        Args:
            origin_lat, origin_lng: Startkoordinaten.
            dest_lat, dest_lng:     Zielkoordinaten.
            mode:                   Verkehrsmittel (driving, walking, bicycling, transit).
            departure_unix:         Abfahrtszeit als Unix-Timestamp (nicht mehr verwendet).

        Returns:
            Reisezeit in Sekunden oder None bei Fehler.
        """
        if mode == "driving":
            coords = f"{origin_lng},{origin_lat};{dest_lng},{dest_lat}"
            url = OSRM_ROUTE_URL.format(coords=coords)
            try:
                resp = requests.get(
                    url,
                    params={"overview": "false"},
                    headers=_OSM_HEADERS,
                    timeout=REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("routes"):
                    return int(data["routes"][0]["duration"])
                logger.debug("OSRM: keine Route nach %s,%s", dest_lat, dest_lng)
            except Exception as e:
                logger.warning("OSRM-Anfrage fehlgeschlagen, Haversine-Fallback: %s", e)

        # Haversine-Schätzung für alle anderen Modi und als Fallback bei driving
        dist_m = _haversine_m(origin_lat, origin_lng, dest_lat, dest_lng)
        speed_mps = _SPEEDS_MPS.get(mode, _SPEEDS_MPS["driving"])
        return int(dist_m * _ROUTE_FACTOR / speed_mps)
