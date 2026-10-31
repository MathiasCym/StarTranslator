// Reference-only data is never sent to the translation or glossary-edit APIs.
(() => {
  let data = null, page = 0, selected = '', busy = false
  const size = 40, normalize = value => String(value || '').normalize('NFKC').toLocaleLowerCase().trim()
  function detail(row) {
    selected = row?.id || ''
    $('catalogDetail').replaceChildren()
    if (!row) { $('catalogDetail').textContent = '没有匹配的术语。'; return }
    for (const language of data.languages) {
      const section = document.createElement('section'), heading = document.createElement('h4'), text = document.createElement('p')
      heading.textContent = `${language.name} · ${language.code}`
      text.lang = language.code; text.textContent = row.terms[language.code] || '— 未提供 —'
      section.append(heading, text); $('catalogDetail').append(section)
    }
    $('catalogDetail').scrollTop = 0
    for (const button of $('catalogRows').querySelectorAll('button')) button.setAttribute('aria-pressed', String(button.dataset.id === selected))
  }
  function render() {
    if (!data) return
    const query = normalize($('catalogSearch').value), code = $('catalogLanguage').value
    const rows = data.entries.filter(row => (!code || row.terms[code]) &&
      (!query || (code ? [row.terms[code]] : Object.values(row.terms)).some(text => normalize(text).includes(query))))
    const pages = Math.max(1, Math.ceil(rows.length / size)); page = Math.max(0, Math.min(page, pages - 1))
    $('catalogCount').textContent = `${rows.length} / ${data.entries.length} 条 · 第 ${page + 1} / ${pages} 页`
    $('catalogPrev').disabled = !page || busy; $('catalogNext').disabled = page + 1 >= pages || busy
    $('catalogRows').replaceChildren()
    const slice = rows.slice(page * size, (page + 1) * size)
    for (const row of slice) {
      const button = document.createElement('button'), primary = document.createElement('strong'), secondary = document.createElement('span')
      button.type = 'button'; button.className = 'catalog-row'; button.dataset.id = row.id
      primary.textContent = row.terms['zh-CN'] || row.terms['en-US'] || Object.values(row.terms)[0]
      secondary.textContent = row.terms[code || 'en-US'] || '— 未提供 —'
      button.append(primary, secondary); button.setAttribute('aria-pressed', 'false')
      button.onclick = () => detail(row); $('catalogRows').append(button)
    }
    detail(slice.find(row => row.id === selected) || slice[0])
    $('catalogRows').scrollTop = 0
  }
  async function load() {
    if (busy) return
    busy = true; $('catalogReload').disabled = true; $('catalogStatus').textContent = '正在读取多语言术语…'
    try {
      data = await callApi('GET', '/api/lexicon/catalog')
      const code = $('catalogLanguage').value
      $('catalogLanguage').replaceChildren(new Option('全部语言', ''), ...data.languages.map(lang => new Option(`${lang.name}（${lang.count} 条）`, lang.code)))
      if (data.languages.some(lang => lang.code === code)) $('catalogLanguage').value = code
      $('catalogStatus').textContent = `${data.source} · ${data.languages.length} 种语言 · 仅供查阅`
      render()
    } catch (error) { $('catalogStatus').textContent = error.message }
    finally { busy = false; $('catalogReload').disabled = false; if (data) render() }
  }
  // This script loads before app.js defines helpers; resolve them on interaction.
  document.getElementById('openMultilingual').onclick = () => { $('multilingualDialog').showModal(); if (!data) load(); else render(); $('catalogSearch').focus() }
  document.getElementById('closeMultilingual').onclick = () => $('multilingualDialog').close()
  document.getElementById('multilingualDialog').addEventListener('close', () => $('openMultilingual').focus())
  document.getElementById('catalogReload').onclick = load
  document.getElementById('catalogSearch').oninput = document.getElementById('catalogLanguage').onchange = () => { page = 0; render() }
  document.getElementById('catalogPrev').onclick = () => { page--; render() }
  document.getElementById('catalogNext').onclick = () => { page++; render() }
})()
