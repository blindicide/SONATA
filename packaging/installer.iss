#define AppVersion "0.1.1"
[Setup]
AppId={{27307A67-6524-4A3F-A570-A1F93A476277}
AppName=SONATA
AppVersion={#AppVersion}
AppVerName=SONATA {#AppVersion} — Overture
AppPublisher=SONATA contributors
AppPublisherURL=https://github.com/blindicide/SONATA
DefaultDirName={localappdata}\Programs\SONATA
DefaultGroupName=SONATA
OutputDir=..\dist\packages
OutputBaseFilename=SONATA-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
UninstallDisplayIcon={app}\SONATA.exe
WizardStyle=classic
LicenseFile=..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Files]
Source: "..\dist\SONATA\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "portable.txt"

[Icons]
Name: "{group}\SONATA"; Filename: "{app}\SONATA.exe"
Name: "{group}\Uninstall SONATA"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\SONATA.exe"; Description: "Launch SONATA"; Flags: nowait postinstall skipifsilent
