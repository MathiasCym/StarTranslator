const $ = id => document.getElementById(id)
const state = { mode: 'check', files: [], references: [], pairs: {}, report: null, selected: new Set(),
  direction: localStorage.getItem('nova.direction') === 'en-zh' ? 'en-zh' : 'zh-en',
  outputDir: localStorage.getItem('nova.exportDir') || '', job: null, busy: false, outputs: [], edits: {}, exportRecords: [], savedReviewFiles: new Set() }
let lastSequence = -1, modelProvider = 'compatible'
let currentVersion = '', changelogLoaded = false
let integrityBusy = false, integrityResult = null, integrityFocus = null
const esc = value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
const basename = path => String(path || '').split(/[\\/]/).pop()
const delay = ms => new Promise(resolve => setTimeout(resolve, ms))
window.StarTextTranslation.mount({ button: $('openTextTranslation'), request: callApi, prefix: '/api/jobs' })
function toast(message, error = false) {
  const box = $('toast')
  box.innerHTML = ''
  const face = document.createElement('img')
  face.className = 'toast-face'; face.src = error ? 'assets/sad.png' : 'assets/happy.png'; face.alt = ''
  const text = document.createElement('span')
  text.className = 'toast-text'; text.textContent = message
  box.append(face, text)
  box.className = 'toast' + (error ? ' err' : ' ok'); box.hidden = false
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { box.hidden = true }, error ? 7000 : 3500)
}
async function callApi(method, path, body) {
  const result = await window.api.api(method, path, body)
  const taskSnapshot = /^\/api\/jobs(?:\/[^/?]+)?$/.test(path) && result?.id && ['queued', 'running', 'complete', 'failed', 'cancelled'].includes(result.status)
  if (!result || (result.error && !taskSnapshot)) throw new Error(result?.error || '服务没有返回结果')
  return result
}
function action(id, fn) {
  $(id).onclick = async event => { try { await fn(event) } catch (error) { toast(error.message, true) } }
}
function updateModelStatus(value) {
  if (!value || value.sequence < lastSequence) return
  lastSequence = value.sequence
  if ($('statusText').textContent !== value.message) $('statusText').textContent = value.message
  $('statusDot').className = 'dot ' + (value.state === 'connected' ? 'ok' : value.state === 'unavailable' ? 'err' : '')
  $('status').title = [value.model, value.detail, value.checkedAt ? '最近检测：' + new Date(value.checkedAt).toLocaleTimeString() : ''].filter(Boolean).join('\n')
}
window.api.onModelStatus(updateModelStatus)
window.api.modelStatus().then(updateModelStatus).catch(error => toast(error.message, true))
window.api.appVersion().then(version => { currentVersion = version; $('appVersion').textContent = 'v' + version; document.title = `星译官 v${version}` })
window.api.onBackendError(message => showTaskFailure(new Error('本地服务启动失败：' + message)))
window.api.onMaximizeChange(value => document.body.classList.toggle('maximized', !!value))
action('winMin', () => window.api.minimize())
action('winMax', () => window.api.toggleMaximize())
action('winClose', () => window.api.closeWindow())
$('outputDir').value = state.outputDir

function setMode(mode) {
  if (state.busy || state.exportBusy) return
  state.mode = mode; state.report = null; state.selected.clear()
  state.edits = {}; state.outputs = []; state.exportRecords = []; state.savedReviewFiles.clear()
  $('modeCheck').classList.toggle('active', mode === 'check'); $('modeTranslate').classList.toggle('active', mode === 'translate')
  $('modeCheck').setAttribute('aria-pressed', String(mode === 'check')); $('modeTranslate').setAttribute('aria-pressed', String(mode === 'translate'))
  const reverse = state.direction === 'en-zh'
  $('dropTitle').textContent = mode === 'check' ? (reverse ? '添加中文译文' : '添加英文译文') : (reverse ? '添加英文原稿' : '添加中文原稿')
  $('documentDirection').value = state.direction
  $('documentDirectionLabel').textContent = mode === 'check' ? '校对语言' : '翻译方向'
  $('documentDirection').options[0].textContent = mode === 'check' ? '英文' : '中文 → 英文'
  $('documentDirection').options[1].textContent = mode === 'check' ? '中文' : '英文 → 中文'
  $('workspaceHint').textContent = mode === 'check' ? '校准术语，打磨表达' : '专业译法，贯穿全文'
  $('llmOption').hidden = mode !== 'check'
  $('translationOptions').hidden = mode !== 'translate' || !state.files.some(path => /\.pptx$/i.test(path))
  $('runBtn').textContent = mode === 'check' ? '开始校对' : '开始翻译'
  $('runCombined').hidden = mode !== 'translate'
  $('scopeHint').textContent = mode === 'check' ? '修改由你确认，支持另存或覆盖原文件。' : '译文单独保存；图片内文字需手动处理。'
  showWorkspace()
}
$('documentDirection').onchange = () => {
  state.direction = $('documentDirection').value; localStorage.setItem('nova.direction', state.direction); setMode(state.mode)
}
function showWorkspace() {
  document.body.classList.remove('results-view')
  $('workspace').hidden = false; $('reportModal').hidden = true; $('reviewCompletePanel').hidden = true; $('translationPanel').hidden = true; $('taskFailurePanel').hidden = true
  renderFiles()
}
async function confirmResultNavigation(message, accept = '完成并返回') {
  if (state.busy || state.exportBusy || state.choosingOutput) return false
  if (state.report || !$('translationPanel').hidden || !$('reviewCompletePanel').hidden) {
    const findings = state.report?.findings || []
    const pending = findings.filter(f => f.editable && !f.applied).length
    const edited = findings.filter((f, i) => !f.applied && state.edits[i] !== undefined && state.edits[i] !== f.suggested).length
    const staged = state.exportRecords.filter(output => output.staged).length
    // Only successful saves for every reviewed file complete this result.
    // A partial export, pending edit or staged final file still needs confirmation.
    if (state.report && !pending && !edited && !staged && !state.report.errors?.length &&
        state.report.files.length && state.report.files.every(file => state.savedReviewFiles.has(file.path))) return true
    const details = [pending && `还有 ${pending} 项替换建议未应用。`, edited && `其中 ${edited} 项替换文本已编辑，尚未保存。`,
      staged && '译文目前仅暂存，最终文件尚未保存。',
      state.report && !state.exportRecords.length && '本次校对尚未导出文件。'].filter(Boolean)
    const accepted = await AppDialogs.ask({ title: '本次任务处理完成了吗？',
      message: [...details, message].join('\n'), accept, cancel: '留在当前结果' })
    return accepted && !state.busy && !state.exportBusy
  }
  return true
}
async function requestMode(mode) {
  if (mode === state.mode) return
  if (!await confirmResultNavigation(`切换到${mode === 'check' ? '校对' : '翻译'}后，将离开当前结果界面，尚未应用的修改不会写入文档。已保存的文件和历史记录会保留。`,
    state.exportRecords.some(output => output.staged) ? '仍然切换' : '完成并切换')) return
  setMode(mode)
}
async function returnToWorkspace() {
  if (await confirmResultNavigation('返回文档页面后，将离开当前结果界面，尚未应用的修改不会写入文档。已保存的文件和历史记录会保留。')) showWorkspace()
}
action('modeCheck', () => requestMode('check'))
action('modeTranslate', () => requestMode('translate'))
action('backBtn', async () => { if (await confirmResultNavigation('关闭报告后返回任务概览，报告、勾选状态和替换文本编辑都会保留，可再次打开报告继续处理。', '返回任务概览')) { $('reportModal').hidden = true; renderCheckCompletion() } })
action('viewReport', openReport); action('reviewCompleteBack', returnToWorkspace)
action('translationBack', returnToWorkspace); action('finishTranslation', returnToWorkspace)
action('failureBack', showWorkspace)
action('failureHistory', () => $('openHistory').click())
for (const id of ['failureExportLog', 'completionExportLog', 'translationExportLog']) action(id, async () => {
  $(id).disabled = true
  try {
    const job = state.job || {}, errors = [...(job.result?.errors || []), ...(state.report?.errors || [])]
    const output = await window.api.exportDiagnostics({ id: job.id, kind: job.kind || state.mode, status: job.status,
      phase: job.phase,detail:job.detail,done:job.done,total:job.total,outputs:job.result?.outputs||[],error: state.lastFailure || job.error, errors })
    if (output) toast('错误日志已保存：' + output)
  } finally { $(id).disabled = false }
})
function showTaskFailure(error) {
  const errors = state.job?.result?.errors || []
  state.lastFailure = error?.message?.trim() || errors.map(e => `${e.path ? basename(e.path) + '：' : ''}${e.error || '未提供错误说明'}`).join('\n') || '任务未能完成，可导出错误日志排查。'
  document.body.classList.remove('results-view')
  $('workspace').hidden = true; $('reportModal').hidden = true; $('reviewCompletePanel').hidden = true; $('translationPanel').hidden = true
  $('taskFailurePanel').hidden = false
  const uncertain = ['queued','running'].includes(state.job?.status)
  $('taskFailureTitle').textContent = uncertain ? '暂时无法获取任务状态' : '任务未完成'
  $('taskFailureNotice').textContent = uncertain ? '连接中断，后台任务可能仍在处理。可导出日志并在历史记录中查看状态。' : '原文件与已保存输出保留。继续任务时会复用本机断点，只处理未完成的部分。'
  $('failureResume').hidden = uncertain || !state.job?.id
  $('taskFailureDetails').textContent = state.lastFailure
}

