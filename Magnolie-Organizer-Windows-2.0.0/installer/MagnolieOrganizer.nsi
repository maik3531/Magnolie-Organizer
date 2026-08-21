Unicode true
!define ROOT "${__FILEDIR__}/.."

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "WinMessages.nsh"
!include "nsDialogs.nsh"
!include "FileFunc.nsh"

!define PRODUCT_NAME "Magnolie Organizer"
!ifndef PRODUCT_VERSION
  !error "PRODUCT_VERSION muss vom Buildsystem gesetzt werden."
!endif
!ifndef OUTPUT_FILE
  !error "OUTPUT_FILE muss auf eine Staging-Datei zeigen."
!endif
!ifndef INSTALLER_FILENAME
  !error "INSTALLER_FILENAME muss vom Buildsystem gesetzt werden."
!endif
!ifndef PUBLISH_DIR
  !error "PUBLISH_DIR muss auf die geprüfte Staging-Ausgabe zeigen."
!endif
!ifndef CORE_MANIFEST
  !error "CORE_MANIFEST muss auf die erzeugte Core-Besitzliste zeigen."
!endif
!ifndef HANDBOOK_MANIFEST
  !error "HANDBOOK_MANIFEST muss auf die erzeugte Handbuch-Besitzliste zeigen."
!endif
!define PRODUCT_PUBLISHER "Magnolie"
!define PRODUCT_EXE "Magnolie Organizer.exe"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\Magnolie Organizer"
!define PRODUCT_MARKER_ID "MagnolieOrganizer.Windows.v1"
!define LEGACY_PRODUCT_MARKER "2.0.0"

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "${OUTPUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\Magnolie Organizer"
InstallDirRegKey HKCU "Software\Magnolie Organizer" "InstallLocation"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
CRCCheck on
ManifestSupportedOS Win10
BrandingText "Magnolie Organizer für Windows"
Icon "${ROOT}/app/magnolie-organizer.ico"
UninstallIcon "${ROOT}/app/magnolie-organizer.ico"

VIProductVersion "${PRODUCT_VERSION}.0"
VIAddVersionKey /LANG=1031 "ProductName" "Magnolie Organizer"
VIAddVersionKey /LANG=1031 "ProductVersion" "${PRODUCT_VERSION}"
VIAddVersionKey /LANG=1031 "FileVersion" "${PRODUCT_VERSION}.0"
VIAddVersionKey /LANG=1031 "CompanyName" "Magnolie"
VIAddVersionKey /LANG=1031 "FileDescription" "Installation von Magnolie Organizer"
VIAddVersionKey /LANG=1031 "LegalCopyright" "Magnolie"
VIAddVersionKey /LANG=1031 "OriginalFilename" "${INSTALLER_FILENAME}"

!define MUI_ICON "${ROOT}/app/magnolie-organizer.ico"
!define MUI_UNICON "${ROOT}/app/magnolie-organizer.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEFINISHPAGE_BITMAP "${ROOT}/installer/welcome.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "${ROOT}/installer/welcome.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT
!define MUI_HEADERIMAGE_BITMAP "${ROOT}/installer/header.bmp"
!define MUI_HEADERIMAGE_UNBITMAP "${ROOT}/installer/header.bmp"
!define MUI_WELCOMEPAGE_TITLE "Willkommen bei Magnolie Organizer"
!define MUI_WELCOMEPAGE_TEXT "Dieser Assistent installiert Magnolie Organizer für Ihr Windows-Benutzerkonto.$\r$\n$\r$\nKalender, Aufgaben, Adressen, Notizen und Gesundheitsdaten bleiben lokal auf Ihrem Computer.$\r$\n$\r$\nKlicken Sie auf Weiter, um die Installation zu beginnen."
!define MUI_FINISHPAGE_TITLE "Magnolie Organizer ist bereit"
!define MUI_FINISHPAGE_TEXT "Die Installation wurde erfolgreich abgeschlossen. Im Startmenü finden Sie Magnolie Organizer und optional das Benutzerhandbuch."
!define MUI_FINISHPAGE_RUN "$INSTDIR\${PRODUCT_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Magnolie Organizer jetzt starten"
!define MUI_FINISHPAGE_LINK "Mehr über Magnolie Organizer"
!define MUI_FINISHPAGE_LINK_LOCATION "https://gitlab.com/maik3531/mint-forgs"

