"""Tests für modules/map_window.py: Symbolwahl und die erzeugte Kartenseite (ohne Fenster)."""

import json
import re

import pytest

pytest.importorskip("PyQt6.QtWebEngineWidgets")

from modules import map_window  # noqa: E402
from modules.map_window import (  # noqa: E402
    SYMBOL_FILES,
    _js_json,
    _place_payload,
    build_map_html,
    load_symbols,
    precipitation_level,
)

DUMMY_SYMBOLS = {level: f"SYM{level}" for level in SYMBOL_FILES}


def ergebnis(name="Konstanz", **extra):
    base = {
        "name": name, "lat": 47.66, "lng": 9.17, "total_sunshine_hours": 9.46,
        "avg_cloud_pct": 12.4, "total_precipitation_mm": 0.0, "duration_sec": 3000,
    }
    return base | extra


@pytest.mark.parametrize(
    ("mm", "level"),
    [(None, 0), (0, 0), (-1, 0), (0.1, 1), (2.49, 1), (2.5, 2), (9.99, 2), (10, 3), (50, 3)],
)
def test_precipitation_level(mm, level):
    assert precipitation_level(mm) == level


def test_symbole_aus_dem_assets_ordner_sind_vorhanden():
    symbols = load_symbols()
    assert set(symbols) == set(SYMBOL_FILES)
    assert all(symbols[level] for level in SYMBOL_FILES)


def test_place_payload_rundet_und_formuliert_tooltip():
    payload = _place_payload(ergebnis(total_precipitation_mm=3.0))
    assert payload["h"] == 9.5 and payload["c"] == 12 and payload["l"] == 2
    assert "Reisezeit: 50 min" in payload["t"]


def test_js_json_verhindert_vorzeitiges_script_ende():
    text = _js_json({"n": "</script><script>alert(1)</script> & <b>"})
    assert "<" not in text and ">" not in text and "&" not in text
    assert json.loads(text)["n"] == "</script><script>alert(1)</script> & <b>"  # verlustfrei


def test_build_map_html_ersetzt_alle_platzhalter():
    html = build_map_html({"name": "Freiburg", "lat": 47.99, "lng": 7.85}, [ergebnis()], DUMMY_SYMBOLS)
    assert "%%" not in html
    assert map_window.LEAFLET_URL in html


def test_build_map_html_maskiert_ortsnamen_aus_openstreetmap():
    boese = '<img src=x onerror=alert(1)></script><script>alert(2)</script>'
    harmlos = "Konstanz"

    def seite(name):
        return build_map_html({"name": name, "lat": 47.99, "lng": 7.85}, [ergebnis(name=name)], DUMMY_SYMBOLS)

    html = seite(boese)
    # Der Name steht nirgends als rohes HTML in der Seite ...
    assert "<img src=x" not in html
    # ... und fügt der Seite keine zusätzlichen Script-Tags hinzu.
    for tag in (r"<script", r"</script>"):
        assert len(re.findall(tag, html)) == len(re.findall(tag, seite(harmlos)))
