function installHistory({ $, action, callApi, esc, basename, openResult }) {
  let page = 0, generation = 0, records = [], debounce
  const kinds = { translate: '翻译', check: '校对', translate_review: '翻译并校对' }
  function details(row) {
    const values = [], counts = row.counts || {}
    if (counts.translated) values.push(`翻译 ${counts.translated} 段`)
    if (counts.segments) values.push(`检查 ${counts.segments} 段`)
    if (counts.replaced) values.push(`替换 ${counts.replaced} 处`)
    if (row.exports?.length) values.push(`输出 ${row.exports.length} 次`)
    if (row.last_output_at) values.push('最近输出：' + new Date(row.last_output_at).toLocaleString('zh-CN'))
    if (row.review_metadata_missing) values.push('早期校对的详细信息未保留')
    if (row.awaiting_confirmation) values.push('译文已暂存，待确认建议并保存最终文件')
    return values.length ? `<p class="hint history-summary">${esc(values.join(' · '))}</p>` : ''
  }
  const statuses = { queued:'排队中',running: '进行中', complete: '已完成', partial: '部分完成', cancelled: '已取消', failed: '未完成', interrupted: '已中断' }
  const now = new Date(), localDate = value => [value.getFullYear(), String(value.getMonth()+1).padStart(2,'0'), String(value.getDate()).padStart(2,'0')].join('-')
  $('historyStart').value = localDate(new Date(now.getFullYear(), now.getMonth(), 1)); $('historyEnd').value = localDate(now)
  async function load(reset = false) {
    if (reset) page = 0
    const token = ++generation
    const query = new URLSearchParams({ preset: $('historyPreset').value, kind: $('historyKind').value, text: $('historySearch').value.trim(), page })
    $('historyDates').hidden = $('historyPreset').value !== 'custom'
    if (!$('historyDates').hidden) { query.set('start', $('historyStart').value); query.set('end', $('historyEnd').value) }
    $('historyStatus').textContent = '正在读取记录…'
    try {
      const result = await callApi('GET', '/api/history?' + query)
      if (token !== generation) return
      records = result.records; page = result.page
      $('historyStatus').textContent = result.total ? `共 ${result.total} 条记录` : '当前时间段没有使用记录。'
      $('historyRows').innerHTML = records.map((row, index) => `<article class="history-entry"><div class="history-entry-head"><strong>${esc(kinds[row.kind] || row.kind)}</strong><span class="replacement-state ${row.status === 'complete' ? 'applied' : ''}">${esc(statuses[row.status] || row.status)}</span><time>${esc(new Date(row.started_at).toLocaleString('zh-CN'))}</time></div>${details(row)}<div class="history-files">${row.paths.map((path, file) => `<div><span title="${esc(path)}">${esc(basename(path))}</span><button class="btn ghost sm" data-history-source="${index}:${file}">原文件位置</button></div>`).join('')}</div>${row.outputs.length ? `<div class="history-outputs">${row.outputs.map((output, file) => `<div><div class="history-output-copy"><strong>${esc(basename(output.path))}</strong><p class="fpath">${esc(output.path)}</p></div>${output.comparison_id ? `<button class="btn ghost sm" data-comparison="${output.comparison_id}">中英对照</button>` : ''}<button class="btn ghost sm" data-history-output="${index}:${file}">打开文件</button><button class="btn ghost sm" data-history-folder="${index}:${file}">打开所在位置</button></div>`).join('')}</div>` : `<p class="hint">${row.output_dir ? '输出目录：' + esc(row.output_dir) : '尚无输出文件'}</p>`}${row.errors.length ? `<details><summary>查看任务提示</summary>${row.errors.map(error => `<p class="hint">${esc(error.error || error.reason || '')}</p>`).join('')}</details>` : ''}</article>`).join('')
      $('historyRows').querySelectorAll('.history-entry').forEach((entry,index) => {
        for (const draft of records[index].drafts || []) {
          const line=document.createElement('div'); line.className='history-files'
          const text=document.createElement('span');text.textContent='暂存译文：'+basename(draft.path);text.title=draft.path
          const button=document.createElement('button');button.className='btn ghost sm';button.textContent='打开暂存译文';button.onclick=()=>openResult('openFile',draft.path)
          line.append(text,button);entry.append(line)
        }
      })
      for (const [attribute, method, output] of [['source', 'openFolder', false], ['output', 'openFile', true], ['folder', 'openFolder', true]]) {
        $('historyRows').querySelectorAll('[data-history-' + attribute + ']').forEach(button => {
          button.onclick = () => {
            const [row, file] = button.getAttribute('data-history-' + attribute).split(':').map(Number)
            return openResult(method, output ? records[row].outputs[file].path : records[row].paths[file])
          }
        })
      }
      $('historyPage').textContent = `${page + 1} / ${Math.max(1, Math.ceil(result.total / result.page_size))}`
      $('historyPrev').disabled = !page; $('historyNext').disabled = (page + 1) * result.page_size >= result.total
    } catch (error) {
      if (token !== generation) return
      $('historyStatus').textContent = error.message; $('historyRows').innerHTML = ''
      $('historyPrev').disabled = $('historyNext').disabled = true
    }
  }
  action('openHistory', () => { $('historyModal').hidden = false; return load(true) })
  action('closeHistory', () => { $('historyModal').hidden = true; generation++ })
  action('refreshHistory', () => load())
  for (const id of ['historyPreset', 'historyKind']) $(id).onchange = () => load(true)
  $('historySearch').oninput = () => { clearTimeout(debounce); debounce = setTimeout(() => load(true), 250) }
  action('historyApplyDates', () => load(true))
  action('historyPrev', () => { page--; return load() })
  action('historyNext', () => { page++; return load() })
  return { refresh: load }
}
