// Team maintenance and updates are optional: the document workflow stays offline-capable.
;(() => {
  let teamBusy=false,teamConfig=null,plan=null,updateValue=null
  const labels={zh:'中文术语',en:'标准英文',variants:'正确别名',machine_variants:'机翻候选',wrong_variants:'已确认错译',note:'备注',source:'参考来源',priority:'规范标记',entry:'完整词条'}
  const display=value=>value===null||value===undefined?'已删除':Array.isArray(value)?value.map(item=>typeof item==='object'?item.zh+' → '+item.en: item).join('\n'):String(value)
  function teamStatus(message,error=false){$('teamStatus').textContent=message;$('teamStatus').classList.toggle('error',error)}
  function teamButtons(){
    for(const id of ['teamPull','teamHistory','teamSaveToken','teamClearToken','teamGetToken','closeTeamSync'])$(id).disabled=teamBusy
    $('teamToken').disabled=$('teamMessage').disabled=teamBusy
    $('teamPush').disabled=teamBusy||!teamConfig?.has_token
    $('teamApply').disabled=teamBusy||!!$('teamConflicts').querySelector('select option[value=""]:checked')
    $('teamConflicts').querySelectorAll('select').forEach(select=>select.disabled=teamBusy)
  }
  function renderConfig(value){
    teamConfig=value;$('teamLastSync').textContent=value.last_sync?'上次同步：'+new Date(value.last_sync).toLocaleString():'尚未同步'
    $('teamTokenState').textContent=value.has_token?'已保存维护授权。':'未配置维护授权，仍可获取团队词库。'
    $('teamClearToken').hidden=!value.has_token;$('teamMessageLabel').hidden=!value.has_token;teamButtons()
  }
  async function teamOperation(operation,message){
    if(teamBusy)return;teamBusy=true;teamButtons();teamStatus(message)
    try{await operation()}catch(error){teamStatus(error.message,true)}finally{teamBusy=false;teamButtons()}
  }
  function resetPreview(){plan=null;$('teamPreview').hidden=$('teamApply').hidden=true;$('teamConflicts').replaceChildren()}
  action('openTeamSync',async()=>{
    if(lexiconEditor.isDirty()||lexiconEditor.state.busy){toast('请先保存当前术语库编辑，再进行团队同步。',true);return}
    resetPreview();$('teamHistoryRows').hidden=true;renderConfig(await callApi('GET','/api/team/settings'));teamStatus('本机词库保持不变，先获取差异，再确认同步。');$('teamDialog').showModal()
  })
  async function closeTeam(){
    if(teamBusy)return
    const dirty=!!$('teamToken').value;$('teamDialog').close()
    if(dirty&&!await AppDialogs.ask({title:'维护授权尚未保存',message:'关闭后将清除本次输入的授权，已有授权保持不变。',accept:'关闭并清除',cancel:'继续配置'})){$('teamDialog').showModal();return}
    $('teamToken').value='';resetPreview()
  }
  action('closeTeamSync',closeTeam);$('teamDialog').addEventListener('cancel',event=>{event.preventDefault();closeTeam()})
  action('teamSaveToken',()=>teamOperation(async()=>{
    const token=$('teamToken').value;if(!token){teamStatus('请输入新授权，或使用已有授权。');return}
    renderConfig(await callApi('POST','/api/team/settings',{token}));$('teamToken').value='';teamStatus('维护授权已加密保存在本机。')
  },'正在保存维护授权…'))
  action('teamClearToken',()=>teamOperation(async()=>{renderConfig(await callApi('POST','/api/team/settings',{clear_token:true}));$('teamToken').value='';resetPreview();teamStatus('已移除维护授权，仍可获取团队词库。')},'正在移除授权…'))
  action('teamGetToken',()=>window.api.openMaintenanceAuthorization())
  for(const [id,kind] of [['teamPull','pull'],['teamPush','push']])action(id,()=>teamOperation(async()=>{
    if(lexiconEditor.isDirty())throw Error('请先保存当前词库编辑。')
    plan=await callApi('POST','/api/team/preview',{action:kind,fingerprint:lexiconEditor.state.fingerprint})
    $('teamPreview').hidden=$('teamApply').hidden=false
    const counts={added:0,changed:0,deleted:0};plan.changes.forEach(change=>counts[change.kind]++)
    $('teamSummary').textContent=`新增 ${counts.added} 条 · 修改 ${counts.changed} 条 · 删除 ${counts.deleted} 条 · 合并后 ${plan.count} 条`
    $('teamChanges').innerHTML=plan.changes.map(change=>`<span>${esc(change.zh)} · ${esc({added:'新增',changed:'修改',deleted:'删除'}[change.kind])}</span>`).join('')
    $('teamConflicts').innerHTML=plan.conflicts.map(conflict=>`<article class="community-conflict"><strong>${esc(conflict.zh)} · ${esc(labels[conflict.field]||conflict.field)}</strong><div class="community-conflict-values"><div><span class="hint">本机内容</span><p>${esc(display(conflict.local))}</p></div><div><span class="hint">团队内容</span><p>${esc(display(conflict.remote))}</p></div></div><label>保留内容<select data-conflict="${esc(conflict.id)}"><option value="">请选择</option><option value="local">保留本机内容</option><option value="remote">采用团队内容</option></select></label></article>`).join('')
    $('teamConflicts').querySelectorAll('select').forEach(select=>select.onchange=teamButtons)
    $('teamApply').textContent=kind==='push'?'确认提交':'确认同步'
    teamStatus(plan.remote_missing?'团队词库尚未发布。维护者可以提交本机内容，其他人可继续使用本机词库。':plan.conflicts.length?'双方修改了相同内容，请逐项选择后确认。':'差异已准备好，确认后才会修改词库。')
  },'正在获取团队词库与差异…'))
  action('teamApply',()=>teamOperation(async()=>{
    if(!plan)throw Error('请先获取差异预览。')
    if(plan.action==='push'&&plan.pending_upload&&!$('teamMessage').value.trim())throw Error('请填写本次维护说明。')
    const choices=Object.fromEntries([...$('teamConflicts').querySelectorAll('select')].map(select=>[select.dataset.conflict,select.value]))
    const result=await callApi('POST','/api/team/apply',{id:plan.id,choices,message:$('teamMessage').value})
    await lexiconEditor.reload();renderConfig(await callApi('GET','/api/team/settings'));resetPreview();$('teamMessage').value=''
    teamStatus((result.committed?'已提交团队词库':'已同步最新内容')+'，共 '+result.count+' 条。'+(result.pending_upload?'本机还保留独立修改，维护者可继续提交。':''))
  },'正在应用已确认的词库内容…'))
  action('teamHistory',()=>teamOperation(async()=>{
    const result=await callApi('GET','/api/team/history');$('teamHistoryRows').hidden=false
    $('teamHistoryRows').innerHTML=result.records.map(record=>`<article><p>${esc(record.message)}</p><small class="hint">${esc(record.author)} · ${esc(new Date(record.date).toLocaleString())}</small></article>`).join('')||'<p class="hint">尚无团队维护记录。</p>';teamStatus('已获取最近维护记录。')
  },'正在读取维护记录…'))
  function renderUpdate(value){
    updateValue=value;$('updateVersions').textContent='当前 v'+value.currentVersion+(value.newVersion?' → v'+value.newVersion:'')
    $('updateMessage').textContent=value.message;$('updateMessage').classList.toggle('error',value.phase==='error')
    $('updateCheck').disabled=['checking','downloading'].includes(value.phase)
    $('updateDownload').hidden=!value.canDownload||['checking','downloading','ready'].includes(value.phase)
    $('updateCancel').hidden=value.phase!=='downloading';$('updateInstall').hidden=value.phase!=='ready'
    $('updateProgressBox').hidden=!['downloading','ready'].includes(value.phase)
    $('updateProgressFill').style.width=(value.progress||0)+'%'
    $('updateDownloadSize').textContent=value.total?`${(value.bytes/1048576||0).toFixed(1)} / ${(value.total/1048576).toFixed(1)} MiB`:'更新包已校验'
    $('updateNotes').hidden=!value.notes;$('updateNotes').textContent=value.notes||''
  }
  window.api.onUpdateStatus(renderUpdate)
  action('openUpdates',async()=>{renderUpdate(await window.api.updateState());$('updateDialog').showModal()})
  action('closeUpdates',()=>$('updateDialog').close())
  action('updateCheck',()=>window.api.checkUpdates().then(renderUpdate))
  action('updateDownload',()=>window.api.downloadUpdate().then(renderUpdate))
  action('updateCancel',()=>window.api.cancelUpdate().then(renderUpdate))
  action('updateInstall',async()=>{
    if(state.busy||state.exportBusy||integrityBusy||profileBusy||lexiconEditor.state.busy||lexiconEditor.isDirty()||profileDirty()){toast('请先完成当前任务，并保存词库与模型配置。',true);return}
    $('updateDialog').close()
    if(!await confirmResultNavigation('安装更新将关闭星译官，请确认已保存本次结果。','已完成，继续更新')){$('updateDialog').showModal();return}
    if(!await AppDialogs.ask({title:'安装新版本？',message:'即将关闭星译官并打开已校验的更新安装包。模型配置、词库和历史记录会保留。',accept:'关闭并安装',cancel:'稍后安装'})){$('updateDialog').showModal();return}
    try{await window.api.installUpdate()}catch(error){toast(error.message,true);$('updateDialog').showModal();renderUpdate(await window.api.updateState())}
  })
  window.Community={get busy(){return teamBusy},get authorizationDirty(){return !!$('teamToken').value}}
})()
