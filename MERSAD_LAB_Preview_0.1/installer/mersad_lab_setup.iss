; Inno Setup Script for MERSAD LAB 1.0 — PREVIEW 0.1 (Windows 10/11 x64)
[Setup]
AppId={{D4A97E2A-8C1F-4B9E-A510-7C09E8110101}
AppName=MERSAD LAB — PREVIEW 0.1
AppVersion=0.1.0
AppPublisher=MERSAD AI Engineering Team
DefaultDirName={autopf}\MERSAD_PREVIEW_0.1\MERSAD_LAB
DefaultGroupName=MERSAD PREVIEW 0.1
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=MERSAD_LAB_Setup_x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\MERSAD_LAB\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\RUN_LAB.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README_AR.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\PHASE1_STATUS_AR.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\MERSAD LAB Preview 0.1"; Filename: "{app}\RUN_LAB.bat"; WorkingDir: "{app}"
Name: "{autodesktop}\MERSAD LAB Preview 0.1"; Filename: "{app}\RUN_LAB.bat"; WorkingDir: "{app}"

[Run]
Filename: "{app}\MERSAD_LAB.exe"; Parameters: "--port 0 --self-check"; StatusMsg: "Verifying MERSAD LAB installation..."; Flags: runhidden waituntilterminated
