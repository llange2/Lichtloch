# Mitmachen

Fehlermeldungen, Ideen und Pull Requests sind willkommen.

## Fehler melden
Bitte als [Issue](../../issues) mit Windows-Version, Lichtloch-Version (Installer-Name bzw. `__version__`) und den
betreffenden Zeilen aus `app.log`. **Entferne vorher Orte oder andere persönliche Angaben** aus dem Log-Auszug.

## Entwicklung
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt

python -m ruff check .          # Lint
python -m pytest                # Tests (kein Netzwerk, kein Fenster nötig)
python sunshine_finder/app.py   # App starten
```

- Neue Logik möglichst als reine Funktionen schreiben und in `tests/` abdecken.
- Der Code, die Oberfläche und die Doku sind deutsch; Bezeichner bleiben englisch.
- Die Version steht in `sunshine_finder/modules/__init__.py` **und** `installer/Lichtloch.iss` (ein Test prüft Gleichstand);
  Änderungen gehören in `CHANGELOG.md`.
- Bitte keine Zugangsdaten, `cache.db`, `app.log` oder Build-Ordner committen (`.gitignore` schützt davor).

## Lizenz
Mit einem Beitrag stimmst du zu, dass er unter der [GPL-3.0](LICENSE) veröffentlicht wird.
