const fs = require('node:fs/promises'), path = require('node:path'), crypto = require('node:crypto'), zlib = require('node:zlib'), { promisify } = require('node:util')
const { createManifest, targetPath } = require('../lib/install-integrity')
const { RECOVERY_INDEX, RECOVERY_DATA, recoverable } = require('../lib/installation-repair')
const gzip = promisify(zlib.gzip)
async function buildComponentRecovery(root, version, destination = root) {
  const baseline = await createManifest(root, version), dataFile = targetPath(destination, RECOVERY_DATA), indexFile = targetPath(destination, RECOVERY_INDEX)
  await fs.mkdir(path.dirname(dataFile), { recursive: true })
  const handle = await fs.open(dataFile, 'w'), entries = []
  let offset = 0
  try {
    for (const entry of baseline.files.filter(file => recoverable(file.path))) {
      const bytes = await fs.readFile(targetPath(root, entry.path))
      if (bytes.length !== entry.size || crypto.createHash('sha256').update(bytes).digest('hex') !== entry.sha256) throw new Error('修复副本生成期间程序文件发生变化：' + entry.path)
      const packed = await gzip(bytes, { level: 6 })
      // writeFile on the open descriptor handles partial OS writes.
      await handle.writeFile(packed)
      entries.push({ ...entry, offset, length: packed.length, packedSha256: crypto.createHash('sha256').update(packed).digest('hex') })
      offset += packed.length
    }
  } finally { await handle.close() }
  await fs.writeFile(indexFile, JSON.stringify({ schema: 1, version, files: entries }))
  return { files: entries.length, bytes: offset }
}
module.exports = { buildComponentRecovery }