Var StartMenuFolder
Var UninstallDeleteData
Var UninstallDeleteDataCheckbox
Var UninstallCleanupFailed
Var UninstallMarkerValid
Var BackupDir
Var ManifestPath
Var PreviousInstall
Var PreviousCoreManifest
Var PreviousHandbookManifest
Var TransactionActive

!insertmacro MUI_PAGE_WELCOME
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE DirectoryLeave
!insertmacro MUI_PAGE_DIRECTORY
!define MUI_STARTMENUPAGE_DEFAULTFOLDER "Magnolie Organizer"
!define MUI_STARTMENUPAGE_REGISTRY_ROOT "HKCU"
!define MUI_STARTMENUPAGE_REGISTRY_KEY "Software\Magnolie Organizer"
!define MUI_STARTMENUPAGE_REGISTRY_VALUENAME "StartMenuFolder"
!insertmacro MUI_PAGE_STARTMENU Application $StartMenuFolder
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
UninstPage custom un.DataPage un.DataLeave
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "German"

Function DirectoryLeave
  ${If} $INSTDIR == "$LOCALAPPDATA\Magnolie Organizer"
    MessageBox MB_ICONSTOP|MB_OK "Dieser Ordner ist für Ihre persönlichen Organizer-Daten reserviert.$\r$\n$\r$\nBitte verwenden Sie den vorgeschlagenen Programmordner unter $LOCALAPPDATA\Programs."
    Abort
  ${EndIf}
  IfFileExists "$INSTDIR\.magnolie-installer" 0 check_empty
    FileOpen $0 "$INSTDIR\.magnolie-installer" r
    FileRead $0 $1
    FileClose $0
    ${If} $1 == "${PRODUCT_MARKER_ID}"
      Goto marker_ok
    ${EndIf}
    ${If} $1 == "${LEGACY_PRODUCT_MARKER}"
      Goto marker_ok
    ${EndIf}
  check_empty:
  IfFileExists "$INSTDIR\*.*" 0 marker_ok
    MessageBox MB_ICONSTOP|MB_OK "Der gewählte Ordner enthält bereits fremde Dateien.$\r$\n$\r$\nWählen Sie einen neuen oder leeren Ordner für Magnolie Organizer."
    Abort
  marker_ok:
FunctionEnd

Function CloseRunningApplication
  check:
  FindWindow $0 "" "Magnolie Organizer"
  ${If} $0 != 0
    MessageBox MB_ICONEXCLAMATION|MB_RETRYCANCEL "Magnolie Organizer läuft noch. Speichern und schließen Sie die Anwendung, bevor Sie fortfahren." IDRETRY check IDCANCEL cancel
  ${EndIf}
  Goto done
  cancel:
    Abort
  done:
FunctionEnd

Function CleanManagedInstall
  StrCpy $PreviousInstall 0
  IfFileExists "$INSTDIR\.magnolie-installer" 0 fresh
  FileOpen $0 "$INSTDIR\.magnolie-installer" r
  FileRead $0 $1
  FileClose $0
  ${If} $1 != "${PRODUCT_MARKER_ID}"
  ${AndIf} $1 != "${LEGACY_PRODUCT_MARKER}"
    MessageBox MB_ICONSTOP|MB_OK "Der vorhandene Programmordner trägt keine gültige Magnolie-Kennung und wird nicht überschrieben."
    Abort
  ${EndIf}
  ; Nach einer vollständigen Deinstallation darf der Marker unbekannte Reste
  ; für eine sichere Wiederinstallation kennzeichnen, ohne eine Altversion vorzutäuschen.
  IfFileExists "$INSTDIR\.magnolie-core.manifest" 0 fresh
  StrCpy $PreviousInstall 1
  fresh:
FunctionEnd

