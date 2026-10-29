# Lichtloch – Sunshine Finder

## Überblick

**Lichtloch** ist eine deutschsprachige Desktop-App (PyQt6 / Python 3.13), die für ein gewähltes Datum und einen Startort die **am wenigsten bewölkten Orte** in Reichweite findet, gefiltert nach Reisezeit und Verkehrsmittel. Die Treffer erscheinen in einer Tabelle und auf Wunsch auf einer Karte.

**Version 1.2.1** – kein Login und keine API-Keys, schneller Start (siehe [CHANGELOG](../CHANGELOG.md)).

---

## Projektstruktur

```
Lichtloch/
├── sunshine_finder/
│   ├── app.py                  → Einstiegspunkt (Startfenster, Qt-Loop)
│   ├── assets/                 → Wetter-Symbole der Karte (Sonne, Sonne mit 1–3 Tropfen)
│   └── modules/
│       ├── __init__.py         → Version, Projekt-URL, User-Agent
│       ├── osm_api.py          → Ortssuche (Open-Meteo), Kandidatensuche (Overpass), Reisezeit (OSRM)
│       ├── weather.py          → Open-Meteo stündliche Wetterdaten + Bewölkungs-Kennzahlen
│       ├── map_window.py       → Kartenfenster (OpenStreetMap/Leaflet, gebündelte Orte)
│       ├── cache.py            → SQLite-Cache + Einstellungen
│       └── gui_main.py         → Haupt-GUI (PyQt6), Detail-Popup mit eigenem Diagramm-Widget
├── tests/                      → pytest-Tests (Logik ohne Netzwerk und ohne Fenster)
├── installer/Lichtloch.iss     → Inno-Setup-Skript für Lichtloch-Setup.exe
├── Lichtloch.spec              → PyInstaller-Spec (onedir)
├── docs/DOKUMENTATION.md       → Diese Datei
├── requirements.txt            → Laufzeit-Abhängigkeiten
├── requirements-dev.txt        → zusätzlich Tests, Linting, PyInstaller
└── pyproject.toml              → Konfiguration von pytest und ruff
```

Beim ersten Start entstehen automatisch `cache.db` (SQLite-Cache + Einstellungen) und `app.log` – neben der EXE bzw. im Ordner `sunshine_finder/`. Beide sind in `.gitignore` eingetragen.

---

## Anmeldung / Schlüssel

Es gibt **keine Anmeldung und keine API-Keys**. Alle verwendeten Dienste sind frei zugänglich (siehe unten). Die Einstellungen (letzter Startort, Reisezeit, Verkehrsmittel …) gehören dem lokalen Nutzer und stehen in `cache.db` (Schlüssel `local`).

---

## Start-Sequenz

1. Logging einrichten, `QApplication` erzeugen, **Startfenster** zeigen.
2. Module importieren, Cache öffnen, Hauptfenster aufbauen und anzeigen.
3. Cache-Aufräumen (abgelaufene Einträge) läuft erst danach im Event-Loop.

Vor dem ersten Fenster findet **kein Netzwerkzugriff** statt. QtWebEngine (Chromium, nur für die Karte) wird erst beim ersten Klick auf „Karte anzeigen“ geladen; dafür ist in `app.py` vor der `QApplication` `AA_ShareOpenGLContexts` gesetzt (Qt verlangt entweder dies oder den Import vor der `QApplication`).

---

## Verwendete Dienste

| Dienst | Zweck | Auth |
|---|---|---|
| Open-Meteo Geocoding | Ortsvorschläge beim Tippen | kostenlos, kein Key |
| OpenStreetMap / Overpass | Kandidatenorte im Umkreis (Server werden der Reihe nach probiert) | kostenlos, kein Key |
| OSRM (Table-Service) | Reisezeit beim Auto, ein Aufruf je 90 Orte | kostenlos, kein Key |
| Open-Meteo | Stündliche Bewölkung, Tageslicht, Niederschlag, Temperatur | kostenlos, kein Key |
| OpenStreetMap-Kacheln + Leaflet / Leaflet.markercluster (cdnjs) | Kartenansicht | kostenlos, kein Key |

