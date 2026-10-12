"""app.py – Einstiegspunkt der Lichtloch App.

Start-Sequenz (bewusst schlank – kein Login, kein Netzwerk vor dem ersten Fenster):
  1. Logging einrichten
  2. QApplication erzeugen und sofort ein Startfenster zeigen
  3. Module importieren, Cache öffnen
  4. Hauptfenster anzeigen
  5. Cache-Aufräumen läuft erst danach im Event-Loop

QtWebEngine (Chromium, nur für die Karte) wird nicht mehr beim Start geladen, sondern
erst beim ersten Klick auf „Karte anzeigen“ (modules/gui_main.py → modules/map_window.py).
"""

import logging
import os
import sys

from PyQt6.QtCore import QCoreApplication, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMessageBox, QSplashScreen


# Logging-Setup: in Datei + Konsole
# Bei einer PyInstaller-EXE liegt __file__ im schreibgeschützten Temp-Verzeichnis.
# Schreibbare Dateien (Log, Cache) müssen neben sys.executable abgelegt werden.
def _get_user_data_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

LOG_FILE = os.path.join(_get_user_data_dir(), "app.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def _make_splash() -> QSplashScreen:
    """Einfaches Startfenster, damit die Wartezeit nicht wie ein Hänger wirkt."""
    pix = QPixmap(420, 140)
    pix.fill(QColor("#1565C0"))
    painter = QPainter(pix)
    title_font = QFont("Segoe UI", 22)
    title_font.setBold(True)
    painter.setFont(title_font)
    painter.setPen(QColor("white"))
    painter.drawText(pix.rect().adjusted(0, 0, 0, -30), Qt.AlignmentFlag.AlignCenter, "☀ Lichtloch")
    painter.setFont(QFont("Segoe UI", 10))
    painter.setPen(QColor("#BBDEFB"))
    painter.drawText(pix.rect().adjusted(0, 70, 0, 0), Qt.AlignmentFlag.AlignCenter, "wird gestartet …")
    painter.end()
    return QSplashScreen(pix, Qt.WindowType.WindowStaysOnTopHint)


def main() -> None:
    # Muss vor der QApplication gesetzt werden: Nur dann darf QtWebEngine (Karte)
    # später, erst beim ersten Klick, importiert werden statt schon beim Start.
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("Lichtloch")
    app.setOrganizationName("Lichtloch")

    logger.info("=== Lichtloch App startet ===")
    splash = _make_splash()
    splash.show()
    app.processEvents()

    try:
        from modules.cache import CacheManager
        from modules.gui_main import MainWindow, patch_main_window_pool_monitoring
        from modules.osm_api import GeoApiClient

        cache = CacheManager()
        window = MainWindow(api_client=GeoApiClient(), cache=cache)
        patch_main_window_pool_monitoring(window)
    except Exception as exc:  # noqa: BLE001 - dem Nutzer anzeigen statt still zu sterben
        logger.exception("Start fehlgeschlagen")
        splash.close()
        QMessageBox.critical(None, "Lichtloch", f"Die App konnte nicht gestartet werden:\n{exc}")
        sys.exit(1)

    window.show()
    splash.finish(window)
    logger.info("Hauptfenster gestartet.")

    # Aufräumen des Caches erst, wenn das Fenster schon sichtbar ist
    QTimer.singleShot(0, cache.cleanup_expired)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