function addFiles(paths, reference = false) {
  if (state.busy) return
  const list = reference ? state.references : state.files
  for (const path of paths) {
    if (DocumentInput.isTemporaryOfficeFile(path)) { toast(DocumentInput.temporaryFileMessage, true); continue }
    if (!DocumentInput.supported(path)) { toast(DocumentInput.formatsMessage, true); continue }
    if (!list.includes(path)) list.push(path)
  }
  renderFiles()
}
function renderFiles() {
  const hasPresentation = state.files.some(path => /\.pptx$/i.test(path))
  $('translationOptions').hidden = state.mode !== 'translate' || !hasPresentation
  if (!hasPresentation) {
    document.querySelector('[name=translationMode][value=faithful]').checked = true
    $('translationOptions').querySelector('.translation-help-button').setAttribute('aria-expanded', 'false')
    $('translationOptions').querySelector('.translation-help').hidden = true
  }
  $('filePanel').hidden = !state.files.length; $('fileCount').textContent = state.files.length
  $('dropzone').classList.toggle('compact', !!state.files.length)
  $('runBtn').disabled = !state.files.length || state.busy
  $('runCombined').disabled = !state.files.length || state.busy
  $('filelist').innerHTML = state.files.map((path, i) => `<li><div class="ico ${/\.docx$/i.test(path) ? 'doc' : 'ppt'}">${esc(path.split('.').pop().toUpperCase())}</div><div class="file-copy"><div class="fname">${esc(basename(path))}</div><div class="fpath">${esc(path)}</div></div><select data-pair="${i}" aria-label="对应原文或对照稿"><option value="">不指定对应稿</option>${state.references.filter(r => r !== path).map(r => `<option value="${esc(r)}"${state.pairs[path] === r ? ' selected' : ''}>${esc(basename(r))}</option>`).join('')}</select><button class="btn ghost sm" data-remove="${i}" aria-label="移除文件">×</button></li>`).join('')
  $('filelist').querySelectorAll('[data-remove]').forEach(button => { button.onclick = () => { state.files.splice(Number(button.dataset.remove), 1); renderFiles() } })
  $('filelist').querySelectorAll('[data-pair]').forEach(select => { select.onchange = () => { state.pairs[state.files[Number(select.dataset.pair)]] = select.value } })
  $('referenceCount').textContent = state.references.length ? `（${state.references.length} 份）` : '（可选）'
  $('referenceList').innerHTML = state.references.map((path, i) => `<li><div class="file-copy"><div>${esc(basename(path))}</div><div class="fpath">${esc(path)}</div></div><button class="btn ghost sm" data-remove="${i}">移除</button></li>`).join('')
  $('referenceList').querySelectorAll('[data-remove]').forEach(button => { button.onclick = () => { const removed = state.references.splice(Number(button.dataset.remove), 1)[0]; for (const key of Object.keys(state.pairs)) if (state.pairs[key] === removed) delete state.pairs[key]; renderFiles() } })
  for (const list of [$('filelist'), $('referenceList')]) {
    for (const copy of list.querySelectorAll('.file-copy')) copy.title = copy.querySelector('.fpath')?.textContent || ''
  }
}
action('pickBtn', async () => addFiles(await window.api.pickFiles()))
action('addMore', async () => addFiles(await window.api.pickFiles()))
action('clearFiles', () => { state.files = []; renderFiles() })
action('addReference', async () => addFiles(await window.api.pickReferences(), true))
action('clearReferences', () => { state.references = []; state.pairs = {}; renderFiles() })
action('pickOutput', async () => { const path = await window.api.pickDirectory(state.outputDir); if (path) { state.outputDir = path; $('outputDir').value = path; localStorage.setItem('nova.exportDir', path) } })
const dropzone = $('dropzone')
for (const name of ['dragenter', 'dragover']) dropzone.addEventListener(name, event => { event.preventDefault(); dropzone.classList.add('over') })
for (const name of ['dragleave', 'drop']) dropzone.addEventListener(name, event => { event.preventDefault(); dropzone.classList.remove('over') })
dropzone.addEventListener('drop', async event => { try { const paths = await Promise.all([...event.dataTransfer.files].map(file => window.api.pathForFile(file))); addFiles(paths.filter(Boolean)) } catch (error) { toast(error.message, true) } })
window.addEventListener('dragover', event => event.preventDefault()); window.addEventListener('drop', event => event.preventDefault())

