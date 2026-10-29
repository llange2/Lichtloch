"""
map_window.py – Kartenfenster der Lichtloch App.

Zeigt alle Orte der Ergebnisliste auf einer OpenStreetMap-Karte
(Leaflet + Leaflet.markercluster, eingebettet via QtWebEngine). Es ist kein
API-Key nötig; Leaflet, das Cluster-Plugin und die Kacheln lädt der
Browser-Teil der App aus dem Internet (cdnjs, tile.openstreetmap.org).

  - Der Startort liegt in der Kartenmitte, der Zoom ist so gewählt, dass alle
    Orte sichtbar sind.
  - Jeder Ort erhält ein Symbol mit der Zahl der Sonnenstunden (eine Nachkommastelle):
      kein Niederschlag → Sonne, sonst Sonne mit Wolke und 1–3 Tropfen.
  - Orte, die auf dem Bildschirm dicht beieinander liegen, werden je Region gebündelt.
    Ein Bündel zeigt das Symbol, das die meisten seiner Orte haben (bei Gleichstand das
    sonnigere), und den Sonnenanteil in % (100 − Bewölkung) des sonnigsten Ortes,
    grün ab 70 %, gelb ab 40 %, sonst orange. Ein Klick zoomt in das Bündel hinein;
    ein Klick auf das Symbol eines einzelnen Orts öffnet dessen Detailansicht (wie ein Klick
    auf die Zeile der Ergebnisliste).
  - Symbole und Zahl skalieren beim Zoomen mit der Karte. Die Sonnen einzelner Orte sind
    kleiner als die der Bündel; die Zahl wird so gesetzt, dass sie in die gelbe Scheibe der
    Sonne passt (nicht in den Strahlenkranz ragt) und dort zentriert ist.
  - Navigation: Mausrad = Zoom, Ziehen mit gedrückter Maustaste = Karte bewegen.
"""

import base64
import json
import logging
import math
import os
import sys
from typing import Optional

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QVBoxLayout, QWidget

logger = logging.getLogger(__name__)

# Pseudo-Origin der Seite. Die OpenStreetMap-Kachelserver verlangen einen gültigen
# Referer; QtWebEngine sendet diesen Wert, weil die Seite per setHtml geladen wird.
MAP_BASE_URL = "https://lichtloch.local/"

# Ein Klick auf einen Ort navigiert zu "lichtloch://spot/<Index>"; die Seite fängt das ab
# (_MapPage) und meldet den Index der Ergebnisliste an das Fenster.
SPOT_SCHEME = "lichtloch"
SPOT_HOST = "spot"

# Feste Versionen der externen Bibliotheken (cdnjs)
LEAFLET_URL = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/"
CLUSTER_URL = "https://cdnjs.cloudflare.com/ajax/libs/leaflet.markercluster/1.5.3/"

# Niederschlags-Abstufung (Tagessumme in mm), angelehnt an die DWD-Intensitäts-
# klassen leicht < 2,5 / mäßig 2,5 bis < 10 / stark ≥ 10 (≥ 10 mm entspricht
# zugleich dem Starkniederschlagstag im DWD-Klimaatlas).
RAIN_MODERATE_MM = 2.5
RAIN_HEAVY_MM = 10.0

SYMBOL_FILES: dict[int, str] = {
    0: "symbol_sun.png",
    1: "symbol_sun_rain_1.png",
    2: "symbol_sun_rain_2.png",
    3: "symbol_sun_rain_3.png",
}

def precipitation_level(precipitation_mm: Optional[float]) -> int:
    """
    Ordnet die Tages-Niederschlagssumme einem Symbol zu.

    0 = kein Niederschlag (nur Sonne)
    1 = leicht   (> 0 bis < 2,5 mm)  → 1 Tropfen
    2 = mäßig    (2,5 bis < 10 mm)   → 2 Tropfen
    3 = stark    (≥ 10 mm)           → 3 Tropfen
    """
    if not precipitation_mm or precipitation_mm <= 0:
        return 0
    if precipitation_mm < RAIN_MODERATE_MM:
        return 1
    if precipitation_mm < RAIN_HEAVY_MM:
        return 2
    return 3


