# Änderungsverlauf

Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

## [Unveröffentlicht]

### Hinzugefügt
- Detailansicht: Temperatur pro Stunde (ganze °C) in einer Zeile über dem Sonnen-Diagramm; Tooltip je Stunde mit Uhrzeit, Temperatur und Bewölkung. Unbekannte Stunden bleiben leer (nicht „0“). `WeatherResult.hourly_temperature_c`, Altdaten ohne dieses Feld werden toleriert.
- Karte: Ein Klick auf das Symbol eines einzelnen Orts öffnet dessen Detailansicht (wie ein Klick auf die Tabellenzeile). Bündel zoomen wie bisher.

## [1.2.1] – erste öffentliche Version

### Geändert
- Karte: Sonnen einzelner Orte sind kleiner als die der Bündel; die Zahlen passen in die gelbe Scheibe der Sonne und sind darauf zentriert (vorher zu groß, 3 % zu weit links/oben und teils im Strahlenkranz). Ursache der Schieflage u. a.: Leaflet setzt am Karten-Container „Helvetica Neue“ und überschrieb die gedachte Schrift – die Zahl hat jetzt eine eigene `font-family`.
- Der User-Agent aller Anfragen enthält jetzt Version und Projekt-URL (`lichtloch-app/<Version> (+URL)`), die Versionsnummer steht zentral in `modules/__init__.py`.
- OSRM-Routenabfrage per `https://` statt `http://`.
- Datenbank: Spalte `google_user_id` heißt jetzt `user_id`; ältere Datenbanken werden beim Start automatisch umgestellt, Einträge mit fremder ID aus der Zeit mit Login entfallen.
- Zeitstempel im Cache ohne das in Python 3.12+ veraltete `datetime.utcnow()`.

### Hinzugefügt
- Tests (`tests/`), Linting (ruff) und CI über GitHub Actions.
- Lizenz (GPL-3.0), README, Hinweise zu Drittkomponenten und Datenquellen.

### Entfernt
- Reste der früheren Google-Anmeldung (Migration `adopt_legacy_preferences`).

## [1.2.0]

### Geändert
- Kein Netzwerkzugriff und kein Warten mehr vor dem ersten Fenster; Startfenster; QtWebEngine wird erst beim Öffnen der Karte geladen.
- Stundendiagramm ohne matplotlib (spart matplotlib, numpy und Pillow im Bundle).
- Auslieferung als onedir bzw. Installer statt Onefile-EXE.

### Entfernt
- Google-Login und `.env` (die App nutzte Google nur für die Identität; alle Daten kamen schon von Open-Meteo, OSM und OSRM).
- Toter Google-Places-Code (`google_api.py` → `osm_api.py`).

## [1.1.0]

### Hinzugefügt
- Sonne wird aus der Bewölkung berechnet (neue Spalte „Bewölkung“, Ranking nach Bewölkung).
- Auswahl der Orte über drei Reisezeit-Bänder.
- Robustere Overpass-Abfrage (mehrere Server, Fehlerdetails).
- Karte (OpenStreetMap/Leaflet, kein API-Key) mit Bündelung und Sonnenanteil, Karten-Button im Hauptfenster.

Basiert auf einer internen Vorversion des „Sunshine Finder“ (1.0.0–1.4.0).
