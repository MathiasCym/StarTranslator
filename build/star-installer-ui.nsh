; Custom brand pages over electron-builder's existing installation engine.
!include nsDialogs.nsh
!include WinMessages.nsh
!define MUI_BGCOLOR "102238"
!define MUI_TEXTCOLOR "E5F2FF"
!define MUI_INSTFILESPAGE_COLORS "E5F2FF 102238"
!define MUI_CUSTOMFUNCTION_GUIINIT StarGUIInit
!ifdef BUILD_UNINSTALLER
  !define MUI_CUSTOMFUNCTION_UNGUIINIT un.StarGUIInit
!endif

!define /ifndef MUI_ICON "${BUILD_RESOURCES_DIR}\icon.ico"
!define /ifndef MUI_UNICON "${BUILD_RESOURCES_DIR}\icon.ico"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT
!define MUI_HEADERIMAGE_BITMAP "${BUILD_RESOURCES_DIR}\installer-header.bmp"
!define MUI_HEADERIMAGE_UNBITMAP "${BUILD_RESOURCES_DIR}\installer-header.bmp"
!define MUI_PAGE_HEADER_TEXT "星译官 · 文档工作台"
!define MUI_PAGE_HEADER_SUBTEXT "中英技术文档翻译与审校"
Var StarPage
Var StarControl
Var StarImage
Var StarImageHandle
!ifndef BUILD_UNINSTALLER
Var StarDirectoryInput
Var StarDirectoryError
Var StarLaunch
!endif

!macro StarFunctions PREFIX
  Function ${PREFIX}StarThemeTree
    Exch $0
    Push $1
    Push $2
    System::Call 'uxtheme::SetWindowTheme(p r0, w "", w "")'
    SetCtlColors $0 E5F2FF 102238
    System::Call 'user32::GetClassName(p r0, t .r2, i ${NSIS_MAX_STRLEN})'
    ${If} $2 == "Button"
      SetCtlColors $0 102238 38BDF8
    ${EndIf}
    ${If} $2 == "msctls_progress32"
      SendMessage $0 0x409 0 0x00E8D522
      SendMessage $0 0x2001 0 0x00382210
    ${EndIf}
    System::Call 'user32::GetWindow(p r0, i 5)p.r1'
    ${DoWhile} $1 != 0
      Push $1
      Call ${PREFIX}StarThemeTree
      System::Call 'user32::GetWindow(p r1, i 2)p.r1'
    ${Loop}
    Pop $2
    Pop $1
    Pop $0
  FunctionEnd

  Function ${PREFIX}StarGUIInit
    ; Remove the stock Windows title frame; brand header and footer remain.
    System::Call 'user32::GetWindowLong(p $HWNDPARENT, i -16)i.r0'
    IntOp $0 $0 & 0xFF3FFFFF
    System::Call 'user32::SetWindowLong(p $HWNDPARENT, i -16, i r0)'
    System::Call 'user32::SetWindowPos(p $HWNDPARENT, p 0, i 0, i 0, i 0, i 0, i 0x27)'
    Push $HWNDPARENT
    Call ${PREFIX}StarThemeTree
    GetDlgItem $0 $HWNDPARENT 1028
    SetCtlColors $0 75CAE9 102238
    SendMessage $0 ${WM_SETTEXT} 0 "STR:MathiasCym · StarTranslator"
    Call ${PREFIX}StarModeShow
  FunctionEnd

  Function ${PREFIX}StarModeShow
    Push $HWNDPARENT
    Call ${PREFIX}StarThemeTree
    !insertmacro MUI_HEADER_TEXT "星译官 · 安装范围" "选择需要使用星译官的 Windows 用户"
  FunctionEnd
!macroend


!macro StarHero PREFIX IMAGE TITLE TEXT
  nsDialogs::Create 1018
  Pop $StarPage
  SetCtlColors $StarPage E5F2FF 102238
  ${NSD_CreateBitmap} 0u 5u 112u 112u ""
  Pop $StarImage
  InitPluginsDir
  File /oname=$PLUGINSDIR\star-hero.bmp "${BUILD_RESOURCES_DIR}\${IMAGE}"
  ${NSD_SetImage} $StarImage "$PLUGINSDIR\star-hero.bmp" $StarImageHandle
  ${NSD_CreateLabel} 126u 10u 174u 30u "${TITLE}"
  Pop $StarControl
  CreateFont $0 "Microsoft YaHei UI" 17 700
  SendMessage $StarControl ${WM_SETFONT} $0 1
  SetCtlColors $StarControl 38D7F8 102238
  ${NSD_CreateLabel} 126u 48u 174u 76u "${TEXT}"
  Pop $StarControl
  SetCtlColors $StarControl E5F2FF 102238
  Push $HWNDPARENT
  Call ${PREFIX}StarThemeTree
