const fs = require('node:fs')
const path = require('node:path')
const { format } = require('node:util')

const MAX_BYTES = 1024 * 1024

function createLogger(file) {
  function write(level, values) {
    // A desktop launch may have no terminal, or its parent may close the pipe.
    // Diagnostic output must not write to those streams or interrupt the app.
    try {
      const target = typeof file === 'function' ? file() : file
      fs.mkdirSync(path.dirname(target), { recursive: true })
      const line = `${new Date().toISOString()} [${level}] ${format(...values)}\n`
      if (fs.existsSync(target) && fs.statSync(target).size >= MAX_BYTES) {
        fs.writeFileSync(target, line)
      } else {
        fs.appendFileSync(target, line)
      }
    } catch (_) {
      // A diagnostic file being unavailable must not fail the user's operation.
    }
  }
  return { info: (...values) => write('INFO', values), error: (...values) => write('ERROR', values) }
}

function installDiagnosticConsole(logger, { target = console, streams = [process.stdout, process.stderr] } = {}) {
  // Electron itself calls console.error before returning a rejected IPC request.
  // Route those messages to the same file as app diagnostics, without a pipe write.
  const previous = new Map()
  for (const name of ['log', 'info', 'debug', 'warn', 'error']) {
    const original = target[name]
    const replacement = (...values) => (name === 'warn' || name === 'error' ? logger.error : logger.info)(...values)
    previous.set(name, { original, replacement }); target[name] = replacement
  }
  const onError = error => {
    if (error?.code !== 'EPIPE') throw error
    logger.error('[stdio receiver closed]', error)
  }
  for (const stream of streams) stream?.on('error', onError)
  return () => {
    for (const [name, { original, replacement }] of previous) if (target[name] === replacement) target[name] = original
    for (const stream of streams) stream?.removeListener('error', onError)
  }
}

module.exports = { createLogger, installDiagnosticConsole }
