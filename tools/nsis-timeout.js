// The bundled builder stops makensis after four minutes. Independent-file LZMA
// compression of the custom Electron installer may legitimately take longer.
// Extend only that compiler's deadline; keep failures and a bounded wait.
const { spawn } = require('node:child_process')
const path = require('node:path')
const util = require('builder-util')
const original = util.spawnAndWrite
util.spawnAndWrite = function (command, args, data, options = {}) {
  if (path.basename(command).toLowerCase() !== 'makensis.exe') return original(command, args, data, options)
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { ...options, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] })
    let output = '', errors = '', timedOut = false
    const timer = setTimeout(() => { timedOut = true; child.kill() }, 20 * 60 * 1000)
    child.stdout.on('data', value => { output += value })
    child.stderr.on('data', value => { errors += value })
    child.stdin.on('error', error => { if (error.code !== 'EPIPE') errors += error.message })
    child.on('error', error => { clearTimeout(timer); reject(error) })
    child.on('close', (code, signal) => {
      clearTimeout(timer)
      if (code === 0) resolve()
      else reject(new Error(`安装包编译失败（退出码 ${code}，信号 ${signal}，超时 ${timedOut}）\n${output}\n${errors}`))
    })
    child.stdin.end(data)
  })
}
