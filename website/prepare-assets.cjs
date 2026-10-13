// Make ASCII upload names without changing the recorded installers.
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto')
const root = path.resolve(__dirname, '..'), out = path.join(__dirname, 'release-assets')
const history = JSON.parse(fs.readFileSync(path.join(root, 'release-history.json')))
  .filter(r => !r.renumberedTo && fs.existsSync(path.join(root, r.installer)))
fs.mkdirSync(out, {recursive: true})
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')
const assets = history.map(r => {
  const source = path.resolve(root, r.installer)
  if (!source.startsWith(root + path.sep)) throw new Error('Invalid installer path')
  if (fs.statSync(source).size !== r.size || hash(source) !== r.sha256) throw new Error('Installer differs: ' + r.version)
  const name = `StarTranslator-Setup-${r.version}.exe`, file = path.join(out, name)
  if (!fs.existsSync(file)) { try { fs.linkSync(source, file) } catch { fs.copyFileSync(source, file) } }
  if (fs.statSync(file).size !== r.size || hash(file) !== r.sha256) throw new Error('Upload file differs: ' + r.version)
  return {version: r.version, name, path: file, size: r.size, sha256: r.sha256}
})
fs.writeFileSync(path.join(__dirname, 'upload-manifest.json'), JSON.stringify(assets, null, 2) + '\n')
console.log(JSON.stringify({assets: assets.length, totalBytes: assets.reduce((n, r) => n + r.size, 0)}))