!macroend

!ifndef BUILD_UNINSTALLER
!macro customWelcomePage
  Page custom StarWelcome
  !define MUI_PAGE_CUSTOMFUNCTION_SHOW StarModeShow
!macroend






!macro customFinishPage
  Page custom StarFinish StarFinishLeave
!macroend



!endif

!macro customUnWelcomePage
  UninstPage custom un.StarWelcome
  !define MUI_PAGE_CUSTOMFUNCTION_SHOW un.StarModeShow
!macroend


!macro StarPageFunctions
  !ifndef BUILD_UNINSTALLER
Function StarWelcome
  !insertmacro MUI_HEADER_TEXT "星译官 · 欢迎" "为中英技术文档带来更准确的表达"
  !insertmacro StarHero "" "installer-hero.bmp" "让每一个术语$\r$\n准确抵达" "欢迎安装星译官 v${VERSION}。$\r$\n$\r$\n文档翻译 · 术语校验$\r$\n中英对照 · 模型复核$\r$\n$\r$\n发布者 MathiasCym"
  nsDialogs::Show
  ${NSD_FreeImage} $StarImageHandle
FunctionEnd
Function StarDirectoryPage
  Call StarNormalizeInstallDirectory
  !insertmacro MUI_HEADER_TEXT "星译官 · 安装位置" "确认安装路径，准备开启文档工作台"
  nsDialogs::Create 1018
  Pop $StarPage
  ${NSD_CreateLabel} 0u 6u 300u 24u "程序将安装到以下文件夹"
  Pop $StarControl
  ${NSD_CreateText} 0u 35u 300u 20u "$INSTDIR"
  Pop $StarDirectoryInput
  ${NSD_CreateLabel} 0u 70u 300u 34u "可直接修改完整路径。建议使用英文目录名。$\r$\n升级安装将保留模型配置与本机术语库。"
  Pop $StarControl
  ${NSD_CreateLabel} 0u 114u 300u 30u ""
  Pop $StarDirectoryError
  Push $HWNDPARENT
  Call StarThemeTree
  nsDialogs::Show
FunctionEnd
Function StarDirectoryLeave
  ${NSD_GetText} $StarDirectoryInput $0
  ${GetRoot} "$0" $1
  ${If} $1 == ""
    ${NSD_SetText} $StarDirectoryError "请输入完整路径，例如 D:\Apps\StarTranslator。"
    Abort
  ${EndIf}
  ; Never allow an install to target the drive root itself.
  ${GetFileName} "$0" $1
  ${If} $1 == ""
    ${NSD_SetText} $StarDirectoryError "请指定程序文件夹，不要使用磁盘根目录。"
    Abort
  ${EndIf}
  StrCpy $INSTDIR $0
FunctionEnd
Function StarProgressShow
  !insertmacro MUI_HEADER_TEXT "星译官 · 正在安装" "正在准备你的文档工作台，请稍候"
  Push $HWNDPARENT
  Call StarThemeTree
FunctionEnd
Function StarFinish
  !insertmacro MUI_HEADER_TEXT "星译官 · 准备就绪" "安装完成，可以开始翻译与审校"
  !insertmacro StarHero "" "installer-happy.bmp" "你的星译官$\r$\n已就位" "文档翻译与术语审校工具已安装完成。$\r$\n$\r$\n本机模型可离线使用；模型连接可在软件中设置。"
  ${NSD_CreateCheckbox} 126u 124u 174u 18u "完成后启动星译官"
  Pop $StarLaunch
  ${NSD_Check} $StarLaunch
  SetCtlColors $StarLaunch E5F2FF 102238
  GetDlgItem $0 $HWNDPARENT 1
  SendMessage $0 ${WM_SETTEXT} 0 "STR:完成"
  nsDialogs::Show
  ${NSD_FreeImage} $StarImageHandle
FunctionEnd
Function StarFinishLeave
  ${NSD_GetState} $StarLaunch $0
  ${If} $0 == ${BST_CHECKED}
    ${StdUtils.ExecShellAsUser} $0 "$launchLink" "open" ""
  ${EndIf}
FunctionEnd
  !endif
!ifdef BUILD_UNINSTALLER
Function un.StarWelcome
  !insertmacro MUI_HEADER_TEXT "星译官 · 卸载" "确认从此电脑移除星译官"
  !insertmacro StarHero "un." "installer-hero.bmp" "感谢你的使用" "即将卸载星译官。$\r$\n$\r$\n你处理的原文与导出文档不会被删除。$\r$\n$\r$\n点击下一步继续，或取消返回。"
  nsDialogs::Show
  ${NSD_FreeImage} $StarImageHandle
FunctionEnd
!endif
!macroend
