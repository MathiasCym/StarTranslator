const { spawn } = require('node:child_process')
const fs = require('node:fs/promises'), path = require('node:path'), crypto = require('node:crypto')

function workerArguments({ uninstall, directory, scope, statusFile }) {
  // NSIS consumes the entire trailing /D or _? value, including spaces.
  // Other parameters must precede it and retain their own quotes.
  if ([directory, statusFile].some(value => typeof value !== 'string' || /["\r\n\0]/.test(value))) throw new Error('安装参数无效。')
  return ['/S', scope === 'all' ? '/allusers' : '/currentuser', `/STAR_STATUS="${statusFile}"`,
    uninstall ? `_?=${directory}` : `/D=${directory}`]
}

async function directoryNeedsElevation(directory, io = fs) {
  let ancestor = directory
  while (true) {
    try {
      const stat = await io.stat(ancestor)
      if (!stat.isDirectory()) throw new Error('安装位置的上级路径不是文件夹。')
      break
    } catch (error) {
      if (['EACCES', 'EPERM'].includes(error.code)) return true
      if (error.code !== 'ENOENT') throw error
      const parent = path.dirname(ancestor)
      if (parent === ancestor) throw new Error('安装位置所在的磁盘不可访问。')
      ancestor = parent
    }
  }
  const probe = path.join(ancestor, `.star-write-${crypto.randomUUID()}.tmp`)
  let handle
  try {
    handle = await io.open(probe, 'wx')
    return false
  } catch (error) {
    if (['EACCES', 'EPERM'].includes(error.code)) return true
    throw error
  } finally {
    if (handle) { await handle.close(); await io.unlink(probe) }
  }
}

const psLiteral = value => "'" + value.replaceAll("'", "''") + "'"
function elevationScript(worker, args) {
  // EncodedCommand and PowerShell literal strings keep paths out of shell code.
  // Only the worker is elevated; the custom installer UI stays with its user.
  return `$ErrorActionPreference='Stop'; try { $starProcess=Start-Process -FilePath ${psLiteral(worker)} -ArgumentList ${psLiteral(args.join(' '))} -WorkingDirectory $env:SystemRoot -Verb RunAs -WindowStyle Hidden -PassThru -Wait; exit $starProcess.ExitCode } catch { $starError=$_.Exception; while($starError -and -not ($starError -is [ComponentModel.Win32Exception])){$starError=$starError.InnerException}; if($starError){exit $starError.NativeErrorCode}; exit 1603 }`
}

function launchWorker({ worker, args, elevate, spawnProcess = spawn }) {
  const options = { windowsHide: true, stdio: 'ignore', cwd: process.env.SystemRoot || process.cwd() }
  if (!elevate) return spawnProcess(worker, args, { ...options, windowsVerbatimArguments: true })
  const script = Buffer.from(elevationScript(worker, args), 'utf16le').toString('base64')
  const powershell = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
  return spawnProcess(powershell, ['-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-EncodedCommand', script], options)
}

function workerOutcome({ code, error, phase, executableExists, uninstall }) {
  const complete = !error && code === 0 && phase === 'complete' && (uninstall ? !executableExists : executableExists)
  if (complete) return { complete: true }
  const reported = /^error:(\d+)$/.exec(phase || '')
  const failureCode = reported ? Number(reported[1]) : code
  const messages = {
    2: '旧版本移除失败。请关闭星译官及正在使用安装目录的程序后重试。',
    5: '当前目录不允许写入。请接受管理员授权，或选择有写入权限的独立文件夹。',
    1618: '已有安装或卸载任务正在进行。请等待完成后重试。',
    1619: '星译官仍在运行。请关闭软件后重试，未保存的工作不会被强制结束。',
    1223: '管理员授权已取消，尚未完成安装或卸载。可以重新开始。',
    1603: '安装组件未能完成操作。请关闭占用程序后重试，或查看安装日志。',
  }
  let message = messages[failureCode]
  if (!message && error) message = ['EACCES', 'EPERM'].includes(error.code) ? messages[5] : `安装组件未能启动：${error.message}`
  if (!message) message = code === 0 ? '安装组件未返回完成确认。请重新打开安装包后重试。' : `操作未完成（${failureCode ?? '未知错误'}）。可查看安装日志确认原因。`
  return { complete: false, message }
}

module.exports = { workerArguments, directoryNeedsElevation, elevationScript, launchWorker, workerOutcome }
