; MARK local Ollama assistant — Windows installer
; Build with Inno Setup 6: https://jrsoftware.org/isinfo.php
;
; The installer copies the source into a user-writable directory. This is
; intentional: MARK stores config/api_keys.json and local memory beside itself.
; The post-install PowerShell step creates the private .venv and shortcuts.

#define AppName "MARK"
#define AppVersion "1.0.0"
#define AppPublisher "MARK"
#define AppURL "https://ollama.com"
#define AppExeName "installer\\mark.bat"

[Setup]
AppId={{B8A7BDE6-2DD4-4B7D-9C74-1E09E7C1C2AD}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
DefaultDirName={localappdata}\Programs\MARK
DefaultGroupName=MARK
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=MARK-Installer
SetupIconFile=..\config\jarvis.ico
UninstallDisplayIcon={app}\config\jarvis.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=no

[Files]
Source: "..\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; \
    Excludes: ".git\*;.venv\*;__pycache__\*;*.pyc;build\*;dist\*;memory\long_term.json;config\api_keys.json;installer\output\*"

[Icons]
Name: "{autodesktop}\MARK"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\config\jarvis.ico"; IconIndex: 0
Name: "{group}\MARK"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\config\jarvis.ico"; IconIndex: 0

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\installer\install.ps1"" -InstallRoot ""{app}"""; \
    WorkingDir: "{app}"; Flags: postinstall waituntilterminated; Description: "Install Python dependencies and finish MARK setup"
Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent; Description: "Launch MARK"

[UninstallDelete]
Type: files; Name: "{autodesktop}\MARK.lnk"
Type: filesandordirs; Name: "{userappdata}\Microsoft\Windows\Start Menu\Programs\MARK"
