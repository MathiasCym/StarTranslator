// The shared window uses the same portal as browsers; local work stays local.
let lanStatus = null, comparisonValue = null
function lanFeedback(message = '', field = '') {
  const box = $('lanMessage')
  box.textContent = message; box.hidden = !message; box.dataset.field = field
  ;(field ? $(field).closest('label') : $('lanState')).insertAdjacentElement('afterend', box)
  for (const id of ['lanPort', 'lanRemote']) $(id).removeAttribute('aria-invalid')
  if (field) { $(field).setAttribute('aria-invalid', 'true'); $(field).focus() }
  if (message) box.scrollIntoView({ block: 'nearest' })
}
async function lanRequest(button, operation, field = '') {
  button.disabled = true; lanFeedback()
  try { await operation() } catch (error) { lanFeedback(error.message, field) }
  finally { button.disabled = false }
}
async function showLan() {
  lanStatus = null; $('lanState').textContent = '正在读取共享状态…'; $('lanAddresses').replaceChildren()
  $('lanDialog').showModal()
  await lanRequest($('lanToggle'), async () => {
    lanStatus = await callApi('GET','/api/lan')
    $('lanPort').value=lanStatus.port||8765; renderLan()
  })
  $('lanToggle').disabled = !lanStatus
}
function renderLan(){
  $('lanState').textContent=lanStatus.enabled?'共享服务已开启 · 同事可通过下面的地址使用':'共享服务已关闭'
  $('lanToggle').textContent=lanStatus.enabled?'关闭共享服务':'开启共享服务'
  const addresses=lanStatus.addresses||[]
  const addressRow=address=>`<div class="shared-address"><input readonly value="${esc(address)}" aria-label="共享地址"><button class="btn ghost" data-shared="${esc(address)}">打开</button></div>`
  // VPN/virtual adapters may add several addresses. Keep the first usable
  // address visible; secondary addresses need space only when requested.
  $('lanAddresses').innerHTML=(addresses[0]?addressRow(addresses[0]):'')+(addresses.length>1?`<details class="lan-other-addresses"><summary>其他共享地址（${addresses.length-1}）</summary>${addresses.slice(1).map(addressRow).join('')}</details>`:'')
  $('lanAddresses').querySelectorAll('[data-shared]').forEach(button=>button.onclick=()=>lanRequest(button,()=>window.api.openSharedService(button.dataset.shared)))
}
action('openLan',showLan);action('closeLan',()=>$('lanDialog').close())
action('lanToggle',async()=>{
  if (!lanStatus) return
  const port = Number($('lanPort').value)
  if (!lanStatus.enabled && (!$('lanPort').value.trim() || !Number.isInteger(port) || port < 1024 || port > 65535)) {
    lanFeedback('共享端口请输入 1024–65535 之间的整数。', 'lanPort'); return
  }
  await lanRequest($('lanToggle'), async () => {
    lanStatus=await callApi('POST','/api/lan',{enabled:!lanStatus.enabled,port}); renderLan()
  })
})
action('lanConnect',()=>lanRequest($('lanConnect'),()=>window.api.openSharedService($('lanRemote').value.trim()),'lanRemote'))
for (const id of ['lanPort', 'lanRemote']) $(id).addEventListener('input', () => {
  if (!$('lanMessage').dataset.field || $('lanMessage').dataset.field === id) lanFeedback()
})
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
