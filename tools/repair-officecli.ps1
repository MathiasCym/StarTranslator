param([string]$InstallDirectory, [switch]$NoPause)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$taskLog = Join-Path $env:TEMP ('StarTranslator-OfficeCLI-Repair-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.txt')
$taskExit = 1
$taskStaging = $null
function Write-RepairLog([string]$Message) {
    $line = (Get-Date -Format 'o') + ' ' + $Message
    Add-Content -LiteralPath $taskLog -Value $line -Encoding UTF8
    Write-Host $Message
}
function Get-Hash([string]$File) {
    $stream = [IO.File]::OpenRead($File)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $algorithm.Dispose(); $stream.Dispose() }
}
function Get-Root([string]$Value) {
    $root = [IO.Path]::GetFullPath($Value.Trim().Trim('"'))
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw '安装目录不存在。' }
    if (-not (Test-Path -LiteralPath (Join-Path $root '星译官.exe') -PathType Leaf)) { throw '此目录没有星译官主程序，请选择实际安装目录。' }
    return $root
}
try {
    Write-RepairLog ('星译官 1.8.5 文档检查组件修复；系统 ' + [Environment]::OSVersion.VersionString + '；64 位系统 ' + [Environment]::Is64BitOperatingSystem)
    $taskPack = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'repair-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $taskPayload = Join-Path $PSScriptRoot 'officecli.exe'
    if ((Get-Item -LiteralPath $taskPayload).Length -ne $taskPack.size -or (Get-Hash $taskPayload) -ne $taskPack.sha256) { throw '修复包组件校验失败，未修改安装目录。请重新获取完整修复包。' }
    if (-not $InstallDirectory) {
        $taskCandidates = New-Object 'System.Collections.Generic.List[string]'
        foreach ($taskHive in @('HKCU:', 'HKLM:')) {
            $taskRegistration = Get-ItemProperty -LiteralPath ($taskHive + '\Software\40dcc9aa-3b67-5e68-9a54-dc7e46ccf86d') -ErrorAction SilentlyContinue
            if ($taskRegistration -and $taskRegistration.PSObject.Properties['InstallLocation'] -and $taskRegistration.InstallLocation) { $taskCandidates.Add([string]$taskRegistration.InstallLocation) }
        }
        $taskCandidates.Add((Join-Path $env:LOCALAPPDATA 'Programs\StarTranslator'))
        $taskCandidates.Add((Join-Path ([Environment]::GetFolderPath('Desktop')) 'StarTranslator'))
        $taskRoots = @($taskCandidates | Select-Object -Unique | Where-Object { (Test-Path -LiteralPath (Join-Path $_ '星译官.exe') -PathType Leaf) -and (Test-Path -LiteralPath (Join-Path $_ 'resources\install-manifest.json') -PathType Leaf) })
        if ($taskRoots.Count -eq 1) { $InstallDirectory = $taskRoots[0] }
        elseif ($NoPause) { throw '没有唯一可用安装目录，请通过 InstallDirectory 参数指定实际安装目录。' }
        else {
            if ($taskRoots.Count) { Write-Host '发现多个安装位置，请填写本次报错中 resources 前面的目录：'; $taskRoots | ForEach-Object { Write-Host $_ } }
            $InstallDirectory = Read-Host '请输入星译官安装目录（只填写到 StarTranslator）'
        }
    }
    $taskRoot = Get-Root $InstallDirectory
    Write-RepairLog ('实际安装目录：' + $taskRoot)
    $taskManifest = Get-Content -LiteralPath (Join-Path $taskRoot 'resources\install-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($taskManifest.version -ne $taskPack.app_version -or $taskManifest.schema -ne 1) { throw '修复包只适用于完整安装的 1.8.5，当前安装清单版本不符。未替换组件。' }
    $taskOfficeEntry = @($taskManifest.files | Where-Object { $_.path -eq 'resources/officecli/officecli.exe' })
    if ($taskOfficeEntry.Count -ne 1 -or $taskOfficeEntry[0].sha256 -ne $taskPack.sha256 -or $taskOfficeEntry[0].size -ne $taskPack.size) { throw '当前安装清单的组件与修复包不匹配，未替换组件。' }
    # Only repair OfficeCLI in an otherwise readable, intact installation.
    foreach ($taskCore in @('星译官.exe', 'resources/app.asar')) {
        $taskEntry = @($taskManifest.files | Where-Object { $_.path -eq $taskCore })
        $taskFile = Join-Path $taskRoot $taskCore
        if ($taskEntry.Count -ne 1 -or (Get-Item -LiteralPath $taskFile).Length -ne $taskEntry[0].size -or (Get-Hash $taskFile) -ne $taskEntry[0].sha256) { throw ('主程序文件未通过校验：' + $taskCore + '。需要完整安装，不能仅修复 OfficeCLI。') }
    }
    $taskComponentFolder = Join-Path $taskRoot 'resources\officecli'
    $taskTarget = Join-Path $taskComponentFolder 'officecli.exe'
    if ((Test-Path -LiteralPath $taskTarget) -and -not (Test-Path -LiteralPath $taskTarget -PathType Leaf)) { throw '组件文件名被文件夹占用，未替换任何内容。请提供此日志。' }
    $taskWasPresent = Test-Path -LiteralPath $taskTarget -PathType Leaf
    $taskNeedsCopy = $true
    if ($taskWasPresent) {
        $taskBeforeHash = Get-Hash $taskTarget
        Write-RepairLog ('修复前：文件存在；大小 ' + (Get-Item -LiteralPath $taskTarget).Length + '；SHA256 ' + $taskBeforeHash)
        $taskNeedsCopy = $taskBeforeHash -ne $taskPack.sha256
    } else { Write-RepairLog '修复前：OfficeCLI 文件缺失。' }
    if ($taskNeedsCopy) {
        [void][IO.Directory]::CreateDirectory($taskComponentFolder)
        $taskStaging = Join-Path $taskComponentFolder ('.star-office-repair-' + [Guid]::NewGuid().ToString('N') + '.tmp')
        Copy-Item -LiteralPath $taskPayload -Destination $taskStaging
        if ((Get-Hash $taskStaging) -ne $taskPack.sha256) { throw '复制后的组件校验失败，未替换原组件。' }
        Move-Item -LiteralPath $taskStaging -Destination $taskTarget -Force
        $taskStaging = $null
        Write-RepairLog '已恢复本版本原始 OfficeCLI 组件。'
    } else { Write-RepairLog '组件内容完整，无需替换。' }
    if ((Get-Item -LiteralPath $taskTarget).Length -ne $taskPack.size -or (Get-Hash $taskTarget) -ne $taskPack.sha256) { throw '恢复后组件未通过校验，请查看文件访问或安全软件记录。' }
    $taskStart = New-Object Diagnostics.ProcessStartInfo
    $taskStart.FileName = $taskTarget
    $taskStart.Arguments = '--version'
    $taskStart.WorkingDirectory = $taskComponentFolder
    $taskStart.UseShellExecute = $false
    $taskStart.CreateNoWindow = $true
    $taskStart.RedirectStandardOutput = $true
    $taskStart.RedirectStandardError = $true
    $taskStart.EnvironmentVariables['OFFICECLI_NO_AUTO_RESIDENT'] = '1'
    $taskStart.EnvironmentVariables['OFFICECLI_SKIP_UPDATE'] = '1'
    $taskProcess = New-Object Diagnostics.Process
    $taskProcess.StartInfo = $taskStart
    try {
        [void]$taskProcess.Start()
        $taskOutput = $taskProcess.StandardOutput.ReadToEndAsync()
        $taskError = $taskProcess.StandardError.ReadToEndAsync()
        if (-not $taskProcess.WaitForExit(30000)) { $taskProcess.Kill(); $taskProcess.WaitForExit(); throw '组件已恢复，但启动检查超过 30 秒。没有反复重试，请提供此日志。' }
        $taskStdout = $taskOutput.GetAwaiter().GetResult()
        $taskStderr = $taskError.GetAwaiter().GetResult()
        Write-RepairLog ('启动检查退出码：' + $taskProcess.ExitCode + '；输出：' + $taskStdout.Trim() + '；错误：' + $taskStderr.Trim())
        if ($taskProcess.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($taskStdout)) { throw '组件已恢复，但启动检查未通过，请提供此日志。' }
    } finally { $taskProcess.Dispose() }
    Write-RepairLog '修复与启动检查完成。请回到星译官重新开始任务；原文、译文和术语库均未修改。'
    $taskExit = 0
} catch {
    Write-RepairLog ('未完成：' + $_.Exception.Message)
    Write-RepairLog ('错误类型：' + $_.Exception.GetType().FullName + '；HRESULT ' + $_.Exception.HResult)
    Write-Host '若提示访问被拒绝，可右键“一键修复.cmd”以管理员身份运行。若仍未完成，请提供下方日志。'
} finally {
    if ($taskStaging -and (Test-Path -LiteralPath $taskStaging -PathType Leaf)) { Remove-Item -LiteralPath $taskStaging -Force -ErrorAction SilentlyContinue }
    $taskSetupLog = Join-Path $env:TEMP 'StarTranslatorSetup\logs\setup.log'
    if (Test-Path -LiteralPath $taskSetupLog -PathType Leaf) {
        Add-Content -LiteralPath $taskLog -Value "`r`n最近安装记录（仅本机保存）：" -Encoding UTF8
        Get-Content -LiteralPath $taskSetupLog -Tail 100 | Add-Content -LiteralPath $taskLog -Encoding UTF8
    }
    Write-Host ('日志文件：' + $taskLog)
    if (-not $NoPause) { [void](Read-Host '按回车关闭') }
}
exit $taskExit
