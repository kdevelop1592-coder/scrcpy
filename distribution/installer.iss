; Inno Setup script for Microscope Controller
; Build: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
#define MyAppName "Microscope Controller"
#define MyAppVersion "1.00"
#define MyAppExe "MicroscopeController.exe"

[Setup]
AppId={{B7A3F1C2-5D8E-4F6A-9C21-3E7D0A5B8F14}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\MicroscopeController
DefaultGroupName={#MyAppName}
OutputDir=output
OutputBaseFilename=MicroscopeController_Setup_{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExe}
LicenseFile=..\LICENSE
InfoAfterFile=INSTALL_GUIDE.txt
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "output\MicroscopeController\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 실행 중인 scrcpy/adb 프로세스 정리 (파일 잠금 방지)
Filename: "{cmd}"; Parameters: "/c taskkill /f /im scrcpy.exe >nul 2>&1"; Flags: runhidden; RunOnceId: "KillScrcpy"
Filename: "{cmd}"; Parameters: "/c taskkill /f /im adb.exe >nul 2>&1"; Flags: runhidden; RunOnceId: "KillAdb"

[CustomMessages]
english.DeleteSettings=Delete saved settings as well?
korean.DeleteSettings=Delete saved settings as well? (saved settings)

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  CfgDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    CfgDir := ExpandConstant('{userappdata}\MicroscopeController');
    if DirExists(CfgDir) then
      if MsgBox(CustomMessage('DeleteSettings'), mbConfirmation, MB_YESNO) = IDYES then
        DelTree(CfgDir, True, True, True);
  end;
end;