def _assets_dir() -> str:
    """Verzeichnis der Symbol-Dateien (auch in der PyInstaller-EXE)."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        return os.path.join(base, "assets")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def load_symbols() -> dict[int, str]:
    """Lädt die vier Symbole als Base64-Strings (für die Einbettung ins HTML)."""
    symbols: dict[int, str] = {}
    for level, filename in SYMBOL_FILES.items():
        with open(os.path.join(_assets_dir(), filename), "rb") as fh:
            symbols[level] = base64.b64encode(fh.read()).decode("ascii")
    return symbols


def _js_json(value) -> str:
    """JSON für die Einbettung in ein <script>-Element (kein vorzeitiges </script>)."""
    text = json.dumps(value, ensure_ascii=False)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _place_payload(result: dict, index: int = 0) -> dict:
    """Reduziert ein Suchergebnis auf die für die Karte nötigen Felder."""
    hours = round(float(result["total_sunshine_hours"]), 1)
    cloud = float(result.get("avg_cloud_pct", 100.0))
    precipitation = float(result.get("total_precipitation_mm") or 0.0)
    minutes = math.ceil(result["duration_sec"] / 60)
    tooltip = (
        f"{result['name']}\n"
        f"Sonnenstunden: {hours:.1f} h\n"
        f"Bewölkung: {cloud:.0f} %\n"
        f"Niederschlag: {precipitation:.1f} mm\n"
        f"Reisezeit: {minutes} min"
    )
    return {
        "i": index,
        "lat": float(result["lat"]),
        "lng": float(result["lng"]),
        "n": result["name"],
        "h": hours,
        "c": round(cloud),
        "l": precipitation_level(precipitation),
        "t": tooltip,
    }



# --------------------------------------------------------------------------- #
# HTML-Seite                                                                   #
# --------------------------------------------------------------------------- #

_MAP_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Lichtloch – Karte</title>
<link rel="stylesheet" href="%%LEAFLET%%leaflet.min.css">
<link rel="stylesheet" href="%%CLUSTER%%MarkerCluster.css">
<style>
  html, body { margin: 0; height: 100%; overflow: hidden;
               font-family: "Segoe UI", Arial, sans-serif; }
  /* --sym = Größe der Bündel-Sonnen, --sym-single = Größe der Sonnen einzelner Orte (kleiner) */
  #map { position: absolute; inset: 0; --sym: 64px; --sym-single: 48px; background: #e8eef2; }
  #msg { display: none; position: absolute; inset: 0; z-index: 2000;
         align-items: center; justify-content: center; text-align: center;
         padding: 24px; background: #fafafa; color: #333;
         font-size: 16px; line-height: 1.6; }
  /* Marker-Hüllen von Leaflet bleiben leer (Größe 0); das Symbol hängt mittig daran. */
  .leaflet-div-icon { background: none; border: none; }
  /* Die Schriftgröße wird in start() so berechnet, dass die Zahl in die gelbe Scheibe der
     Sonne passt (--k-* = Schriftgröße im Verhältnis zur Symbolgröße). */
  .sym { --S: var(--sym); --base: var(--base-cluster, 0.85);
         position: absolute; width: var(--S); height: var(--S);
         transform: translate(-50%, -50%);
         display: flex; align-items: center; justify-content: center;
         background-repeat: no-repeat; background-size: 100% 100%;
         font-size: calc(var(--S) * var(--k-cluster, 0.16));
         user-select: none; }
  .sym.single { --S: var(--sym-single); --base: var(--base-single, 0.85);
                font-size: calc(var(--S) * var(--k-single, 0.2)); }
  /* Die gelbe Scheibe der Sonne liegt in allen Grafiken bei 49,6 % / 50,5 % der Symbolgröße
     (Durchmesser ≈ 48 %). Die Zahl wird per Flexbox mittig gesetzt und von dort um den Versatz der
     Scheibe und der Zeichen im Textfeld verschoben: --dx = seitlicher Versatz der Zeichen,
     --ink = halbe Zeichenhöhe, --base = Lage der Grundlinie im 1em hohen Feld (in start()
     je Schriftgröße gemessen: Chromium rundet dabei bei kleinen Schriften auf ganze Pixel). */
  .sym .num { position: relative;
              left: calc(var(--S) * -0.004 - var(--dx, 0) * 1em);
              top: calc(var(--S) * 0.005 - (var(--base) - var(--ink, 0.35) - 0.5) * 1em);
              /* explizit: Leaflet setzt am Container "Helvetica Neue"; gemessen wird mit dieser Schrift */
              font-family: "Segoe UI", Arial, sans-serif;
              font-size: 1em; font-weight: 700; line-height: 1;
              white-space: nowrap;
              color: #4a2200;
              text-shadow: 0 0 0.12em rgba(255, 244, 200, 0.95),
                           0 0 0.24em rgba(255, 244, 200, 0.7);
              pointer-events: none; }
  .sym.cluster, .sym.single { cursor: pointer; }
  .sym .num.good { color: #12701a; }
  .sym .num.ok   { color: #7a5c00; }
  .sym .num.poor { color: #b04a0b; }
  .origin { width: 16px; height: 16px; margin: -8px 0 0 -8px; border-radius: 50%;
            background: #e53935; border: 3px solid #fff; box-shadow: 0 0 4px rgba(0,0,0,.6);
            box-sizing: border-box; }
  .s0 { background-image: url(data:image/png;base64,%%SYM0%%); }
  .s1 { background-image: url(data:image/png;base64,%%SYM1%%); }
  .s2 { background-image: url(data:image/png;base64,%%SYM2%%); }
  .s3 { background-image: url(data:image/png;base64,%%SYM3%%); }
</style>
</head>
<body>
<div id="map"></div>
<div id="msg"></div>
<script>
(function () {
  "use strict";

  var ORIGIN = %%ORIGIN%%;
  var PLACES = %%PLACES%%;
  var LEAFLET = "%%LEAFLET%%";
  var CLUSTER = "%%CLUSTER%%";

  // Symbolgröße (Kantenlänge der Symbol-Grafik in px) auf Höhe des Start-Zooms
  // (bei sehr vielen Orten etwas kleiner) und Änderung pro Zoomstufe. Bewusst < 2
  // pro Stufe: Die Symbole wachsen beim Hineinzoomen spürbar mit, überdecken sich
  // aber nicht dauerhaft.
  var BASE_SIZE = Math.max(40, Math.min(64, Math.round(64 * Math.sqrt(60 / Math.max(PLACES.length, 1)))));
  var ZOOM_STEP = 1.4, MIN_SIZE = 22, MAX_SIZE = 190;
  var MIN_FIT_ZOOM = 2, MAX_FIT_ZOOM = 15;
  var CLUSTER_RADIUS_PX = 60;

  // Sonnen einzelner Orte sind kleiner als die der Bündel (Anteil der Bündel-Größe).
  var SINGLE_SCALE = 0.75;
  // Die gelbe Scheibe der Sonne (ohne Strahlenkranz) hat ≈ 48 % der Symbolgröße als
  // Durchmesser. Die Zahl belegt höchstens FIT davon, damit sie nicht in die Strahlen ragt.
  var DISC = 0.48, FIT = 0.9;

  var mapEl = document.getElementById("map");

  // Maße der Zeichen (in em) für Schriftgröße und Zentrierung. Das 1em hohe Textfeld
  // (line-height: 1) liegt mittig auf der Sonne; die Zeichen sitzen darin nicht genau mittig.
  // Gemessen werden: Breite (w), seitlicher Versatz der Zeichen zur Feldmitte (dx) und halbe
  // Zeichenhöhe über der Grundlinie (c); das CSS gleicht den Versatz damit aus.
  var FONT = '"Segoe UI", Arial, sans-serif';
  var measureCtx = document.createElement("canvas").getContext("2d");
  var inkCache = {};
  function ink(text) {
    if (inkCache[text]) return inkCache[text];
    measureCtx.font = "700 100px " + FONT;
    var m = measureCtx.measureText(text);
    var l = m.actualBoundingBoxLeft / 100, r = m.actualBoundingBoxRight / 100;
    var aa = m.actualBoundingBoxAscent / 100, ad = m.actualBoundingBoxDescent / 100;
    var res = { w: l + r, dx: (r - l) / 2 - m.width / 200, c: (aa - ad) / 2 };
    if (!isFinite(res.w + res.dx + res.c) || res.w <= 0) {
      res = { w: m.width / 100, dx: 0, c: 0.35 };    // ältere Engine ohne diese Messwerte
    }
    return (inkCache[text] = res);
  }

  // Lage der Grundlinie im 1em hohen Textfeld bei einer bestimmten Schriftgröße, im Browser
  // gemessen (Sonde mit Nullgröße-Element, dessen Unterkante auf der Grundlinie sitzt).
  // Bei kleinen Schriften rundet Chromium Ascent/Descent auf ganze Pixel, die Lage hängt also
  // von der Größe ab (bei 100 px ≈ 0,91 em, bei 11 px ≈ 0,84 em).
  function baselineAt(px) {
    var d = document.createElement("div");
    d.style.cssText = "position:absolute;left:-9999px;top:0;white-space:nowrap;font:700 " +
                      px.toFixed(2) + "px/1 " + FONT;
    d.innerHTML = '0<span style="display:inline-block;width:0;height:0"></span>';
    document.body.appendChild(d);
    var b = (d.lastChild.getBoundingClientRect().bottom - d.getBoundingClientRect().top) / px;
    document.body.removeChild(d);
    return b;
  }

  function showMessage(html) {
    var m = document.getElementById("msg");
    m.innerHTML = html;
    m.style.display = "flex";
  }

  function esc(t) {
    return String(t).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  function load(url, cb, onerror) {
    var el = document.createElement("script");
    el.src = url; el.onload = cb; el.onerror = onerror || function () {};
    document.head.appendChild(el);
  }

  // Sonnenanteil (100 − Bewölkung) → Farbklasse der Zahl
  function band(sunPct) { return sunPct >= 70 ? "good" : (sunPct >= 40 ? "ok" : "poor"); }

  // Symbol eines einzelnen Ortes bzw. eines Bündels (hängt mittig am Marker, Größe 0)
  function symbolIcon(level, text, cls, extra) {
    var m = ink(text);
    return L.divIcon({
      className: "", iconSize: [0, 0], iconAnchor: [0, 0],
      html: '<div class="sym s' + level + (extra || "") + '"><span class="num ' + cls +
            '" style="--dx:' + m.dx.toFixed(3) + ";--ink:" + m.c.toFixed(3) + '">' + text + "</span></div>"
    });
  }

  function start() {
    var originLL = L.latLng(ORIGIN.lat, ORIGIN.lng);
    var map = L.map(mapEl, { zoomControl: true, worldCopyJump: true });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18, attribution: "&copy; OpenStreetMap contributors"
    }).addTo(map);

    // Startort in der Mitte; die Grenzen reichen so weit, dass der entfernteste Ort noch sichtbar ist.
    function fit() {
      var dLat = 0, dLng = 0;
      PLACES.forEach(function (p) {
        dLat = Math.max(dLat, Math.abs(p.lat - ORIGIN.lat));
        dLng = Math.max(dLng, Math.abs(p.lng - ORIGIN.lng));
      });
      if (!dLat && !dLng) { map.setView(originLL, 11); return; }
      var bounds = L.latLngBounds(
        [ORIGIN.lat - dLat, ORIGIN.lng - dLng], [ORIGIN.lat + dLat, ORIGIN.lng + dLng]);
      var z = map.getBoundsZoom(bounds, false, L.point(BASE_SIZE / 2 + 16, BASE_SIZE / 2 + 16));
      map.setView(originLL, Math.max(MIN_FIT_ZOOM, Math.min(MAX_FIT_ZOOM, z)), { animate: false });
    }
    map.setView(originLL, 8);   // Leaflet braucht eine Ansicht, bevor Grenzen berechnet werden
    fit();
    var fitZoom = map.getZoom();

    // Schriftgröße je Symbolgröße: breitester Text (Einzelort "00.0", Bündel "100%") füllt FIT
    // des Scheibendurchmessers.
    var kSingle = DISC * FIT / ink("00.0").w, kCluster = DISC * FIT / ink("100%").w;
    mapEl.style.setProperty("--k-single", kSingle.toFixed(4));
    mapEl.style.setProperty("--k-cluster", kCluster.toFixed(4));

    function applySize() {
      var s = BASE_SIZE * Math.pow(ZOOM_STEP, map.getZoom() - fitZoom);
      s = Math.max(MIN_SIZE, Math.min(MAX_SIZE, s));
      var single = s * SINGLE_SCALE;
      mapEl.style.setProperty("--sym", s.toFixed(1) + "px");
      mapEl.style.setProperty("--sym-single", single.toFixed(1) + "px");
      mapEl.style.setProperty("--base-cluster", baselineAt(s * kCluster).toFixed(4));
      mapEl.style.setProperty("--base-single", baselineAt(single * kSingle).toFixed(4));
    }
    applySize();
    map.on("zoom", applySize);

    // Startort (wird nie gebündelt)
    L.marker(originLL, {
      icon: L.divIcon({ className: "", iconSize: [0, 0], html: '<div class="origin"></div>' }),
      zIndexOffset: -1000, keyboard: false
    }).bindTooltip(esc(ORIGIN.name) + " (Startort)").addTo(map);

    // Orte bündeln (ohne Cluster-Plugin werden sie einzeln gezeichnet).
    // Ein Bündel zeigt das Symbol, das die meisten Orte haben (Gleichstand → sonnigeres),
    // und den Sonnenanteil des sonnigsten Ortes.
    var layer = L.markerClusterGroup ? L.markerClusterGroup({
      maxClusterRadius: CLUSTER_RADIUS_PX, showCoverageOnHover: false, spiderfyOnMaxZoom: true,
      iconCreateFunction: function (cluster) {
        var children = cluster.getAllChildMarkers();
        var bestCloud = 100, votes = {}, sunniest = null;
        children.forEach(function (m) {
          if (m.options.cloud < bestCloud || !sunniest) { bestCloud = m.options.cloud; sunniest = m; }
          votes[m.options.level] = (votes[m.options.level] || 0) + 1;
        });
        var level = Object.keys(votes).sort(function (a, b) {
          return votes[b] - votes[a] || a - b;
        })[0];
        var sunPct = 100 - bestCloud;
        cluster._sunPct = sunPct;
        return symbolIcon(level, sunPct + "%", "wide " + band(sunPct), " cluster");
      }
    }) : L.featureGroup();
    layer.addTo(map);

    PLACES.forEach(function (p) {
      var tip = esc(p.t).replace(/\n/g, "<br>");
      L.marker([p.lat, p.lng], {
        icon: symbolIcon(p.l, p.h.toFixed(1), "", " single"),
        cloud: p.c, level: p.l, keyboard: false,
        zIndexOffset: Math.round(p.h * 10)
      }).bindTooltip(tip).on("click", function () {
        // Detailansicht des Ortes: das Fenster fängt diese Navigation ab (siehe _MapPage)
        window.location.href = "%%SPOT_SCHEME%%://%%SPOT_HOST%%/" + p.i;
      }).addTo(layer);
    });

    // Fenster wird beim Start noch maximiert → bis zur ersten Benutzer-Aktion neu einpassen.
    var interacted = false;
    ["mousedown", "wheel", "touchstart", "keydown", "dblclick"].forEach(function (ev) {
      mapEl.addEventListener(ev, function () { interacted = true; }, { capture: true, passive: true });
    });
    map.on("resize", function () {
      if (interacted) return;
      fit();
      fitZoom = map.getZoom();
      applySize();
    });
  }

  // Leaflet zuerst, dann das (optionale) Cluster-Plugin; die Karte funktioniert auch ohne.
  load(LEAFLET + "leaflet.min.js", function () {
    load(CLUSTER + "leaflet.markercluster.js", start, start);
  }, function () {
    showMessage("<div><b>Die Karte konnte nicht geladen werden.</b><br>" +
                "Bitte Internetverbindung prüfen.</div>");
  });
})();
</script>
</body>
</html>
"""


