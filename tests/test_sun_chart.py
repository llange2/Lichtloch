"""Tests für das Stundendiagramm (Temperatur-Zeile und Tooltip), ohne Fenster."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from modules.gui_main import SunChart  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def chart(temp):
    return SunChart([0.5] * 24, [50] * 24, [1] * 24, "Test", temperature=temp)


def test_tooltip_nennt_uhrzeit_temperatur_und_bewoelkung(app):
    assert chart([12.34] * 24).hour_tooltip(9) == "09:00 – 12.3 °C – Bewölkung 50 %"


def test_tooltip_ohne_temperatur_fuer_unbekannte_und_altdaten(app):
    assert chart([None] * 24).hour_tooltip(3) == "03:00 – Bewölkung 50 %"
    assert chart(None).hour_tooltip(3) == "03:00 – Bewölkung 50 %"


def test_diagramm_zeichnet_mit_luecken_und_altdaten(app):
    for temp in ([None, 3.0] * 12, None):
        w = chart(temp)
        w.resize(600, 236)
        assert not w.grab().isNull()
