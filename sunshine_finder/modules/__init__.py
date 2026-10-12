"""Lichtloch – Sunshine Finder: Module der App."""

# Einzige Quelle der Versionsnummer. Der Installer (installer/Lichtloch.iss) muss
# denselben Wert führen; tests/test_version.py prüft das.
__version__ = "1.2.1"

PROJECT_URL = "https://github.com/llange2/lichtloch"

# Identifiziert die App gegenüber Open-Meteo, Overpass und OSRM (deren Nutzungsrichtlinien
# verlangen einen eindeutigen User-Agent mit Kontaktmöglichkeit).
USER_AGENT = f"lichtloch-app/{__version__} (+{PROJECT_URL})"