def build_map_html(
    origin: dict,
    results: list[dict],
    symbols: Optional[dict[int, str]] = None,
) -> str:
    """
    Erzeugt die komplette HTML-Seite der Karte.

    Args:
        origin:  Startort als dict mit 'name', 'lat', 'lng'.
        results: Suchergebnisse (Format wie aus SearchWorker).
        symbols: Base64-Symbole je Stufe (Standard: aus dem assets-Ordner).
    """
    if symbols is None:
        symbols = load_symbols()

    origin_payload = {
        "name": origin.get("name", ""),
        "lat": float(origin["lat"]),
        "lng": float(origin["lng"]),
    }
    places = [_place_payload(r, i) for i, r in enumerate(results)]

    html = _MAP_HTML_TEMPLATE
    for level in SYMBOL_FILES:
        html = html.replace(f"%%SYM{level}%%", symbols[level])
    html = html.replace("%%LEAFLET%%", LEAFLET_URL)
    html = html.replace("%%CLUSTER%%", CLUSTER_URL)
    html = html.replace("%%SPOT_SCHEME%%", SPOT_SCHEME)
    html = html.replace("%%SPOT_HOST%%", SPOT_HOST)
    html = html.replace("%%ORIGIN%%", _js_json(origin_payload))
    html = html.replace("%%PLACES%%", _js_json(places))
    return html


