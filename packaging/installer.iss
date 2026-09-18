; Inno Setup script for DSI Redline.
; Build the app first (pyinstaller packaging/DSI_Redline.spec), then compile this
; with Inno Setup 6:  ISCC.exe packaging\installer.iss
; Produces dist_installer\DSI_Redline_Setup_<version>.exe

#define MyAppName "DSI Redline"
#define MyAppVersion "1.5.2"
#define MyAppPublisher "DSI Innovations, LLC"
#define MyAppExeName "DSI Redline.exe"
; A private ProgID for our PDF association. Kept distinct from the system PDF
; handler so installing only ADDS DSI Redline to the "Open with" list and the
; Default-Apps picker — it never silently hijacks the user's current default.
#define MyPdfProgId "DSIRedline.pdf"

[Setup]
AppId={{B5F4B0A2-3E2D-4C7A-9F1E-DS1REDLINE0001}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppCopyright=© DSI Innovations, LLC 2026
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist_installer
OutputBaseFilename=DSI_Redline_Setup_{#MyAppVersion}
SetupIconFile=..\app\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
; Tell the shell its file-association data changed so the new "Open with" entry
; shows up immediately (no reboot / re-login needed).
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "pdfassoc"; Description: "Register {#MyAppName} as a PDF viewer (adds it to the Windows ""Open with"" list and the Default Apps picker)"; GroupDescription: "File associations:"

[Files]
; The one-folder PyInstaller output (includes the bundled docs vault).
Source: "..\dist\DSI Redline\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; --- File association: make DSI Redline a selectable PDF opener -------------
; HKA = HKLM for an all-users (admin) install, HKCU otherwise. Everything is
; gated on the "pdfassoc" task and removed on uninstall.
;
; 1) Our ProgID: how Windows opens a PDF *with* DSI Redline.
Root: HKA; Subkey: "Software\Classes\{#MyPdfProgId}"; ValueType: string; ValueName: ""; ValueData: "PDF Document"; Flags: uninsdeletekey; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\{#MyPdfProgId}"; ValueType: string; ValueName: "FriendlyTypeName"; ValueData: "PDF Document"; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\{#MyPdfProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\{#MyPdfProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: pdfassoc
;
; 2) Add our ProgID to the .pdf "Open with" list (ADDITIVE — does not change the
;    current default handler).
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "{#MyPdfProgId}"; ValueData: ""; Flags: uninsdeletevalue; Tasks: pdfassoc
;
; 3) Register the executable itself so it appears under "Open with ▸ Choose
;    another app" with a friendly name and is offered for .pdf files.
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#MyAppName}"; Flags: uninsdeletekey; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Tasks: pdfassoc
;
; 4) Capabilities + RegisteredApplications so DSI Redline shows up in
;    Settings ▸ Apps ▸ Default apps and can be SET as the default PDF handler.
Root: HKA; Subkey: "Software\{#MyAppPublisher}\{#MyAppName}\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#MyAppName}"; Flags: uninsdeletekey; Tasks: pdfassoc
Root: HKA; Subkey: "Software\{#MyAppPublisher}\{#MyAppName}\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "PDF markup and wire-number / component-label extraction"; Tasks: pdfassoc
Root: HKA; Subkey: "Software\{#MyAppPublisher}\{#MyAppName}\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "{#MyPdfProgId}"; Tasks: pdfassoc
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: "Software\{#MyAppPublisher}\{#MyAppName}\Capabilities"; Flags: uninsdeletevalue; Tasks: pdfassoc

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
