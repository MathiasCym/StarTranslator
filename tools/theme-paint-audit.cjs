// Browser-side checks; document iframe pixels and mascot images retain originals.
module.exports=function auditThemePaint(){
 const issues=[],parse=value=>{const a=value.match(/[\d.]+/g)?.map(Number);return a?.length>=3?[a[0],a[1],a[2],a[3]??1]:null}
 function background(element){const stack=[];for(let e=element;e;e=e.parentElement)stack.unshift(getComputedStyle(e).backgroundColor);let value=[255,255,255];for(const raw of stack){const c=parse(raw);if(c)value=value.map((v,i)=>c[i]*c[3]+v*(1-c[3]))}return value}
 function luminance(c){return c.slice(0,3).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0)}
 function check(element,pseudo){const style=getComputedStyle(element,pseudo),name=(element.id?'#'+element.id:element.tagName.toLowerCase()+'.'+String(element.className||'').slice(0,70))+(pseudo||'');
  // Status dots and the radio/check glyphs are intentional small indicators,
  // not panel fills. They retain semantic green/red and contrasting ink.
  const rect=element.getBoundingClientRect(),surface=rect.width*rect.height>600
  const c=parse(style.backgroundColor);if(surface&&c&&c[3]>.2&&luminance(c)<.45)issues.push({name,kind:'dark-background',color:style.backgroundColor})
  for(const raw of style.backgroundImage.match(/rgba?\([^)]*\)/g)||[]){const v=parse(raw);if(surface&&v&&v[3]>.2&&luminance(v)<.45)issues.push({name,kind:'dark-gradient',color:raw})}
  const text=!pseudo&&([...element.childNodes].some(n=>n.nodeType===3&&n.textContent.trim())||['TEXTAREA','SELECT'].includes(element.tagName)||element.tagName==='INPUT'&&!['checkbox','radio'].includes(element.type));
  if(text){const ink=parse(style.color);if(ink){if(ink[2]-ink[0]>14&&ink[2]>ink[1]*.95)issues.push({name,kind:'blue-text',color:style.color});
   if(!element.closest(':disabled')){const a=luminance(ink),b=luminance(background(element)),ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);if(ratio<4.5)issues.push({name,kind:'text-contrast',ratio:Number(ratio.toFixed(2)),color:style.color})}
  }}
 }
 for(const element of document.querySelectorAll('body,body *')){
  if(['IMG','IFRAME','CANVAS','SCRIPT','STYLE','OPTION','SVG','PATH','CIRCLE'].includes(element.tagName.toUpperCase())||!element.getClientRects().length)continue
  const rect=element.getBoundingClientRect();if(rect.width<1||rect.height<1)continue
  check(element);for(const pseudo of ['::before','::after']){const s=getComputedStyle(element,pseudo);if(s.content!=='none'&&s.content!=='normal'&&s.display!=='none')check(element,pseudo)}
 }
 for(const dialog of document.querySelectorAll('dialog[open]'))check(dialog,'::backdrop')
 // White is the base surface. A selected state needs an opaque highlight and
 // a strong boundary/glyph; text contrast alone cannot establish selection.
 const selected='.mode.active,.chip.active,.term-card.active,.profile-row.active,.picker-entry.selected,.lexicon-views button.active,button[aria-pressed="true"],.translation-choice:has(input:checked),.output-choice:has(input:checked)'
 for(const element of document.querySelectorAll(selected)){
  if(!element.getClientRects().length)continue
  const style=getComputedStyle(element),fill=parse(style.backgroundColor),edge=parse(style.borderColor)
  if(!fill||fill[3]<.95||Math.max(...fill.slice(0,3))-Math.min(...fill.slice(0,3))<45)issues.push({name:element.id||element.className,kind:'selection-not-distinct',color:style.backgroundColor})
  if(edge&&fill&&style.borderStyle!=='none'&&(Math.max(luminance(edge),luminance(fill))+.05)/(Math.min(luminance(edge),luminance(fill))+.05)<3)issues.push({name:element.id||element.className,kind:'selected-boundary-contrast'})
 }
 for(const element of document.querySelectorAll('input[type="checkbox"]:checked,input[type="radio"]:checked,input:indeterminate')){
  if(!element.getClientRects().length||element.disabled)continue
  const style=getComputedStyle(element),fill=parse(style.backgroundColor)
  if(!fill||fill[3]<.95||fill[0]-fill[2]<60||!(/111111|rgb\(17, 17, 17\)/.test(style.backgroundImage)))issues.push({name:element.id,kind:'checked-glyph-not-distinct',fill:style.backgroundColor,image:style.backgroundImage.slice(0,100)})
 }
 for(const element of document.querySelectorAll('body,.card,.panel,.modal-card,.review-complete,.term-detail,.lexicon-list,.profile-block')){
  if(!element.getClientRects().length||element.matches(selected))continue
  const style=getComputedStyle(element),fill=parse(style.backgroundColor)
  if(fill&&fill[3]>.5&&(Math.min(...fill.slice(0,3))<245||Math.max(...fill.slice(0,3))-Math.min(...fill.slice(0,3))>5))issues.push({name:element.id||element.className,kind:'base-surface-not-white',color:style.backgroundColor})
 }
 return issues.slice(0,24)
}
