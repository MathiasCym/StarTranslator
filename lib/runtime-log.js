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

module.exports = { createLogger }