function busy(value) {
  state.busy = value
  $('translationOptions').disabled = value
  $('jobProgressTrack').classList.toggle('active', value)
  for (const id of ['modeCheck', 'modeTranslate', 'documentDirection', 'openLexicon', 'openModel', 'runCombined']) $(id).disabled = value || (id === 'runCombined' && !state.files.length)
  $('jobPanel').hidden = !value; $('runBtn').disabled = value || !state.files.length
}
async function runTask(combined = false, restored = null) {
  if (state.busy || state.choosingOutput || (!restored && !state.files.length)) return
  let kind = restored?.kind || (combined && state.mode === 'translate' ? 'translate_review' : state.mode)
  let combinedOutput = restored?.combined_output || 'both'
  if (kind === 'translate_review' && !restored) {
    combinedOutput = await chooseCombinedOutput()
    if (!combinedOutput) return
  }
  const submitted = restored ? {paths:restored.paths,references:restored.references || [],pairs:restored.pairs || {}} : { paths: state.files.slice(), references: state.references.slice(), pairs: { ...state.pairs } }
  state.job = null; state.lastFailure = ''; state.report = null; state.outputs = []; state.exportRecords = []
  $('taskFailurePanel').hidden = true
  busy(true); $('workspace').hidden = true; $('reportModal').hidden = true; $('reviewCompletePanel').hidden = true; $('translationPanel').hidden = true
  document.body.classList.remove('results-view')
  $('jobMessage').textContent = '正在准备任务…'; $('jobProgress').removeAttribute('value'); $('cancelJob').disabled = false
  $('liveFindings').hidden = true; $('liveFindings').innerHTML = ''
  $('jobStages').hidden = kind !== 'translate_review'; renderJobPhase({ phase: 'preparing' })
  try {
    state.job = await callApi('POST', '/api/jobs', restored || { kind, ...submitted, direction: state.direction, translation_mode:document.querySelector('[name=translationMode]:checked').value, combined_output: combinedOutput, use_llm: $('useLlm').checked, workers:$('parallelWork').checked?3:1,output_dir: state.outputDir || null })
    let failures = 0
    while (['queued','running'].includes(state.job.status)) {
      await delay(600)
      try { state.job = await callApi('GET', '/api/jobs/' + state.job.id); failures = 0 } catch (error) { if (++failures > 3) throw error; continue }
      kind = state.job.kind || kind
      $('jobStages').hidden = kind !== 'translate_review'
      $('jobMessage').textContent = state.job.message.replaceAll('术语规则检查', '术语检查').replaceAll('规则检查', '术语检查').replaceAll('模型复核', '深度审校')
      renderJobPhase(state.job)
      renderLiveFindings(state.job.partial_findings || [])
    }
    kind = state.job.kind || kind
    consumeCompleted(state.job.result, submitted)
    const resultErrors = state.job.result?.errors || []
    if (state.job.status === 'failed' && !state.job.result?.findings?.length && !state.job.result?.outputs?.length) {
      throw new Error([state.job.error, ...resultErrors.map(e => `${e.path ? basename(e.path) + '：' : ''}${e.error}`)].filter(Boolean).join('\n'))
    }
    if (kind === 'translate_review' && state.job.result?.report) {
      state.outputs = state.job.result.outputs || []
      loadReport(state.job.result.report, state.outputs); showCheckCompletion()
    } else if (kind === 'check' && state.job.result?.findings) {
      loadReport(state.job.result); showCheckCompletion()
    } else if (state.job.status === 'failed') {
      renderLiveFindings(state.job.partial_findings || []); throw new Error(state.job.error)
    } else if (kind === 'translate' && state.job.result) {
      state.outputs = state.job.result.outputs || []; showTranslation(state.job.result, state.job.status === 'cancelled')
    } else { showWorkspace(); toast(state.job.message) }
  } catch (error) { showTaskFailure(error) } finally { busy(false); renderFiles() }
}
function chooseCombinedOutput() {
  state.choosingOutput = true; $('combinedOutputModal').hidden = false
  return new Promise(resolve => {
    const finish = value => { $('combinedOutputModal').hidden = true; state.choosingOutput = false; resolve(value) }
    $('combinedOutputStart').onclick = () => finish(document.querySelector('input[name=combinedOutput]:checked').value)
    $('combinedOutputCancel').onclick = () => finish(null)
  })
}
function renderJobPhase(job) {
  const labels = { preparing: '准备', translate: '翻译', repair:'补译与核对',image_text:'图片文字核对',output_check:'实际输出复查',layout:'文字排版',consistency:'全文一致性',format:'格式对照',check: '校对', export: '保存', complete: '完成' }
  const phase = labels[job.phase] || '处理'
  const unit=job.phase==='image_text'?'张':['format','output_check'].includes(job.phase)?'页':'段',elapsed=job.activity_at?Math.max(0,Math.floor(Date.now()/1000-job.activity_at)):0
  $('jobDetail').textContent = job.status === 'queued' ? '等待前面的任务完成，可随时取消' : [job.total?`${phase}：${job.done} / ${job.total} ${unit}`:phase,job.detail||(job.phase==='check'?'正在准备校对译文…':'正在处理文档…'),elapsed>=8?`本步骤已等待 ${elapsed} 秒`:''].filter(Boolean).join(' · ')
  const percent = Number.isFinite(job.percent) ? job.percent : job.total ? 100 * job.done / job.total : null
  const progress = $('jobProgress'), track = $('jobProgressTrack')
  if (percent !== null) {
    progress.value = Math.min(100, Math.max(0, percent))
    track.style.setProperty('--job-percent', progress.value + '%')
  } else {
    progress.removeAttribute('value'); track.style.setProperty('--job-percent', '100%')
  }
  track.classList.toggle('indeterminate', percent === null)
  progress.setAttribute('aria-valuetext', percent === null ? phase + '中' : phase + '：' + Math.round(progress.value) + '%')
  $('jobStages').querySelectorAll('[data-phase]').forEach(chip => {
    const active = chip.dataset.phase === (job.phase==='output_check'?'format':['repair','layout','consistency','image_text'].includes(job.phase)?'translate':job.phase)
    chip.classList.toggle('active', active)
    if (active) chip.setAttribute('aria-current', 'step'); else chip.removeAttribute('aria-current')
  })
}
const pathKey = path => String(path).replaceAll('/', '\\').toLowerCase()
function consumeCompleted(result, submitted) {
  const completed = new Set((result?.completed_paths || []).map(pathKey))
  state.files = state.files.filter(path => !completed.has(pathKey(path)))
  for (const path of Object.keys(state.pairs)) if (completed.has(pathKey(path))) delete state.pairs[path]
  if (submitted.paths.every(path => completed.has(pathKey(path)))) {
    const used = new Set(submitted.references.map(pathKey))
    state.references = state.references.filter(path => !used.has(pathKey(path)))
    for (const path of Object.keys(state.pairs)) if (used.has(pathKey(state.pairs[path]))) delete state.pairs[path]
  }
}
function loadReport(report, outputs = []) {
  state.report = report; state.selected.clear(); state.edits = {}; state.savedReviewFiles.clear()
  state.exportRecords = outputs.map(output => ({ path: output.path, layoutWarnings: output.layout_warnings || [],
    draft:report.kind==='translate_review'&&!output.review_exported,reportPath:output.path,
    staged: output.staged, targetDir: output.target_dir, comparison_id: output.comparison_id,
    text: output.staged ? '译文已暂存，确认建议后保存最终文件' : output.review_status === 'complete' ? '译文已保存，校对建议尚未应用' : '译文已保存，校对未完成' }))
  $('reportStatus').value = 'pending'; $('reportFilter').value = 'all'; $('searchBox').value = ''
  $('completionOutput').value = ''; $('reportOutput').value = ''
  report.findings.forEach((f, i) => { if (f.method === 'rule' && f.editable && !f.applied) state.selected.add(i) })
  $('exportResults').hidden = true
}
action('runBtn', () => runTask())
action('runCombined', () => runTask(true))
action('cancelJob', async () => { if (state.job) { await callApi('POST', `/api/jobs/${state.job.id}/cancel`, {}); $('cancelJob').disabled = true; $('jobMessage').textContent = '正在结束当前处理…' } })

// 模型复核过程中陆续发现的问题，实时显示在进度条下方。
function renderLiveFindings(findings) {
  const box = $('liveFindings')
  if (!findings.length) { box.hidden = true; box.innerHTML = ''; return }
  box.hidden = false
  const recent = findings.slice(-8).reverse()
  box.innerHTML = `<div class="live-head">已发现 ${findings.length} 项（复核结束时可在报告中逐条处理）</div>` +
    recent.map(f => `<div class="live-item"><span class="found">${esc(f.found_text)}</span> → <span class="suggest">${esc(f.suggested)}</span><span class="live-pos">${esc(f.file)}${f.slide ? ' 第 ' + f.slide + ' 页' : f.para ? ' 段 ' + f.para : ''}</span></div>`).join('')
}

