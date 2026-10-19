const fs = require('node:fs')
const path = require('node:path')
const { newer } = require('./github-updates')

function highlights(notes) {
  return String(notes || '').slice(0, 20000).split(/\r?\n/)
    .filter(line => /^\s*(?:\d+[.)、]|[-*])\s+/.test(line))
    .map(line => line.replace(/^\s*(?:\d+[.)、]|[-*])\s+/, '').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/[*`_]/g, '').trim())
    .filter(Boolean).slice(0, 5).map(line => line.length > 150 ? line.slice(0, 149) + '…' : line)
}
class UpdateNotifications {
  constructor({ userData, currentVersion, check, now = () => new Date() }) {
    this.file = path.join(userData, 'update-notifications.json')
    this.currentVersion = currentVersion; this.check = check; this.now = now
    this.pending = null; this.checked = false; this.retryAfter = 0; this.offered = new Set()
    this.preferences = { ignored: [] }
    try {
      const value = JSON.parse(fs.readFileSync(this.file, 'utf8'))
      if (Array.isArray(value.ignored)) this.preferences.ignored = value.ignored.filter(v => /^\d+\.\d+\.\d+$/.test(v)).slice(-100)
    } catch {}
  }
  save() {
    fs.mkdirSync(path.dirname(this.file), { recursive: true })
    const temporary = this.file + '.tmp'
    fs.writeFileSync(temporary, JSON.stringify(this.preferences), { mode: 0o600 })
    fs.renameSync(temporary, this.file)
  }
  startup() {
    if (this.pending) return this.pending
    // Check once per application process, including subsequent launches today.
    // Persist only ignored versions; the old checkedDay preference is obsolete.
    if (this.checked || this.now().getTime() < this.retryAfter) return Promise.resolve(null)
    this.pending = (async () => {
      try {
        const value = await this.check()
        this.checked = true
        if (!value || !newer(value.version, this.currentVersion) || this.preferences.ignored.includes(value.version)) return null
        this.offered.add(value.version)
        const items = highlights(value.notes)
        return { version: value.version, highlights: items.length ? items : ['本次更新包含功能改进与问题修复，可在软件更新中查看完整说明。'] }
      } catch {
        // Offline startup stays quiet. Never block document work.
        this.retryAfter = this.now().getTime() + 15 * 60 * 1000
        return null
      } finally { this.pending = null }
    })()
    return this.pending
  }
  ignore(version) {
    if (!this.offered.has(version)) throw Error('请从当前更新提醒中设置。')
    if (!this.preferences.ignored.includes(version)) this.preferences.ignored.push(version)
    this.preferences.ignored = this.preferences.ignored.slice(-100)
    this.save()
  }
}
module.exports = { UpdateNotifications, highlights }
