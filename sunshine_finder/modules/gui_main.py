"""
gui_main.py – Haupt-GUI der Lichtloch App (PyQt6, Deutsch).

Enthält:
  - MainWindow:        Hauptfenster mit Formular und Ergebnistabelle.
  - SearchWorker:      QRunnable für parallele Directions + Wetter-Abfragen.
  - DetailDialog:      Detail-Popup mit Stundendiagramm.
  - LocationCompleter: Autocomplete-Dropdown für den Startort.
"""

import logging
import math
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import (
    QDate,
    QObject,
    QPointF,
    QRectF,
    QRunnable,
    QStringListModel,
    Qt,
    QThreadPool,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QCompleter,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from modules.cache import LOCAL_USER_ID, CacheManager
from modules.osm_api import GeoApiClient, GeoApiError
from modules.weather import fetch_weather

logger = logging.getLogger(__name__)

# Verkehrsmittel: Anzeigename → API-Schlüssel
TRAVEL_MODES: dict[str, str] = {
    "Auto (Driving)": "driving",
    "Zu Fuß (Walking)": "walking",
    "Fahrrad (Bicycling)": "bicycling",
    "ÖPNV (Transit)": "transit",
}

MAX_TRAVEL_TIME_HOURS = 12.0
MAX_THREAD_COUNT = 5


# ============================================================= #
# Signals-Klasse für Worker-Kommunikation                        #
# ============================================================= #

class WorkerSignals(QObject):
    """Signals, die ein SearchWorker an den Main Thread senden kann."""
    result_ready = pyqtSignal(dict)   # Ein Ort wurde erfolgreich verarbeitet
    finished = pyqtSignal()           # Alle Worker fertig
    error = pyqtSignal(str)           # Fehler-Meldung
    candidates_ready = pyqtSignal(list)  # Kandidatenliste geladen


# ============================================================= #
# Worker: lädt Kandidatenorte (Overpass) im Hintergrund         #
# ============================================================= #

class CandidateSearchWorker(QRunnable):
    """Ruft nearby_search im Hintergrund auf und meldet Ergebnisse bzw. Fehler via Signal."""

    def __init__(
        self,
        api_client: GeoApiClient,
        lat: float,
        lng: float,
        signals: WorkerSignals,
        max_results: int = 60,
        only_cities: bool = True,
        mode: str = "driving",
        max_duration_sec: int = 3600,
    ) -> None:
        super().__init__()
        self.api = api_client
        self.lat = lat
        self.lng = lng
        self.signals = signals
        self.max_results = max_results
        self.only_cities = only_cities
        self.mode = mode
        self.max_duration_sec = max_duration_sec

    @pyqtSlot()
    def run(self) -> None:
        try:
            candidates = self.api.nearby_search(
                self.lat, self.lng,
                max_results=self.max_results,
                only_cities=self.only_cities,
                mode=self.mode,
                max_duration_sec=self.max_duration_sec,
            )
        except GeoApiError as e:
            logger.error("Kandidatensuche fehlgeschlagen: %s", e)
            self.signals.error.emit(str(e))
            return
        except Exception as e:  # noqa: BLE001 - dem Nutzer anzeigen statt still zu scheitern
            logger.exception("Kandidatensuche: unerwarteter Fehler")
            self.signals.error.emit(f"Unerwarteter Fehler bei der Ortssuche: {e}")
            return
        self.signals.candidates_ready.emit(candidates)


# ============================================================= #
# Worker: verarbeitet einen Kandidaten-Ort                       #
# ============================================================= #

class SearchWorker(QRunnable):
    """
    Verarbeitet einen Kandidaten-Ort: Directions-Check + Wetterdaten.
    Kommuniziert über WorkerSignals mit dem Main Thread.
    """

    def __init__(
        self,
        candidate: dict,
        origin_lat: float,
        origin_lng: float,
        mode: str,
        date_str: str,
        departure_unix: int,
        max_duration_sec: int,
        api_client: GeoApiClient,
        cache: CacheManager,
        signals: WorkerSignals,
    ) -> None:
        super().__init__()
        self.candidate = candidate
        self.origin_lat = origin_lat
        self.origin_lng = origin_lng
        self.mode = mode
        self.date_str = date_str
        self.departure_unix = departure_unix
        self.max_duration_sec = max_duration_sec
        self.api = api_client
        self.cache = cache
        self.signals = signals

    @pyqtSlot()
    def run(self) -> None:
        """Hauptlogik des Workers."""
        name = self.candidate["name"]
        dest_lat = self.candidate["lat"]
        dest_lng = self.candidate["lng"]

        try:
            # Schritt 1: Reisezeit (bereits bei der Kandidatenauswahl bestimmt, sonst Cache/API)
            duration_sec = self.candidate.get("duration_sec")
            if duration_sec is None:
                duration_sec = self.cache.get_directions(
                    self.origin_lat, self.origin_lng,
                    dest_lat, dest_lng,
                    self.mode, self.date_str
                )
            if duration_sec is None:
                duration_sec = self.api.get_travel_duration(
                    self.origin_lat, self.origin_lng,
                    dest_lat, dest_lng,
                    self.mode, self.departure_unix
                )
                if duration_sec is not None:
                    self.cache.set_directions(
                        self.origin_lat, self.origin_lng,
                        dest_lat, dest_lng,
                        self.mode, self.date_str, duration_sec
                    )

            if duration_sec is None:
                logger.debug("Keine Route zu %s.", name)
                return

            if duration_sec > self.max_duration_sec:
                logger.debug("Ort %s überschreitet Reisezeitlimit (%ds > %ds).",
                             name, duration_sec, self.max_duration_sec)
                return

            # Schritt 2: Wetterdaten immer frisch laden (kein Cache-Lesezugriff)
            weather = fetch_weather(dest_lat, dest_lng, self.date_str)
            if weather is None:
                logger.debug("Wetterdaten für %s nicht verfügbar.", name)
                return
            self.cache.set_weather(dest_lat, dest_lng, self.date_str, weather.to_dict())

            # Ergebnis an Main Thread senden
            self.signals.result_ready.emit({
                "name": name,
                "place_id": self.candidate["place_id"],
                "lat": dest_lat,
                "lng": dest_lng,
                "duration_sec": duration_sec,
                "total_sunshine_hours": weather.total_sunshine_hours,
                "longest_sunshine_period_hours": weather.longest_sunshine_period_hours,
                "avg_cloud_pct": weather.avg_cloud_pct,
                "measured_sunshine_hours": weather.measured_sunshine_hours,
                "avg_temperature_c": weather.avg_temperature_c,
                "total_precipitation_mm": weather.total_precipitation_mm,
                "hourly_sunshine_seconds": weather.hourly_sunshine_seconds,
                "hourly_precipitation_mm": weather.hourly_precipitation_mm,
                "hourly_cloud_pct": weather.hourly_cloud_pct,
                "hourly_sun_fraction": weather.hourly_sun_fraction,
                "hourly_is_day": weather.hourly_is_day,
            })

        except Exception as e:
            logger.error("Worker-Fehler für %s: %s", name, e)


# ============================================================= #
# Detail-Dialog                                                  #
# ============================================================= #

class DetailDialog(QDialog):
    """Zeigt Details für einen ausgewählten Ort (inkl. Stundendiagramm)."""

    def __init__(self, result: dict, selected_date: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.result = result
        self.selected_date = selected_date
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle(f"Details: {self.result['name']}")
        self.setMinimumWidth(700)
        self.setMinimumHeight(520)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ---- Kopfzeile ----
        name_label = QLabel(f"<b>{self.result['name']}</b>")
        name_label.setFont(QFont("Segoe UI", 14))
        layout.addWidget(name_label)

        # ---- Maps-Link ----
        lat = self.result["lat"]
        lng = self.result["lng"]
        maps_url = f"https://www.google.com/maps?q={lat},{lng}"
        maps_label = QLabel(f'<a href="{maps_url}">In Google Maps öffnen</a>')
        maps_label.setOpenExternalLinks(True)
        layout.addWidget(maps_label)

        # ---- Kennzahlen ----
        duration_min = math.ceil(self.result["duration_sec"] / 60)
        info_text = (
            f"Reisezeit: <b>{duration_min} min</b> &nbsp;|&nbsp; "
            f"Sonnenstunden: <b>{self.result['total_sunshine_hours']:.1f} h</b> &nbsp;|&nbsp; "
            f"Bewölkung: <b>{self.result.get('avg_cloud_pct', 100.0):.0f} %</b> &nbsp;|&nbsp; "
            f"Längste klare Phase: <b>{self.result['longest_sunshine_period_hours']:.0f} h</b> &nbsp;|&nbsp; "
            f"Niederschlag: <b>{self.result['total_precipitation_mm']:.1f} mm</b>"
        )
        info_label = QLabel(info_text)
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        measured = self.result.get("measured_sunshine_hours")
        if measured is not None:
            hint_label = QLabel(
                f"Zum Vergleich: direkte Sonnenscheindauer laut Wettermodell: {measured:.1f} h"
            )
            hint_label.setStyleSheet("color: #666; font-size: 11px;")
            layout.addWidget(hint_label)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(separator)

        # ---- Stundendiagramm ----
        chart_widget = self._create_chart()
        layout.addWidget(chart_widget)

        # ---- Stündliche Niederschlagsliste ----
        precip_label = QLabel("<b>Stündlicher Niederschlag:</b>")
        layout.addWidget(precip_label)

        scroll = QScrollArea()
        scroll.setFixedHeight(100)
        scroll.setWidgetResizable(True)
        precip_widget = QWidget()
        precip_layout = QHBoxLayout(precip_widget)
        precip_layout.setSpacing(4)

        hourly_precip = self.result.get("hourly_precipitation_mm", [])
        for hour, mm in enumerate(hourly_precip):
            cell = QLabel(f"{hour:02d}h\n{mm:.1f}mm")
            cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.setStyleSheet(
                "background: #e3f2fd; border-radius: 4px; padding: 2px; font-size: 10px;"
                if mm > 0 else
                "background: #f5f5f5; border-radius: 4px; padding: 2px; font-size: 10px;"
            )
            precip_layout.addWidget(cell)

        scroll.setWidget(precip_widget)
        layout.addWidget(scroll)

        # ---- Schließen-Button ----
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _create_chart(self) -> QWidget:
        """Erstellt das Sonnen-Stundendiagramm (Sonnenanteil = 100 % − Bewölkung)."""
        return SunChart(
            sun_fraction=self.result.get("hourly_sun_fraction") or [],
            cloud=self.result.get("hourly_cloud_pct") or [],
            is_day=self.result.get("hourly_is_day") or [],
            title=f"Sonne am {self.selected_date} (100 % − Bewölkung)",
        )


class SunChart(QWidget):
    """
    Stundendiagramm als reines QPainter-Widget (ersetzt matplotlib: spart ~60 MB im Bundle
    und ~0,5 s beim ersten Öffnen des Detail-Popups).

    Balkenhöhe = Sonnenanteil (100 % − Bewölkung); Nachtstunden bleiben grau und flach,
    die Zahl über einem Tagbalken ist die Bewölkung in %.
    """

    _DAY = QColor("#FFC107")
    _NIGHT = QColor("#B0BEC5")
    _GRID = QColor("#E0E0E0")
    _AXIS = QColor("#888888")
    _TEXT = QColor("#555555")
    _Y_MAX = 1.15          # Platz über 100 % für die Bewölkungszahl
    _NIGHT_HEIGHT = 0.03   # Nachtbalken sind nur ein flacher Strich
    _YTICKS = (0.0, 0.25, 0.5, 0.75, 1.0)

    def __init__(
        self,
        sun_fraction: list,
        cloud: list,
        is_day: list,
        title: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._sun = list(sun_fraction)
        self._cloud = list(cloud)
        self._is_day = list(is_day)
        self._title = title
        self.setFixedHeight(220)
        self.setMinimumWidth(420)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))

        w, h = self.width(), self.height()
        left, right, top, bottom = 52, 12, 30, 44
        plot = QRectF(left, top, max(1, w - left - right), max(1, h - top - bottom))

        title_font = QFont("Segoe UI", 10)
        title_font.setBold(True)
        p.setFont(title_font)
        p.setPen(QColor("#222222"))
        p.drawText(QRectF(0, 4, w, 22), Qt.AlignmentFlag.AlignCenter, self._title)

        small = QFont("Segoe UI", 8)
        p.setFont(small)

        # ---- Gitter + Y-Achse ----
        for v in self._YTICKS:
            y = plot.bottom() - v / self._Y_MAX * plot.height()
            p.setPen(QPen(self._GRID, 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(self._TEXT)
            p.drawText(
                QRectF(0, y - 8, left - 6, 16),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{round(v * 100)} %",
            )
        p.setPen(QPen(self._AXIS, 1))
        p.drawLine(plot.bottomLeft(), plot.bottomRight())
        p.drawLine(plot.topLeft(), plot.bottomLeft())

        # ---- Balken ----
        n = len(self._sun)
        if n:
            slot = plot.width() / n
            bar_w = slot * 0.8
            cloud_font = QFont("Segoe UI", 6)
            for hour, value in enumerate(self._sun):
                day = bool(self._is_day[hour]) if hour < len(self._is_day) else True
                v = value if day else self._NIGHT_HEIGHT
                bar_h = min(max(v, 0.0), self._Y_MAX) / self._Y_MAX * plot.height()
                x = plot.left() + hour * slot
                bar = QRectF(x + (slot - bar_w) / 2, plot.bottom() - bar_h, bar_w, bar_h)
                p.fillRect(bar, self._DAY if day else self._NIGHT)
                if day and hour < len(self._cloud):
                    label_y = plot.bottom() - min(v, 1.0) / self._Y_MAX * plot.height() - 14
                    p.setFont(cloud_font)
                    p.setPen(self._TEXT)
                    p.drawText(
                        QRectF(x - 2, label_y, slot + 4, 12),
                        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                        str(self._cloud[hour]),
                    )
                if hour % 2 == 0:
                    p.setFont(small)
                    p.setPen(self._TEXT)
                    p.drawText(
                        QRectF(x - 6, plot.bottom() + 3, slot + 12, 14),
                        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                        f"{hour}h",
                    )

        # ---- Achsenbeschriftung ----
        p.setFont(small)
        p.setPen(self._TEXT)
        p.drawText(
            QRectF(plot.left(), h - 20, plot.width(), 16),
            Qt.AlignmentFlag.AlignCenter,
            "Stunde (Zahl über dem Balken = Bewölkung in %)",
        )
        p.save()
        p.translate(12, plot.center().y())
        p.rotate(-90)
        p.drawText(
            QRectF(-plot.height() / 2, -8, plot.height(), 16),
            Qt.AlignmentFlag.AlignCenter,
            "Sonnenanteil",
        )
        p.restore()
        p.end()


# ============================================================= #
# Hauptfenster                                                   #
# ============================================================= #

class MainWindow(QWidget):
    """Hauptfenster der Lichtloch App."""

    DEFAULT_TRAVEL_TIME_HOURS = 1.5
    DEFAULT_TRAVEL_MODE = "driving"
    DEFAULT_ONLY_CITIES = True
    DEFAULT_MAX_RESULTS = 60
    DEFAULT_NO_PRECIPITATION_ONLY = False

    def __init__(self, api_client: GeoApiClient, cache: CacheManager) -> None:
        super().__init__()
        self.api = api_client
        self.cache = cache
        self.user_id = LOCAL_USER_ID

        # Zustand
        self._selected_place: Optional[dict] = None  # {name, place_id, lat, lng}
        self._results: list[dict] = []
        self._pending_workers: int = 0
        self._collected_results: list[dict] = []
        self._last_sort_column: Optional[int] = None
        self._last_sort_ascending: bool = True
        self._search_failed: bool = False
        self._results_origin: Optional[dict] = None  # Startort der angezeigten Ergebnisse
        self._results_date: str = ""
        self._map_window: Optional[QWidget] = None

        # Thread Pool
        self._pool = QThreadPool.globalInstance()
        self._pool.setMaxThreadCount(MAX_THREAD_COUNT)

        # Worker-Signals (geteilt über alle Worker)
        self._signals = WorkerSignals()
        self._signals.result_ready.connect(self._on_result_ready)
        self._signals.finished.connect(self._on_search_finished)
        self._signals.candidates_ready.connect(self._on_candidates_ready)
        self._signals.error.connect(self._on_candidates_failed)

        # Suchparameter für spätere Verwendung in _on_candidates_ready
        self._pending_search_params: Optional[dict] = None

        self._setup_ui()
        self._load_user_preferences()

    # ------------------------------------------------------------------ #
    # UI-Aufbau                                                            #
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        self.setWindowTitle("Lichtloch – Sonnenstunden-Finder")
        self.setMinimumWidth(1120)
        self.resize(1180, 700)
        self.setMinimumHeight(700)

        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ---- Header ----
        header = self._build_header()
        root.addWidget(header)

        # ---- Formular ----
        form_widget = QWidget()
        form_widget.setObjectName("formArea")
        form_layout = QVBoxLayout(form_widget)
        form_layout.setContentsMargins(20, 16, 20, 16)
        form_layout.setSpacing(12)

        form_layout.addLayout(self._build_location_row())
        form_layout.addLayout(self._build_city_filter_row())
        form_layout.addLayout(self._build_travel_mode_row())
        form_layout.addLayout(self._build_date_row())
        form_layout.addLayout(self._build_distance_row())
        form_layout.addLayout(self._build_search_row())

        root.addWidget(form_widget)

        # ---- Fortschrittsbalken ----
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)  # indeterminate
        self._progress_bar.setVisible(False)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setTextVisible(False)
        root.addWidget(self._progress_bar)

        # ---- Statuszeile ----
        self._status_label = QLabel("")
        self._status_label.setContentsMargins(20, 0, 20, 4)
        self._status_label.setStyleSheet("color: #666; font-size: 12px;")
        root.addWidget(self._status_label)

        # ---- Ergebnistabelle ----
        self._table = self._build_table()
        root.addWidget(self._table, stretch=1)

        # Stylesheet
        self.setStyleSheet("""
            QWidget { font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; }
            #formArea { background: #FAFAFA; border-bottom: 1px solid #E0E0E0; }
            #header { background: #1565C0; }
            QTableWidget { gridline-color: #E0E0E0; }
            QHeaderView::section {
                background: #1565C0; color: white; font-weight: bold;
                padding: 6px; border: none;
            }
            QLineEdit, QDateEdit {
                border: 1px solid #BDBDBD; border-radius: 4px;
                padding: 5px 8px; background: white;
            }
            QLineEdit:focus, QDateEdit:focus { border-color: #1565C0; }
            QPushButton#searchBtn {
                background: #1565C0; color: white; border: none;
                border-radius: 4px; padding: 8px 24px; font-size: 14px; font-weight: bold;
            }
            QPushButton#searchBtn:hover { background: #1976D2; }
            QPushButton#searchBtn:disabled { background: #90A4AE; }
            QPushButton#mapBtn {
                background: white; color: #1565C0; border: 1px solid #1565C0;
                border-radius: 4px; padding: 8px 18px; font-size: 14px;
            }
            QPushButton#mapBtn:hover { background: #E3F2FD; }
            QPushButton#mapBtn:disabled { color: #90A4AE; border-color: #B0BEC5; }
            QRadioButton { spacing: 6px; }
            QProgressBar { background: #E3F2FD; border: none; }
            QProgressBar::chunk { background: #1565C0; }
        """)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("header")
        header.setFixedHeight(56)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 20, 0)

        title = QLabel("☀ Lichtloch")
        title.setStyleSheet("color: white; font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        layout.addStretch()

        return header

    def _build_location_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        label = QLabel("Startort:")
        label.setFixedWidth(160)

        self._location_edit = QLineEdit()
        self._location_edit.setPlaceholderText("Ort eingeben (mind. 3 Zeichen)...")
        self._location_edit.textChanged.connect(self._on_location_text_changed)

        # Autocomplete via QCompleter
        self._completer_model = QStringListModel()
        self._completer = QCompleter(self._completer_model, self)
        self._completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.activated[str].connect(self._on_suggestion_selected)
        self._location_edit.editingFinished.connect(self._sync_selected_place_from_text)
        self._location_edit.setCompleter(self._completer)

        # Intern: Suggestions-Mapping (Anzeige → place_id)
        self._suggestions: list[dict] = []

        row.addWidget(label)
        row.addWidget(self._location_edit, stretch=1)
        return row

    def _build_city_filter_row(self) -> QHBoxLayout:
        row = QHBoxLayout()

        # Ausrichtung wie beim Startort: links erst die Label-Spalte (160px)
        spacer_label = QLabel("")
        spacer_label.setFixedWidth(160)
        row.addWidget(spacer_label)

        self._only_cities_cb = QCheckBox("Nur Städte")
        self._only_cities_cb.setChecked(True)
        self._only_cities_cb.setToolTip(
            "Aktiviert: sucht nur Städte und größere Orte (city/town).\n"
            "Deaktiviert: sucht auch Dörfer und Vororte (village/suburb)."
        )

        slider_label = QLabel("Maximale Anzahl Orte:")
        slider_label.setContentsMargins(20, 0, 0, 0)

        # Links = Maximum (250), Rechts = Minimum (10) → invertiert
        self._max_results_slider = QSlider(Qt.Orientation.Horizontal)
        self._max_results_slider.setMinimum(10)
        self._max_results_slider.setMaximum(250)
        self._max_results_slider.setValue(60)
        self._max_results_slider.setInvertedAppearance(True)
        self._max_results_slider.setFixedWidth(180)
        self._max_results_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._max_results_slider.setTickInterval(60)

        self._max_results_value_label = QLabel("60")
        self._max_results_value_label.setFixedWidth(28)
        self._max_results_value_label.setStyleSheet("font-weight: bold;")
        self._max_results_slider.valueChanged.connect(
            lambda v: self._max_results_value_label.setText(str(v))
        )

        self._no_precipitation_cb = QCheckBox("Nur Orte ohne Niederschlag")
        self._no_precipitation_cb.setChecked(False)
        self._no_precipitation_cb.setToolTip(
            "Aktiviert: zeigt nur Orte an, bei denen kein Niederschlag vorhergesagt wird.\n"
            "Deaktiviert: alle Orte werden angezeigt."
        )

        row.addWidget(self._only_cities_cb)
        row.addWidget(self._no_precipitation_cb)
        row.addWidget(slider_label)
        row.addWidget(self._max_results_slider)
        row.addWidget(self._max_results_value_label)
        row.addStretch()
        return row

    def _build_travel_mode_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        label = QLabel("Verkehrsmittel:")
        label.setFixedWidth(160)

        self._mode_buttons: dict[str, QRadioButton] = {}
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(20)

        for display, api_key in TRAVEL_MODES.items():
            btn = QRadioButton(display)
            self._mode_buttons[api_key] = btn
            mode_layout.addWidget(btn)

        # Standard: Auto
        self._mode_buttons["driving"].setChecked(True)
        mode_layout.addStretch()

        row.addWidget(label)
        row.addLayout(mode_layout)
        return row

    def _build_date_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        label = QLabel("Datum:")
        label.setFixedWidth(160)

        self._date_edit = QDateEdit()
        self._date_edit.setCalendarPopup(True)
        self._date_edit.setDate(QDate.currentDate())
        self._date_edit.setMinimumDate(QDate.currentDate())
        self._date_edit.setMaximumDate(QDate.currentDate().addDays(7))
        self._date_edit.setDisplayFormat("dd.MM.yyyy")
        self._date_edit.setFixedWidth(160)

        row.addWidget(label)
        row.addWidget(self._date_edit)
        row.addStretch()
        return row

    def _build_distance_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        label = QLabel("Max. Reisezeit (h):")
        label.setFixedWidth(160)

        self._distance_edit = QLineEdit()
        self._distance_edit.setPlaceholderText("z.B. 1.5")
        self._distance_edit.setText("1.5")
        self._distance_edit.setFixedWidth(100)

        hint = QLabel("(> 0, max. 12.0 Stunden)")
        hint.setStyleSheet("color: #888; font-size: 11px;")

        row.addWidget(label)
        row.addWidget(self._distance_edit)
        row.addWidget(hint)
        row.addStretch()
        return row

    def _build_search_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._search_btn = QPushButton("Suchen")
        self._search_btn.setObjectName("searchBtn")
        self._search_btn.setFixedHeight(38)
        self._search_btn.clicked.connect(self._on_search_clicked)
        self._map_btn = QPushButton("Karte anzeigen")
        self._map_btn.setObjectName("mapBtn")
        self._map_btn.setFixedHeight(38)
        self._map_btn.setEnabled(False)
        self._map_btn.setToolTip(
            "Zeigt die Orte der Ergebnisliste auf einer Karte. "
            "Orte in der Nähe werden je Region gebündelt."
        )
        self._map_btn.clicked.connect(self._on_map_clicked)
        row.addStretch()
        row.addWidget(self._map_btn)
        row.addWidget(self._search_btn)
        return row

    def _build_table(self) -> QTableWidget:
        headers = [
            "#", "Ort", "Sonnenstunden (h)", "Bewölkung (%)",
            "Längste klare Phase (h)", "Temperatur (°C)", "Reisezeit (min)", "Niederschlag (mm)"
        ]
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(False)
        table.setSortingEnabled(False)
        table.horizontalHeader().setSectionsClickable(True)
        table.horizontalHeader().setSortIndicatorShown(True)
        table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)
        table.cellDoubleClicked.connect(self._on_table_row_clicked)
        table.cellClicked.connect(self._on_table_row_clicked)

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)

        # Spaltenbreiten
        table.setColumnWidth(0, 40)
        table.setColumnWidth(1, 220)
        table.setColumnWidth(2, 130)
        table.setColumnWidth(3, 110)
        table.setColumnWidth(4, 160)
        table.setColumnWidth(5, 120)
        table.setColumnWidth(6, 110)
        table.setColumnWidth(7, 120)

        return table

    # ------------------------------------------------------------------ #
    # Nutzereinstellungen                                                  #
    # ------------------------------------------------------------------ #

    def _load_user_preferences(self) -> None:
        """Lädt die zuletzt gespeicherten Einstellungen."""
        try:
            prefs = self.cache.get_user_preferences(self.user_id)
            if prefs is None:
                return

            if prefs.get("last_place_name") and prefs.get("last_place_id"):
                self._location_edit.setText(prefs["last_place_name"])
                self._selected_place = {
                    "name": prefs["last_place_name"],
                    "place_id": prefs["last_place_id"],
                    "lat": prefs.get("last_place_lat", 0.0),
                    "lng": prefs.get("last_place_lng", 0.0),
                }

            if prefs.get("last_travel_time") is not None:
                self._distance_edit.setText(str(prefs["last_travel_time"]))

            mode = prefs.get("last_travel_mode")
            if mode in self._mode_buttons:
                self._mode_buttons[mode].setChecked(True)

            if prefs.get("last_only_cities") is not None:
                self._only_cities_cb.setChecked(bool(prefs["last_only_cities"]))

            if prefs.get("last_max_results") is not None:
                slider_val = int(prefs["last_max_results"])
                slider_val = max(self._max_results_slider.minimum(), slider_val)
                slider_val = min(self._max_results_slider.maximum(), slider_val)
                self._max_results_slider.setValue(slider_val)

            if prefs.get("last_date_iso"):
                parsed_date = QDate.fromString(str(prefs["last_date_iso"]), "yyyy-MM-dd")
                if parsed_date.isValid():
                    today = QDate.currentDate()
                    max_day = today.addDays(7)
                    if parsed_date < today:
                        parsed_date = today
                    elif parsed_date > max_day:
                        parsed_date = max_day
                    self._date_edit.setDate(parsed_date)

            if prefs.get("last_no_precipitation_only") is not None:
                self._no_precipitation_cb.setChecked(bool(prefs["last_no_precipitation_only"]))

            logger.debug("Nutzereinstellungen geladen für %s.", self.user_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Nutzereinstellungen konnten nicht angewendet werden (%s). Verwende Defaults.",
                exc,
            )
            self._apply_default_preferences()

    def _apply_default_preferences(self) -> None:
        """Setzt alle einstellbaren Parameter auf definierte Defaultwerte zurück."""
        self._only_cities_cb.setChecked(self.DEFAULT_ONLY_CITIES)
        self._max_results_slider.setValue(self.DEFAULT_MAX_RESULTS)
        if self.DEFAULT_TRAVEL_MODE in self._mode_buttons:
            self._mode_buttons[self.DEFAULT_TRAVEL_MODE].setChecked(True)
        self._distance_edit.setText(str(self.DEFAULT_TRAVEL_TIME_HOURS))
        self._date_edit.setDate(QDate.currentDate())
        self._no_precipitation_cb.setChecked(self.DEFAULT_NO_PRECIPITATION_ONLY)

    def _save_user_preferences(self, mode: str, travel_time: float) -> None:
        """Speichert aktuelle Suchparameter des Nutzers."""
        place_name = None
        place_id = None
        place_lat = None
        place_lng = None
        if self._selected_place:
            place_name = self._selected_place.get("name")
            place_id = self._selected_place.get("place_id")
            place_lat = self._selected_place.get("lat")
            place_lng = self._selected_place.get("lng")

        self.cache.set_user_preferences(
            user_id=self.user_id,
            last_place_name=place_name,
            last_place_id=place_id,
            last_place_lat=place_lat,
            last_place_lng=place_lng,
            last_travel_time=travel_time,
            last_travel_mode=mode,
            last_only_cities=self._only_cities_cb.isChecked(),
            last_max_results=self._max_results_slider.value(),
            last_date_iso=self._date_edit.date().toString("yyyy-MM-dd"),
            last_no_precipitation_only=self._no_precipitation_cb.isChecked(),
        )

    # ------------------------------------------------------------------ #
    # Event Handler                                                        #
    # ------------------------------------------------------------------ #

    def _on_location_text_changed(self, text: str) -> None:
        """Trigger Autocomplete ab 3 Zeichen."""
        normalized_text = text.strip()

        # Wenn der Text bereits exakt einem vorhandenen Vorschlag entspricht,
        # übernehmen wir direkt diesen Ort und vermeiden ein erneutes Lookup.
        for s in self._suggestions:
            if s["description"].strip().casefold() == normalized_text.casefold():
                self._selected_place = {
                    "name": s["description"],
                    "place_id": s["place_id"],
                    "lat": s["lat"],
                    "lng": s["lng"],
                }
                return

        if len(normalized_text) < 3:
            self._completer_model.setStringList([])
            self._suggestions = []
            self._selected_place = None
            return

        suggestions = self.api.geocode_location(normalized_text)
        self._suggestions = suggestions
        descriptions = [s["description"] for s in suggestions]
        self._completer_model.setStringList(descriptions)

        if descriptions:
            self._completer.complete()

        # Bei Textänderung: gespeicherten Ort zurücksetzen
        if self._selected_place and self._selected_place.get("name") != normalized_text:
            self._selected_place = None

    def _on_suggestion_selected(self, text: str) -> None:
        """Wird aufgerufen, wenn der Nutzer einen Autocomplete-Vorschlag auswählt."""
        for s in self._suggestions:
            if s["description"] == text:
                # Koordinaten direkt aus Geocoding-Ergebnis übernehmen
                self._selected_place = {
                    "name": text,
                    "place_id": s["place_id"],
                    "lat": s["lat"],
                    "lng": s["lng"],
                }
                logger.debug("Ort ausgewählt: %s (lat=%s, lng=%s)", text, s["lat"], s["lng"])
                return

    def _sync_selected_place_from_text(self) -> None:
        """Versucht, den aktuell eingegebenen Text einem Vorschlag zuzuordnen."""
        text = self._location_edit.text().strip()
        if not text:
            return

        for s in self._suggestions:
            if s["description"].strip().casefold() == text.casefold():
                self._selected_place = {
                    "name": s["description"],
                    "place_id": s["place_id"],
                    "lat": s["lat"],
                    "lng": s["lng"],
                }
                return

    def _on_search_clicked(self) -> None:
        """Startet die Suche nach Validierung aller Felder."""
        if not self._validate_inputs():
            return

        mode = self._get_selected_mode()
        travel_hours = float(self._distance_edit.text().replace(",", "."))
        date_str = self._date_edit.date().toString("yyyy-MM-dd")
        only_cities = self._only_cities_cb.isChecked()
        max_results = self._max_results_slider.value()

        # Einstellungen speichern
        self._save_user_preferences(mode, travel_hours)

        # UI sofort sperren und Feedback geben
        self._search_btn.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._table.setRowCount(0)
        self._collected_results = []
        self._results = []
        self._search_failed = False
        self._map_btn.setEnabled(False)
        self._results_origin = {
            "name": self._selected_place.get("name", ""),
            "lat": self._selected_place["lat"],
            "lng": self._selected_place["lng"],
        }
        self._results_date = date_str

        # Suchparameter zwischenspeichern für _on_candidates_ready
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=8, minute=0)
        self._pending_search_params = {
            "mode": mode,
            "date_str": date_str,
            "departure_unix": int(dt.timestamp()),
            "max_duration_sec": int(travel_hours * 3600),
            "origin_lat": self._selected_place["lat"],
            "origin_lng": self._selected_place["lng"],
            "only_cities": only_cities,
            "max_results": max_results,
        }

        # Cache prüfen (schneller SQLite-Lookup im Main Thread)
        cached = self.cache.get_nearby_candidates(
            self._selected_place["lat"],
            self._selected_place["lng"],
            mode,
            only_cities,
            max_results,
            int(travel_hours * 3600),
        )
        if cached is not None:
            self._status_label.setText(
                f"{len(cached)} Orte aus Cache geladen. Reisezeiten und Wetter werden geprüft …"
            )
            self._on_candidates_ready(cached)
            return

        self._status_label.setText("Suche Orte in Reichweite …")

        # Kandidatensuche im Hintergrund starten
        candidate_worker = CandidateSearchWorker(
            api_client=self.api,
            lat=self._selected_place["lat"],
            lng=self._selected_place["lng"],
            signals=self._signals,
            max_results=max_results,
            only_cities=only_cities,
            mode=mode,
            max_duration_sec=int(travel_hours * 3600),
        )
        self._pool.start(candidate_worker)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Speichert beim Schließen die aktuell sichtbaren Parameter."""
        try:
            mode = self._get_selected_mode()
            travel_hours = float(self._distance_edit.text().replace(",", "."))
            if 0 < travel_hours <= MAX_TRAVEL_TIME_HOURS:
                self._save_user_preferences(mode, travel_hours)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Einstellungen beim Schließen nicht gespeichert: %s", exc)
        super().closeEvent(event)

    @pyqtSlot(list)
    def _on_candidates_ready(self, candidates: list) -> None:
        """Wird aufgerufen, wenn die Kandidatenliste im Hintergrund geladen wurde."""
        if not candidates:
            self._on_search_no_results()
            return

        p = self._pending_search_params

        # Kandidaten im Cache speichern (INSERT OR REPLACE – kein Duplikat bei Cache-Hit)
        self.cache.set_nearby_candidates(
            p["origin_lat"], p["origin_lng"],
            p["mode"], p["only_cities"], p["max_results"],
            p["max_duration_sec"],
            candidates,
        )

        self._status_label.setText(
            f"{len(candidates)} Orte gefunden. Reisezeiten und Wetter werden geprüft …"
        )
        self._pending_workers = len(candidates)

        for candidate in candidates:
            worker = SearchWorker(
                candidate=candidate,
                origin_lat=p["origin_lat"],
                origin_lng=p["origin_lng"],
                mode=p["mode"],
                date_str=p["date_str"],
                departure_unix=p["departure_unix"],
                max_duration_sec=p["max_duration_sec"],
                api_client=self.api,
                cache=self.cache,
                signals=self._signals,
            )
            self._pool.start(worker)

        self._monitor_pool(len(candidates))

    def _monitor_pool(self, total: int) -> None:
        """Zählt erledigte Worker; sendet finished-Signal wenn alle fertig."""
        # Da QThreadPool kein eingebautes "all done"-Signal hat,
        # nutzen wir einen internen Zähler, der über result_ready und
        # das Ende des Pools ermittelt wird.
        self._remaining_workers = total

        def _count_down(result: dict) -> None:
            self._remaining_workers -= 1
            if self._remaining_workers <= 0:
                self._signals.finished.emit()

        # Wrapper: zählt Ergebnisse + nicht-Ergebnisse
        # Da Worker IMMER endet (mit oder ohne Ergebnis), nutzen wir
        # einen dedizierten "done"-Mechanismus:
        self._done_count = 0
        self._total_workers = total
        self._signals.result_ready.connect(self._count_worker_done)

        # QThreadPool.waitForDone() in QTimer-Poll wäre Blocking → nicht nutzen.
        # Stattdessen: Worker sendet finished am Ende via _count_worker_done.

    def _count_worker_done(self, _result: dict = None) -> None:
        """Zählt abgeschlossene Worker und emittiert finished wenn alle fertig."""
        # Dieser Slot wird pro Ergebnis aufgerufen.
        # Für Worker ohne Ergebnis gibt es keinen Callback – wir warten auf den Pool.
        pass

    @pyqtSlot(str)
    def _on_candidates_failed(self, message: str) -> None:
        """Die Ortssuche ist gescheitert (z. B. Overpass nicht erreichbar)."""
        self._search_failed = True
        self._progress_bar.setVisible(False)
        self._search_btn.setEnabled(True)
        self._status_label.setText("Ortssuche fehlgeschlagen.")
        QMessageBox.warning(self, "Ortssuche fehlgeschlagen", message)

    @pyqtSlot(dict)
    def _on_result_ready(self, result: dict) -> None:
        """Empfängt ein Ergebnis von einem Worker."""
        self._collected_results.append(result)

    @pyqtSlot()
    def _on_search_finished(self) -> None:
        """Wird aufgerufen, wenn alle Worker abgeschlossen sind."""
        if self._search_failed:  # Fehler wurde bereits gemeldet
            return
        self._progress_bar.setVisible(False)
        self._search_btn.setEnabled(True)

        if not self._collected_results:
            self._on_search_no_results()
            return

        # Sortierung: Bewölkung ↑, längste klare Phase ↓, Reisezeit ↑, Niederschlag ↑
        sorted_results = sorted(
            self._collected_results,
            key=lambda r: (
                r["avg_cloud_pct"],
                -r["longest_sunshine_period_hours"],
                r["duration_sec"],
                r["total_precipitation_mm"],
            )
        )

        # Optional: nur Orte ohne Niederschlag anzeigen
        if self._no_precipitation_cb.isChecked():
            sorted_results = [r for r in sorted_results if r["total_precipitation_mm"] == 0]

        if not sorted_results:
            self._on_search_no_results(no_precip_filter=True)
            return

        self._results = [
            {**r, "rank": idx + 1}
            for idx, r in enumerate(sorted_results)
        ]
        self._last_sort_column = None
        self._fill_table(self._results)
        self._map_btn.setEnabled(True)
        total_found = len(self._collected_results)
        shown = len(sorted_results)
        if self._no_precipitation_cb.isChecked() and shown < total_found:
            self._status_label.setText(
                f"Suche abgeschlossen. {shown} von {total_found} Orten ohne Niederschlag angezeigt."
            )
        else:
            self._status_label.setText(
                f"Suche abgeschlossen. {shown} Orte gefunden."
            )

    def _on_search_no_results(self, no_precip_filter: bool = False) -> None:
        """Zeigt Fehlermeldung, wenn keine Ergebnisse gefunden wurden."""
        self._progress_bar.setVisible(False)
        self._search_btn.setEnabled(True)
        self._status_label.setText("Keine Ergebnisse.")
        if no_precip_filter:
            QMessageBox.information(
                self,
                "Keine Orte ohne Niederschlag",
                "Es wurden Orte gefunden, aber nach dem Filter 'Nur Orte ohne Niederschlag' "
                "verbleiben keine Ergebnisse. Bitte Filter deaktivieren oder Distanz erhöhen.",
            )
        else:
            QMessageBox.information(
                self,
                "Keine Orte gefunden",
                "Keine Orte gefunden. Bitte Distanz erhöhen oder Datum ändern.",
            )

    def _on_table_row_clicked(self, row: int, _col: int) -> None:
        """Öffnet das Detail-Popup für die angeklickte Zeile."""
        if row < 0 or row >= len(self._results):
            return
        result = self._results[row]
        date_str = self._date_edit.date().toString("yyyy-MM-dd")
        dlg = DetailDialog(result, date_str, self)
        dlg.exec()

    def _on_map_clicked(self) -> None:
        """Öffnet das Kartenfenster mit den Orten der aktuellen Ergebnisliste."""
        if not self._results or self._results_origin is None:
            return
        try:
            from modules.map_window import MapWindow
        except ImportError as exc:
            logger.error("Kartenmodul nicht verfügbar: %s", exc)
            QMessageBox.warning(
                self, "Karte nicht verfügbar",
                "Für die Karte wird das Paket „PyQt6-WebEngine“ benötigt "
                "(pip install PyQt6-WebEngine)."
            )
            return
        try:
            window = MapWindow(self._results_origin, self._results, self._results_date)
        except Exception as exc:  # noqa: BLE001 - z. B. fehlende Symbol-Dateien
            logger.exception("Kartenfenster konnte nicht geöffnet werden")
            QMessageBox.warning(
                self, "Karte nicht verfügbar", f"Die Karte konnte nicht geöffnet werden:\n{exc}"
            )
            return
        self._map_window = window  # Referenz halten, sonst wird das Fenster eingesammelt
        window.show()

    # ------------------------------------------------------------------ #
    # Hilfsmethoden                                                        #
    # ------------------------------------------------------------------ #

    def _validate_inputs(self) -> bool:
        """Prüft alle Pflichtfelder und zeigt bei Fehler ein Popup."""
        if not self._selected_place:
            self._sync_selected_place_from_text()

        if not self._selected_place:
            self._show_error("Bitte wählen Sie einen Startort aus der Vorschlagsliste.")
            return False

        text = self._distance_edit.text().replace(",", ".")
        try:
            val = float(text)
            if val <= 0 or val > MAX_TRAVEL_TIME_HOURS:
                raise ValueError
        except ValueError:
            self._show_error(
                f"Bitte geben Sie eine gültige Max. Reisezeit ein (0 < Wert ≤ {MAX_TRAVEL_TIME_HOURS})."
            )
            return False

        today = QDate.currentDate()
        chosen = self._date_edit.date()
        if chosen < today or chosen > today.addDays(7):
            self._show_error("Das Datum muss zwischen heute und heute + 7 Tagen liegen.")
            return False

        return True

    def _get_selected_mode(self) -> str:
        """Gibt den API-Schlüssel des gewählten Verkehrsmittels zurück."""
        for api_key, btn in self._mode_buttons.items():
            if btn.isChecked():
                return api_key
        return "driving"

    def _on_header_clicked(self, column: int) -> None:
        """Sortiert die Ergebnistabelle nach Header-Klick mit spaltenspezifischer Initialrichtung."""
        initial_orders = {
            0: False,  # # zuerst absteigend
            1: True,   # Ort zuerst A-Z
            2: False,  # Sonnenstunden zuerst absteigend
            3: True,   # Bewölkung zuerst aufsteigend (wenig Wolken = gut)
            4: False,  # Längste klare Phase zuerst absteigend
            5: False,  # Temperatur zuerst absteigend
            6: True,   # Reisezeit zuerst aufsteigend
            7: True,   # Niederschlag zuerst aufsteigend
        }

        if column not in initial_orders or not self._results:
            return

        if self._last_sort_column == column:
            ascending = not self._last_sort_ascending
        else:
            ascending = initial_orders[column]

        self._last_sort_column = column
        self._last_sort_ascending = ascending

        key_map = {
            0: lambda r: r.get("rank", 0),
            1: lambda r: r.get("name", "").casefold(),
            2: lambda r: r.get("total_sunshine_hours", 0.0),
            3: lambda r: r.get("avg_cloud_pct", 100.0),
            4: lambda r: r.get("longest_sunshine_period_hours", 0.0),
            5: lambda r: r.get("avg_temperature_c", 0.0),
            6: lambda r: r.get("duration_sec", 0),
            7: lambda r: r.get("total_precipitation_mm", 0.0),
        }
        key_fn = key_map[column]
        self._results = sorted(self._results, key=key_fn, reverse=not ascending)
        self._fill_table(self._results)

        order = (
            Qt.SortOrder.AscendingOrder if ascending
            else Qt.SortOrder.DescendingOrder
        )
        self._table.horizontalHeader().setSortIndicator(column, order)

    def _fill_table(self, results: list[dict]) -> None:
        """Befüllt die Ergebnistabelle mit den Top-Ergebnissen."""
        self._table.setRowCount(len(results))
        for row, r in enumerate(results):
            duration_min = math.ceil(r["duration_sec"] / 60)

            items = [
                str(r.get("rank", row + 1)),
                r["name"],
                f"{r['total_sunshine_hours']:.1f}",
                f"{r.get('avg_cloud_pct', 100.0):.0f}",
                f"{r['longest_sunshine_period_hours']:.0f}",
                f"{r.get('avg_temperature_c', 0.0):.1f}",
                str(duration_min),
                f"{r['total_precipitation_mm']:.1f}",
            ]
            for col, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter
                    if col != 1
                    else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                # Bewölkungs-Spalte farblich hervorheben (≤ 30 % gut, ≤ 60 % mittel)
                if col == 3:
                    cloud = r.get("avg_cloud_pct", 100.0)
                    if cloud <= 30:
                        item.setBackground(QColor("#C8E6C9"))  # grün
                    elif cloud <= 60:
                        item.setBackground(QColor("#FFF9C4"))  # gelb
                    else:
                        item.setBackground(QColor("#FFCCBC"))  # orange
                self._table.setItem(row, col, item)

        # Spalten bleiben kontrolliert, damit kein horizontaler Scrollbar nötig ist.
        self._table.setColumnWidth(0, 40)

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "Eingabefehler", message)


# ============================================================= #
# Pool-Fertig-Überwachung via QTimer                             #
# ============================================================= #

class PoolMonitor(QObject):
    """
    Überwacht den QThreadPool und emittiert ein Signal, wenn alle Worker fertig sind.
    Verwendet QTimer für nicht-blockierendes Polling.
    """
    all_done = pyqtSignal()

    def __init__(self, pool: QThreadPool, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._pool = pool
        self._timer_id: int = 0

    def start_monitoring(self) -> None:
        from PyQt6.QtCore import QTimer
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._check)
        self._timer.start()

    def _check(self) -> None:
        if self._pool.activeThreadCount() == 0:
            self._timer.stop()
            self.all_done.emit()


def patch_main_window_pool_monitoring(window: MainWindow) -> None:
    """
    Patcht das MainWindow so, dass der PoolMonitor den finished-Signal auslöst,
    sobald alle Worker des Thread-Pools abgearbeitet sind.

    Diese Funktion wird von app.py nach Erstellen des MainWindow aufgerufen.
    """
    monitor = PoolMonitor(window._pool, window)
    monitor.all_done.connect(window._on_search_finished)
    window._pool_monitor = monitor  # Referenz halten

    # Original _on_search_clicked erweitern
    original_on_search = window._on_search_clicked.__func__

    def patched_on_search(self_win: MainWindow) -> None:
        original_on_search(self_win)
        # Monitor neu starten (kurze Verzögerung, damit Worker gestartet sind)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(100, self_win._pool_monitor.start_monitoring)

    import types
    window._on_search_clicked = types.MethodType(patched_on_search, window)
    window._search_btn.clicked.disconnect()
    window._search_btn.clicked.connect(window._on_search_clicked)
