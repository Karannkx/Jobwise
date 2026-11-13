; Inno Setup script. Build (from repo root, after PyInstaller):
;   iscc /DAppVersion=1.0.0 packaging\windows\installer.iss
; Output: dist\Jobwise-Windows-x64.exe  (self-contained installer; no Python required)

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6F1C8E52-3B0A-4D6E-9A41-5E2C7D9B1A33}}
AppName=Jobwise
AppVersion={#AppVersion}
AppPublisher=Karan Kumar (karannkx)
DefaultDirName={autopf}\Jobwise
DefaultGroupName=Jobwise
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename=Jobwise-Windows-x64
SetupIconFile=..\..\assets\icon.ico
UninstallDisplayIcon={app}\Jobwise.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\..\dist\Jobwise\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Jobwise"; Filename: "{app}\Jobwise.exe"
Name: "{autodesktop}\Jobwise"; Filename: "{app}\Jobwise.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Jobwise.exe"; Description: "Launch Jobwise"; Flags: nowait postinstall skipifsilent
