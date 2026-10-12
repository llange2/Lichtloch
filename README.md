# ☀ Lichtloch

[![CI](https://github.com/llange2/lichtloch/actions/workflows/ci.yml/badge.svg)](https://github.com/llange2/lichtloch/actions/workflows/ci.yml)
[![Lizenz: GPL v3](https://img.shields.io/badge/Lizenz-GPLv3-blue.svg)](LICENSE)

**Lichtloch findet das Wolkenloch:** Die Windows-App zeigt dir für einen Tag in den nächsten sieben Tagen, in welchen Orten
rund um deinen Startort der Himmel am wenigsten bewölkt ist – gefiltert nach Reisezeit und Verkehrsmittel,
als Tabelle und auf einer Karte.

> **English summary:** Lichtloch is a German-language Windows desktop app (Python, PyQt6) that finds the sunniest
> places within a given travel time of your start location for a chosen day (up to 7 days ahead). Cloud cover comes
> from [Open-Meteo](https://open-meteo.com/), candidate towns from OpenStreetMap, drive times from OSRM. No account and
> no API key are needed. Download the installer from the
> [Releases](https://github.com/llange2/lichtloch/releases) page or run it from source (see below). The UI is in German.
> Licensed under GPL-3.0.

<!-- Screenshot: Bild als docs/screenshot.png ablegen (mit neutralem Startort) und die nächste Zeile aktivieren
![Lichtloch: Karte mit sonnigen Orten](docs/screenshot.png)
-->

## Funktionen

- Ortssuche mit Vorschlägen, Datum bis 7 Tage im Voraus, maximale Reisezeit bis 12 Stunden
- Verkehrsmittel: Auto (Fahrzeit über OSRM), zu Fuß, Fahrrad, ÖPNV (Luftlinien-Schätzung)
- Ranking nach Bewölkung (Tageslicht-Mittel), längster klarer Phase, Reisezeit und Niederschlag
- Orte aus allen Richtungen und Entfernungen (drei Reisezeit-Bänder), auf Wunsch nur Städte oder nur Orte ohne Niederschlag
- Detailansicht mit Stundendiagramm und Karte (OpenStreetMap) mit gebündelten Sonnen-Symbolen
- **Kein Konto, kein API-Key, keine Telemetrie**

## Installation

### Als Programm (Windows 10/11, 64 Bit)

Lade `Lichtloch-Setup.exe` von der [Releases](https://github.com/llange2/lichtloch/releases)-Seite und führe sie aus
(Installation pro Benutzer, kein Administrator nötig).
Das Programm ist nicht digital signiert; Windows SmartScreen zeigt deshalb beim ersten Start evtl. eine Warnung
(„Weitere Informationen“ → „Trotzdem ausführen“).

### Aus dem Quellcode

Voraussetzung: Python 3.10 oder neuer.

```bash
git clone https://github.com/llange2/lichtloch.git
cd lichtloch
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python sunshine_finder/app.py
```

### Programm selbst bauen

```bash
pip install -r requirements-dev.txt
python -m PyInstaller --noconfirm --distpath dist_neu --workpath build_neu Lichtloch.spec   # Ergebnis: dist_neu\Lichtloch\Lichtloch.exe
ISCC.exe installer\Lichtloch.iss                                                          # optional (Inno Setup): dist_setup\Lichtloch-Setup.exe
```

## Datenschutz und Datenquellen

Lichtloch hat keine eigenen Server. Beim Suchen werden diese öffentlichen Dienste direkt von deinem Rechner aus abgefragt
(dabei sehen sie deine IP-Adresse und die jeweils gesendeten Daten):

| Dienst | gesendet |
|---|---|
| [Open-Meteo](https://open-meteo.com/) (Ortssuche, Wetter) | getippter Ortsname; Koordinaten und Datum der Orte |
| [Overpass API](https://overpass-api.de/) / OpenStreetMap | Koordinaten des Startorts und Suchradius |
| [OSRM](https://project-osrm.org/) (Fahrzeit mit dem Auto) | Koordinaten des Startorts und der Kandidatenorte |
| OpenStreetMap-Kacheln, cdnjs (Kartenansicht) | Kartenausschnitt (Kachel-Koordinaten) |

Lokal speichert die App neben der Programmdatei `cache.db` (zwischengespeicherte Abfragen für 24 Stunden und deine
letzten Einstellungen, z. B. den zuletzt gewählten Startort) und `app.log` (technische Meldungen). Beide Dateien kannst du
jederzeit löschen. Lizenzen und Namensnennung der Datenquellen: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Wetterdaten: [Open-Meteo.com](https://open-meteo.com/) (CC BY 4.0), Kartendaten © [OpenStreetMap-Mitwirkende](https://www.openstreetmap.org/copyright).

Die öffentlichen Overpass-Server und der OSRM-Demo-Server sind für leichte Nutzung gedacht und manchmal überlastet –
dann erscheint eine Meldung, und ein späterer Versuch hilft.

## Entwicklung

```bash
pip install -r requirements-dev.txt
python -m ruff check .     # Lint
python -m pytest           # Tests (ohne Netzwerk und ohne sichtbares Fenster)
```

Ausführliche technische Beschreibung: [docs/DOKUMENTATION.md](docs/DOKUMENTATION.md) · Änderungen: [CHANGELOG.md](CHANGELOG.md) ·
Mitmachen: [CONTRIBUTING.md](CONTRIBUTING.md)

## Lizenz

[GNU General Public License v3.0](LICENSE). Lichtloch nutzt PyQt6, das unter der GPL v3 steht; deshalb gilt sie auch für dieses Projekt.
