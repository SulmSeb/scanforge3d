; Inno-Setup-Skript fuer ScanForge 3D
#define AppName "ScanForge 3D"
#define AppVersion "1.0.0"
#define AppExe "ScanForge3D.exe"

[Setup]
AppId={{6B0E7C4D-3F1A-4E5B-9C2D-5A7F3E8B1D42}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=ScanForge
DefaultDirName={autopf}\ScanForge 3D
DefaultGroupName={#AppName}
OutputDir=Output
OutputBaseFilename=ScanForge3D_Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzlich:"

[Files]
Source: "dist\ScanForge3D\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} deinstallieren"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Installiere Microsoft Visual C++ Laufzeit ..."; Flags: waituntilterminated
Filename: "{app}\{#AppExe}"; Description: "{#AppName} jetzt starten"; Flags: nowait postinstall skipifsilent