# --------------------------------------------------------------------------- #
# Fenster                                                                      #
# --------------------------------------------------------------------------- #

def parse_spot_url(url: QUrl) -> Optional[int]:
    """Index des Ortes aus "lichtloch://spot/<Index>" oder None, wenn die URL anders aufgebaut ist."""
    if url.scheme() != SPOT_SCHEME or url.host() != SPOT_HOST:
        return None
    part = url.path().lstrip("/")
    return int(part) if part.isdigit() else None


class _MapPage(QWebEnginePage):
    """Fängt Klicks auf Orte ab (Navigation zu lichtloch://spot/<Index>) und meldet sie."""

    spot_clicked = pyqtSignal(int)

    def acceptNavigationRequest(self, url, nav_type, is_main_frame) -> bool:  # type: ignore[override]
        if url.scheme() == SPOT_SCHEME:
            index = parse_spot_url(url)
            if index is not None:
                self.spot_clicked.emit(index)
            return False  # die Karte selbst bleibt stehen
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class MapWindow(QWidget):
    """Eigenständiges Fenster mit der OpenStreetMap-Karte der Suchergebnisse."""

    # Index (in der übergebenen Ergebnisliste) des Ortes, dessen Symbol angeklickt wurde
    spot_clicked = pyqtSignal(int)

    def __init__(self, origin: dict, results: list[dict], date_label: str) -> None:
        html = build_map_html(origin, results)  # vor dem Fenster: Symbol-Dateien fehlen → Fehler

        super().__init__(None)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(f"Lichtloch – Karte: {origin.get('name', '')} ({date_label})")
        self.resize(1280, 800)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._view = QWebEngineView(self)
        self._page = _MapPage(self._view)
        self._page.spot_clicked.connect(self.spot_clicked)
        self._view.setPage(self._page)
        layout.addWidget(self._view)

        self._view.setHtml(html, QUrl(MAP_BASE_URL))
        logger.info("Kartenfenster geöffnet (%d Orte).", len(results))
