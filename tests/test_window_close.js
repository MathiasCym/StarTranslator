const { test } = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const { installWindowCloseGuard } = require('../lib/window-close')

function fixture() {
  const win = new EventEmitter(), wc = new EventEmitter(), messages = []
  let destroyed = false, attempts = 0
  wc.isDestroyed = () => false
  wc.send = (channel, token) => messages.push({ channel, token })
  win.webContents = wc; win.isDestroyed = () => destroyed
  win.close = () => {
    attempts++
    const event = { blocked: false, preventDefault() { this.blocked = true } }
    win.emit('close', event)
    if (!event.blocked) destroyed = true
    return event.blocked
  }
  return { win, wc, messages, guard: installWindowCloseGuard(win), attempts: () => attempts }
}

test('startup and crashed renderers remain closable', () => {
  const a = fixture(); assert.equal(a.win.close(), false)
  const b = fixture(); b.guard.ready(b.wc); b.wc.emit('render-process-gone')
  assert.equal(b.win.close(), false)
})
test('close waits for one decision and cancellation allows another attempt', () => {
  const f = fixture()
  assert.equal(f.guard.ready({}), false); assert.equal(f.guard.ready(f.wc), true)
  assert.equal(f.win.close(), true); assert.equal(f.win.close(), true)
  assert.equal(f.messages.length, 1)
  const first = f.messages[0]; assert.equal(first.channel, 'window-close-request')
  assert.equal(f.guard.answer(f.wc, first.token, false), true)
  assert.equal(f.win.isDestroyed(), false)
  assert.equal(f.win.close(), true); assert.notEqual(f.messages[1].token, first.token)
})
test('only the owner and current token can authorize closing', () => {
  const f = fixture(); f.guard.ready(f.wc); f.win.close()
  const token = f.messages[0].token
  for (const [sender, value, answer] of [[{},token,true],[f.wc,'stale',true],[f.wc,token,'true']])
    assert.equal(f.guard.answer(sender, value, answer), false)
  assert.equal(f.win.isDestroyed(), false)
  assert.equal(f.guard.answer(f.wc, token, true), true)
  assert.equal(f.win.isDestroyed(), true); assert.equal(f.attempts(), 2)
  assert.equal(f.guard.answer(f.wc, token, true), false)
})
test('reload invalidates old decisions and requires a fresh ready handshake', () => {
  const f = fixture(); f.guard.ready(f.wc); f.win.close()
  const token = f.messages[0].token
  f.wc.emit('did-start-loading'); f.guard.ready(f.wc)
  assert.equal(f.guard.answer(f.wc, token, true), false)
  assert.equal(f.win.close(), true); assert.notEqual(f.messages[1].token, token)
  assert.equal(f.guard.answer(f.wc, f.messages[1].token, false), true)
})