function reportRows() {
  const query = $('searchBox').value.toLowerCase(), filter = $('reportFilter').value
  const status = $('reportStatus').value
  return (state.report?.findings || []).map((f, index) => ({ f, index })).filter(({ f, index }) =>
    (status === 'all' || (status === 'applied' ? f.applied : !f.applied)) &&
    (filter === 'all' || f.method === filter || f.kind === filter) && `${f.found_text} ${state.edits[index] ?? f.suggested} ${f.concept_zh} ${f.file}`.toLowerCase().includes(query))
}
function showCheckCompletion() {
  $('taskFailurePanel').hidden = true
  document.body.classList.remove('results-view')
  $('workspace').hidden = true; $('translationPanel').hidden = true; $('reportModal').hidden = true
  $('reviewCompletePanel').hidden = false
  renderCheckCompletion()
}
function reviewCompletionState(report, job) {
  const stats = report.stats || {}, findings = report.findings || []
  const manual = findings.filter(f => f.reason?.startsWith('翻译待核对：') || f.reason?.startsWith('英译中未完成：'))
  const manualTotal = stats.manual_review ?? manual.length
  const manualPending = manual.filter(f => !f.applied).length
  const untranslated = findings.filter(f => !f.applied && (f.reason?.startsWith('英译中未完成：') || /[\u3400-\u9fff]/.test(f.found_text || '') &&
    (f.reason?.startsWith('翻译待核对：') || f.reason?.startsWith('未译中文：')))).length
  const unreviewed = Math.max(0, (stats.unreviewed || 0) - manualTotal)
  // Older reports used "partial" for both human decisions and failed calls.
  const processing = stats.review_processing_status ||
    (stats.model_status === 'partial' && manualTotal && !unreviewed && !stats.errors && !stats.truncated ? 'complete' : stats.model_status)
  const errors = [...new Set([job?.error, ...(report.errors || []).map(e => e.error)].filter(Boolean))]
  if (stats.errors) errors.push(`${stats.errors} 段未能完成模型检查，已保留完成部分。`)
  if (stats.truncated) errors.push(`${stats.truncated} 段模型响应被截断，检查尚未完成。`)
  if (unreviewed && !stats.errors) errors.push(`${unreviewed} 段尚未完成模型检查。`)
  const interrupted = !!errors.length || job?.status === 'failed' || ['partial', 'unavailable', 'not_started'].includes(processing)
  const cancelled = job?.status === 'cancelled' || processing === 'cancelled'
  const notStarted = report.kind === 'translate_review' && processing === 'not_started'
  if (interrupted && !errors.length) errors.push(notStarted ? '校对尚未开始，已完成译文和断点已保留。' : '模型检查未能全部完成，已保留可用文件与完成部分。')
  return { manualPending, untranslated, interrupted, cancelled, notStarted, errors,
    canResume: (interrupted || cancelled || untranslated > 0) && job?.can_resume !== false }
}
function renderCheckCompletion() {
  const r = state.report
  if (!r) return
  const s = r.stats || {}, files = r.files || [], findings = r.findings || []
  const combined = r.kind === 'translate_review', label = combined ? '翻译并校对' : '校对'
  const { cancelled, interrupted, notStarted, manualPending, untranslated, errors, canResume } = reviewCompletionState(r, state.job)
  const reverseOutput = s.target_language === 'zh' || (r.outputs || []).some(output => output.direction === 'en-zh')
  $('completionResume').hidden = !canResume
  $('completionResume').textContent = untranslated && !interrupted && !cancelled ? '继续未完成翻译' : '从断点继续'
  $('completionIssue').hidden = !errors.length
  $('completionIssue').textContent = errors.join('；')
  $('completionExportLog').hidden = !interrupted
  $('reviewCompleteTitle').textContent = cancelled ? `${label}已取消` : notStarted ? '文件已保留 · 校对尚未开始' : interrupted ? `${label}已结束 · 部分检查未完成` : manualPending ? `${label}处理完成 · ${manualPending} 处待人工核对` : `${label}完成`
  $('reviewCompleteNotice').textContent = cancelled ? '已保留完成部分。' : interrupted ? '可用文件和已完成部分已保留，未完成原因见下方；可查看报告并保存当前文件。' : untranslated ? `仍有 ${untranslated} 处未译中文，可继续补译或在报告中填写英文；已完成内容和当前文件均保留。` : manualPending ? `自动处理已结束，${manualPending} 处内容需要人工确认，具体位置和原因已列在报告中；可以继续保存文件。` : s.model_status === 'not_requested' ? '术语检查已完成，打开报告查看并处理建议。' : '本次审校已完成，建议由你确认后应用。'
  if (reverseOutput && untranslated && !cancelled && !interrupted) $('reviewCompleteNotice').textContent = `仍有 ${untranslated} 处英文未完成翻译，可继续补译或在报告中填写中文；当前文件和完成部分已保留。`
  if (reverseOutput && s.model_status === 'not_requested') $('reviewCompleteNotice').textContent = '已读取中文文档。当前关闭深度审校，尚未执行中文语义检查。'
  $('completionSummary').innerHTML = [[files.length, '文档'], [s.segments ?? 0, '检查段落'], [findings.length, '审校建议'], [findings.filter(f => f.applied).length, '已替换建议']].map(([n, label]) => `<div class="stat"><div class="n">${n}</div><div class="l">${label}</div></div>`).join('')
  const remaining = findings.filter(f => !f.applied).length
  const needsSave = combined && state.exportRecords.some(o => o.staged)
  $('completionReviewTitle').textContent = remaining ? `下一步：查看 ${remaining} 项校对建议` : needsSave ? '下一步：确认并保存译文' : findings.length ? `${findings.length} 项建议已应用` : '本次没有替换建议'
  $('completionReviewHint').textContent = remaining ? '请打开报告查看修改原因与上下文，选择采纳、编辑或保留当前译文。建议不会自动应用。' : needsSave ? '打开报告查看检查范围，再点击“保存译文”输出最终文件。' : '仍可打开报告核对检查范围、提示和已采用的修改。'
  $('completionReviewStep').classList.toggle('has-suggestions',remaining > 0 || needsSave)
  $('viewReport').textContent = remaining ? '查看并处理校对建议' : needsSave ? '查看报告并保存译文' : '查看校对报告'
  $('completionFiles').textContent = files.map(f => f.source?basename(f.source):f.name||basename(f.path||'')).join(' · ')
  $('completionFiles').title = files.map(f => f.path).join('\n')
  $('completionDetails').textContent = combined ? `已翻译 ${state.outputs.reduce((n, o) => n + (o.translated || 0), 0)} 段，校对 ${s.judged || 0} 段${manualPending ? `；另有 ${manualPending} 处待人工核对` : ''}。原稿保留，校对建议由你确认后应用。${r.output_mode === 'final' ? state.exportRecords.some(o => o.staged) ? '当前译文暂存，确认后保存最终文件。' : '最终文件已保存。' : ''}` : ''
  $('completionDetails').hidden = !combined
  renderCompletionOutput()
}
function renderCompletionOutput() {
  const outputs = (state.exportRecords || []).filter(r => r.path), chosen = $('completionOutput').value
  $('completionOutput').innerHTML = outputs.map((r, i) => `<option value="${i}">${esc(basename(r.path))}${r.staged||r.draft?' · 翻译初稿':' · 已保存稿'}</option>`).join('')
  $('completionOutput').hidden = outputs.length < 2
  $('completionOutput').value = chosen && Number(chosen) < outputs.length ? chosen : String(outputs.length - 1)
  const output = outputs[Number($('completionOutput').value)], source = state.report?.files?.[0]?.path || ''
  const path = output?.staged ? output.targetDir : output?.path || state.outputDir || source
  $('completionPath').textContent = output?.staged ? '译文已暂存，确认建议后保存至：' + output.targetDir : output?.path || '尚未应用修改，原文件保留。'
  $('completionPath').title = output?.path || ''
  $('completionOpenFolder').disabled = !path
  $('completionOpenFolder').onclick = () => openResult('openFolder', path)
  $('completionOpenFile').hidden = !output
  $('completionOpenFile').textContent = output?.staged ? '预览暂存译文' : '打开文件'
  $('completionOpenFile').onclick = () => output && openResult('openFile', output.path)
  const compare=$('completionCompare'),draft=!!(output?.staged||output?.draft)
  compare.hidden=!output?.comparison_id
  compare.innerHTML=PageComparison.buttonContent+`<span>· ${draft?'初稿':'已保存稿'}</span>`
  compare.title=output?`对照中文原稿与${draft?'翻译初稿':'当前保存的文件'}：${basename(output.path)}`:''
  if(output?.comparison_id)compare.dataset.comparison=output.comparison_id
  else delete compare.dataset.comparison
}
$('completionOutput').onchange = renderCompletionOutput
function openReport() {
  if (!state.report) return
  renderReport()
  $('reportModal').hidden = false
}
function selectableFinding(f, index) { return !!(f?.editable && !f.applied && String(state.edits[index] ?? f.suggested ?? '').trim()) }
function updateSelection() {
  for (const index of [...state.selected]) if (!selectableFinding(state.report?.findings[index], index)) state.selected.delete(index)
  const eligible = reportRows().filter(({f,index}) => selectableFinding(f,index)), count = eligible.filter(({index}) => state.selected.has(index)).length
  $('selectAll').checked = eligible.length > 0 && count === eligible.length
  $('selectAll').indeterminate = count > 0 && count < eligible.length
  const empty = reportRows().filter(({f,index}) => f.editable && !f.applied && !selectableFinding(f,index)).length
  $('selectAll').title = `选择当前筛选下全部 ${eligible.length} 项可应用建议` + (empty ? `；另有 ${empty} 项需先填写替换文本` : '')
  $('selInfo').textContent = `已选 ${state.selected.size} 项` + (empty ? ` · ${empty} 项待填写` : '')
  $('selInfo').title = '同段重复出现的内容会一并处理。'
  $('applyBtn').disabled = $('overwriteBtn').disabled = !!state.exportBusy || !state.selected.size
  $('saveCurrentBtn').disabled = !!state.exportBusy || !state.report?.files.some(file => file.review_available !== false)
  for (const id of ['reportStatus', 'reportFilter', 'searchBox', 'selectRules', 'selectAll', 'reportCompare', 'reportOutput']) $(id).disabled = !!state.exportBusy
  $('selectAll').disabled = !!state.exportBusy || !eligible.length
  $('reportBody').querySelectorAll('[data-edit]').forEach(input => { input.disabled = !!state.exportBusy })
  $('reportBody').querySelectorAll('[data-index]').forEach(input => { const i = Number(input.dataset.index), f = state.report.findings[i]; input.disabled = !!state.exportBusy || !f.editable || f.applied || !(state.edits[i] ?? f.suggested).trim() })
}
function renderReport() {
  const r = state.report, s = r.stats
  const finalOnly = r.kind === 'translate_review' && r.output_mode === 'final'
  const noSuggestions = !r.findings.length
  $('applyBtn').textContent = finalOnly ? '应用所选并保存最终文件' : r.kind === 'translate_review' ? '应用所选并保存校对文件' : '应用所选并另存'
  $('applyBtn').hidden = noSuggestions
  $('overwriteBtn').hidden = r.kind === 'translate_review' || noSuggestions || r.files.some(file => /\.pdf$/i.test(file.path))
  $('saveCurrentBtn').hidden = r.kind !== 'translate_review' && !noSuggestions
  $('saveCurrentBtn').textContent = noSuggestions ? '保存译文' : '不应用建议，保存当前译文'
  $('overwriteBtn').textContent = r.kind === 'translate_review' ? '应用所选并覆盖译文文件' : '应用所选并覆盖原文件'
  $('summary').innerHTML = [[r.findings.length, '审校建议'], [s.rule_hits, '术语规范'], [s.llm_hits, '深度审校'], [`${s.judged}/${s.segments}`, '深度审校段落']].map(([n,l]) => `<div class="stat"><div class="n">${n}</div><div class="l">${l}</div></div>`).join('')
  const coverage = s.model_status === 'complete' ? '审校完成，可选中建议并应用修改。' : s.model_status === 'not_requested' ? '术语检查已完成；拼写、语法及翻译准确性需启用深度审校。' : '深度审校未完成。已完成的建议仍可查看，剩余内容尚未检查。'
  $('reportNotice').textContent = [coverage, s.consistency_hits ? `另有 ${s.consistency_hits} 项全文用语统一建议，确认后可应用。` : '', ...(s.warnings || []), ...(r.errors || []).map(e => `${e.path ? basename(e.path) + '：' : ''}${e.error}`), s.unsupported ? `${s.unsupported} 处图片、图表或复杂文字结构不能自动改写，请人工检查。` : ''].filter(Boolean).join('\n')
  const manual = r.kind === 'translate_review' ? state.outputs.flatMap(o => (o.review_items || []).map(w => ({ ...w, file: basename(o.path) }))) : []
  $('reportManualNotes').hidden = !manual.length
  $('reportManualNotes').innerHTML = manual.length ? `<summary>查看翻译中需人工核对的内容（${manual.length} 处）</summary>${manual.map(w => `<p class="hint">${esc(w.file)}${w.slide ? ' · 第 ' + w.slide + ' 页' : ''}：${esc(w.reason)}<br>原稿：${esc(w.source_text)}<br>当前内容：${esc(w.translation)}</p>`).join('')}` : ''
  const rows = reportRows()
  $('reportBody').innerHTML = rows.length ? rows.map(({ f, index }) => `<article class="suggestion-card" data-finding="${index}"><div class="suggestion-head"><input type="checkbox" aria-label="选择此项建议" data-index="${index}"${state.selected.has(index) ? ' checked' : ''}${!f.editable || f.applied ? ' disabled' : ''}><span class="pos" title="${esc(f.file_path)}">${esc(f.file)} · ${f.slide ? '第 ' + f.slide + ' 页' : '段 ' + f.para}</span><span class="replacement-state ${f.applied ? 'applied' : ''}">${f.applied ? '已替换' : '未替换'}</span><span class="tag ${f.method === 'rule' ? 'high' : 'llm'}">${f.method === 'rule' ? '术语规范' : f.method === 'consistency' ? '全文一致性' : '深度审校'}</span></div><div class="suggestion-copy"><div><span class="source-label">原文${f.occurrences > 1 ? ' · ' + f.occurrences + ' 处' : ''}</span><p class="suggestion-source">${esc(f.found_text)}</p></div><label>${f.applied ? '已采用的替换文本' : '替换为 · 可编辑'}<textarea class="suggestion-text" data-edit="${index}" aria-label="编辑替换文本"${!f.editable || f.applied ? ' readonly' : ''}>${esc(state.edits[index] ?? f.suggested)}</textarea></label></div><p class="ctx">${f.concept_zh ? esc(f.concept_zh) + ' · ' : ''}${esc(f.reason)}${f.editable ? '' : '<br>' + esc(f.not_editable_reason)}</p><details><summary class="hint">查看上下文</summary><p class="ctx">${esc(f.context)}</p></details></article>`).join('') : '<p class="notice">当前筛选下没有建议。已替换的项目可切换筛选查看。</p>'
  $('reportBody').querySelectorAll('input').forEach(input => { input.onchange = () => { const i = Number(input.dataset.index); input.checked ? state.selected.add(i) : state.selected.delete(i); updateSelection() } })
  $('reportBody').querySelectorAll('[data-edit]').forEach(input => { input.oninput = () => {
    const index = Number(input.dataset.edit); state.edits[index] = input.value
    const select = input.closest('.suggestion-card').querySelector('[data-index]')
    select.disabled = !input.value.trim()
    if (!input.value.trim()) { state.selected.delete(index); select.checked = false }
    updateSelection()
  } })
  updateSelection()
  renderReportOutputs()
  renderCheckCompletion()
}
$('reportFilter').onchange = $('reportStatus').onchange = renderReport; $('searchBox').oninput = renderReport
$('selectAll').onchange = event => { const checked = event.target.checked; for (const { f, index } of reportRows()) if (selectableFinding(f,index)) checked ? state.selected.add(index) : state.selected.delete(index); renderReport() }
action('selectRules', () => { reportRows().forEach(({f, index}) => { if (['rule', 'consistency'].includes(f.method) && f.editable && !f.applied && (state.edits[index] ?? f.suggested).trim()) state.selected.add(index) }); renderReport() })
async function exportReport(overwrite = false, saveCurrent = false) {
  if (state.exportBusy || (!state.selected.size && !saveCurrent)) return
  state.exportBusy = true; updateSelection(); $('backBtn').disabled = true
  $('exportProgressBox').hidden = false
  const groups = new Map(), results = []
  try {
    if (saveCurrent || state.report.output_mode === 'final') for (const file of state.report.files) if (file.review_available !== false) groups.set(file.path, { selected: {}, edits: [] })
    if (!saveCurrent) for (const index of state.selected) { const f = state.report.findings[index]; if (!f.editable || f.applied) continue; if (!groups.has(f.file_path)) groups.set(f.file_path, { selected: {}, edits: [] }); const group = groups.get(f.file_path), text = (state.edits[index] ?? f.suggested).trim(); if (!text) throw new Error('替换文本不能为空。'); (group.selected[f.segment_id] ||= []).push([f.found_text, text]); group.edits.push({ index, text }) }
    for (const [path, group] of groups) {
      try {
        let task = await callApi('POST', '/api/reports/exports', { report_id: state.report.report_id, path, ...group, save_unchanged: saveCurrent || state.report.output_mode === 'final', output_dir: overwrite ? null : state.outputDir || null, overwrite })
        while (['queued','running'].includes(task.status)) {
          $('exportProgressText').textContent = `${basename(path)} · ${task.message}` + (task.total ? `（${task.done}/${task.total}）` : '')
          if (task.total) $('exportProgress').value = 100 * task.done / task.total
          else $('exportProgress').removeAttribute('value')
          await delay(400)
          task = await callApi('GET', '/api/reports/exports/' + task.id)
        }
        if (task.status !== 'complete') throw new Error(task.error || '保存未完成。')
        const r = task.result
        state.savedReviewFiles.add(path)
        results.push({ path: r.output,reportPath:path, comparison_id: r.comparison_id, layoutWarnings: r.layout_warnings || [], text: (state.report.kind === 'translate_review' ? r.overwritten ? '已更新校对文件，' : '校对文件已保存，' : r.overwritten ? '已覆盖原文件，' : '已另存，') + `替换 ${r.applied_count} 处` + (r.failed.length ? `；${r.failed.length} 项未完成` : '') + (r.content_warnings?.length ? '；'+r.content_warnings.join('；') : '') })
        if (state.report.kind === 'translate_review') {
          state.exportRecords = state.exportRecords.filter(record => record.path!==path&&record.reportPath!==path&&record.path!==r.output)
          state.outputs=state.outputs.map(output=>output.path===path||output.reportPath===path?{...output,path:r.output,reportPath:path,comparison_id:r.comparison_id,staged:false,review_exported:true}:output)
        }
        for (const { index, finding } of r.finding_updates || []) { state.report.findings[index] = finding; if (!finding.editable || finding.applied) { state.selected.delete(index); delete state.edits[index] } }
      }
      catch (error) { results.push({ text: `${basename(path)}：${error.message}` }) }
    }
    state.exportRecords.push(...results); $('reportOutput').value = ''; $('completionOutput').value = ''; $('reportStatus').value = 'pending'; renderReport()
  } finally { state.exportBusy = false; $('exportProgressBox').hidden = true; $('backBtn').disabled = false; updateSelection() }
}
action('applyBtn', () => exportReport(false))
action('overwriteBtn', () => exportReport(true))
action('saveCurrentBtn', () => exportReport(false, true))
function renderReportOutputs() {
  const records = state.exportRecords || [], outputs = records.filter(r => r.path)
  const chosen = $('reportOutput').value
  $('reportOutput').innerHTML = outputs.map((r, i) => `<option value="${i}">${esc(basename(r.path))}</option>`).join('')
  $('reportOutput').hidden = outputs.length < 2
  $('reportOutput').value = chosen && Number(chosen) < outputs.length ? chosen : String(outputs.length - 1)
  const output = outputs[Number($('reportOutput').value)]
  const source = state.report?.files?.[0]?.path || state.report?.findings?.[0]?.file_path || ''
  const path = output?.staged ? output.targetDir : output?.path || state.outputDir || source
  $('reportOutputPath').textContent = output?.staged ? '译文已暂存，确认后保存至：' + output.targetDir : output?.path || '应用修改后，输出文件会出现在这里。'
  $('reportOutputPath').title = output?.path || ''
  $('reportOpenFolder').disabled = !path; $('reportOpenFile').disabled = !output
  $('reportOpenFile').textContent = output?.staged ? '预览暂存译文' : '打开文件'
  $('reportOpenFolder').onclick = () => openResult('openFolder', path)
  $('reportOpenFile').onclick = () => output && openResult('openFile', output.path)
  const compare=$('reportCompare')
  compare.hidden=!output?.comparison_id;compare.disabled=!!state.exportBusy
  compare.innerHTML=PageComparison.buttonContent+`<span>· ${output?.staged||output?.draft?'初稿':'已保存稿'}</span>`
  if(output?.comparison_id)compare.dataset.comparison=output.comparison_id
  else delete compare.dataset.comparison
  compare.title=output?.staged||output?.draft?'对照原稿与翻译初稿':'对照原稿与当前保存的文件'
  $('exportResults').hidden = !records.length
  $('exportResults').innerHTML = records.slice().reverse().map(r => `<div>${esc(r.text)}${r.path ? '<p class="fpath">' + esc(basename(r.path)) + '</p>' : ''}${layoutWarningMarkup(r.layoutWarnings)}</div>`).join('')
}
$('reportOutput').onchange = renderReportOutputs
async function openResult(method, path) { try { await window.api[method](path) } catch (error) { toast(error.message, true) } }
function layoutWarningMarkup(warnings = []) {
  return warnings.length ? `<details><summary>查看版式提示（${warnings.length} 处）</summary>${warnings.map(w => `<p class="hint">${esc(w.reason)}${w.slide ? ' 第 ' + w.slide + ' 页' : ''}${w.text ? ' · ' + esc(w.text) : ''}</p>`).join('')}</details>` : ''
}
function showTranslation(result, cancelled) {
  $('taskFailurePanel').hidden = true
  document.body.classList.add('results-view')
  state.outputs = result.outputs
  $('workspace').hidden = true; $('reviewCompletePanel').hidden = true; $('reportModal').hidden = true; $('translationPanel').hidden = false
  const pending = result.outputs.some(r => r.needs_review)
  const combined = result.outputs.some(r => r.auto_reviewed)
  $('translationFace').src = cancelled || !result.outputs.length ? 'assets/sad.png' : 'assets/happy.png'
  $('translationTitle').textContent = cancelled ? '翻译已取消，保留已完成文件' : !result.outputs.length ? '翻译未完成' : pending ? '翻译草稿已保存 · 部分内容待核对' : result.errors.length ? '部分译文已完成' : '翻译结果 · 是否继续校对？'
  if (combined && !cancelled && result.outputs.length) $('translationTitle').textContent = pending || result.errors.length ? '翻译并校对 · 部分内容待检查' : '翻译并校对已完成'
  $('translationNotice').textContent = pending ? '已保留处理结果，原稿未修改。待核对内容与未译正文列在下方，可继续结合原稿校对。' : result.outputs.length ? '译文单独保存，原稿保留。文字排版已适配，仍需关注的位置列在下方。' : '尚未生成译文，原稿保留。未完成的原因见下方。'
  $('translationFiles').innerHTML = result.outputs.map((r, i) => `<li><div class="file-copy"><div>${esc(basename(r.path))}${r.needs_review ? ' · 待核对草稿' : ''}</div><div class="fpath">翻译 ${r.translated} 段${r.needs_review ? `；${r.needs_review} 段待核对` : ''}${r.untranslated ? `；${r.untranslated} 处仍有中文` : ''}${r.skipped ? `；${r.skipped} 处需人工检查` : ''}。${r.layout_checked ? ' 已检查文档结构并适配文字排版。' : ''}<br>${esc(r.path)}</div>${r.review_items?.length ? `<details open><summary>查看待核对内容（${r.review_items.length} 处）</summary>${r.review_items.map(w => `<p class="hint">${w.slide ? '第 ' + w.slide + ' 页 · ' : ''}${esc(w.reason)}<br>原稿：${esc(w.source_text)}<br>当前内容：${esc(w.translation)}</p>`).join('')}</details>` : ''}${r.warnings.length ? `<details><summary>查看未处理内容</summary>${r.warnings.map(w => `<p class="hint">${w.slide ? '第' + w.slide + '页：' : ''}${esc(w.reason)} ${esc(w.text)}</p>`).join('')}</details>` : ''}${r.consistency_hits ? `<p class="hint">发现 ${r.consistency_hits} 项全文用语统一建议，继续校对可在报告中确认。</p>` : ''}${layoutWarningMarkup(r.layout_warnings)}</div><div class="row-actions">${r.comparison_id ? `<button class="btn ghost sm comparison-button" data-comparison="${r.comparison_id}">${PageComparison.buttonContent}</button>` : ''}<button class="btn ghost sm" data-open="${i}">打开译文</button><button class="btn ghost sm" data-folder="${i}">所在位置</button></div></li>`).join('')
  $('translationFiles').querySelectorAll('[data-open]').forEach(b => { b.onclick = () => openResult('openFile', result.outputs[Number(b.dataset.open)].path) })
  $('translationFiles').querySelectorAll('[data-folder]').forEach(b => { b.onclick = () => openResult('openFolder', result.outputs[Number(b.dataset.folder)].path) })
  $('translationErrors').textContent = result.errors.map(e => `${e.path ? basename(e.path) + '：' : ''}${e.error || '未提供错误说明'}`).join('\n')
  $('translationExportLog').hidden = !result.errors.length
  $('translationErrors').hidden = !result.errors.length
  $('reviewTranslation').disabled = !result.outputs.length
  $('reviewTranslation').textContent = combined ? '再次校对' : '继续校对译文'
  $('finishTranslation').textContent = result.outputs.length ? '暂不校对' : '返回文档'
  if (combined) $('finishTranslation').textContent = '返回文档'
  $('translationOutput').innerHTML = result.outputs.map((r,i) => `<option value="${i}">${esc(basename(r.path))}</option>`).join('')
  $('translationOutput').hidden = result.outputs.length < 2
  $('translationOutput').value = '0'; renderTranslationOutput()
}
function renderTranslationOutput() {
  const output = state.outputs[Number($('translationOutput').value)]
  $('translationOutputPath').textContent = output?.path || '尚无输出文件'
  $('translationOutputPath').title = output?.path || ''
  $('translationOpenFolder').disabled = $('translationOpenFile').disabled = !output
  $('translationOpenFolder').onclick = () => output && openResult('openFolder', output.path)
  $('translationOpenFile').onclick = () => output && openResult('openFile', output.path)
}
$('translationOutput').onchange = renderTranslationOutput
action('reviewTranslation', async () => {
  const outputs = state.outputs.slice(); setMode('check'); state.files = outputs.map(r => r.path)
  for (const r of outputs) { if (!state.references.includes(r.source)) state.references.push(r.source); state.pairs[r.path] = r.source }
  $('useLlm').checked = true; renderFiles(); await runTask()
})

