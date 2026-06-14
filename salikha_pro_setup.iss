[Setup]
AppName=Salikha Studio Pro
AppVersion=1.0.1
AppPublisher=Salikha
AppPublisherURL=https://salikha.com
AppSupportURL=https://salikha.com
AppUpdatesURL=https://salikha.com
DefaultDirName={autopf}\Salikha Studio Pro
DefaultGroupName=Salikha Studio Pro
AllowNoIcons=yes
OutputDir=installer
OutputBaseFilename=SalikhaStudioPro_Setup_v1.0.1
SetupIconFile=Salikha Photoman Ico.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
Password=salikha.studio
LicenseFile=license.txt
DisableWelcomePage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1; Check: not IsAdminInstallMode

[Files]
Source: "dist\salikha_pro.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Salikha Studio Pro"; Filename: "{app}\salikha_pro.exe"
Name: "{group}\Uninstall Salikha Studio Pro"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Salikha Studio Pro"; Filename: "{app}\salikha_pro.exe"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\Salikha Studio Pro"; Filename: "{app}\salikha_pro.exe"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\salikha_pro.exe"; Description: "{cm:LaunchProgram,Salikha Studio Pro}"; Flags: nowait postinstall skipifsilent