Function TrimManifestLine
  trim:
    StrCpy $3 $2 1 -1
    StrCmp $3 "$\r" remove
    StrCmp $3 "$\n" remove done
  remove:
    StrCpy $2 $2 -1
    Goto trim
  done:
FunctionEnd

Function BackupManagedManifest
  IfFileExists "$ManifestPath" 0 done
  FileOpen $0 "$ManifestPath" r
  loop:
    ClearErrors
    FileReadUTF16LE $0 $2
    IfErrors close
    Call TrimManifestLine
    StrCpy $3 $2 2
    StrCmp $3 "F|" 0 loop
    StrCpy $3 $2 "" 2
    StrCmp $3 ".magnolie-core.manifest" loop
    StrCmp $3 ".magnolie-handbook.manifest" loop
    StrCmp $3 ".magnolie-installer" loop
    StrCmp $3 "Magnolie Organizer deinstallieren.exe" loop
    IfFileExists "$INSTDIR\$3" 0 loop
    ${GetParent} "$BackupDir\$3" $4
    CreateDirectory "$4"
    ClearErrors
    CopyFiles /SILENT "$INSTDIR\$3" "$4"
    IfErrors failed
    Goto loop
  failed:
    FileClose $0
    SetErrors
    Return
  close:
    FileClose $0
  done:
    ClearErrors
FunctionEnd

Function DeleteManagedManifest
  IfFileExists "$ManifestPath" 0 done
  FileOpen $0 "$ManifestPath" r
  loop:
    ClearErrors
    FileReadUTF16LE $0 $2
    IfErrors close
    Call TrimManifestLine
    StrCpy $3 $2 2
    StrCpy $4 $2 "" 2
    StrCmp $3 "F|" 0 +6
      IfFileExists "$INSTDIR\$4" 0 loop
      ClearErrors
      Delete "$INSTDIR\$4"
      IfErrors failed
      Goto loop
    StrCmp $3 "D|" 0 loop
      RMDir "$INSTDIR\$4"
      Goto loop
  close:
    FileClose $0
    ClearErrors
    Return
  failed:
    FileClose $0
    SetErrors
    Return
  done:
    ClearErrors
FunctionEnd

Function RestoreManagedManifest
  IfFileExists "$ManifestPath" 0 done
  FileOpen $0 "$ManifestPath" r
  loop:
    ClearErrors
    FileReadUTF16LE $0 $2
    IfErrors close
    Call TrimManifestLine
    StrCpy $3 $2 2
    StrCmp $3 "F|" 0 loop
    StrCpy $3 $2 "" 2
    IfFileExists "$BackupDir\$3" 0 loop
    ${GetParent} "$INSTDIR\$3" $4
    CreateDirectory "$4"
    CopyFiles /SILENT "$BackupDir\$3" "$4"
    Goto loop
  close:
    FileClose $0
  done:
FunctionEnd

