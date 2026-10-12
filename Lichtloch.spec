# -*- mode: python ; coding: utf-8 -*-
#
# Lichtloch – PyInstaller-Spec (onedir statt onefile).
#
# Onefile entpackt bei JEDEM Start den gesamten Inhalt nach %TEMP% (Messung der alten
# 225-MB-EXE: 7,6 s bis zum ersten Fenster im besten Fall, kalt über 28 s). Onedir startet
# direkt aus dem Programmordner. Als einzelne Datei zum Weitergeben dient ein Installer
# (siehe installer/Lichtloch.iss) oder das ZIP.
#
# Bauen:  .venv\Scripts\python.exe -m PyInstaller --noconfirm Lichtloch.spec
import os

ROOT = SPECPATH                                  # Ordner dieser .spec
SRC = os.path.join(ROOT, 'sunshine_finder')

# Python-Pakete, die die App nicht (mehr) benötigt
EXCLUDES = [
    'matplotlib', 'numpy', 'PIL', 'tkinter', 'setuptools', 'pkg_resources',
    'google', 'google_auth_oauthlib', 'dotenv', 'cryptography', 'requests_oauthlib',
    'PyQt6.QtQuick3D', 'PyQt6.QtMultimedia', 'PyQt6.QtMultimediaWidgets', 'PyQt6.QtPdf',
    'PyQt6.QtPdfWidgets', 'PyQt6.QtSensors', 'PyQt6.QtSerialPort', 'PyQt6.QtTextToSpeech',
    'PyQt6.QtBluetooth', 'PyQt6.QtNfc', 'PyQt6.QtDesigner', 'PyQt6.QtHelp', 'PyQt6.QtSql',
    'PyQt6.QtTest', 'PyQt6.QtSpatialAudio', 'PyQt6.QtRemoteObjects', 'PyQt6.QtCharts',
    'PyQt6.QtDataVisualization', 'PyQt6.Qt3DCore',
]

# Dateien im Qt-Bundle, die die App nie benutzt (Pfad enthält / endet auf ...)
_DROP_CONTAINS = (
    '/qml/',                                    # QML-Module (die App nutzt nur Widgets)
    'qtwebengine_devtools_resources',           # Chromium-DevTools (ca. 30 MB)
    '.debug.pak',
    'qt6quick3d', 'qt6quickcontrols2', 'qt6quicktemplates2', 'qt6quickdialogs',
    'qt6multimedia', 'qt6pdf', 'qt6sensors', 'qt6serialport', 'qt6texttospeech',
    'qt6bluetooth', 'qt6nfc', 'qt6designer', 'qt6help', 'qt6sql', 'qt6test',
    'qt6spatialaudio', 'qt6remoteobjects', 'qt6charts', 'qt6datavisualization',
    'qt6quicktest',
    'qpdf.dll', 'qtposition_nmea',              # Plugins, deren Qt-DLL oben entfernt wird
)
_KEEP_LOCALES = ('en-us.pak', 'de.pak')


def _unused(entry):
    dest = entry[0].replace('\\', '/').lower()
    if dest.endswith('.qm'):                    # Qt-Übersetzungen (kein QTranslator im Code)
        return True
    if 'qtwebengine_locales/' in dest and not dest.endswith(_KEEP_LOCALES):
        return True
    return any(token in dest for token in _DROP_CONTAINS)


a = Analysis(
    [os.path.join(SRC, 'app.py')],
    pathex=[SRC],
    binaries=[],
    datas=[(os.path.join(SRC, 'assets'), 'assets')],   # Karten-Symbole (map_window.py)
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
a.binaries = [e for e in a.binaries if not _unused(e)]
a.datas = [e for e in a.datas if not _unused(e)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Lichtloch',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(ROOT, 'sun.ico'),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='Lichtloch',
)