const lexiconEditor = installLexicon({ $, action, callApi, esc, basename })
const refreshGlossary = lexiconEditor.refreshGlossary
async function resumeHistoryTask(row) {
  if (state.busy || state.exportBusy) { toast('请先等待当前任务结束'); return }
  if (!await confirmResultNavigation('将从本机断点继续处理这项任务，已保存的输出文件保留。','继续任务')) return
  const data = await callApi('GET','/api/history/'+encodeURIComponent(row.id)+'/resume')
  $('historyModal').hidden = true
  state.direction = data.direction === 'en-zh' ? 'en-zh' : 'zh-en'
  setMode(data.kind === 'check' ? 'check' : 'translate')
  await runTask(false,data)
}
action('failureResume',()=>resumeHistoryTask(state.job))
action('completionResume',()=>resumeHistoryTask(state.job))
const historyEditor = installHistory({ $, action, callApi, esc, basename, openResult, resumeTask:resumeHistoryTask })

/* ---------- 关于星译官 ---------- */
function parseChangelog(text) {
  const releases = []
  let current = null
  for (const raw of String(text || '').split(/\r?\n/)) {
    const line = raw.trim()
    const heading = line.match(/^##\s*\[([^\]]+)\]\s*(?:[-–—]\s*(\S+))?/)
    if (heading) { current = { version: heading[1], date: heading[2] || '', items: [] }; releases.push(current); continue }
    const bullet = line.match(/^(?:[-*]|\d+[.)])\s+(.+)$/)
    if (bullet && current) { current.items.push(bullet[1]); if (/^\d+[.)]/.test(line)) current.numbered = true }
  }
  return releases
}
function renderAbout(releases) {
  const log = $('aboutLog')
  if (!releases.length) { log.innerHTML = '<p class="hint">未找到更新记录。</p>'; return }
  log.innerHTML = releases.map(release => {
    const isCurrent = release.version === currentVersion
    const list = release.numbered ? 'ol' : 'ul'
    const items = release.items.length
      ? `<${list}>${release.items.map(i => `<li>${esc(i)}</li>`).join('')}</${list}>`
      : '<p class="hint">本版无详细说明。</p>'
    return `<section class="about-release${isCurrent ? ' current' : ''}">
      <div class="about-release-head"><span class="about-ver">v${esc(release.version)}</span>
      ${release.date ? `<span class="about-date">${esc(release.date)}</span>` : ''}
      ${isCurrent ? '<span class="about-badge">当前版本</span>' : ''}</div>${items}</section>`
  }).join('')
}
async function openAbout() {
  $('aboutModal').hidden = false
  $('authorContactDetails').hidden = true
  $('contactAuthor').setAttribute('aria-expanded', 'false')
  $('authorContactStatus').textContent = ''
  $('aboutVersion').textContent = currentVersion ? 'v' + currentVersion : ''
  if (!changelogLoaded) {
    $('aboutLog').innerHTML = '<p class="hint">正在读取更新记录…</p>'
    try { renderAbout(parseChangelog(await window.api.changelog())); changelogLoaded = true }
    catch (error) { $('aboutLog').innerHTML = `<p class="hint">${esc(error.message)}</p>` }
  }
}
action('openAbout', openAbout)
action('aboutOpen', openAbout)
action('closeAbout', () => { $('aboutModal').hidden = true })
action('contactAuthor', () => {
  const details = $('authorContactDetails')
  details.hidden = !details.hidden
  $('contactAuthor').setAttribute('aria-expanded', String(!details.hidden))
})
action('copyAuthorEmail', async () => {
  $('authorContactStatus').textContent = ''
  try {
    await window.api.copyAuthorEmail()
    $('authorContactStatus').textContent = '邮箱已复制'
  } catch (error) {
    $('authorContactStatus').textContent = '复制未完成，可手动选择邮箱复制。'
    throw error
  }
})