Function PrepareManagedUpgrade
  Call CleanManagedInstall
  GetTempFileName $BackupDir
  Delete "$BackupDir"
  CreateDirectory "$BackupDir"
  IfFileExists "$INSTDIR\.magnolie-installer" 0 marker_ready
    ClearErrors
    CopyFiles /SILENT "$INSTDIR\.magnolie-installer" "$BackupDir"
    IfErrors backup_failed
  marker_ready:
  StrCpy $PreviousCoreManifest 0
  StrCpy $PreviousHandbookManifest 0
  ${If} $PreviousInstall == 1
    IfFileExists "$INSTDIR\.magnolie-core.manifest" 0 legacy_core
      StrCpy $PreviousCoreManifest 1
      ClearErrors
      CopyFiles /SILENT "$INSTDIR\.magnolie-core.manifest" "$BackupDir"
      Rename "$BackupDir\.magnolie-core.manifest" "$BackupDir\previous-core.manifest"
      IfErrors backup_failed
      Goto core_ready
    legacy_core:
      ClearErrors
      CopyFiles /SILENT "$PLUGINSDIR\magnolie-core.manifest" "$BackupDir"
      Rename "$BackupDir\magnolie-core.manifest" "$BackupDir\previous-core.manifest"
      IfErrors backup_failed
    core_ready:
    IfFileExists "$INSTDIR\.magnolie-handbook.manifest" 0 legacy_handbook
      StrCpy $PreviousHandbookManifest 1
      ClearErrors
      CopyFiles /SILENT "$INSTDIR\.magnolie-handbook.manifest" "$BackupDir"
      Rename "$BackupDir\.magnolie-handbook.manifest" "$BackupDir\previous-handbook.manifest"
      IfErrors backup_failed
      Goto handbook_ready
    legacy_handbook:
      IfFileExists "$INSTDIR\handbuch\*.*" 0 handbook_ready
      ClearErrors
      CopyFiles /SILENT "$PLUGINSDIR\magnolie-handbook.manifest" "$BackupDir"
      Rename "$BackupDir\magnolie-handbook.manifest" "$BackupDir\previous-handbook.manifest"
      IfErrors backup_failed
    handbook_ready:
    StrCpy $ManifestPath "$BackupDir\previous-core.manifest"
    Call BackupManagedManifest
    IfErrors backup_failed
    StrCpy $ManifestPath "$BackupDir\previous-handbook.manifest"
    Call BackupManagedManifest
    IfErrors backup_failed
    IfFileExists "$BackupDir\Magnolie Organizer deinstallieren.exe" uninstaller_backed_up
      ClearErrors
      CopyFiles /SILENT "$INSTDIR\Magnolie Organizer deinstallieren.exe" "$BackupDir"
      IfErrors backup_failed
    uninstaller_backed_up:
    StrCpy $TransactionActive 1
    StrCpy $ManifestPath "$BackupDir\previous-core.manifest"
    Call DeleteManagedManifest
    IfErrors cleanup_failed
    StrCpy $ManifestPath "$BackupDir\previous-handbook.manifest"
    Call DeleteManagedManifest
    IfErrors cleanup_failed
    Delete "$INSTDIR\.magnolie-core.manifest"
    Delete "$INSTDIR\.magnolie-handbook.manifest"
    Delete "$INSTDIR\.magnolie-installer"
    Delete "$INSTDIR\Magnolie Organizer deinstallieren.exe"
  ${EndIf}
  StrCpy $TransactionActive 1
  Return
  backup_failed:
    RMDir /r "$BackupDir"
    MessageBox MB_ICONSTOP|MB_OK "Die vorhandene Installation konnte nicht vollständig gesichert werden. Sie wurde nicht verändert."
    Abort
  cleanup_failed:
    Call RollbackManagedUpgrade
    MessageBox MB_ICONSTOP|MB_OK "Eine vorhandene Programmdatei konnte nicht ersetzt werden.$\r$\n$\r$\nBitte schließen Sie Magnolie Organizer und das Benutzerhandbuch vollständig und starten Sie die Installation erneut. Die vorige Installation wurde wiederhergestellt."
    Abort
FunctionEnd

Function RollbackManagedUpgrade
  ${If} $TransactionActive != 1
    Return
  ${EndIf}
  StrCpy $ManifestPath "$PLUGINSDIR\magnolie-handbook.manifest"
  Call DeleteManagedManifest
  StrCpy $ManifestPath "$PLUGINSDIR\magnolie-core.manifest"
  Call DeleteManagedManifest
  Delete "$INSTDIR\.magnolie-core.manifest"
  Delete "$INSTDIR\.magnolie-handbook.manifest"
  Delete "$INSTDIR\.magnolie-installer"
  Delete "$INSTDIR\Magnolie Organizer deinstallieren.exe"
  ${If} $PreviousInstall == 1
    StrCpy $ManifestPath "$BackupDir\previous-core.manifest"
    Call RestoreManagedManifest
    StrCpy $ManifestPath "$BackupDir\previous-handbook.manifest"
    Call RestoreManagedManifest
    ${If} $PreviousCoreManifest == 1
      CopyFiles /SILENT "$BackupDir\previous-core.manifest" "$INSTDIR"
      Rename "$INSTDIR\previous-core.manifest" "$INSTDIR\.magnolie-core.manifest"
    ${EndIf}
    ${If} $PreviousHandbookManifest == 1
      CopyFiles /SILENT "$BackupDir\previous-handbook.manifest" "$INSTDIR"
      Rename "$INSTDIR\previous-handbook.manifest" "$INSTDIR\.magnolie-handbook.manifest"
    ${EndIf}
    CopyFiles /SILENT "$BackupDir\Magnolie Organizer deinstallieren.exe" "$INSTDIR"
  ${EndIf}
  IfFileExists "$BackupDir\.magnolie-installer" 0 marker_restored
    CopyFiles /SILENT "$BackupDir\.magnolie-installer" "$INSTDIR"
  marker_restored:
  RMDir /r "$BackupDir"
  StrCpy $TransactionActive 0
