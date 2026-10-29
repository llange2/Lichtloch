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


def test_tooltip_nennt_uhrzeit_temperatur_sonne_und_bewoelkung(app):
    assert chart([12.34] * 24).hour_tooltip(9) == "9:00 – 12.3 °C – Sonne 50 % (Bewölkung 50 %)"


def test_tooltip_ohne_temperatur_fuer_unbekannte_und_altdaten(app):
    assert chart([None] * 24).hour_tooltip(13) == "13:00 – Sonne 50 % (Bewölkung 50 %)"
    assert chart(None).hour_tooltip(3) == "3:00 – Sonne 50 % (Bewölkung 50 %)"


def test_tooltip_nachts_ohne_sonne_mit_nacht_hinweis(app):
    w = SunChart([0.0] * 24, [100] * 24, [0] * 24, "Test", temperature=[-3.0] * 24)
    assert w.hour_tooltip(2) == "2:00 – -3.0 °C – Nacht"
    assert w._sun_pct(2) is None


def test_diagramm_zeichnet_mit_luecken_und_altdaten(app):
    for temp in ([None, 3.0] * 12, None):
        w = chart(temp)
        w.resize(600, 250)
        assert not w.grab().isNull()
