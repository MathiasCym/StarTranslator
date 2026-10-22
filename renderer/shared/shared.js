'use strict'
const $ = id => document.getElementById(id)
const esc = x => String(x ?? '').replace(/[&<>"']/g,c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))
let csrf = '', jobs = [], selected = '', comparison = null, lastDetail = '', polling = false, comparisonBase = ''
const labels = {translate:'翻译',check:'校对',translate_review:'翻译并校对',queued:'排队中',running:'处理中',complete:'已完成',failed:'未完成',cancelled:'已取消',partial:'部分完成',interrupted:'已中断'}
async function api(path, options = {}) {
  const response = await fetch(path,{...options,headers:{'X-Star-CSRF':csrf,...options.headers}})
  const data = await response.json()
  if (!response.ok) throw Error(data.error || '共享服务没有返回结果')
  return data
}
function progressMarkup(value) {
  const percent=Math.max(0,Math.min(100,Number(value)||0))
  return `<div class="shared-progress active"><progress value="${percent}" max="100" aria-label="任务进度"></progress><span class="shared-reflection" aria-hidden="true"></span></div>`
}
function setProgress(progress,value,active) {
  progress.value=Math.max(0,Math.min(100,Number(value)||0))
  const track=progress.closest('.shared-progress');track.style.setProperty('--shared-percent',progress.value+'%');track.classList.toggle('active',active)
  if(!track.style.getPropertyValue('--reflection-delay'))track.style.setProperty('--reflection-delay',-(Date.now()%2400)+'ms')
}
function showError(error) { $('error').textContent = error.message; $('error').hidden = false }
function action(id, fn) { $(id).onclick = async () => { try { await fn() } catch(e) { showError(e) } } }
function mode() {
  const kind=document.querySelector('[name=kind]:checked').value,hasPresentation=[...$('files').files].some(file=>/\.pptx$/i.test(file.name))
  $('outputField').hidden=kind!=='translate_review'; $('translationOptions').hidden=kind==='check'||!hasPresentation
  if(!hasPresentation){document.querySelector('[name=translationMode][value=faithful]').checked=true;$('translationOptions').querySelector('.translation-help-button').setAttribute('aria-expanded','false');$('translationOptions').querySelector('.translation-help').hidden=true}
}
document.querySelectorAll('[name=kind]').forEach(el => el.onchange = mode); mode()
for (const [id,label] of [['files','fileNames'],['references','referenceNames']]) $(id).onchange = () => { $(label).textContent = [...$(id).files].map(f=>f.name).join('、') || (id === 'files' ? '支持 Office、PDF、文本、电子书和字幕，每份不超过 150 MB。PDF 文字层输出为 Word。' : ''); mode() }
$('form').onsubmit = async event => {
  event.preventDefault(); $('error').hidden = true
  const form = new FormData(), kind = document.querySelector('[name=kind]:checked').value
  for (const file of $('files').files) form.append('files',file)
  for (const file of $('references').files) form.append('references',file)
  form.append('options',JSON.stringify({kind,translation_mode:document.querySelector('[name=translationMode]:checked').value,combined_output:$('outputMode').value,use_llm:$('useLlm').checked,workers:$('parallelWork').checked?3:1}))
  $('submit').disabled = true; $('uploadProgress').hidden = false; setProgress($('uploadProgress'),0,true)
  try {
    const job = await new Promise((resolve,reject) => {
      const xhr = new XMLHttpRequest(); xhr.open('POST','/shared/jobs'); xhr.setRequestHeader('X-Star-CSRF',csrf)
      xhr.upload.onprogress = e => { if(e.lengthComputable) { setProgress($('uploadProgress'),100*e.loaded/e.total,true); $('uploadStatus').textContent = `正在上传 ${Math.round(100*e.loaded/e.total)}%` } }
      xhr.onerror = () => reject(Error('未能连接共享电脑，请检查局域网连接。'))
      xhr.onload = () => { try { const value=JSON.parse(xhr.responseText); if(xhr.status!==200) reject(Error(value.error)); else resolve(value) } catch(e) { reject(Error('上传未完成，请重试。')) } }
      xhr.send(form)
    })
    selected = job.id; lastDetail = ''; $('files').value = ''; $('references').value = ''; $('fileNames').textContent = '文档已提交，可继续添加下一项任务。'; $('referenceNames').textContent = ''; $('uploadStatus').textContent = '上传完成，已加入任务队列。'; await refresh()
  } catch(e) { showError(e) } finally { $('submit').disabled = false; $('uploadProgress').hidden = true }
}
async function refresh() {
  if(polling) return
  polling=true
  try {
    jobs=(await api('/shared/jobs')).jobs
    $('jobs').innerHTML = jobs.length ? jobs.map(j=>`<article class="job"><div class="section-head"><strong>${esc(labels[j.kind])}</strong><span class="badge">${esc(labels[j.status])}</span></div><p>${esc(j.message)}</p>${['queued','running'].includes(j.status)?progressMarkup(j.percent)+`<p class="hint">${esc(j.detail||'正在处理文档…')}${j.total?` · ${j.done} / ${j.total} ${j.phase==='image_text'?'张':['format','output_check'].includes(j.phase)?'页':'段'}`:''}</p>`:''}<div class="row-actions"><button data-show="${j.id}">查看${['queued','running'].includes(j.status)?'进度':'结果'}</button>${['queued','running'].includes(j.status)?`<button data-cancel="${j.id}">取消任务</button>`:''}${!['queued','running'].includes(j.status)?`<a class="download" href="/shared/jobs/${j.id}/diagnostics">导出任务诊断</a><button data-cleanup="${j.id}">删除任务与文件</button>`:''}</div></article>`).join('') : '<p class="empty">提交一份文档，开始你的第一个任务。</p>'
    $('jobs').querySelectorAll('.shared-progress progress').forEach(p=>setProgress(p,p.value,true))
    $('jobs').querySelectorAll('[data-show]').forEach(b=>b.onclick=()=>showJobResult(b.dataset.show))
    for (const job of jobs.filter(value=>value.can_resume)) {
      const row=$('jobs').querySelector(`[data-show="${job.id}"]`)?.parentElement
      if(!row)continue
      const button=document.createElement('button');button.textContent='继续未完成任务';button.className='primary'
      button.onclick=async()=>{button.disabled=true;try{const restored=await api(`/shared/jobs/${job.id}/resume`,{method:'POST'});selected=restored.id;lastDetail='';await refresh()}catch(error){showError(error)}finally{button.disabled=false}}
      row.append(button)
    }
    $('jobs').querySelectorAll('[data-cancel]').forEach(b=>b.onclick=async()=>{try {await api(`/shared/jobs/${b.dataset.cancel}/cancel`,{method:'POST'});await refresh()}catch(e){showError(e)}})
    $('jobs').querySelectorAll('[data-cleanup]').forEach(button=>button.onclick=()=>{ $('cleanupDialog').dataset.job=button.dataset.cleanup; $('cleanupDialog').showModal() })
    renderDetail()
  } finally {polling=false}
}
const reportDrafts = new Map()
function revealResult(element) {
  element.scrollIntoView({block:'start',behavior:'instant'})
}
function showJobResult(id) {
  selected=id;lastDetail='';renderDetail()
  $('detailTitle').tabIndex=-1;$('detailTitle').focus({preventScroll:true});revealResult($('detail'))
}
function downloadMarkup(job) {
  if(!job.downloads.length) return ''
  return `<section class="result-downloads" aria-label="下载结果"><h3>已生成文件</h3><p class="hint">点击下载，将文档保存到你的电脑。</p><div class="download-list">${job.downloads.map(d=>`<a class="result-download" href="/shared/jobs/${job.id}/download/${d.index}" download="${esc(d.name)}"><svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg><span><strong>下载文档</strong><small>${esc(d.name)}</small></span></a>`).join('')}</div></section>`
}
function renderDetail() {
  const job=jobs.find(j=>j.id===selected)
  if(!job) return
  const key=JSON.stringify([job.id,job.status,job.percent,job.downloads,job.result?.report?.findings?.filter(f=>f.applied).length])
  if(key===lastDetail) return
  lastDetail=key;$('detail').hidden=false;$('detailTitle').textContent=labels[job.kind]+' · '+labels[job.status];$('detailMessage').textContent=job.message
  const active=['queued','running'].includes(job.status)
  $('taskProgress').hidden=!active;setProgress($('taskProgress'),job.percent,active)
  const result=job.result||{},report=result.report||(result.report_id?result:null)
  const draft=reportDrafts.get(job.id)||{selected:new Set(),edits:{},file:0,filter:'pending'}
  reportDrafts.set(job.id,draft)
  if(report) (report.findings||[]).forEach((f,i)=>{if(f.applied){draft.selected.delete(i);delete draft.edits[i]}})
  const noSuggestions=report&&!report.findings?.length
  const outputs=(result.outputs||[]).map((o,i)=>`<div class="row-actions"><span>${esc(o.path)}${o.staged?' · 等待确认后保存':''}</span>${o.comparison_id?`<button class="comparison-button" data-compare="${i}">${PageComparison.buttonContent}</button>`:''}</div>${o.consistency_hits&&!report?`<p class="hint">发现 ${o.consistency_hits} 项全文用语统一建议，可在校对报告中确认。</p>`:''}${[...(o.review_items||[]),...(o.layout_warnings||[])].length?`<details><summary>查看需检查的位置</summary>${o.consistency_hits&&!report?`<p class="hint">发现 ${o.consistency_hits} 项全文用语统一建议，可在校对报告中确认。</p>`:''}${[...(o.review_items||[]),...(o.layout_warnings||[])].map(w=>`<p class="hint">${esc(w.reason)}</p>`).join('')}</details>`:''}`).join('')
  const reportHtml=report?`<h3>校对报告 · ${(report.findings||[]).length} 项建议</h3><p class="hint">${report.stats?.model_status==='complete'?'校对完成，确认建议后保存。':'请查看检查范围和提示；未完成的检查不能视为全文通过。'}</p><p class="hint">${report.stats?.consistency_hits?`${report.stats.consistency_hits} 项全文用语统一建议。`:''} ${esc((report.stats?.warnings||[]).join('\n'))}</p><div class="filters"><select id="reportFile" aria-label="选择报告文档">${(report.files||[]).map((f,i)=>`<option value="${i}">${esc(f.name)}</option>`).join('')}</select><select id="reportFilter" aria-label="筛选建议"><option value="pending">未替换</option><option value="applied">已替换</option><option value="all">全部建议</option></select><select id="reportType" aria-label="筛选建议类型"><option value="all">全部类型</option><option value="rule">术语规范</option><option value="consistency">全文一致性</option><option value="llm">深度审校</option></select></div><div class="review-selection"><label><input id="selectAllSuggestions" type="checkbox">全选当前建议</label><span id="selectionCount" class="hint"></span></div><div id="findings"></div><div class="review-controls"><button id="reportCompare" class="comparison-button" hidden>${PageComparison.buttonContent}</button><button id="saveReview" class="primary"${noSuggestions?' hidden':''}>应用所选并保存</button>${job.kind==='translate_review'||noSuggestions?`<button id="saveUnchanged"${noSuggestions?' class="primary"':''}>${noSuggestions?'保存译文':'不应用建议，保存译文'}</button>`:''}</div><p id="savedMessage" class="hint" role="status" aria-live="polite">${esc(draft.savedMessage||'')}</p>`:''
  $('results').innerHTML=`<p class="error">${esc([job.error,...(result.errors||[]).map(e=>(e.path?e.path+'：':'')+e.error)].filter(Boolean).join('\n'))}</p>${outputs}${reportHtml}${downloadMarkup(job)}`
  $('results').querySelectorAll('[data-compare]').forEach(b=>b.onclick=async()=>{try{comparisonBase=`/shared/jobs/${job.id}/comparison/${b.dataset.compare}`;comparison=await api(comparisonBase);openComparison()}catch(e){showError(e)}})
  if(!report) return
  $('reportFile').value=String(Math.min(draft.file,Math.max(0,report.files.length-1)));$('reportFilter').value=draft.filter;$('reportType').value=draft.type||'all'
  const rows=()=> (report.findings||[]).map((f,i)=>({f,i})).filter(({f})=>f.file_index===Number($('reportFile').value)&&(!draft.type||draft.type==='all'||f.method===draft.type)&&(draft.filter==='all'||(draft.filter==='applied'?f.applied:!f.applied)))
  const usable=({f,i})=>f.editable&&!f.applied&&String(draft.edits[i]??f.suggested).trim()
  function selection() {
    const available=rows().filter(usable),chosen=available.filter(({i})=>draft.selected.has(i))
    $('selectAllSuggestions').disabled=!available.length
    $('selectAllSuggestions').checked=!!available.length&&chosen.length===available.length
    $('selectAllSuggestions').indeterminate=chosen.length>0&&chosen.length<available.length
    $('selectionCount').textContent=`已选 ${chosen.length} / ${available.length} 项可处理建议`
    $('saveReview').disabled=!chosen.length
    if($('saveUnchanged'))$('saveUnchanged').disabled=!report.files.length
  }
  function render() {
    const compare=$('reportCompare'),index=report.files[Number($('reportFile').value)]?.comparison_index
    compare.hidden=!Number.isInteger(index);compare.title='对照中文原稿与当前译文；保存后显示最新文件'
    compare.onclick=async()=>{try{comparisonBase=`/shared/jobs/${job.id}/comparison/${index}`;comparison=await api(comparisonBase);openComparison()}catch(e){showError(e)}}
    $('findings').innerHTML=rows().map(({f,i})=>`<article class="suggestion"><div class="section-head"><label><input type="checkbox" data-select="${i}"${draft.selected.has(i)?' checked':''}${!usable({f,i})?' disabled':''}> ${esc(f.file)}${f.slide?' · 第 '+f.slide+' 页':''}</label><span class="badge">${f.applied?'已替换':'未替换'}</span><span class="badge">${f.method==='consistency'?'全文一致性':f.method==='rule'?'术语规范':'深度审校'}</span></div><p>${esc(f.found_text)}</p><textarea aria-label="替换文本" data-edit="${i}"${f.applied||!f.editable?' readonly':''}>${esc(draft.edits[i]??f.suggested)}</textarea><p class="hint">${esc(f.reason)} ${esc(f.not_editable_reason)}</p><details><summary>查看上下文</summary><p class="hint">${esc(f.context)}</p></details></article>`).join('')||`<p class="empty">${noSuggestions?'本次没有替换建议，可以直接保存译文。':'该筛选条件下没有建议，已替换的项目可切换筛选查看。'}</p>`
    $('findings').querySelectorAll('[data-select]').forEach(el=>el.onchange=()=>{const i=Number(el.dataset.select);el.checked?draft.selected.add(i):draft.selected.delete(i);selection()})
    $('findings').querySelectorAll('[data-edit]').forEach(el=>el.oninput=()=>{const i=Number(el.dataset.edit);draft.edits[i]=el.value;const box=$('findings').querySelector(`[data-select="${i}"]`);box.disabled=!usable({f:report.findings[i],i});if(box.disabled){draft.selected.delete(i);box.checked=false}selection()})
    selection()
    if(draft.saving) $('results').querySelectorAll('button,input,select,textarea').forEach(el=>el.disabled=true)
  }
  $('reportFile').onchange=()=>{draft.file=Number($('reportFile').value);render()}
  $('reportFilter').onchange=()=>{draft.filter=$('reportFilter').value;render()}
  $('reportType').onchange=()=>{draft.type=$('reportType').value;render()}
  $('selectAllSuggestions').onchange=()=>{for(const {i} of rows().filter(usable))$('selectAllSuggestions').checked?draft.selected.add(i):draft.selected.delete(i);render()}
  render()
  const save=async unchanged=>{
    if(draft.saving) return
    const edits=unchanged?[]:rows().filter(({f,i})=>usable({f,i})&&draft.selected.has(i)).map(({i})=>({index:i,text:draft.edits[i]??report.findings[i].suggested}))
    if(!edits.length&&!unchanged)throw Error('请先选择需要应用的建议。')
    const fileIndex=Number($('reportFile').value)
    draft.saving=true;draft.savedMessage=''
    const controls=[...$('results').querySelectorAll('button,input,select,textarea')];controls.forEach(el=>el.disabled=true)
    const indicator=document.createElement('progress');indicator.max=100;indicator.setAttribute('aria-label','保存文件进度');$('savedMessage').after(indicator)
    try {
      let task=await api(`/shared/jobs/${job.id}/exports`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file_index:fileIndex,edits,save_unchanged:unchanged})})
      while(['queued','running'].includes(task.status)) {
        $('savedMessage').textContent=task.message+(task.total?`（${task.done}/${task.total}）`:'')
        if(task.total)indicator.value=100*task.done/task.total;else indicator.removeAttribute('value')
        await new Promise(resolve=>setTimeout(resolve,500))
        task=await api(`/shared/jobs/${job.id}/exports/${task.id}`)
      }
      if(task.status!=='complete')throw Error(task.error||'保存未完成。')
      draft.savedMessage='文件已保存，可在下方下载。'+(task.result?.content_warnings||[]).join('；');lastDetail='';await refresh();revealResult($('savedMessage'))
    } finally {indicator.remove();draft.saving=false;if($('saveReview')){lastDetail='';renderDetail();$('savedMessage').textContent=draft.savedMessage||''}}
  }
  action('saveReview',()=>save(false));if($('saveUnchanged'))action('saveUnchanged',()=>save(true))
}

