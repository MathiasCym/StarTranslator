function installLexicon({ $, action, callApi, esc, basename }) {
  // Both views edit the same rows, with one fingerprint and one save action.
  const state = { path: '', columns: [], header: [], rows: [], fingerprint: '', dirty: false,
    busy: false, selected: -1, page: 0, view: 'list', visibleColumns: new Set(['zh', 'en', 'note']) }
  const names = { zh: '中文术语', en: '标准英文', variants: '正确别名', machine_variants: '机翻候选',
    wrong_variants: '已确认错译', note: '解释 / 备注', priority: '确认状态', source: '来源' }
  const fields = { termZh: 'zh', termEn: 'en', termAliases: 'variants', termMachine: 'machine_variants',
    termWrong: 'wrong_variants', termNote: 'note' }
  const listFields = ['variants', 'machine_variants', 'wrong_variants'], pageSize = 40
  let suggesting = false
  const cell = (row, key) => String(row?.[state.columns.indexOf(key)] ?? '')
  const lines = text => text.split(/\r?\n/).map(value => value.trim()).filter(Boolean)
  const selectedRow = () => state.rows[state.selected]
  async function dirtyGuard(accept = '放弃修改') {
    if (state.busy) return false
    return !state.dirty || await AppDialogs.ask({ title: '放弃术语库修改？',
      message: '当前词库的修改尚未保存。放弃后，本次编辑的内容不会保留。', accept })
  }
  function status(message, error = false) {
    $('lexiconStatus').textContent = message
    $('lexiconStatus').classList.toggle('error', error)
  }
  function availability() {
    const loaded = !!state.path, selected = !!selectedRow()
    for (const id of ['closeLexicon', 'reloadLexicon', 'importTerms', 'exportTerms', 'lexiconExportFormat', 'createShared', 'connectShared', 'useLocal', 'syncReviewed',
      'lexiconListView', 'lexiconGridView']) $(id).disabled = state.busy
    $('revealLexicon').disabled = !loaded || state.busy
    $('importTerms').disabled = !loaded || state.busy
    $('exportTerms').disabled = !loaded || state.busy
    $('openTeamSync').disabled = !loaded || state.busy || state.dirty
    $('addTerm').disabled = !loaded || state.busy
    $('deleteTerm').disabled = !selected || state.busy
    $('saveLexicon').disabled = !loaded || !state.dirty || state.busy
    $('termForm').querySelectorAll('textarea,button').forEach(element => { element.disabled = !selected || state.busy })
    $('suggestVariants').disabled = !selected || state.busy || suggesting
    $('tableBody').querySelectorAll('textarea,button').forEach(element => { element.disabled = state.busy })
    $('lexiconColumnOptions').querySelectorAll('input').forEach(element => { element.disabled = state.busy })
    $('lexiconDirtyBadge').textContent = state.dirty ? '未保存' : loaded ? '已保存' : '未读取'
    $('lexiconDirtyBadge').classList.toggle('dirty', state.dirty)
    $('lexiconTotal').textContent = state.rows.length + ' 条'
    pageRows()
  }
  function markDirty() { state.dirty = true; status('修改尚未保存。'); availability() }
  async function operation(fn, message) {
    if (state.busy) return
    state.busy = true; availability(); status(message)
    try { return await fn() }
    catch (error) { status(error.message, true); throw error }
    finally { state.busy = false; availability() }
  }
  async function refreshGlossary() {
    const result = await callApi('GET', '/api/lexicon')
    $('glossaryInfo').textContent = '术语库 ' + result.entries.length + ' 条'
    return result
  }
  function ensureColumn(key) {
    let index = state.columns.indexOf(key)
    if (index >= 0) return index
    index = state.columns.length
    state.columns.push(key); state.header.push(names[key] || key)
    state.rows.forEach(row => { row[index] = '' })
    renderColumnOptions()
    return index
  }
  function changeCell(row, key, value, columnIndex) {
    row[columnIndex ?? ensureColumn(key)] = value
    if (['zh', 'en', 'wrong_variants'].includes(key)) row[ensureColumn('priority')] = '2'
    markDirty()
  }
  function filteredRows() {
    return rankTermRows(state.rows, state.columns, $('termSearch').value)
  }
  function pageRows() {
    const filtered = filteredRows(), pages = Math.max(1, Math.ceil(filtered.length / pageSize))
    state.page = Math.min(Math.max(0, state.page), pages - 1)
    $('termCount').textContent = filtered.length + ' / ' + state.rows.length + ' 条 · 第 ' + (state.page + 1) + ' / ' + pages + ' 页'
    $('lexiconMatches').textContent = filtered.length + ' 条'
    $('termsPrev').disabled = state.busy || !state.page
    $('termsNext').disabled = state.busy || state.page >= pages - 1
    return filtered.slice(state.page * pageSize, (state.page + 1) * pageSize)
  }
  function renderCards(rows = pageRows()) {
    const scroll = $('termRows').scrollTop
    $('termRows').innerHTML = rows.map(({ row, index }) => {
      const aliases = lines(cell(row, 'variants')).length, wrong = lines(cell(row, 'wrong_variants')).length
      return '<button class="term-card' + (index === state.selected ? ' active' : '') + '" data-term="' + index + '" role="listitem" aria-current="' + (index === state.selected) + '">' +
        '<span class="term-card-zh" title="' + esc(cell(row, 'zh') || '新术语') + '">' + esc(cell(row, 'zh') || '新术语') + '</span><span class="term-card-en" title="' + esc(cell(row, 'en') || '尚未填写标准英文') + '">' + esc(cell(row, 'en') || '尚未填写标准英文') + '</span>' +
        (aliases || wrong ? '<span class="term-card-tags">' + (aliases ? '<span>' + aliases + ' 个别名</span>' : '') +
          (wrong ? '<span class="wrong-tag">' + wrong + ' 项错译</span>' : '') + '</span>' : '') + '</button>'
    }).join('') || '<div class="lexicon-empty">没有匹配的术语<br><span>试试其他关键词，或新增术语。</span></div>'
    $('termRows').querySelectorAll('[data-term]').forEach(button => { button.onclick = () => {
      if (state.busy) return
      state.selected = Number(button.dataset.term); renderCards(); fillTerm()
    } })
    $('termRows').scrollTop = scroll
  }
  function resizeCell(element) {
    element.style.height = 'auto'
    const minimum = element.closest('table.grid') ? 36 : 50
    element.style.height = Math.min(160, Math.max(minimum, element.scrollHeight + 2)) + 'px'
  }
  function visibleColumns() {
    return state.columns.map((key, index) => ({ key, index })).filter(({ key, index }) =>
      !['priority', 'source'].includes(key) && (['zh', 'en'].includes(key) || state.visibleColumns.has(key || 'extra-' + index)))
  }
  function renderColumnOptions() {
    $('lexiconColumnOptions').innerHTML = state.columns.map((key, index) => ({ key, index }))
      .filter(({ key }) => !['priority', 'source', 'zh', 'en'].includes(key)).map(({ key, index }) => {
        const token = key || 'extra-' + index
        return '<label><input type="checkbox" data-column="' + esc(token) + '"' + (state.visibleColumns.has(token) ? ' checked' : '') + '>' +
          esc(names[key] || state.header[index] || '附加字段') + '</label>'
      }).join('') || '<span class="hint">暂无其他列，可在详情中补充。</span>'
    $('lexiconColumnOptions').querySelectorAll('input').forEach(input => { input.onchange = () => {
      if (input.checked) state.visibleColumns.add(input.dataset.column); else state.visibleColumns.delete(input.dataset.column)
      renderGrid()
    } })
  }
  function renderGrid(rows = pageRows()) {
    const columns = visibleColumns()
    $('tableHead').closest('table').style.minWidth = columns.length > 4 ? (columns.length * 190 + 112) + 'px' : '100%'
    $('tableHead').innerHTML = '<tr>' + columns.map(({ key, index }) => '<th' + (key === 'zh' ? ' class="grid-zh"' : '') + '>' +
      esc(names[key] || state.header[index] || '附加字段') + '</th>').join('') + '<th class="grid-actions">操作</th></tr>'
    $('tableBody').innerHTML = rows.map(({ row, index }) => '<tr>' + columns.map(({ key, index: column }) =>
      '<td' + (key === 'zh' ? ' class="grid-zh"' : '') + '><textarea aria-label="' + esc(names[key] || state.header[column] || '附加字段') +
      '" data-r="' + index + '" data-c="' + column + '" rows="1" title="' + esc(row[column]) + '">' + esc(row[column]) + '</textarea></td>').join('') +
      '<td class="grid-actions"><button class="btn ghost sm" data-detail="' + index + '">详情</button><button class="btn ghost sm danger" data-delete="' + index + '">删除</button></td></tr>').join('') ||
      '<tr><td colspan="' + (columns.length + 1) + '"><div class="lexicon-empty">没有匹配的术语</div></td></tr>'
    $('tableBody').querySelectorAll('textarea').forEach(element => {
      resizeCell(element)
      element.oninput = () => {
        const column = Number(element.dataset.c)
        changeCell(state.rows[Number(element.dataset.r)], state.columns[column], element.value, column)
        element.title = element.value; resizeCell(element)
      }
    })
    $('tableBody').querySelectorAll('[data-detail]').forEach(button => { button.onclick = () => {
      state.selected = Number(button.dataset.detail); setView('list')
    } })
    $('tableBody').querySelectorAll('[data-delete]').forEach(button => { button.onclick = () => deleteRow(Number(button.dataset.delete)) })
    availability()
  }
  function fillTerm() {
    const row = selectedRow()
    $('termForm').hidden = !row; $('termEmpty').hidden = !!row
    $('termHeading').textContent = row ? cell(row, 'zh') || '新术语' : '选择一个术语'
    for (const [id, key] of Object.entries(fields)) { $(id).value = cell(row, key); resizeCell($(id)) }
    $('termForm').scrollTop = 0
    availability()
  }
  function render() {
    const rows = pageRows()
    if (state.view === 'list') renderCards(rows); else renderGrid(rows)
    fillTerm(); availability()
  }
  function setView(view) {
    if (state.busy) return
    state.view = view
    $('lexiconListPane').hidden = view !== 'list'; $('lexiconGridPane').hidden = view !== 'grid'
    for (const [id, name] of [['lexiconListView', 'list'], ['lexiconGridView', 'grid']]) {
      $(id).classList.toggle('active', view === name); $(id).setAttribute('aria-pressed', String(view === name))
    }
    $('lexiconColumns').open = false; render()
  }
  function setData(result, keepPosition = false) {
    state.path = result.path; state.columns = [...(result.columns || [])]; state.header = [...(result.header || state.columns)]
    state.rows = result.rows || []; state.fingerprint = result.fingerprint; state.dirty = false
    if (!keepPosition) { $('termSearch').value = ''; state.page = 0; state.selected = state.rows.length ? 0 : -1 }
    else state.selected = Math.min(state.selected, state.rows.length - 1)
    $('lexiconPath').textContent = result.path; $('lexiconFile').textContent = basename(result.path); $('lexiconFile').title = result.path
    $('lexiconKind').textContent = /\.(xlsx|xlsm)$/i.test(result.path) ? 'Excel 词库' : /\.(csv|tsv)$/i.test(result.path) ? '表格词库' : 'JSON 词库'
    renderColumnOptions(); render()
  }
  async function load(keepPosition = false) {
    setData(await callApi('GET', '/api/glossary/table'), keepPosition)
    await refreshGlossary()
  }
  action('openLexicon', () => operation(async () => {
    $('lexiconModal').hidden = false
    $('lexiconImportReport').hidden = true
    await load(); status('词库已就绪。')
  }, '正在读取术语库…'))
  action('closeLexicon', async () => {
    if (!await dirtyGuard('放弃并关闭')) return
    $('lexiconModal').hidden = true; state.dirty = false; state.rows = []; state.selected = -1; state.path = ''; state.fingerprint = ''
  })
  action('lexiconListView', () => setView('list'))
  action('lexiconGridView', () => setView('grid'))
  $('termSearch').oninput = () => {
    state.page = 0
    const rows = pageRows()
    state.selected = rows[0]?.index ?? -1
    render(); $('termRows').scrollTop = 0; $('lexiconGridPane').querySelector('.gridwrap').scrollTop = 0
  }
  for (const [id, key] of Object.entries(fields)) $(id).oninput = () => {
    if (!selectedRow() || state.busy) return
    changeCell(selectedRow(), key, $(id).value)
    resizeCell($(id))
    $('termHeading').textContent = cell(selectedRow(), 'zh') || '新术语'
    renderCards()
  }
  for (const [id, step] of [['termsPrev', -1], ['termsNext', 1]]) action(id, () => {
    if (state.busy) return
    state.page += step; state.selected = pageRows()[0]?.index ?? -1; render()
    $('termRows').scrollTop = 0; $('lexiconGridPane').querySelector('.gridwrap').scrollTop = 0
  })
  action('addTerm', () => {
    if (state.busy || !state.path) return
    const row = state.columns.map(key => key === 'priority' ? '2' : key === 'source' ? '团队维护' : '')
    state.rows.unshift(row); state.selected = 0; state.page = 0; $('termSearch').value = ''
    markDirty(); render(); status('填写新术语的中文和标准英文，再保存词库。')
    if (state.view === 'list') $('termZh').focus(); else $('tableBody').querySelector('textarea')?.focus()
  })
  function deleteRow(index) {
    if (state.busy || !state.rows[index]) return
    state.rows.splice(index, 1)
    if (state.selected > index) state.selected--
    else if (state.selected === index) state.selected = Math.min(index, state.rows.length - 1)
    markDirty(); render()
  }
  action('deleteTerm', () => deleteRow(state.selected))
  action('saveLexicon', () => operation(async () => {
    const result = await callApi('POST', '/api/glossary/table', { path: state.path, rows: state.rows, columns: state.columns, fingerprint: state.fingerprint })
    state.fingerprint = result.fingerprint; state.dirty = false
    try { await load(true); status('已保存 ' + result.count + ' 条术语。') }
    catch (error) { status('已保存，但重新读取失败：' + error.message, true) }
  }, '正在保存词库…'))
  action('reloadLexicon', async () => {
    if (!await dirtyGuard('放弃并重新读取')) return
    return operation(async () => { await load(); status('已重新读取最新词库。') }, '正在重新读取…')
  })
  action('revealLexicon', () => state.path && window.api.openFolder(state.path))
  for (const [id, create] of [['createShared', true], ['connectShared', false]]) action(id, async () => {
    if (!await dirtyGuard()) return
    return operation(async () => {
      const path = await window.api.pickSharedLexicon(create)
      if (!path) { status('已取消选择，当前词库保持不变。'); return }
      await callApi('POST', '/api/lexicon/select', { path, create }); await load()
      $('lexiconManagement').open = false; status(create ? '已创建共享词库，可让同事连接同一文件。' : '已连接共享词库，保存前会检查文件是否被改动。')
    }, create ? '正在创建共享词库…' : '正在连接共享词库…')
  })
  action('useLocal', async () => {
    if (!await dirtyGuard('放弃并切换')) return
    return operation(async () => {
      await callApi('POST', '/api/lexicon/select', {}); await load(); $('lexiconManagement').open = false; status('已切换为本机词库。')
    }, '正在切换词库…')
  })
  action('importTerms', () => {
    if (!state.path) return
    return operation(async () => {
      const paths = await window.api.pickGlossary()
      if (!paths.length) { status('已取消导入，当前词库保持不变。'); return }
      const result = await callApi('POST', '/api/lexicon/import', { paths, fingerprint: state.fingerprint,rows:state.rows,columns:state.columns })
      await load(); $('lexiconManagement').open = false
      const conflicts=result.conflicts || []
      $('lexiconImportReport').hidden=!conflicts.length; $('lexiconImportReport').open=false
      $('lexiconImportSummary').textContent='查看 '+conflicts.length+' 项导入差异（已保留当前译法与标记）'
      $('lexiconImportConflicts').innerHTML=conflicts.map((item,index)=>'<div class="lexicon-import-conflict"><div><strong>'+esc(item.zh)+'</strong><p>当前：'+esc(item.existing.join(' / '))+'</p><p>导入：'+esc(item.incoming)+'</p><p class="hint">'+esc(item.reason)+'</p></div><button class="btn ghost sm" data-import-conflict="'+index+'">查看本机条目</button></div>').join('')
      $('lexiconImportConflicts').querySelectorAll('[data-import-conflict]').forEach(button=>{button.onclick=()=>{
        if(state.busy)return
        const item=conflicts[Number(button.dataset.importConflict)]
        $('termSearch').value=item.zh;state.page=0
        state.selected=filteredRows()[0]?.index ?? -1
        $('lexiconImportReport').open=false;setView('list');$('termEn').focus()
      }})
      status('已导入并保存：新增 '+result.added+' 条，补充 '+result.updated+' 条，'+result.unchanged+' 条保持不变。'+(conflicts.length?'有 '+conflicts.length+' 项差异，可展开查看。':''))
    }, '正在导入术语…')
  })
  action('exportTerms',()=>{
    if(!state.path)return
    return operation(async()=>{
      const target=await window.api.exportGlossaryPath($('lexiconExportFormat').value)
      if(!target){status('已取消导出，词库保持不变。');return}
      const result=await callApi('POST','/api/lexicon/export',{path:target.path,destination_fingerprint:target.fingerprint,rows:state.rows,columns:state.columns})
      status('已导出 '+result.count+' 条至 '+basename(result.path)+'。'+(state.dirty?'副本已包含当前改动；本机词库尚未保存。':'可将文件交给同事导入。'))
    },'正在导出词库…')
  })
  action('syncReviewed', async () => {
    if (!state.path || !await dirtyGuard()) return
    return operation(async () => {
      const result = await callApi('POST', '/api/lexicon/reviewed', { fingerprint: state.fingerprint })
      await load(); $('lexiconManagement').open = false
      const conflicts = result.review.conflicts
      status('已合并 ' + result.review.changes.length + ' 项核对结果。' + (conflicts.length ?
        '保留 ' + conflicts.length + ' 项团队自定义译法：' + conflicts.map(c => c.zh + '（建议 ' + c.suggested + '）').join('；') : '已保留团队备注和自定义术语。'))
    }, '正在合并核对结果…')
  })
  action('suggestVariants', async () => {
    const row = selectedRow()
    if (!row || state.busy || suggesting) return
    const entry = Object.fromEntries(Object.values(fields).map(key => [key, listFields.includes(key) ? lines(cell(row, key)) : cell(row, key)]))
    entry.priority = Number(cell(row, 'priority')) || 2; entry.source = cell(row, 'source')
    suggesting = true; availability(); status('正在补充候选写法…')
    try {
      const result = await callApi('POST', '/api/lexicon/suggest', { entry })
      if (!state.rows.includes(row) || $('lexiconModal').hidden) return
      changeCell(row, 'machine_variants', [...new Set([...lines(cell(row, 'machine_variants')), ...result.variants])].join('\n'))
      if (selectedRow() === row) { $('termMachine').value = cell(row, 'machine_variants'); resizeCell($('termMachine')) }
      status('候选已补充，请检查后保存。')
    } catch (error) { status(error.message, true); throw error }
    finally { suggesting = false; availability() }
  })
  // Reflow long cells without rebuilding rows or losing edits when the window changes.
  let gridWidth = 0
  new ResizeObserver(([entry]) => {
    const width = Math.round(entry.contentRect.width)
    if (!width || width === gridWidth) return
    gridWidth = width
    $('tableBody').querySelectorAll('textarea').forEach(resizeCell)
  }).observe($('lexiconGridPane').querySelector('.gridwrap'))
  return { state, refreshGlossary, isDirty: () => state.dirty, reload: () => load(true) }
}
