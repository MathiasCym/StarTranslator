const el = id => document.getElementById(id)
let options, current = '', parent = '', entries = [], selected = new Set(), history = [], request = 0, busy = false, loading = false, overwrite = false, anchor = '', sort = 'name', descending = false
const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' })
const rows = new Map()
function message(text, error = false) { el('pickerMessage').textContent = text; el('pickerMessage').classList.toggle('error', error) }
function resetOverwrite() { overwrite = false; el('pickerAccept').textContent = options.mode === 'save' ? '保存文件' : options.mode === 'directory' ? '选择此文件夹' : '选择文件' }
function visibleEntries() {
  const query = el('pickerSearch').value.trim().toLowerCase(), direction = descending ? -1 : 1
  return entries.filter(e => e.name.toLowerCase().includes(query)).sort((a, b) => {
    if (a.directory !== b.directory) return a.directory ? -1 : 1
    let result
    if (sort === 'size' || sort === 'modified') {
      const av = a[sort], bv = b[sort]
      if (Number.isFinite(av) !== Number.isFinite(bv)) return Number.isFinite(av) ? -1 : 1
      result = Number.isFinite(av) ? av - bv : 0
    } else if (sort === 'type') result = collator.compare(a.type || a.name.split('.').pop(), b.type || b.name.split('.').pop())
    else result = collator.compare(a.name, b.name)
    return direction * result || collator.compare(a.name, b.name)
  })
}
function updateSelection() {
  for (const [path, buttons] of rows) for (const row of buttons) {
    const checked = selected.has(path)
    row.classList.toggle('selected', checked); row.setAttribute('aria-selected', String(checked))
    row.querySelector('.file-check').textContent = checked ? '✓' : ''
  }
  if (options.mode === 'open') {
    const names = new Map(entries.map(entry => [entry.path, entry.targetName || entry.name]))
    const text = [...selected].map(path => names.get(path) || path.split(/[\\/]/).pop()).join('\n')
    el('pickerSelectedNames').value = text; el('pickerSelectedNames').title = text
    el('pickerNameLabel').textContent = selected.size ? `已选 ${selected.size} 项` : '已选文件'
  }
  el('pickerAccept').disabled = busy || loading || !current || (options.mode === 'open' ? !selected.size : options.mode === 'save' ? !el('pickerName').value.trim() : false)
}
function selectionMessage() { message(options.mode === 'save' ? '选择保存名称后点击保存。' : selected.size ? `已选 ${selected.size} 个文件` : '尚未选择文件。') }
function updateSort() {
  el('pickerSort').value = sort; el('pickerOrder').textContent = descending ? '降序 ↓' : '升序 ↑'
  const orders = { name: '名称顺序', modified: descending ? '新到旧' : '旧到新', type: '类型名称顺序', size: descending ? '大到小' : '小到大' }
  el('pickerOrder').title = orders[sort]; el('pickerOrder').setAttribute('aria-label', `当前${descending ? '降序' : '升序'}，点击切换为${descending ? '升序' : '降序'}`)
  try { localStorage.setItem('startranslator.picker.sort', JSON.stringify({ sort, descending })) } catch {}
}
function render() {
  const fragment = document.createDocumentFragment(); rows.clear()
  const visible = visibleEntries()
  for (const [index, entry] of visible.entries()) {
    const row = document.createElement('button'); row.className = 'picker-entry' + (selected.has(entry.path) ? ' selected' : '')
    row.setAttribute('role', 'option'); row.setAttribute('aria-selected', String(selected.has(entry.path)))
    const kind = document.createElement('span'); kind.className = 'file-kind'; kind.textContent = (entry.directory ? '文件夹' : (entry.type || entry.name.split('.').pop()).toUpperCase()) + (entry.shortcut ? ' ↗' : '')
    const name = document.createElement('span'); name.className = 'file-name'; name.textContent = entry.name
    const check = document.createElement('span'); check.className = 'file-check'; check.textContent = selected.has(entry.path) ? '✓' : ''
    row.append(kind, name, check)
    row.title = entry.shortcut ? `${entry.name}\n快捷方式目标：${entry.path}` : entry.name
    row.onclick = event => {
      if (busy || loading) return
      if (entry.directory) { navigate(entry.path); return }
      resetOverwrite()
      if (options.mode === 'save') { el('pickerName').value = entry.name; selected = new Set([entry.path]) }
      else if (options.multiple && event.shiftKey && visible.some(e => e.path === anchor)) {
        const first = visible.findIndex(e => e.path === anchor)
        for (let i = Math.min(first, index); i <= Math.max(first, index); i++) if (!visible[i].directory) selected.add(visible[i].path)
      } else if (options.multiple) {
        if (selected.has(entry.path)) selected.delete(entry.path); else selected.add(entry.path)
        anchor = entry.path
      } else selected = new Set([entry.path])
      // Keep the rows, focused button and scroll geometry intact when selection changes.
      updateSelection(); selectionMessage()
    }
    row.ondblclick = () => { if (!entry.directory && !options.multiple) accept() }
    if (!rows.has(entry.path)) rows.set(entry.path, [])
    rows.get(entry.path).push(row); fragment.append(row)
  }
  if (!visible.length) { const hint = document.createElement('p'); hint.className = 'hint'; hint.textContent = '此位置没有匹配的文件或文件夹。'; fragment.append(hint) }
  el('pickerList').replaceChildren(fragment); updateSelection()
}
async function navigate(directory, remember = true, refresh = false) {
  const sequence = ++request
  const scroll = el('pickerList').scrollTop
  loading = true; updateSelection()
  message('正在读取文件夹…')
  try {
    const result = await window.picker.list(directory)
    if (sequence !== request) return
    if (remember && current && current !== result.directory) history.push(current)
    const sameDirectory = refresh && current === result.directory
    current = result.directory; parent = result.parent; entries = result.files
    selected = sameDirectory ? new Set([...selected].filter(path => entries.some(e => e.path === path))) : new Set(); anchor = ''
    el('pickerPath').value = current; if (!sameDirectory) el('pickerSearch').value = ''; el('pickerBack').disabled = !history.length; el('pickerUp').disabled = parent === current
    resetOverwrite(); render(); el('pickerList').scrollTop = sameDirectory ? scroll : 0
    message(options.mode === 'directory' ? '进入目标文件夹后，点击“选择此文件夹”。' : options.multiple ? '点击文件勾选，可选择多个；Shift 点击可连续选择。' : '点击文件选择，或双击打开。')
    if (selected.size) selectionMessage()
  } catch (error) { if (sequence === request) message('无法读取此位置：' + error.message, true) }
  finally { if (sequence === request) { loading = false; updateSelection() } }
}
async function accept() {
  if (busy || loading || !current || el('pickerAccept').disabled) return
  busy = true; el('pickerAccept').disabled = true
  try {
    const result = await window.picker.confirm({ directory: current, name: el('pickerName').value, paths: [...selected], overwrite })
    if (result.overwrite) { overwrite = true; message(`“${result.name}”已存在。再次点击“确认覆盖”将替换该文件。`, true); el('pickerAccept').textContent = '确认覆盖' }
  } catch (error) { message(error.message, true) }
  finally { busy = false; updateSelection() }
}
el('pickerCancel').onclick = el('pickerClose').onclick = () => window.picker.cancel()
el('pickerAccept').onclick = accept
el('pickerPathForm').onsubmit = event => { event.preventDefault(); navigate(el('pickerPath').value.trim()) }
el('pickerBack').onclick = () => { if (history.length) navigate(history.pop(), false) }
el('pickerUp').onclick = () => navigate(parent)
el('pickerRefresh').onclick = () => navigate(current, false, true)
el('pickerSearch').oninput = () => { anchor = ''; render(); el('pickerList').scrollTop = 0 }
el('pickerSort').onchange = () => { sort = el('pickerSort').value; anchor = ''; updateSort(); render(); el('pickerList').scrollTop = 0 }
el('pickerOrder').onclick = () => { descending = !descending; anchor = ''; updateSort(); render(); el('pickerList').scrollTop = 0 }
el('pickerName').oninput = () => { resetOverwrite(); updateSelection() }
el('pickerNew').onclick = () => { el('pickerNewForm').hidden = !el('pickerNewForm').hidden; if (!el('pickerNewForm').hidden) el('pickerNewName').focus() }
el('pickerNewForm').onsubmit = async event => {
  event.preventDefault()
  try { const target = await window.picker.mkdir(current, el('pickerNewName').value.trim()); el('pickerNewName').value = ''; el('pickerNewForm').hidden = true; await navigate(target) }
  catch (error) { message(error.message, true) }
}
document.onkeydown = event => {
  if (event.key === 'Escape') window.picker.cancel()
  if (event.altKey && event.key === 'ArrowUp') { event.preventDefault(); navigate(parent) }
  if (event.ctrlKey && event.key.toLowerCase() === 'l') { event.preventDefault(); el('pickerPath').focus(); el('pickerPath').select() }
  if (event.ctrlKey && event.key.toLowerCase() === 'a' && event.target.closest('#pickerList') && options.multiple) {
    event.preventDefault(); if (busy || loading) return
    for (const entry of visibleEntries()) if (!entry.directory) selected.add(entry.path)
    updateSelection(); selectionMessage()
  }
}
;(async () => {
  options = await window.picker.options()
  document.title = '星译官 · ' + options.title; el('pickerTitle').textContent = options.title
  el('pickerList').setAttribute('aria-multiselectable', String(!!options.multiple))
  el('pickerNameRow').hidden = options.mode === 'directory'; el('pickerName').hidden = options.mode !== 'save'; el('pickerName').value = options.name || ''
  el('pickerSelectedNames').hidden = options.mode !== 'open'; el('pickerNameLabel').textContent = options.mode === 'save' ? '文件名' : '已选文件'
  try { const saved = JSON.parse(localStorage.getItem('startranslator.picker.sort')); if (['name','modified','type','size'].includes(saved?.sort)) { sort = saved.sort; descending = saved.descending === true } } catch {}
  updateSort()
  el('pickerType').textContent = options.mode === 'directory' ? '文件夹' : options.extensions.map(e => '*.' + e).join(' · ')
  for (const location of options.locations) {
    const button = document.createElement('button'); button.className = 'btn ghost sm'; button.textContent = location.name; button.title = location.path; button.onclick = () => navigate(location.path); el('pickerLocations').append(button)
  }
  await navigate(options.directory)
})().catch(error => message(error.message, true))
