// The shared window uses the same portal as browsers; local work stays local.
let lanStatus = null, comparisonValue = null
async function showLan() {
  lanStatus = await callApi('GET','/api/lan')
  $('lanPort').value=lanStatus.port||8765; renderLan(); $('lanDialog').showModal()
}
function renderLan(){
  $('lanState').textContent=lanStatus.enabled?'共享服务已开启 · 同事可通过下面的地址使用':'共享服务已关闭'
  $('lanToggle').textContent=lanStatus.enabled?'关闭共享服务':'开启共享服务'
  $('lanAddresses').innerHTML=(lanStatus.addresses||[]).map(address=>`<div class="shared-address"><input readonly value="${esc(address)}" aria-label="共享地址"><button class="btn ghost" data-shared="${esc(address)}">打开</button></div>`).join('')
  $('lanAddresses').querySelectorAll('[data-shared]').forEach(button=>button.onclick=()=>window.api.openSharedService(button.dataset.shared).catch(e=>toast(e.message,true)))
}
action('openLan',showLan);action('closeLan',()=>$('lanDialog').close())
action('lanToggle',async()=>{
  $('lanToggle').disabled=true
  try{lanStatus=await callApi('POST','/api/lan',{enabled:!lanStatus.enabled,port:Number($('lanPort').value)});renderLan()}finally{$('lanToggle').disabled=false}
})
action('lanConnect',()=>window.api.openSharedService($('lanRemote').value.trim()))
async function showComparison(comparisonId){
  comparisonValue=await callApi('GET','/api/comparisons/'+comparisonId)
  $('comparisonNote').textContent=`${comparisonValue.source_name} → ${comparisonValue.output_name}${comparisonValue.output_changed?' · 页面预览显示当前文件；文字对照保留上次保存的内容。':''}`
  $('compareSearch').value='';$('comparePage').innerHTML='<option value="">全部页面</option>'+[...new Set(comparisonValue.rows.map(r=>r.slide).filter(Boolean))].map(n=>`<option value="${n}">第 ${n} 页</option>`).join('')
  renderComparison()
  const port=await window.api.backendPort(),base=`http://127.0.0.1:${port}/api/comparisons/${comparisonId}/preview/`
  PageComparison.open($('comparisonDialog'),document.querySelector('#comparisonDialog .comparison-filters'),document.querySelector('#comparisonDialog .comparison-scroll'),comparisonValue,{source:base+'source',output:base+'output'})
}
function renderComparison(){
  const query=$('compareSearch').value.toLowerCase(),page=$('comparePage').value
  $('comparisonRows').innerHTML=comparisonValue.rows.filter(row=>(!page||String(row.slide)===page)&&(!query||(row.source+' '+row.translation).toLowerCase().includes(query))).map(row=>`<tr><td><small>${row.slide?'第 '+row.slide+' 页 · ':''}段 ${row.para||''}${!row.editable?' · '+esc(row.note||'需人工检查'):''}</small>${esc(row.source)}</td><td>${esc(row.translation)}</td></tr>`).join('')
}
$('compareSearch').oninput=renderComparison;$('comparePage').onchange=renderComparison
action('closeComparison',()=>$('comparisonDialog').close())
// Delegation keeps comparison available after result/report/history rerenders.
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-comparison]')
  if(button)showComparison(button.dataset.comparison).catch(e=>toast(e.message,true))
})
