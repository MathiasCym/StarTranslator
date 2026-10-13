function validateSharedAddress(value) {
  let url
  try { url = new URL(value) } catch (_) { throw new Error('请填写完整的局域网共享地址。') }
  const parts = url.hostname.split('.').map(Number)
  const ipv4 = parts.length === 4 && parts.every(n => Number.isInteger(n) && n >= 0 && n <= 255)
  const local = url.hostname === 'localhost' || (ipv4 && (parts[0] === 127 || parts[0] === 10 ||
    (parts[0] === 192 && parts[1] === 168) || (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31)))
  if (!local || url.protocol !== 'http:' || url.username || url.password || url.search || url.hash || url.pathname !== '/' || !url.port) {
    throw new Error('请使用局域网中的共享地址，例如 http://192.168.1.10:8765。')
  }
  return url.origin + '/'
}
module.exports = { validateSharedAddress }
