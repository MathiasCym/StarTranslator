const { test } = require('node:test')
const assert = require('node:assert/strict')
const http = require('node:http')
const { once } = require('node:events')
const { ModelConnectionMonitor } = require('../lib/model-monitor')

function health(state = 'connected') {
  return JSON.stringify({ status: 'ok', model_status: { state, message: state, detail: '', model: 'test-model' } })
}

async function fixture(t, options = {}) {
  const state = { handler: (_request, response) => response.end(health()), requests: 0 }
  const server = http.createServer((request, response) => {
    state.requests++
    state.handler(request, response)
  })
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  const updates = []
  const waiters = []
  const monitor = new ModelConnectionMonitor({
    getPort: () => server.address()?.port,
    onStatus: status => {
      updates.push(status)
      for (const waiter of [...waiters]) waiter(status)
    },
    intervalMs: 25, timeoutMs: 100, ...options,
  })
  t.after(async () => {
    monitor.stop()
    server.closeAllConnections()
    await new Promise(resolve => server.close(resolve))
  })
  function next(predicate = () => true) {
    return new Promise((resolve, reject) => {
      const deadline = setTimeout(() => { remove(); reject(new Error('Status did not arrive')) }, 2500)
      const remove = () => { clearTimeout(deadline); const i = waiters.indexOf(listener); if (i >= 0) waiters.splice(i, 1) }
      const listener = value => { if (predicate(value)) { remove(); resolve(value) } }
      waiters.push(listener)
    })
  }
  return { state, monitor, updates, next }
}

test('default monitoring reports at a one-second interval', async t => {
  const { monitor, next } = await fixture(t, { intervalMs: 1000 })
  assert.equal(monitor.intervalMs, 1000)
  const first = next()
  monitor.start()
  const a = await first
  const b = await next()
  assert.equal(a.state, 'connected')
  assert.ok(b.checkedAt - a.checkedAt >= 750)
  assert.ok(b.checkedAt - a.checkedAt < 2000)
  assert.ok(b.sequence > a.sequence)
})

test('disconnect and reconnect automatically update the light', async t => {
  const { state, monitor, next } = await fixture(t)
  const first = next()
  monitor.start()
  assert.equal((await first).state, 'connected')
  state.handler = (_request, response) => { response.writeHead(503); response.end() }
  assert.equal((await next()).state, 'unavailable')
  state.handler = (_request, response) => response.end(health())
  assert.equal((await next()).state, 'connected')
})

test('a healthy backend alone cannot make the model light green', async t => {
  const { state, monitor, next } = await fixture(t)
  state.handler = (_request, response) => response.end(JSON.stringify({ status: 'ok', llm_available: true }))
  const pending = next()
  monitor.start()
  assert.equal((await pending).state, 'unavailable')
})

test('unknown model status stays unknown', async t => {
  const { state, monitor, next } = await fixture(t)
  state.handler = (_request, response) => response.end(health('unknown'))
  const pending = next()
  monitor.start()
  assert.equal((await pending).state, 'unknown')
})

test('hanging requests do not overlap and time out', async t => {
  const { state, monitor, next } = await fixture(t, { timeoutMs: 100, intervalMs: 1000 })
  let received
  const arrived = new Promise(resolve => { received = resolve })
  state.handler = () => received()
  const pending = next()
  monitor.start()
  await arrived
  for (let i = 0; i < 20; i++) monitor.tick()
  assert.equal(state.requests, 1)
  const result = await pending
  assert.equal(result.state, 'unavailable')
  assert.match(result.detail, /超时/)
  assert.equal(monitor.active, null)
})

test('a cancelled old response cannot overwrite a backend failure', async t => {
  const { state, monitor, updates } = await fixture(t, { intervalMs: 1000 })
  let received
  const arrived = new Promise(resolve => { received = resolve })
  let oldResponse
  state.handler = (_request, response) => { oldResponse = response; received() }
  monitor.start()
  await arrived
  monitor.backendUnavailable('backend exited')
  const sequence = monitor.status.sequence
  oldResponse.end(health())
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(monitor.status.sequence, sequence)
  assert.equal(monitor.status.state, 'unavailable')
  assert.equal(updates.some(value => value.state === 'connected'), false)
})

test('stopping cancels the pending probe and prevents later updates', async t => {
  const { state, monitor, updates } = await fixture(t)
  let received
  const arrived = new Promise(resolve => { received = resolve })
  let oldResponse
  state.handler = (_request, response) => { oldResponse = response; received() }
  monitor.start()
  await arrived
  monitor.stop()
  oldResponse.end(health())
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(monitor.active, null)
  assert.equal(monitor.timer, null)
  assert.equal(updates.length, 0)
})
