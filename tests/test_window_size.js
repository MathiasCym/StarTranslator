const { test } = require('node:test')
const assert = require('node:assert/strict')
const { defaultWindowSize } = require('../lib/window-size')

test('the default is larger and leaves room on a 1080p desktop', () => {
  const size = defaultWindowSize({ width: 1920, height: 1040 })
  assert.equal(size.width, 1440)
  assert.equal(size.height, 960)
  assert(size.width < 1920 && size.height < 1080)
})

test('smaller desktops retain margins and allow the window below the usual minimum', () => {
  for (const workArea of [{ width: 1366, height: 728 }, { width: 1280, height: 680 }, { width: 1024, height: 728 }]) {
    const size = defaultWindowSize(workArea)
    assert(workArea.width - size.width >= 80)
    assert(workArea.height - size.height >= 80)
    assert(size.minWidth <= size.width && size.minHeight <= size.height)
  }
})
