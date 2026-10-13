/* A shared page viewer for desktop and browser clients. Document frames have no app bridge. */
window.PageComparison = (() => {
  let current = null, sequence = 0
  const buttons = 'class="btn ghost sm" type="button"'
  function mount(dialog, filters, text) {
    const box = document.createElement('div'); box.className = 'page-comparison'
    box.innerHTML = `<div class="pc-toolbar"><button ${buttons} data-mode="pages" aria-pressed="true">页面对照</button><button ${buttons} data-mode="text" aria-pressed="false">文字对照</button><label class="pc-sync"><input type="checkbox" checked>同步翻页与滚动</label><select class="pc-zoom" aria-label="页面缩放"><option value="fit">适合宽度</option><option value="1">100%</option><option value="1.25">125%</option><option value="1.5">150%</option><option value="2">200%</option></select><button ${buttons} data-expand>展开查看</button></div><div class="pc-panes">${['source','output'].map((side,i)=>`<section class="pc-pane" data-side="${side}"><div class="pc-pane-head"><strong>${i?'处理后英文':'中文原稿'}</strong><small></small></div><p class="pc-status" role="status">正在准备完整页面…</p><iframe class="pc-frame" title="${i?'英文文档页面':'中文原稿页面'}" sandbox="allow-scripts" referrerpolicy="no-referrer"></iframe><div class="pc-nav"><button ${buttons} data-prev aria-label="${i?'英文':'原稿'}上一页">上一页</button><input type="number" min="1" value="1" aria-label="${i?'英文':'原稿'}页码"><span data-count>/ —</span><button ${buttons} data-next aria-label="${i?'英文':'原稿'}下一页">下一页</button></div></section>`).join('')}</div>`
    dialog.insertBefore(box, filters)
    const value = { dialog, box, filters, text, panes: {}, mode: 'pages' }
    for (const side of ['source','output']) {
      const pane=box.querySelector(`[data-side="${side}"]`),frame=pane.querySelector('iframe')
      const p={pane,frame,number:pane.querySelector('input'),status:pane.querySelector('.pc-status'),page:1,total:0,ready:false};value.panes[side]=p
      pane.querySelector('[data-prev]').onclick=()=>go(value,side,p.page-1)
      pane.querySelector('[data-next]').onclick=()=>go(value,side,p.page+1)
      p.number.onchange=()=>go(value,side,Number(p.number.value))
    }
    box.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>mode(value,b.dataset.mode))
    box.querySelector('[data-expand]').onclick=()=>{dialog.classList.toggle('pc-expanded');box.querySelector('[data-expand]').textContent=dialog.classList.contains('pc-expanded')?'还原大小':'展开查看'}
    box.querySelector('select').onchange=()=>Object.values(value.panes).forEach(p=>send(p,{type:'zoom',value:box.querySelector('select').value}))
    dialog.addEventListener('close',()=>{
      // Native close events are queued. A newer open must keep its own frames.
      if(dialog.open)return
      if(current===value)current=null
      Object.values(value.panes).forEach(p=>{clearTimeout(p.timer);p.frame.src='about:blank'})
      dialog.classList.remove('pc-expanded');box.querySelector('[data-expand]').textContent='展开查看'
    })
    return value
  }
  function mode(v,mode) {
    v.mode=mode;v.box.querySelector('.pc-panes').hidden=mode!=='pages';v.filters.hidden=v.text.hidden=mode!=='text'
    v.box.style.flex=mode==='pages'?'1':'0';v.box.querySelector('.pc-sync').hidden=mode!=='pages';v.box.querySelector('select').hidden=mode!=='pages'
    v.box.querySelectorAll('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===mode)))
  }
  function send(p,data) { if(p.ready)p.frame.contentWindow.postMessage({channel:'star-page-preview',token:p.token,...data},'*') }
  function go(v,side,page) {
    const p=v.panes[side];page=Math.max(1,Math.min(p.total||1,Math.round(page)||1));send(p,{type:'goto',page,fraction:0})
    if(v.box.querySelector('.pc-sync input').checked)send(v.panes[side==='source'?'output':'source'],{type:'goto',page,fraction:0})
  }
  window.addEventListener('message',event=>{
    const v=current,data=event.data;if(!v||data?.channel!=='star-page-preview')return
    const entry=Object.entries(v.panes).find(([,p])=>p.frame.contentWindow===event.source);if(!entry)return
    const [side,p]=entry
    if(data.token!==p.token)return
    if(data.type==='error'){clearTimeout(p.timer);p.status.hidden=false;p.status.textContent=String(data.message||'页面预览未完成').slice(0,500);return}
    if(data.type==='ready'){
      const first=!p.ready;clearTimeout(p.timer);p.ready=true;p.status.hidden=true;p.total=Math.max(1,Math.min(10000,Number(data.total)||1));p.number.max=p.total;p.pane.querySelector('[data-count]').textContent='/ '+p.total
      if(first)send(p,{type:'zoom',value:v.box.querySelector('select').value});return
    }
    if(data.type==='position'&&p.ready){
      p.page=Math.max(1,Math.min(p.total,Math.round(Number(data.page))||1));p.number.value=p.page
      p.pane.querySelector('[data-prev]').disabled=p.page<=1;p.pane.querySelector('[data-next]').disabled=p.page>=p.total
      if(!data.command&&v.box.querySelector('.pc-sync input').checked)send(v.panes[side==='source'?'output':'source'],{type:'goto',page:p.page,fraction:Math.max(0,Math.min(1,Number(data.fraction)||0))})
    }
  })
  return {
    open(dialog,filters,text,metadata,urls) {
      const v=dialog._pageComparison||(dialog._pageComparison=mount(dialog,filters,text));current=v;mode(v,'pages')
      dialog.classList.remove('pc-expanded');v.box.querySelector('[data-expand]').textContent='展开查看'
      v.box.querySelector('select').value='fit'
      const opening=String(++sequence)
      for(const side of ['source','output']) {
        const p=v.panes[side];p.ready=false;p.page=1;p.total=0;p.number.value=1;p.status.hidden=false;p.status.textContent='正在准备完整页面…'
        p.pane.querySelector('small').textContent=metadata[side+'_name'];p.pane.querySelector('[data-count]').textContent='/ —'
        p.token=opening+'-'+side
        const url=new URL(urls[side],location.href);url.searchParams.set('preview_token',p.token)
        p.frame.src=url.href;clearTimeout(p.timer);p.timer=setTimeout(()=>{if(!p.ready){p.status.hidden=false;p.status.textContent='页面准备时间较长。可关闭后重试，或切换文字对照。'}},125000)
      }
      if(!dialog.open)dialog.showModal()
    }
  }
})()