function openComparison() {
  $('comparisonNote').textContent=comparison.source_name+' → '+comparison.output_name+(comparison.output_changed?' · 页面预览显示当前文件；文字对照保留上次保存的内容。':'')
  $('compareSearch').value='';$('comparePage').innerHTML='<option value="">全部页面</option>'+[...new Set(comparison.rows.map(r=>r.slide).filter(Boolean))].map(n=>`<option value="${n}">第 ${n} 页</option>`).join(''); renderComparison()
  PageComparison.open($('comparison'),document.querySelector('#comparison .filters'),document.querySelector('#comparison .comparison-scroll'),comparison,{source:comparisonBase+'/preview/source',output:comparisonBase+'/preview/output'})
}
function renderComparison(){const q=$('compareSearch').value.toLowerCase(),p=$('comparePage').value;$('comparisonRows').innerHTML=comparison.rows.filter(r=>(!p||String(r.slide)===p)&&(!q||(r.source+' '+r.translation).toLowerCase().includes(q))).map(r=>`<tr><td><small>${r.slide?'第 '+r.slide+' 页 · ':''}段 ${r.para||''}${!r.editable?' · '+esc(r.note||'需人工检查'):''}</small>${esc(r.source)}</td><td>${esc(r.translation)}</td></tr>`).join('')}
$('compareSearch').oninput=renderComparison;$('comparePage').onchange=renderComparison
action('closeComparison',()=>$('comparison').close());action('closeDetail',()=>{selected='';$('detail').hidden=true});action('refresh',refresh)
;(async()=>{try{csrf=(await api('/shared/session')).csrf;await refresh();setInterval(()=>refresh().catch(showError),1500)}catch(e){showError(e)}})()

action('cancelCleanup',()=> $('cleanupDialog').close())
action('acceptCleanup',async()=>{const id=$('cleanupDialog').dataset.job;await api(`/shared/jobs/${id}/cleanup`,{method:'POST'});$('cleanupDialog').close();reportDrafts.delete(id);if(selected===id){selected='';$('detail').hidden=true}await refresh()})

action('contactAuthor',()=>{$('sharedContactStatus').textContent='';$('contactDialog').showModal()})
action('closeContact',()=>$('contactDialog').close())
action('copySharedEmail',async()=>{
  const field=$('sharedAuthorEmail');field.focus();field.select()
  let copied=false
  try{copied=document.execCommand('copy')}catch{}
  if(!copied&&navigator.clipboard?.writeText){try{await navigator.clipboard.writeText(field.value);copied=true}catch{}}
  $('sharedContactStatus').textContent=copied?'邮箱已复制。':'请按 Ctrl+C，或长按选中的邮箱复制。'
  if(copied)$('copySharedEmail').focus()
})
