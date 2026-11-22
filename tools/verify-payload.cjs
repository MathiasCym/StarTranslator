const fs=require('fs'),path=require('path'),assert=require('assert/strict'),{app}=require('electron')
const root=path.resolve(__dirname,'..'),folder=path.resolve(process.argv[2]),version=JSON.parse(fs.readFileSync(path.join(root,'package.json'))).version
const packaged = path.resolve(process.argv[3] || path.join(root, 'dist/win-unpacked'))
const output = path.resolve(process.argv[4] || path.join(root, 'dist/qa/release-200/payload-result.json'))

async function verify() {
  const manifest = 'resources/install-manifest.json'
  const bytes = fs.readFileSync(path.join(folder, manifest))
  assert(bytes.equals(fs.readFileSync(path.join(packaged, manifest))), 'Extracted manifest differs from the packaged app')
  assert(bytes.equals(fs.readFileSync(path.join(folder, '$PLUGINSDIR/stage', manifest))), 'Installer stage manifest differs from the extracted app')
  const result = await require('../lib/install-integrity').verifyInstallation(folder, JSON.parse(bytes), version)
  assert(result.complete, JSON.stringify(result.failures))
  fs.mkdirSync(path.dirname(output), { recursive: true })
  fs.writeFileSync(output, JSON.stringify({ passed: true, version, files: result.checked, stageMatches: true }, null, 2))
  console.log('Verified ' + result.checked + ' installer files')
  app.exit(0)
}

verify().catch(error => {
  console.error(error)
  app.exit(1)
})