FunctionEnd

Function InstallFailed
  Call RollbackManagedUpgrade
  MessageBox MB_ICONSTOP|MB_OK "Die Installation ist fehlgeschlagen. Die vorige gültige Installation wurde wiederhergestellt."
  Abort
FunctionEnd

Section "Magnolie Organizer (erforderlich)" SEC_MAIN
  SectionIn RO
  Call CloseRunningApplication
  SetShellVarContext current
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  ClearErrors
  File /oname=magnolie-core.manifest "${CORE_MANIFEST}"
  File /oname=magnolie-handbook.manifest "${HANDBOOK_MANIFEST}"
  IfErrors manifest_extract_failed
  Call PrepareManagedUpgrade
  SetOutPath "$INSTDIR"
  ClearErrors
  File /r /x "*.pdb" /x "handbuch" "${PUBLISH_DIR}/*.*"
  IfErrors install_failed
  CopyFiles /SILENT "$PLUGINSDIR\magnolie-core.manifest" "$INSTDIR"
  Rename "$INSTDIR\magnolie-core.manifest" "$INSTDIR\.magnolie-core.manifest"
  IfErrors install_failed

  WriteRegStr HKCU "Software\Magnolie Organizer" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "Magnolie Organizer"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\${PRODUCT_EXE},0"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" "$\"$INSTDIR\Magnolie Organizer deinstallieren.exe$\""
  WriteRegStr HKCU "${UNINSTALL_KEY}" "QuietUninstallString" "$\"$INSTDIR\Magnolie Organizer deinstallieren.exe$\" /S"
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "EstimatedSize" 226900

  !insertmacro MUI_STARTMENU_WRITE_BEGIN Application
    CreateDirectory "$SMPROGRAMS\$StartMenuFolder"
    Delete "$SMPROGRAMS\$StartMenuFolder\Magnolie Organizer Benutzerhandbuch.lnk"
    Delete "$SMPROGRAMS\$StartMenuFolder\Magnolie Organizer deinstallieren.lnk"
    CreateShortcut "$SMPROGRAMS\$StartMenuFolder\Magnolie Organizer.lnk" "$INSTDIR\${PRODUCT_EXE}" "" "$INSTDIR\${PRODUCT_EXE}" 0
  !insertmacro MUI_STARTMENU_WRITE_END
  Goto main_done
  manifest_extract_failed:
    MessageBox MB_ICONSTOP|MB_OK "Die eingebettete Besitzliste konnte nicht entpackt werden. Die vorhandene Installation wurde nicht verändert."
    Abort
  install_failed:
    Call InstallFailed
  main_done:
SectionEnd

Section "Benutzerhandbuch" SEC_HANDBUCH
  SetShellVarContext current
  SetOutPath "$INSTDIR\handbuch"
  ClearErrors
  File /r "${PUBLISH_DIR}/handbuch/*.*"
  IfErrors handbook_failed
  SetOutPath "$INSTDIR"
  CopyFiles /SILENT "$PLUGINSDIR\magnolie-handbook.manifest" "$INSTDIR"
  Rename "$INSTDIR\magnolie-handbook.manifest" "$INSTDIR\.magnolie-handbook.manifest"
  IfErrors handbook_failed
  !insertmacro MUI_STARTMENU_WRITE_BEGIN Application
    CreateShortcut "$SMPROGRAMS\$StartMenuFolder\Magnolie Organizer Benutzerhandbuch.lnk" "$INSTDIR\${PRODUCT_EXE}" "--handbook" "$INSTDIR\${PRODUCT_EXE}" 0
  !insertmacro MUI_STARTMENU_WRITE_END
  Goto handbook_done
  handbook_failed:
    Call InstallFailed
  handbook_done:
