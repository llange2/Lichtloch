# Drittkomponenten und Datenquellen

Lichtloch selbst steht unter der **GNU General Public License v3.0** (siehe [LICENSE](LICENSE)).
Die folgenden Komponenten und Dienste werden benutzt. Maßgeblich sind jeweils die Lizenztexte und
Nutzungsbedingungen der Projekte selbst; diese Übersicht ersetzt sie nicht.

## Bibliotheken (im Programm enthalten)

| Komponente | Verwendung | Lizenz |
|---|---|---|
| [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) | Oberfläche | GPL v3 (oder kommerziell von Riverbank) – der Grund für die GPL-Lizenz von Lichtloch |
| [Qt 6](https://www.qt.io/) inkl. Qt WebEngine (Chromium) | Oberfläche, Karte | LGPL v3 / GPL v3; Chromium enthält weitere Open-Source-Komponenten |
| [requests](https://requests.readthedocs.io/) und Abhängigkeiten (urllib3, certifi, idna, charset-normalizer) | HTTP-Abfragen | Apache-2.0, MIT, MPL-2.0, BSD-3-Clause |
| [Python](https://www.python.org/) | Laufzeit | PSF License |
| [PyInstaller](https://pyinstaller.org/) | Erzeugt das Windows-Programm (nur beim Bauen) | GPL v2 mit Ausnahme für das erzeugte Programm |

## Bibliotheken (zur Laufzeit von cdnjs geladen, nicht mitgeliefert)

| Komponente | Version | Lizenz |
|---|---|---|
| [Leaflet](https://leafletjs.com/) | 1.9.4 | BSD-2-Clause |
| [Leaflet.markercluster](https://github.com/Leaflet/Leaflet.markercluster) | 1.5.3 | MIT |

## Daten und Dienste

| Dienst | Verwendung | Hinweis |
|---|---|---|
| [OpenStreetMap](https://www.openstreetmap.org/copyright) | Ortsnamen und Koordinaten (Overpass API), Kartenkacheln | © OpenStreetMap-Mitwirkende, Daten unter der [ODbL](https://opendatacommons.org/licenses/odbl/). Die [Nutzungsrichtlinie der Kachelserver](https://operations.osmfoundation.org/policies/tiles/) gilt: nur für normale, geringe Nutzung. Die öffentlichen Overpass-Server sind geteilte Ressourcen. |
| [Open-Meteo](https://open-meteo.com/) | Wetterdaten und Ortssuche | Wetterdaten von Open-Meteo.com, Lizenz [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); die kostenlose API ist nur für nicht-kommerzielle Nutzung gedacht. Die Ortssuche beruht u. a. auf [GeoNames](https://www.geonames.org/) (CC BY 4.0). |
| [OSRM](https://project-osrm.org/) | Fahrzeit mit dem Auto | Der öffentliche Demo-Server `router.project-osrm.org` ist für leichte Nutzung gedacht und ohne Garantie. |

## Grafiken

Die Karten-Symbole in `sunshine_finder/assets/` und das Programm-Symbol `sun.ico`:

> **Herkunft und Lizenz: noch einzutragen** (Urheber/Quelle und Lizenz der Grafiken).
