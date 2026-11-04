'use strict'
window.StarDocumentLanguages = (() => {
  const names = { 'zh-CN':'简体中文', 'en-US':'英语', 'zh-Hant-TW':'繁体中文', 'ja-JP':'日语', ko:'韩语' }
  const legacy = { 'zh-en':['zh-CN','en-US'], 'en-zh':['en-US','zh-CN'] }
  function pair(value) {
    const values = legacy[value] || String(value || '').split('>')
    return values.length === 2 && names[values[0]] && names[values[1]] && values[0] !== values[1] ? values : legacy['zh-en']
  }
  function direction(src,dst) { return src === 'zh-CN' && dst === 'en-US' ? 'zh-en' : src === 'en-US' && dst === 'zh-CN' ? 'en-zh' : src+'>'+dst }
  function configure(select,kind,value) {
    const [src,dst] = pair(value), check = kind === 'check'
    select.replaceChildren()
    for (const source of Object.keys(names)) {
      if (check) {
        const option = document.createElement('option'); option.value = direction(source === 'zh-CN' ? 'en-US' : 'zh-CN',source); option.textContent = names[source]; select.append(option)
      } else {
        const group = document.createElement('optgroup'); group.label = names[source]+'原稿'
        for (const target of Object.keys(names).filter(code => code !== source)) {
          const option = document.createElement('option'); option.value = direction(source,target); option.textContent = names[source]+' → '+names[target]; group.append(option)
        }
        select.append(group)
      }
    }
    select.value = check ? direction(dst === 'zh-CN' ? 'en-US' : 'zh-CN',dst) : direction(src,dst)
    return select.value
  }
  return { names, pair, direction, configure }
})()