function integrityProgress(value) {
  if (!integrityBusy) return
  const labels = { checking: '校验程序文件', preparing: '验证本机修复副本', repairing: '自动修复组件', rechecking: '重新校验程序文件', testing: '检查文档组件能否启动' }
  $('integrityStatus').textContent = `${labels[value.phase] || '正在处理'} · ${value.percent || 0}%${value.total ? `（${value.checked || 0} / ${value.total} 项）` : ''}`
  $('integrityProgress').hidden = false; $('integrityProgress').value = value.percent || 0
}
window.api.onInstallationStatus(integrityProgress)
action('openIntegrity', () => {
  integrityFocus = document.activeElement
  $('integrityModal').hidden = false
  $('startIntegrity').focus()
})
function closeIntegrity() {
  if (integrityBusy) return
  $('integrityModal').hidden = true
  if (integrityFocus?.isConnected) integrityFocus.focus()
}
action('closeIntegrity', closeIntegrity)
$('integrityModal').addEventListener('keydown', event => {
  if (event.key === 'Escape') { event.preventDefault(); closeIntegrity() }
  if (event.key === 'Tab') {
    const controls = [...$('integrityModal').querySelectorAll('button:not(:disabled)')].filter(el => !el.hidden)
    if (!controls.length) { event.preventDefault(); return }
    const first = controls[0], last = controls.at(-1)
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  }
})
action('startIntegrity', async () => {
  if (integrityBusy) return
  if (state.busy || state.exportBusy || state.choosingOutput || profileBusy || lexiconEditor.state.busy) {
    $('integrityStatus').textContent = '正在处理任务或保存数据，请完成后再校验。'; return
  }
  const allowRestart = (!$('workspace').hidden || (!state.report && $('translationPanel').hidden)) && !lexiconEditor.isDirty() && !profileDirty()
  integrityBusy = true; integrityResult = null
  $('startIntegrity').disabled = $('closeIntegrity').disabled = true
  $('integrityExportLog').hidden = true; $('integrityDetails').hidden = true; $('integrityDetails').replaceChildren()
  $('integrityProgress').hidden = false; $('integrityProgress').value = 0; $('integrityStatus').textContent = '正在准备校验…'
  $('startIntegrity').textContent = '正在校验…'; $('integrityStatus').focus()
  try {
    const result = integrityResult = await window.api.checkInstallation(allowRestart)
    $('integrityStatus').textContent = result.message
    $('integrityProgress').value = 100
    for (const item of [...(result.failures || []), ...(result.repairErrors || []), ...(result.componentErrors || []), ...(result.serviceError ? [{ path: '本地服务', reason: result.serviceError }] : [])]) {
      const row = document.createElement('p'); row.textContent = `${item.path}：${item.reason}`; $('integrityDetails').append(row)
    }
    $('integrityDetails').hidden = !$('integrityDetails').childElementCount
    $('integrityExportLog').hidden = result.complete && !result.serviceError
  } catch (error) {
    integrityResult = { message: error.message, complete: false }
    $('integrityStatus').textContent = error.message; $('integrityProgress').hidden = true; $('integrityExportLog').hidden = false
  } finally {
    integrityBusy = false; $('startIntegrity').disabled = $('closeIntegrity').disabled = false
    $('startIntegrity').textContent = '重新校验并自动修复'; $('startIntegrity').focus()
  }
})
action('integrityExportLog', async () => {
  $('integrityExportLog').disabled = true
  try { const file = await window.api.exportDiagnostics({ kind: 'integrity', status: integrityResult?.complete ? 'complete' : 'failed', error: integrityResult?.message }); if (file) toast('诊断日志已保存：' + file) }
  finally { $('integrityExportLog').disabled = false }
})

