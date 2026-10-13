const http = require('node:http')

// 在主进程计时，即使窗口最小化也持续检测。始终只有一个在途请求。
class ModelConnectionMonitor {
  constructor({ getPort, onStatus, intervalMs = 1000, timeoutMs = 1500 }) {
    this.getPort = getPort
    this.onStatus = onStatus
    this.intervalMs = intervalMs
    this.timeoutMs = timeoutMs
    this.timer = null
    this.active = null
    this.running = false
    this.status = { state: 'starting', message: '正在启动服务…', detail: '', model: '', sequence: 0, checkedAt: null }
  }

  publish(value) {
    this.status = { ...value, sequence: this.status.sequence + 1, checkedAt: Date.now() }
    this.onStatus(this.status)
  }

  start() {
    if (this.running) return
    this.running = true
    this.tick()
    this.timer = setInterval(() => this.tick(), this.intervalMs)
  }

  cancelRequest() {
    const token = this.active
    this.active = null
    if (token) {
      clearTimeout(token.deadline)
      token.request.destroy()
    }
  }

  stop() {
    this.running = false
    clearInterval(this.timer)
    this.timer = null
    this.cancelRequest()
  }

  backendUnavailable(detail = '本地服务未连接，请重新启动软件。') {
    this.cancelRequest()
    this.publish({ state: 'unavailable', message: '本地服务未连接', detail, model: '' })
  }

  tick() {
    if (!this.running || this.active) return
    const port = this.getPort()
    if (!port) { this.backendUnavailable(); return }
    const token = { request: null, deadline: null }
    this.active = token
    const finish = value => {
      if (this.active !== token) return
      this.active = null
      clearTimeout(token.deadline)
      if (this.running) this.publish(value)
    }
    const unavailable = detail => finish({ state: 'unavailable', message: '连接检测失败', detail, model: '' })
    token.request = http.get({ hostname: '127.0.0.1', port, path: '/api/health', agent: false }, response => {
      if (response.statusCode !== 200) {
        response.resume()
        unavailable('本地服务暂时无法完成检测。')
        return
      }
      let body = ''
      response.setEncoding('utf8')
      response.on('data', chunk => {
        body += chunk
        if (body.length > 65536) {
          unavailable('连接检测响应过大。')
          token.request.destroy()
        }
      })
      response.on('error', () => unavailable('连接检测中断。'))
      response.on('end', () => {
        try {
          const data = JSON.parse(body)
          const status = data.model_status
          if (data.status !== 'ok' || !status || !['connected', 'unavailable', 'unknown'].includes(status.state)) {
            throw new Error('Invalid status')
          }
          if (typeof status.message !== 'string') throw new Error('Invalid message')
          finish({
            state: status.state,
            message: status.message.slice(0, 80),
            detail: typeof status.detail === 'string' ? status.detail.slice(0, 500) : '',
            model: typeof status.model === 'string' ? status.model.slice(0, 200) : '',
          })
        } catch (_) { unavailable('连接检测响应无效。') }
      })
    })
    token.request.on('error', () => unavailable('无法连接本地服务，请重新启动软件。'))
    // 总时限包括连接与读取，避免慢响应长期阻塞之后的检测。
    token.deadline = setTimeout(() => {
      unavailable('连接检测超时，将自动重试。')
      token.request.destroy()
    }, this.timeoutMs)
  }
}

module.exports = { ModelConnectionMonitor }
