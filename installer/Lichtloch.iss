; Inno-Setup-Skript fuer Lichtloch: buendelt den onedir-Build zu EINER Datei (Lichtloch-Setup.exe).
; Vorher bauen:   .venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath dist_neu --workpath build_neu Lichtloch.spec
; Dann kompilieren: ISCC.exe installer\Lichtloch.iss   ->  dist_setup\Lichtloch-Setup.exe
;
; Installation pro Benutzer (kein Admin noetig): Die App schreibt app.log und cache.db neben
; die EXE, das geht nur in einem fuer den Benutzer beschreibbaren Ordner.

#define AppName "Lichtloch"
; Muss mit __version__ in sunshine_finder\modules\__init__.py uebereinstimmen (tests\test_version.py prueft das).
#define AppVersion "1.3.0"

[Setup]
AppId={{6E0F2C4A-5B7D-4E1A-9C3B-1A7D52F0B4C8}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisherURL=https://github.com/llange2/lichtloch
AppSupportURL=https://github.com/llange2/lichtloch/issues
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist_setup
OutputBaseFilename=Lichtloch-Setup
SetupIconFile=..\sun.ico
UninstallDisplayIcon={app}\Lichtloch.exe
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist_neu\Lichtloch\*"; DestDir: "{app}"; Excludes: "app.log,cache.db"; Flags: recursesubdirs createallsubdirs ignoreversion
; Lizenz (GPL-3.0) und Hinweise zu Drittkomponenten gehoeren zur Weitergabe des Programms
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\Lichtloch.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Lichtloch.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Lichtloch.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\app.log"
Type: files; Name: "{app}\cache.db"
