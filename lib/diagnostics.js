const fs = require('node:fs/promises'), path = require('node:path'), os = require('node:os')
const { digest } = require('./install-integrity')

function redact(value, secrets = []) {
  let text = String(value ?? '')
  for (const secret of secrets.filter(s => typeof s === 'string' && s.length >= 4).sort((a, b) => b.length - a.length)) text = text.split(secret).join('[已隐藏]')
  return text.replace(/(\b(?:api[_-]?key|x-api-key|authorization|password|access[_-]?token)\b["']?\s*[:=]\s*["']?)(?:Bearer\s+)?[^\s,"'}]+/gi, '$1[已隐藏]')
    .replace(/\bsk-[A-Za-z0-9_-]{8,}/g, '[已隐藏]')
    .replace(/\b(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{16,}/g,'[已隐藏]')
}
function collectSecrets(value, secrets = []) {
  if (value && typeof value === 'object') for (const [key, item] of Object.entries(value)) {
    if (/api.?key|password|secret|token/i.test(key) && typeof item === 'string') secrets.push(item)
    else collectSecrets(item, secrets)
  }
  return secrets
}
function taskMetadata(task = {}) {
  const text = value => typeof value === 'string' ? value.slice(0, 4000) : ''
  return { id: text(task.id), kind: text(task.kind), status: text(task.status), phase: text(task.phase), error: text(task.error),
    errors: (Array.isArray(task.errors) ? task.errors : []).slice(0, 100).map(item => ({ path: text(item.path), error: text(item.error) })) }
}
async function buildDiagnostics({ version, resources, userData, setupLog, task }) {
  let secrets = []
  try { secrets = collectSecrets(JSON.parse(await fs.readFile(path.join(userData, 'model-settings.json'), 'utf8'))) } catch {}
  const info = { exported_at: new Date().toISOString(), version, windows: { type: os.type(), release: os.release(), version: os.version(), arch: os.arch() },
    installation: path.dirname(resources), task: taskMetadata(task), components: [] }
  let manifest
  try { manifest = JSON.parse(await fs.readFile(path.join(resources, 'install-manifest.json'), 'utf8')); info.manifest_version = manifest.version } catch (error) { info.manifest_error = error.code || error.message }
  for (const relative of ['officecli/officecli.exe', 'python-runtime/python.exe', 'python-runtime/python311.dll', 'app.asar.unpacked/backend/server.py']) {
    const item = { path: path.join(resources, relative) }
    try {
      const stat = await fs.stat(item.path); item.size = stat.size; item.sha256 = await digest(item.path)
      const expected = manifest?.files?.find(file => file.path === 'resources/' + relative)
      item.matches_installer = expected ? stat.size === expected.size && item.sha256 === expected.sha256 : null
    } catch (error) { item.error = error.code || error.message }
    info.components.push(item)
  }
  let report = '星译官 · 错误诊断\r\n\r\n' + JSON.stringify(info, null, 2) + '\r\n'
  for (const [label, file] of [['完整性校验与修复', path.join(userData, 'logs/integrity.log')], ['文档检查记录', path.join(userData, 'logs/officecli.jsonl')], ['运行日志', path.join(userData, 'logs/runtime.log')], ['安装日志', setupLog]]) {
    if (!file) continue
    let tail
    try { const bytes = await fs.readFile(file); tail = bytes.subarray(Math.max(0, bytes.length - 64 * 1024)).toString('utf8') } catch (error) { tail = '日志不可读取：' + (error.code || error.message) }
    report += '\r\n===== ' + label + '（最近内容） =====\r\n' + tail + '\r\n'
  }
  return redact(report, secrets)
}
module.exports = { redact, collectSecrets, taskMetadata, buildDiagnostics }
