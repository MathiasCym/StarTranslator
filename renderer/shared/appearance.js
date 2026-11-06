// Runs before styles: no first-frame dark flash after choosing light mode.
;(()=>{
 const key='startranslator-appearance',valid=v=>v==='dark'||v==='light'
 let saved='dark';try{const v=localStorage.getItem(key);if(valid(v))saved=v}catch{}
 const requested=new URLSearchParams(location.search).get('star-theme')
 let current=valid(window.appearance?.initial)?window.appearance.initial:valid(requested)?requested:saved
 function apply(value,persist=true){
  if(!valid(value))return
  const root=document.documentElement,changing=root.dataset.theme&&root.dataset.theme!==value
  if(changing)root.classList.add('appearance-switching')
  current=value;document.documentElement.dataset.theme=value
  if(changing)requestAnimationFrame(()=>requestAnimationFrame(()=>root.classList.remove('appearance-switching')))
  if(persist)try{localStorage.setItem(key,value)}catch{}
  document.querySelectorAll('[data-theme-toggle]').forEach(button=>{
   button.setAttribute('aria-pressed',String(value==='light'))
   button.title=button.ariaLabel=value==='light'?'切换为深色模式':'切换为浅色模式'
  })
  document.querySelectorAll('[data-theme-select]').forEach(select=>select.value=value)
 }
 async function set(value){
  if(!valid(value))return
  try{if(window.appearance)value=await window.appearance.set(value);apply(value)}
  catch(error){
   let notice=document.getElementById('appearanceError')
   if(!notice){notice=document.createElement('p');notice.id='appearanceError';notice.className='appearance-error';notice.setAttribute('role','alert');notice.setAttribute('popover','manual');document.body.append(notice)}
   notice.textContent=error.message||'界面模式未能保存。';notice.showPopover?.()
  }
 }
 apply(current,false)
 window.appearance?.onChange(value=>apply(value))
 window.addEventListener('storage',event=>{if(event.key===key&&valid(event.newValue))apply(event.newValue,false)})
 document.addEventListener('DOMContentLoaded',()=>{
  apply(current)
  document.querySelectorAll('[data-theme-toggle]').forEach(button=>button.addEventListener('click',()=>set(current==='light'?'dark':'light')))
  document.querySelectorAll('[data-theme-select]').forEach(select=>select.addEventListener('change',()=>set(select.value)))
 })
 window.StarAppearance={get:()=>current,apply,set}
})()
