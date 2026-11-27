; BabySitter installer.
; The version on the next line must match src/babysitter/version.py.
; Inno Setup supports silent installs with /SILENT, which the future updater uses.
; A silent install does not delete anything in %LOCALAPPDATA%\BabySitter.

#define MyAppName "BabySitter"
#define MyAppVersion "0.28.0"
#define MyAppExeName "BabySitter.exe"

[Setup]
AppId={{8F3C1E2A-6B47-4D91-9C2E-5A7B0D4E6F18}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=BabySitter
DefaultDirName={autopf}\BabySitter
DefaultGroupName=BabySitter
DisableProgramGroupPage=yes
OutputDir=..\dist-installer
OutputBaseFilename=BabySitter-Setup-{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
; Do not touch the user's saved files. They live outside the install folder.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Add a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: checked
Name: "startmenu"; Description: "Add a Start menu shortcut"; GroupDescription: "Shortcuts:"; Flags: checked

[Files]
Source: "..\dist\BabySitter.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\BabySitter"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{autoprograms}\BabySitter"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenu

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Start BabySitter"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep <> usUninstall then
    Exit;
  { Silent uninstall (used by a future updater) must never delete personal data. }
  if UninstallSilent then
    Exit;
  DataDir := ExpandConstant('{localappdata}\BabySitter');
  if DirExists(DataDir) then
  begin
    if MsgBox('Also delete BabySitter settings and data in:' + #13#10 + DataDir + #13#10 + #13#10 + 'Ollama, and the models it downloaded, are not removed.', mbConfirmation, MB_YESNO) = IDYES then
      DelTree(DataDir, True, True, True);
  end;
end;
