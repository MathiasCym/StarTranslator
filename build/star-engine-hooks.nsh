; Interactive instances use the Electron lock; silent workers use this mutex.
!macroundef ALLOW_ONLY_ONE_INSTALLER_INSTANCE
!macro ALLOW_ONLY_ONE_INSTALLER_INSTANCE
  ${If} ${Silent}
    System::Call 'kernel32::CreateMutex(p 0, i 1, t "${APP_GUID}-worker")?e'
    Pop $0
    ${If} $0 == 183
      SetErrorLevel 1618
      Quit
    ${EndIf}
  ${EndIf}
!macroend
