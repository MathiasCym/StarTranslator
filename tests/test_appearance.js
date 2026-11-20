const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const read = name => fs.readFileSync(path.join(__dirname, '..', name), 'utf8')

test('the desktop, picker and LAN use the shared palette with no theme switch', () => {
  for (const [name, surface] of [['index.html','desktop'], ['file-picker.html','picker'], ['shared/index.html','shared']]) {
    const entry = read('renderer/' + name)
    assert.match(entry, new RegExp('data-surface="' + surface + '"'))
    assert.match(entry, /studio\.css/)
    assert.doesNotMatch(entry, /data-theme-toggle|appearance-light|appearance\.js/)
  }
  assert.doesNotMatch(read('renderer/setup.html'), /studio\.css|data-theme-toggle/)
})
test('the local UI package has a separate profile and never installs updates', () => {
  const script = read('tools/build-ui-preview.cjs')
  const main = read('main.js')
  assert.match(script, /extraMetadata: \{ starPreview: true \}/)
  assert.match(script, /publish: 'never'/)
  assert.match(main, /app\.setPath\('userData', profile\)/)
  assert.match(main, /if\(!app.isPackaged \|\| previewBuild\)return null/)
  assert.match(main, /if\(previewBuild\)throw Error\('本地测试版停用在线安装更新。'\)/)
})
