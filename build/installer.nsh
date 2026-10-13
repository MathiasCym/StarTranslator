; NSIS provides only the background engine. All visible UI is Electron.
; Independent compressed files allow the UI to open before the application
; payload is read. Do not enable solid compression here.
SetCompressor /FINAL lzma
SetCompress auto
!define /redef APP_FILENAME "StarTranslator"
Var StarStatusFile
Var StarStatusHandle
Var StarUserDirectory
Var StarMachineDirectory
!macro StarReadLocations
  ReadRegStr $StarUserDirectory HKCU "${INSTALL_REGISTRY_KEY}" InstallLocation
  ReadRegStr $StarMachineDirectory HKLM "${INSTALL_REGISTRY_KEY}" InstallLocation
!macroend
!macro StarWriteStatus PHASE
  ; Command-line state survives UAC, which starts a fresh environment.
  ${StdUtils.GetParameter} $StarStatusFile "STAR_STATUS" ""
  ${If} $StarStatusFile == ""
    ReadEnvStr $StarStatusFile "STAR_SETUP_STATUS"
  ${EndIf}
  ${If} $StarStatusFile != ""
    FileOpen $StarStatusHandle "$StarStatusFile" w
    FileWrite $StarStatusHandle "${PHASE}"
    FileClose $StarStatusHandle
  ${EndIf}
!macroend
!macro customHeader
  !ifndef BUILD_UNINSTALLER
    !include "${BUILD_RESOURCES_DIR}\setup-runtime.nsh"
  !endif
  !include "${BUILD_RESOURCES_DIR}\install-path-hooks.nsh"
  !include "${BUILD_RESOURCES_DIR}\star-engine-hooks.nsh"
!macroend
!macro customCheckAppRunning
  ; Preserve unsaved work instead of automatically killing the app.
  ${nsProcess::FindProcess} "${APP_EXECUTABLE_FILENAME}" $R0
  ${If} $R0 == 0
    !insertmacro StarWriteStatus "error:1619"
    SetErrorLevel 1619
    Quit
  ${EndIf}
  !insertmacro StarWriteStatus "files"
!macroend
!macro customInit
  Call StarNormalizeInstallDirectory
  ${IfNot} ${Silent}
    InitPluginsDir
    SetOutPath "$PLUGINSDIR\stage"
    File /oname=StarTranslatorSetup.exe "${STAR_APP_DIR}\${APP_EXECUTABLE_FILENAME}"
    File "${STAR_APP_DIR}\*.dll"
    File "${STAR_APP_DIR}\*.pak"
    File "${STAR_APP_DIR}\*.bin"
    File "${STAR_APP_DIR}\icudtl.dat"
    File "${STAR_APP_DIR}\vk_swiftshader_icd.json"
    SetOutPath "$PLUGINSDIR\stage\locales"
    File "${STAR_APP_DIR}\locales\zh-CN.pak"
    File "${STAR_APP_DIR}\locales\en-US.pak"
    SetOutPath "$PLUGINSDIR\stage\resources"
    File "${STAR_APP_DIR}\resources\app.asar"
    File "${STAR_APP_DIR}\resources\icon.png"
    File "${STAR_APP_DIR}\resources\install-manifest.json"
    ; These files are marked unpacked in app.asar. Chromium resolves their
    ; logical archive paths to this adjacent directory, including the picker.
    SetOutPath "$PLUGINSDIR\stage\resources\app.asar.unpacked\renderer\assets"
    File /r "${STAR_APP_DIR}\resources\app.asar.unpacked\renderer\assets\*.*"
    !insertmacro StarReadLocations
    ExecWait '"$PLUGINSDIR\stage\StarTranslatorSetup.exe" --star-setup --star-worker "$EXEPATH" --star-directory "$INSTDIR" --star-locations-loaded --star-user-directory "$StarUserDirectory" --star-machine-directory "$StarMachineDirectory"' $0
    SetErrorLevel $0
    Quit
  ${Else}
    !insertmacro StarWriteStatus "checking"
    ; Stock assisted installers skip the later running check after UAC.
    ; Always check before an upgrade can launch the old uninstaller.
    !insertmacro customCheckAppRunning
  ${EndIf}
!macroend
!macro customFiles_x64
  !insertmacro StarWriteStatus "registering"
!macroend
!macro customUnInit
  ${IfNot} ${Silent}
    InitPluginsDir
    CreateDirectory "$PLUGINSDIR\stage"
    CopyFiles /SILENT "$INSTDIR\${APP_EXECUTABLE_FILENAME}" "$PLUGINSDIR\stage"
    CopyFiles /SILENT "$INSTDIR\*.dll" "$PLUGINSDIR\stage"
    CopyFiles /SILENT "$INSTDIR\*.pak" "$PLUGINSDIR\stage"
    CopyFiles /SILENT "$INSTDIR\*.bin" "$PLUGINSDIR\stage"
    CopyFiles /SILENT "$INSTDIR\icudtl.dat" "$PLUGINSDIR\stage"
    CopyFiles /SILENT "$INSTDIR\vk_swiftshader_icd.json" "$PLUGINSDIR\stage"
    CreateDirectory "$PLUGINSDIR\stage\locales"
    CopyFiles /SILENT "$INSTDIR\locales\zh-CN.pak" "$PLUGINSDIR\stage\locales"
    CopyFiles /SILENT "$INSTDIR\locales\en-US.pak" "$PLUGINSDIR\stage\locales"
    CreateDirectory "$PLUGINSDIR\stage\resources"
    CopyFiles /SILENT "$INSTDIR\resources\app.asar" "$PLUGINSDIR\stage\resources"
    CopyFiles /SILENT "$INSTDIR\resources\icon.png" "$PLUGINSDIR\stage\resources"
    CreateDirectory "$PLUGINSDIR\stage\resources\app.asar.unpacked\renderer\assets"
    CopyFiles /SILENT "$INSTDIR\resources\app.asar.unpacked\renderer\assets\*.*" "$PLUGINSDIR\stage\resources\app.asar.unpacked\renderer\assets"
    Rename "$PLUGINSDIR\stage\${APP_EXECUTABLE_FILENAME}" "$PLUGINSDIR\stage\StarTranslatorSetup.exe"
    !insertmacro StarReadLocations
    ExecWait '"$PLUGINSDIR\stage\StarTranslatorSetup.exe" --star-uninstall --star-worker "$EXEPATH" --star-directory "$INSTDIR" --star-locations-loaded --star-user-directory "$StarUserDirectory" --star-machine-directory "$StarMachineDirectory"' $0
    SetErrorLevel $0
    Quit
  ${Else}
    !insertmacro StarWriteStatus "files"
  ${EndIf}
!macroend
!macro customUnInstall
  !insertmacro StarWriteStatus "complete"
!macroend

; Preserve the old uninstaller's reason instead of collapsing every failure
; into exit code 2. These hooks also prevent stock Windows error dialogs.
!macro StarHandleUninstallResult
  ${If} ${Errors}
    !insertmacro StarWriteStatus "error:1603"
    SetErrorLevel 1603
    Quit
  ${EndIf}
  ${If} $R0 != 0
    !insertmacro StarWriteStatus "error:$R0"
    SetErrorLevel $R0
    Quit
  ${EndIf}
!macroend
!macro customUnInstallCheck
  !insertmacro StarHandleUninstallResult
!macroend
!macro customUnInstallCheckCurrentUser
  !insertmacro StarHandleUninstallResult
!macroend