let profileState = { active: '', max: 5, profiles: [], editing: '' }
let profileBusy = false, profileBaseline = ''
const profileFields = ['modelProfileName', 'modelPreset', 'modelFormat', 'modelAuth', 'modelUrl', 'modelName', 'modelKey']
function updateProtocolFields() {
  const internal = modelProvider === 'intranet'
  $('modelFormatField').hidden = internal; $('modelAuthField').hidden = internal
  if (internal) { $('modelFormat').value = 'openai'; $('modelAuth').value = 'auto' }
  $('modelFormatHint').textContent = internal ? '保存不会切换连接，点击“使用配置”后生效。' :
    $('modelFormat').value === 'anthropic' ? 'Claude 原生接口选择 Anthropic；中转服务的密钥发送方式以服务方说明为准。' : '兼容接口选择 OpenAI；中转服务支持 Claude 时也可能使用此格式。'
}
$('modelFormat').onchange = updateProtocolFields
function profileFormValue() { return JSON.stringify([modelProvider, ...profileFields.map(id => $(id).value)]) }
function profileDirty() { return !$('modelModal').hidden && profileBaseline && profileBaseline !== profileFormValue() }
async function profileGuard(accept = '放弃修改') {
  if (profileBusy) return false
  return !profileDirty() || await AppDialogs.ask({ title: '放弃未保存的修改？',
    message: '当前模型配置的修改尚未保存。放弃后，本次填写的内容不会保留。', accept })
}
function updateProfileControls() {
  $('modelSave').disabled = profileBusy
  $('modelUse').disabled = profileBusy || !profileState.editing
  $('modelClose').disabled = profileBusy
  $('profileNew').disabled = profileBusy || profileState.profiles.length >= profileState.max
  $('profileList').querySelectorAll('button').forEach(b => { b.disabled = profileBusy })
  $('profileList').querySelectorAll('[data-profile]').forEach(card => {
    card.setAttribute('aria-disabled', String(profileBusy)); card.tabIndex = profileBusy ? -1 : 0
  })
  profileFields.forEach(id => { $(id).disabled = profileBusy })
}
function captureProfileForm() { profileBaseline = profileFormValue(); updateProfileControls() }
async function profileRequest(fn) {
  if (profileBusy) return
  profileBusy = true; updateProfileControls()
  try { await fn() }
  catch (error) { $('modelMessage').textContent = error.message; toast(error.message, true) }
  finally { profileBusy = false; updateProfileControls() }
}
function renderProfiles() {
  $('profileLimit').textContent = `${profileState.profiles.length} / ${profileState.max}`
  $('profileEncryption').textContent = profileState.encryption === 'dpapi' ? '密钥由本机系统加密保存，不随软件分发。' : '当前系统不支持加密，密钥以明文保存在本机。'
  $('profileList').innerHTML = profileState.profiles.map(p => {
    const active = p.id === profileState.active
    return `<div class="profile-row${active ? ' active' : ''}${p.id === profileState.editing ? ' editing' : ''}" data-profile="${esc(p.id)}" role="button" tabindex="0" aria-pressed="${p.id === profileState.editing}">
      <div class="profile-copy"><div class="profile-name">${esc(p.name)}</div>
      <div class="profile-badges">${active ? '<span class="tag high">使用中</span>' : ''}${p.pending ? '<span class="tag medium">修改待使用</span>' : ''}</div>
      <div class="hint">${esc(p.model || '未填模型')} · ${p.has_key ? '已存密钥' : '未设密钥'}</div></div>
      <div class="row-actions">
        <button class="btn ghost sm danger" data-delete="${esc(p.id)}">删除</button>
      </div></div>`
  }).join('') || '<p class="hint">暂无配置。在右侧填写后点击“保存配置”，再选择是否使用。</p>'
  $('profileList').querySelectorAll('[data-profile]').forEach(card => {
    const select = async () => {
      if (card.dataset.profile !== profileState.editing && await profileGuard()) loadProfileForEdit(card.dataset.profile)
    }
    card.onclick = event => { if (!event.target.closest('button')) select() }
    card.onkeydown = event => {
      if (event.target === card && (event.key === 'Enter' || event.key === ' ')) {
        event.preventDefault(); select()
      }
    }
  })
  $('profileList').querySelectorAll('[data-delete]').forEach(b => { b.onclick = async event => {
    event.stopPropagation()
    if (profileBusy) return
    const id = b.dataset.delete, name = profileState.profiles.find(p => p.id === id)?.name || '此配置'
    if (!await AppDialogs.ask({ title: '删除模型配置？', message: `“${name}”及其已保存的密钥将被删除。` +
      (profileState.editing === id && profileDirty() ? '\n当前未保存的修改也会放弃。' : ''), accept: '删除配置', cancel: '保留配置', danger: true })) return
    await profileRequest(async () => {
      const result = await callApi('POST', `/api/model/profiles/${id}/delete`, {})
      profileState = { ...profileState, ...result }
      if (profileState.editing === id) resetProfileForm()
      renderProfiles(); $('modelMessage').textContent = '已删除配置。'
    })
  } })
  updateProfileControls()
}
function loadProfileForEdit(id) {
  const p = profileState.profiles.find(x => x.id === id); if (!p) return
  profileState.editing = id
  $('modelProfileName').value = p.name; modelProvider = p.provider === 'intranet' ? 'intranet' : 'compatible'
  $('modelPreset').value = modelProvider
  $('modelFormat').value = p.api_format || 'openai'; $('modelAuth').value = p.auth_type || 'auto'; updateProtocolFields()
  $('modelUrl').value = p.base_url; $('modelName').value = p.model; $('modelKey').value = ''
  $('modelKey').placeholder = p.has_key ? '留空保留已存密钥' : '填写接口密钥，可留空'
  $('modelMessage').textContent = p.pending ? '已保存的修改尚未用于连接，点击“使用配置”后生效。' : '正在编辑：' + p.name
  captureProfileForm(); renderProfiles()
}
function resetProfileForm() {
  profileState.editing = ''; modelProvider = 'compatible'
  profileFields.forEach(id => { $(id).value = '' })
  $('modelPreset').value = 'compatible'
  $('modelFormat').value = 'openai'; $('modelAuth').value = 'auto'; updateProtocolFields()
  $('modelKey').placeholder = '填写此配置的接口密钥，可留空'
  $('modelMessage').textContent = '新建配置：保存后不会自动切换当前连接。'
  captureProfileForm(); renderProfiles(); $('modelProfileName').focus()
}
action('profileNew', async () => { if (await profileGuard()) resetProfileForm() })
action('openModel', async () => {
  const [settings, profiles] = await Promise.all([callApi('GET', '/api/model/settings'), callApi('GET', '/api/model/profiles')])
  profileState = { ...profileState, ...profiles, editing: '' }
  $('modelModal').hidden = false
  if (profiles.profiles.some(p => p.id === profiles.active)) loadProfileForEdit(profiles.active)
  else resetProfileForm()
})
$('modelPreset').onchange = () => {
  const preset = $('modelPreset').value
  modelProvider = preset === 'intranet' ? 'intranet' : 'compatible'
  $('modelUrl').value = preset === 'intranet' ? 'http://llm.novastar.tech:31000/v1' : ''
  $('modelName').value = ''
  $('modelKey').value = ''
  $('modelFormat').value = 'openai'; $('modelAuth').value = 'auto'; updateProtocolFields()
}
action('modelClose', async () => { if (await profileGuard('放弃并关闭')) { $('modelModal').hidden = true; profileBaseline = '' } })
action('modelSave', () => profileRequest(async () => {
  const body = { id: profileState.editing || undefined, name: $('modelProfileName').value,
    provider: modelProvider, base_url: $('modelUrl').value, model: $('modelName').value,
    api_format: $('modelFormat').value, auth_type: $('modelAuth').value }
  if ($('modelKey').value) body.api_key = $('modelKey').value
  const result = await callApi('POST', '/api/model/profiles', body)
  profileState = { ...profileState, ...result, editing: result.profile.id }
  loadProfileForEdit(result.profile.id)
  $('modelMessage').textContent = '已保存“' + result.profile.name + '”。当前连接未改变，点击“使用配置”才会应用。'
  toast('配置已保存，当前连接未改变。')
}))
async function activateProfile(id) {
  if (profileBusy) return
  if (profileDirty()) { $('modelMessage').textContent = '请先保存修改，或关闭并放弃修改后再选择使用。'; toast('请先保存修改，再使用配置。', true); return }
  await profileRequest(async () => {
    const result = await callApi('POST', `/api/model/profiles/${id}/activate`, {})
    profileState = { ...profileState, ...result }
    loadProfileForEdit(id)
    $('modelMessage').textContent = '已使用“' + (profileState.profiles.find(p => p.id === id)?.name || '') + '”，右上角状态灯会自动检测连接。'
    toast('已切换模型连接。')
    $('modelModal').hidden = true; profileBaseline = ''
  })
}
action('modelUse', () => { if (profileState.editing) return activateProfile(profileState.editing) })
let initialized = false
async function initialize() {
  if (initialized) return
  initialized = true
  try { await refreshGlossary() } catch (error) { $('glossaryInfo').textContent = '术语库不可访问，请打开术语库检查'; toast(error.message, true) }
}
window.api.onBackendReady(initialize)
;(async () => { for (let i = 0; i < 60 && !initialized; i++) { if (await window.api.backendPort()) { await initialize(); break } await delay(500) } })().catch(error => toast(error.message, true))
renderFiles()