Der Link „In Google Maps öffnen“ im Detail-Popup ist eine normale Web-Adresse, die im Browser geöffnet wird (kein Login, kein Key).

Alle Anfragen senden den User-Agent `lichtloch-app/<Version> (+Projekt-URL)` (`modules/__init__.py`). Lizenzen und Namensnennungen der Datenquellen: [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

---

## Such-Logik

1. **Startort-Koordinaten** aus dem gewählten Vorschlag der Open-Meteo-Ortssuche.
2. **Kandidatenorte** via Overpass (OpenStreetMap): Städte bzw. auch Dörfer/Vororte im Umkreis (höchstens 300 km). Bei mehr als 400 Orten wird gleichmäßig ausgedünnt, damit nahe *und* ferne Gebiete im Pool bleiben. Fällt ein Server aus, wird der nächste probiert; scheitern alle, meldet die App je Server den Grund.
3. **Reisezeit** für *alle* Kandidaten: Auto per OSRM (ein Aufruf je 90 Orte), sonst Luftlinien-Schätzung. Orte über dem Reisezeit-Limit werden verworfen.
4. **Auswahl nach Reisezeit-Bändern** – die maximale Ortsanzahl wird zu gleichen Teilen auf **drei Reisezeit-Bänder** verteilt (z. B. 1,5 h → 0–30, 30–60, 60–90 min). Innerhalb eines Bandes werden die Orte **möglichst weit auseinander** gewählt, damit alle Richtungen abgedeckt sind. Nicht genutzte Quote eines dünn besetzten Bandes geht an die übrigen Bänder.
5. **Wetterdaten** – Open-Meteo für jeden gewählten Ort (Datum, stündlich; bei HTTP 429/5xx bis zu 3 Versuche).
6. **Sortierung:**
   1. Bewölkung (Tageslicht-Mittel) ↑
   2. Längste klare Phase ↓
   3. Kürzeste Reisezeit ↑
   4. Niedrigster Niederschlag ↑
7. Alle Treffer werden in der Tabelle angezeigt (höchstens so viele wie „Maximale Anzahl Orte“, 10–250).

### Bewölkungs-Kennzahlen

- **Sonnenstunden** = Summe über alle Tageslicht-Stunden von (100 % − Bewölkung); 50 % Bewölkung zählen als halbe Sonnenstunde.
- **Bewölkung (%)** = Mittel über die Tageslicht-Stunden. Fehlende Werte zählen als 100 %.
- **Längste klare Phase** = längste Folge von Tageslicht-Stunden mit höchstens 50 % Bewölkung.
- Die direkte Sonnenscheindauer des Wettermodells (`sunshine_duration`) wird nur im Detail-Popup zum Vergleich gezeigt: Sie stimmt nicht immer mit der Bewölkung überein, und das frühere Zählen jeder Stunde mit mehr als 0 s Sonne als volle Sonnenstunde ließ überwiegend bewölkte Orte „sonnig“ wirken.
- Farbe der Spalte „Bewölkung“: grün bis 30 %, gelb bis 60 %, sonst orange.

## Caching (SQLite, 24h Ablaufzeit)

| Tabelle | Inhalt | Schlüssel |
|---|---|---|
| `directions_cache` | Reisezeit in Sekunden | Hash(lat, lng, datum, modus) |
| `weather_cache` | Stündliche Wetterdaten (JSON) | Hash(Schema-Version, lat, lng, datum) |
| `nearby_cache` | Ausgewählte Kandidatenorte inkl. Reisezeit (max. 10 Einträge, LRU) | Hash(Schema-Version, Startort, Modus, Filter, Anzahl, Reisezeit) |
| `user_preferences` | Letzter Startort, Reisezeit, Modus | feste ID `local` |

Ältere Datenbanken mit der früheren Spalte `google_user_id` werden beim Start automatisch auf `user_id` umgestellt (`CacheManager._migrate_legacy_user_id_column`).

---

## Installation & Start

### Aus dem Quellcode

```bash
pip install -r requirements.txt
python sunshine_finder/app.py
```

Voraussetzungen: Python 3.10+ und eine Internetverbindung. Keine `.env`, keine Konfigurationsdatei.

### Als Programm (Windows)

```bash
# 1. Bauen (onedir) – Ergebnis: dist_neu\Lichtloch\Lichtloch.exe
.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath dist_neu --workpath build_neu Lichtloch.spec

# 2. Optional: Installer als EINE Datei – Ergebnis: dist_setup\Lichtloch-Setup.exe
ISCC.exe installer\Lichtloch.iss
```

Warum **onedir** statt einer einzelnen EXE aus PyInstaller (`--onefile`): Eine Onefile-EXE entpackt bei *jedem* Start den kompletten Inhalt nach `%TEMP%` (bei der alten 225-MB-Variante dauerte es bis zum ersten Fenster gemessen 7,6 s im besten Fall, bei kaltem Start über 28 s). Der Installer entpackt nur einmal bei der Installation (pro Benutzer nach `%LOCALAPPDATA%\Programs\Lichtloch`, kein Admin nötig; `app.log` und `cache.db` liegen neben der EXE und brauchen einen beschreibbaren Ordner).

---

## GUI-Elemente

| Element | Beschreibung |
|---|---|
| Kopfzeile | Titel „☀ Lichtloch“ |
| Startort | Textfeld mit Ortsvorschlägen (Open-Meteo Geocoding) |
| Verkehrsmittel | Radio Buttons: Auto / Zu Fuß / Fahrrad / ÖPNV |
| Datum | Datumsauswahl (heute bis +7 Tage) |
| Max. Reisezeit | Freitext in Stunden (0 < Wert ≤ 12) |
| Suchen-Button | Startet Suche, deaktiviert während Ladevorgang |
| Ergebnistabelle | Orte mit Rang, Sonnenstunden, Bewölkung, längster klarer Phase, Temperatur, Reisezeit, Niederschlag (Spaltenkopf anklicken zum Sortieren) |
| Karte anzeigen | Öffnet die Karte mit den Orten der Tabelle (erst nach einer Suche aktiv) |
| Detail-Popup | Stundendiagramm (Balken = 100 % − Bewölkung; je Stunde von oben nach unten: rote Temperatur „10°C“, Balken, Sonne in % (= Balkenhöhe, nachts leer), Uhrzeit „9:00“; bei schmaler Anzeige nur jede 2./3. Spalte beschriftet; Tooltip „9:00 – 7.3 °C – Sonne 70 % (Bewölkung 30 %)“, nachts zusätzlich „Nacht“; unbekannte Temperaturen bleiben leer; `SunChart`, mit QPainter gezeichnet), Google-Maps-Link, Niederschlagsdetails, Vergleichswert des Wettermodells |

---

## Kartenansicht

- Voraussetzung: das Paket `PyQt6-WebEngine` und eine Internetverbindung (Leaflet und das Cluster-Plugin kommen von cdnjs, die Kacheln von tile.openstreetmap.org). Ein API-Key ist nicht nötig. Fehlt das Paket, erscheint beim Klick ein Hinweis; ohne Internet zeigt die Karte eine Fehlermeldung.
- Der Startort liegt in der Kartenmitte, der Zoom zeigt alle Orte.
- Jeder Ort zeigt ein Symbol mit den Sonnenstunden (eine Nachkommastelle): Sonne bei keinem Niederschlag, sonst Sonne mit Wolke und 1–3 Tropfen (leicht < 2,5 mm, mäßig < 10 mm, stark ≥ 10 mm). Der Tooltip nennt zusätzlich Bewölkung und Reisezeit.
- **Größen:** Die Sonnen einzelner Orte sind kleiner (75 %) als die der Bündel. Die Zahl wird so groß gesetzt, dass sie höchstens 90 % der gelben Scheibe der Sonne belegt (nicht in den Strahlenkranz ragt) und sitzt mittig auf der Scheibe. Die Schriftgröße wird beim Laden der Karte aus der gemessenen Textbreite berechnet (breitester Text: „00.0“ bzw. „100%“) und skaliert mit dem Zoom. Stellschrauben im JavaScript von `map_window.py`: `SINGLE_SCALE`, `FIT`, `DISC`. Die Scheibe liegt in allen Symbol-Grafiken bei 49,6 % / 50,5 % der Bildgröße (Durchmesser ≈ 48 %); wird ein Symbol ausgetauscht, müssen diese Werte (`DISC`, CSS `.sym .num`) neu bestimmt werden.
- **Bündelung:** Orte, die bei der aktuellen Zoomstufe weniger als 60 Pixel auseinander liegen, bilden ein Bündel. Es zeigt das Symbol, das die meisten seiner Orte haben (bei Gleichstand das sonnigere), und den Sonnenanteil (100 − Bewölkung) des sonnigsten Ortes – grün ab 70 %, gelb ab 40 %, sonst orange. Ein Klick zoomt hinein; ab Zoomstufe 17 wird nicht mehr gebündelt.
- **Klick auf einen einzelnen Ort** öffnet dessen Detail-Popup (wie ein Klick auf die Tabellenzeile). Der Marker navigiert zu `lichtloch://spot/<Index>`; `_MapPage.acceptNavigationRequest` fängt das ab (die Karte bleibt stehen) und `MapWindow.spot_clicked` meldet den Index der beim Öffnen übergebenen Ergebnisliste an `MainWindow`.
- Ortsnamen stammen aus OpenStreetMap und sind damit fremde Eingaben: Sie gelangen nur als JSON mit maskierten Zeichen (`_js_json`) in die Seite und werden vor der Anzeige in Tooltips HTML-maskiert (`esc()`).

---

## Fehlerbehandlung

- Alle HTTP-Fehler werden in `app.log` protokolliert (Level INFO/WARNING/ERROR).
- Fehlgeschlagene Einzelorte werden übersprungen (kein App-Absturz).
- Sind alle Overpass-Server nicht erreichbar, erscheint ein Hinweis mit dem Grund je Server (Sperre/Überlastung der öffentlichen Server ist häufig – später erneut versuchen oder die Reisezeit verringern).
- 0 Ergebnisse → Popup mit Hinweis, Distanz zu erhöhen oder Datum zu ändern.
- Schlägt der Start fehl, erscheint ein Meldungsfenster mit dem Grund (und Eintrag in `app.log`).

---

## Technologien

- **Python 3.13** mit Typannotationen
- **PyQt6 ≥ 6.5** – GUI, QThreadPool, Signals/Slots
- **PyQt6-WebEngine** – Kartenfenster (Leaflet 1.9.4, Leaflet.markercluster 1.5.3, OpenStreetMap-Kacheln), wird erst beim Öffnen der Karte geladen
- **requests** – alle HTTP-Calls
- **SQLite** (stdlib) – Cache und Einstellungen

---

## Hinweise für Entwickler

- Entwicklungswerkzeuge installieren: `pip install -r requirements-dev.txt`.
- Tests: `python -m pytest` (laufen ohne Netzwerk und ohne sichtbares Fenster; `QT_QPA_PLATFORM=offscreen` empfohlen). Lint: `python -m ruff check .`. Beides läuft auch in der CI (`.github/workflows/ci.yml`).
- **Version:** nur in `sunshine_finder/modules/__init__.py` ändern und denselben Wert in `installer/Lichtloch.iss` eintragen (`tests/test_version.py` schlägt sonst fehl).
- Beim Bauen blendet `Lichtloch.spec` ungenutzte Qt-Teile aus (DevTools, QML, Multimedia, Übersetzungen, nicht benötigte Sprachen von Chromium). Fehlt danach etwas, zuerst `_DROP_CONTAINS` in der Spec prüfen.
- Bekannte Baustelle: Die Überwachung des Thread-Pools (`PoolMonitor`, `patch_main_window_pool_monitoring` in `gui_main.py`) wird nachträglich per Patch in das Hauptfenster eingehängt; `MainWindow._monitor_pool` ist weitgehend Altlast. Sauberer wäre ein direkter Zähler im Hauptfenster.