SectionEnd

Section /o "Verknüpfung auf dem Desktop" SEC_DESKTOP
  SetShellVarContext current
  CreateShortcut "$DESKTOP\Magnolie Organizer.lnk" "$INSTDIR\${PRODUCT_EXE}" "" "$INSTDIR\${PRODUCT_EXE}" 0
SectionEnd

Section -Commit
  ClearErrors
  WriteUninstaller "$INSTDIR\Magnolie Organizer deinstallieren.exe"
  IfErrors commit_failed
  FileOpen $0 "$INSTDIR\.magnolie-installer" w
  IfErrors commit_failed
  FileWrite $0 "${PRODUCT_MARKER_ID}"
  IfErrors commit_close_failed
  FileClose $0
  RMDir /r "$BackupDir"
  StrCpy $TransactionActive 0
  Goto commit_done
  commit_close_failed:
    FileClose $0
  commit_failed:
    Call InstallFailed
  commit_done:
SectionEnd

LangString DESC_SEC_MAIN ${LANG_GERMAN} "Installiert die selbstenthaltende 64-Bit-Anwendung und legt die Einträge im Windows-Startmenü an."
LangString DESC_SEC_HANDBUCH ${LANG_GERMAN} "Installiert das Windows-Benutzerhandbuch und legt dafür einen Eintrag im Startmenü an."
LangString DESC_SEC_DESKTOP ${LANG_GERMAN} "Legt zusätzlich eine Verknüpfung auf Ihrem Desktop an."
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_MAIN} $(DESC_SEC_MAIN)
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_HANDBUCH} $(DESC_SEC_HANDBUCH)
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_DESKTOP} $(DESC_SEC_DESKTOP)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function un.CloseRunningApplication
  FindWindow $0 "" "Magnolie Organizer"
  ${If} $0 != 0
    MessageBox MB_ICONEXCLAMATION|MB_OK "Bitte schließen Sie Magnolie Organizer vor der Deinstallation."
    Abort
  ${EndIf}
FunctionEnd

Function un.DataPage
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ${NSD_CreateLabel} 0 0 100% 34u "Programmdateien und Verknüpfungen werden vollständig entfernt. Ihre Organizer-Daten bleiben standardmäßig erhalten."
  Pop $0
  ${NSD_CreateCheckbox} 0 48u 100% 20u "Auch lokale Benutzerdaten und Einstellungen löschen"
  Pop $UninstallDeleteDataCheckbox
  ${NSD_CreateLabel} 16u 72u 94% 36u "Betrifft: $LOCALAPPDATA\Magnolie Organizer. Sicherungen im Dokumente-Ordner werden nicht gelöscht."
  Pop $0
  nsDialogs::Show
FunctionEnd

Function un.DataLeave
  ${NSD_GetState} $UninstallDeleteDataCheckbox $UninstallDeleteData
FunctionEnd

Function un.TrimManifestLine
  trim:
    StrCpy $3 $2 1 -1
    StrCmp $3 "$\r" remove
    StrCmp $3 "$\n" remove done
  remove:
    StrCpy $2 $2 -1
    Goto trim
  done:
FunctionEnd

Function un.DeleteManagedManifest
  IfFileExists "$ManifestPath" 0 done
  ClearErrors
  FileOpen $0 "$ManifestPath" r
  IfErrors failed
  loop:
    ClearErrors
    FileReadUTF16LE $0 $2
    IfErrors close
    Call un.TrimManifestLine
    StrCpy $3 $2 2
    StrCpy $4 $2 "" 2
    StrCmp $3 "F|" un_manifest_file
    StrCmp $3 "D|" 0 loop
      RMDir "$INSTDIR\$4"
      Goto loop
    un_manifest_file:
      StrCmp $4 ".magnolie-core.manifest" loop
      StrCmp $4 ".magnolie-handbook.manifest" loop
      StrCmp $4 ".magnolie-installer" loop
      StrCmp $4 "Magnolie Organizer deinstallieren.exe" loop
      ClearErrors
      Delete "$INSTDIR\$4"
      IfErrors 0 loop
      StrCpy $UninstallCleanupFailed 1
      Goto loop
  close:
    FileClose $0
    Goto done
  failed:
    StrCpy $UninstallCleanupFailed 1
  done:
FunctionEnd

Section "Uninstall"
  Call un.CloseRunningApplication
  SetShellVarContext current
  ReadRegStr $StartMenuFolder HKCU "Software\Magnolie Organizer" "StartMenuFolder"
  ${If} $StartMenuFolder == ""
    StrCpy $StartMenuFolder "Magnolie Organizer"
  ${EndIf}
  IfFileExists "$INSTDIR\.magnolie-installer" 0 no_product_marker
    FileOpen $0 "$INSTDIR\.magnolie-installer" r
    FileRead $0 $1
    FileClose $0
    StrCpy $UninstallMarkerValid 0
    ${If} $1 == "${PRODUCT_MARKER_ID}"
      StrCpy $UninstallMarkerValid 1
    ${ElseIf} $1 == "${LEGACY_PRODUCT_MARKER}"
      StrCpy $UninstallMarkerValid 1
    ${EndIf}
    ${If} $UninstallMarkerValid == 1
    ${AndIf} ${FileExists} "$INSTDIR\.magnolie-core.manifest"
      StrCpy $UninstallCleanupFailed 0
      StrCpy $ManifestPath "$INSTDIR\.magnolie-handbook.manifest"
      Call un.DeleteManagedManifest
      StrCpy $ManifestPath "$INSTDIR\.magnolie-core.manifest"
      Call un.DeleteManagedManifest
      ${If} $UninstallCleanupFailed == 1
        SetErrorLevel 1
        MessageBox MB_ICONSTOP|MB_OK "Mindestens eine Programmdatei konnte nicht gelöscht werden.$\r$\n$\r$\nBitte schließen Sie Magnolie Organizer und das Benutzerhandbuch vollständig und starten Sie die Deinstallation erneut. Die Besitzlisten bleiben für den nächsten Versuch erhalten."
        Goto uninstall_done
      ${EndIf}
      Delete "$INSTDIR\.magnolie-handbook.manifest"
      Delete "$INSTDIR\.magnolie-core.manifest"
      Delete "$INSTDIR\.magnolie-installer"
      Delete "$INSTDIR\Magnolie Organizer deinstallieren.exe"
      RMDir "$INSTDIR\handbuch"
      ClearErrors
      RMDir "$INSTDIR"
      IfErrors 0 product_removed
        FileOpen $0 "$INSTDIR\.magnolie-installer" w
        FileWrite $0 "${PRODUCT_MARKER_ID}"
        FileClose $0
      Goto product_removed
    ${EndIf}
  no_product_marker:
    SetErrorLevel 1
    MessageBox MB_ICONEXCLAMATION|MB_OK "Verwaltete Programmdateien wurden nicht gelöscht, weil Marker oder Besitzliste fehlen beziehungsweise ungültig sind. Unbekannte Ordnerinhalte bleiben geschützt."
    Goto uninstall_done
  product_removed:
  Delete "$DESKTOP\Magnolie Organizer.lnk"
  Delete "$SMPROGRAMS\$StartMenuFolder\Magnolie Organizer.lnk"
  Delete "$SMPROGRAMS\$StartMenuFolder\Magnolie Organizer Benutzerhandbuch.lnk"
  Delete "$SMPROGRAMS\$StartMenuFolder\Magnolie Organizer deinstallieren.lnk"
  RMDir "$SMPROGRAMS\$StartMenuFolder"
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
  DeleteRegKey HKCU "Software\Magnolie Organizer"
  ${If} $UninstallDeleteData == ${BST_CHECKED}
    RMDir /r "$LOCALAPPDATA\Magnolie Organizer"
  ${EndIf}
  uninstall_done:
SectionEnd