// Ask in the app before any close entry point or reload discards an editor draft.
let exitAllowed = false, navigationDecision = false
async function confirmExit(reload = false) {
  if(window.Community?.busy){toast('正在同步团队词库，请完成后再关闭。');return false}
  if (integrityBusy) { toast('正在校验或修复，请完成后再关闭。'); return false }
  if (profileBusy || lexiconEditor.state.busy) { toast('正在保存或读取，请稍候再关闭。'); return false }
  if (!reload && (await callApi('GET','/api/maintenance/status').catch(()=>({busy:state.busy||state.exportBusy}))).busy) {
    return AppDialogs.ask({title:'还有任务正在处理',message:'退出星译官会中止本机和共享工作台中的任务。已保存的文件保留，尚未完成的内容需要重新处理。',accept:'中止任务并退出',cancel:'继续处理'})
  }
  const parts = [profileDirty() && '模型配置', lexiconEditor.isDirty() && '术语库',window.Community?.authorizationDirty&&'维护授权'].filter(Boolean)
  if (!parts.length) return true
  const teamWasOpen=$('teamDialog').open
  if(teamWasOpen)$('teamDialog').close()
  const accepted=await AppDialogs.ask({ title: reload ? '放弃修改并重新载入？' : '放弃修改并退出？',
    message: parts.join('和') + '还有未保存的修改。继续后，本次编辑的内容不会保留。',
    accept: reload ? '放弃并重新载入' : '放弃并退出', cancel: '继续编辑' })
  if(!accepted&&teamWasOpen)$('teamDialog').showModal()
  return accepted
}
window.api.onCloseRequest(async token => {
  try {
    const accepted = await confirmExit()
    exitAllowed = accepted
    if (!await window.api.answerCloseRequest(token, accepted)) exitAllowed = false
  } catch (error) { exitAllowed = false; toast(error.message, true) }
})
window.api.closeGuardReady().catch(error => toast(error.message, true))
window.addEventListener('beforeunload', event => {
  if (exitAllowed || (!lexiconEditor.isDirty() && !profileDirty()&&!window.Community?.authorizationDirty)) return
  event.preventDefault(); event.returnValue = false
  if (navigationDecision) return
  navigationDecision = true
  confirmExit(true).then(accepted => {
    navigationDecision = false
    if (accepted) { exitAllowed = true; window.location.reload() }
  }).catch(error => { navigationDecision = false; toast(error.message, true) })
})
