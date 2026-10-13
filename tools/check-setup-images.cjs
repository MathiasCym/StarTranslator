// Verify the real executable extracted from the installer, before any installation.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict')
const net = require('node:net'), { spawn } = require('node:child_process')
const crypto = require('node:crypto')
const root = path.resolve(__dirname, '..'), stage = path.resolve(process.argv[2] || '')
const out = path.join(root, 'dist/qa/repair-190-setup'), run = path.join(out, 'run-' + Date.now())
const version = JSON.parse(fs.readFileSync(path.join(root, 'package.json'))).version
const checks = [], errors = [], wait = ms => new Promise(resolve => setTimeout(resolve, ms))
fs.mkdirSync(run, { recursive: true })
assert(process.argv[2] && fs.existsSync(path.join(stage, 'StarTranslatorSetup.exe')), 'Provide an extracted installer stage')
class DevTools {
  constructor(ws) {
    this.ws = ws; this.next = 0; this.pending = new Map()
    ws.addEventListener('message', event => {
      const data = JSON.parse(event.data)
      if (data.method === 'Runtime.exceptionThrown') errors.push(data.params.exceptionDetails.text)
      const entry = this.pending.get(data.id); if (!entry) return
      this.pending.delete(data.id); clearTimeout(entry.timer)
      if (data.error) entry.reject(new Error(JSON.stringify(data.error))); else entry.resolve(data.result)
    })
  }
  call(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++this.next, timer = setTimeout(() => { this.pending.delete(id); reject(new Error('DevTools timeout: ' + method)) }, 10000)
      this.pending.set(id, { resolve, reject, timer }); this.ws.send(JSON.stringify({ id, method, params }))
    })
  }
  async evaluate(expression) {
    const result = await this.call('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true, userGesture: true })
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails))
    return result.result.value
  }
  close() { this.ws.close() }
}
async function connect(port, suffix) {
  for (let i = 0; i < 150; i++) {
    try {
      const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`, { signal: AbortSignal.timeout(1000) })).json()
      const page = pages.find(p => p.type === 'page' && p.url.endsWith(suffix))
      if (page) {
        const ws = new WebSocket(page.webSocketDebuggerUrl)
        await new Promise((resolve, reject) => { ws.addEventListener('open', resolve, { once: true }); ws.addEventListener('error', reject, { once: true }) })
        const client = new DevTools(ws); await client.call('Runtime.enable'); return client
      }
    } catch {}
    await wait(100)
  }
  throw new Error('Installer page not available: ' + suffix)
}
async function images(client) {
  const data = await client.evaluate(`(async()=>{
    const list=[...document.images]; await Promise.all(list.map(image=>image.decode()));
    return list.map(image=>{const r=image.getBoundingClientRect();return {src:image.getAttribute('src'),width:image.naturalWidth,height:image.naturalHeight,visible:r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight}})
  })()`)
  assert(data.length && data.every(image => image.width > 0 && image.height > 0 && image.visible), JSON.stringify(data))
  return data
}
async function capture(client, name) {
  const shot = await client.call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false })
  fs.writeFileSync(path.join(out, name + '.png'), Buffer.from(shot.data, 'base64'))
}
async function verifyMode(uninstall) {
  const folder = path.join(run, uninstall ? 'uninstall' : 'install'), target = path.join(folder, 'StarTranslator')
  fs.mkdirSync(target, { recursive: true }); fs.mkdirSync(path.join(folder, 'temp'), { recursive: true })
  const port = await new Promise(resolve => { const server = net.createServer(); server.listen(0, '127.0.0.1', () => { const p = server.address().port; server.close(() => resolve(p)) }) })
  const log = fs.openSync(path.join(folder, 'runtime.log'), 'w')
  const child = spawn(path.join(stage, 'StarTranslatorSetup.exe'), [uninstall ? '--star-uninstall' : '--star-setup', '--star-worker', path.join(out, 'not-executed.exe'), '--star-directory', target, '--star-locations-loaded', `--remote-debugging-port=${port}`, '--remote-debugging-address=127.0.0.1', '--disable-background-timer-throttling'], {
    cwd: stage, windowsHide: true, stdio: ['ignore', log, log], env: { ...process.env, TEMP: path.join(folder, 'temp'), TMP: path.join(folder, 'temp') }
  })
  let client, picker
  try {
    client = await connect(port, 'setup.html')
    for (let i = 0; i < 100 && !await client.evaluate("typeof setupInfo!=='undefined' && !!setupInfo"); i++) await wait(100)
    assert.equal(await client.evaluate('setupInfo.version'), version)
    assert.equal(await client.evaluate('setupInfo.uninstall'), uninstall)
    assert((await client.evaluate('setupInfo.directory')).startsWith(run))
    const assets = await images(client); assert.equal(assets.length, 2)
    await capture(client, uninstall ? 'uninstall-images' : 'install-images')
    checks.push({ mode: uninstall ? 'uninstall' : 'install', actualStageExecutable: true, images: assets })
    if (!uninstall) {
      await client.evaluate("document.querySelector('#setupBrowse').click();true")
      picker = await connect(port, 'file-picker.html')
      const avatar = await images(picker); assert.equal(avatar.length, 1)
      await capture(picker, 'installer-picker-image')
      checks.push({ mode: 'installer-directory-picker', actualStageExecutable: true, images: avatar })
      await picker.evaluate("document.querySelector('#pickerClose').click();true"); picker.close(); picker = null
    }
    // Never click the installation, uninstall or launch actions.
    await client.evaluate("document.querySelector('#setupClose').click();true").catch(() => {})
    for (let i = 0; i < 50 && child.exitCode === null; i++) await wait(100)
  } finally {
    picker?.close(); client?.close()
    if (child.exitCode === null) child.kill()
    fs.closeSync(log)
  }
}
;(async () => {
  try {
    const unpacked = path.join(stage, 'resources/app.asar.unpacked/renderer/assets')
    const originals = path.join(root, 'dist/win-unpacked/resources/app.asar.unpacked/renderer/assets')
    for (const name of fs.readdirSync(originals)) assert(fs.readFileSync(path.join(unpacked, name)).equals(fs.readFileSync(path.join(originals, name))), name)
    await verifyMode(false); await verifyMode(true); assert.deepEqual(errors, [])
    const archiveSha256=crypto.createHash('sha256').update(fs.readFileSync(path.join(stage,'resources/app.asar'))).digest('hex')
    const executableSha256=crypto.createHash('sha256').update(fs.readFileSync(path.join(stage,'StarTranslatorSetup.exe'))).digest('hex')
    const result = { passed: true, version, stage, archiveSha256, executableSha256, checks, errors, installationExecuted: false, uninstallExecuted: false, existingInstallationChanged: false }
    fs.writeFileSync(path.join(out, 'images-result.json'), JSON.stringify(result, null, 2)); console.log(JSON.stringify(result))
  } catch (error) {
    fs.writeFileSync(path.join(out, 'images-result.json'), JSON.stringify({ passed: false, version, stage, checks, errors, error: error.stack }, null, 2))
    console.error(error); process.exitCode = 1
  }
})()
