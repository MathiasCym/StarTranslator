!ifndef BUILD_UNINSTALLER
  Var StarExplicitDirectory
  !macro preInit
    ; NSIS has already parsed the full trailing /D path here, including spaces.
    ; The stock multi-user helper later reparses it as a single word.
    ${StdUtils.GetParameter} $R0 "D" ""
    ${If} $R0 != ""
      StrCpy $StarExplicitDirectory "$INSTDIR"
    ${EndIf}
  !macroend
  Function StarNormalizeInstallDirectory
    Push $R0
    Push $R1
    ; Explicit /D overrides and unrelated custom directory names are retained.
    ${If} $StarExplicitDirectory != ""
      StrCpy $INSTDIR "$StarExplicitDirectory"
    ${Else}
      ${GetFileName} "$INSTDIR" $R0
      ${If} $R0 == "NovaTerm Checker"
      ${OrIf} $R0 == "novaterm-checker"
      ${OrIf} $R0 == "星译官"
        ${GetParent} "$INSTDIR" $R1
        StrCpy $INSTDIR "$R1\StarTranslator"
      ${EndIf}
    ${EndIf}
    Pop $R1
    Pop $R0
  FunctionEnd

  ; The silent all-users branch resets INSTDIR inside the install section.
  ; Wrap that late call as well, after the stock UI functions are compiled.
  Function StarSetInstallModePerAllUsers
    !insertmacro setInstallModePerAllUsers
    Call StarNormalizeInstallDirectory
  FunctionEnd
  !macroundef setInstallModePerAllUsers
  !macro setInstallModePerAllUsers
    Call StarSetInstallModePerAllUsers
  !macroend

  ; 升级时 electron-builder 会"保留"旧快捷方式（重命名而非重建），所以安装包
  ; 里改过的 APP_DESCRIPTION 不会刷新到快捷方式上——鼠标悬停就还显示老标语。
  ; customInstall 在 addDesktopLink / addStartMenuLink 之后运行，此时两个
  ; $new*Link 变量已由 setLinkVars 填好，可直接按当前描述重建快捷方式。
  !macro customInstall
    !ifndef DO_NOT_CREATE_DESKTOP_SHORTCUT
    ${If} ${FileExists} "$newDesktopLink"
      Delete "$newDesktopLink"
    ${EndIf}
    CreateShortCut "$newDesktopLink" "$appExe" "" "$appExe" 0 "" "" "${APP_DESCRIPTION}"
    ClearErrors
    WinShell::SetLnkAUMI "$newDesktopLink" "${APP_ID}"
    !endif

    !ifndef DO_NOT_CREATE_START_MENU_SHORTCUT
    ${If} ${FileExists} "$newStartMenuLink"
      Delete "$newStartMenuLink"
    ${EndIf}
    CreateShortCut "$newStartMenuLink" "$appExe" "" "$appExe" 0 "" "" "${APP_DESCRIPTION}"
    ClearErrors
    WinShell::SetLnkAUMI "$newStartMenuLink" "${APP_ID}"
    !endif

    System::Call 'Shell32::SHChangeNotify(i 0x8000000, i 0, i 0, i 0)'
    !insertmacro StarWriteStatus "complete"
  !macroend
!endif
