// Reference-only data is never sent to the translation or glossary-edit APIs.
(() => {
  let data = null, page = 0, selected = '', busy = false
  const size = 40, normalize = value => String(value || '').normalize('NFKC').toLocaleLowerCase().trim()
  const referenceLanguages = () => data.languages.filter(language => !['zh-CN', 'en-US'].includes(language.code))
  const coverage = row => referenceLanguages().filter(language => row.terms[language.code]).length
  function detail(row) {
    selected = row?.id || ''
    $('catalogDetail').replaceChildren()
    if (!row) { $('catalogDetail').textContent = '没有匹配的术语。'; return }
    if (!coverage(row)) {
      const notice = document.createElement('p'); notice.className = 'catalog-missing'
      notice.textContent = '官方原表未提供这一条目的小语种译法，仅收录了中文和英文。可选择左侧带有小语种标记的词条，或按语言筛选。'
      $('catalogDetail').append(notice)
    }
    for (const language of data.languages) {
      const section = document.createElement('section'), heading = document.createElement('h4'), text = document.createElement('p')
      heading.textContent = `${language.name} · ${language.code}`
      text.lang = language.code; text.textContent = row.terms[language.code] || `官方原表未提供${language.name}译法`
      if (!row.terms[language.code]) text.className = 'catalog-unavailable'
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
    // The original first rows contain only Chinese/English. Lead with actual
    // multilingual rows; retain and search every source row without inventing cells.
    rows.sort((a, b) => Number(coverage(b) > 0) - Number(coverage(a) > 0))
    const pages = Math.max(1, Math.ceil(rows.length / size)); page = Math.max(0, Math.min(page, pages - 1))
    $('catalogCount').textContent = `${rows.length} / ${data.entries.length} 条 · 第 ${page + 1} / ${pages} 页`
    $('catalogPrev').disabled = !page || busy; $('catalogNext').disabled = page + 1 >= pages || busy
    $('catalogRows').replaceChildren()
    const slice = rows.slice(page * size, (page + 1) * size)
    for (const row of slice) {
      const button = document.createElement('button'), primary = document.createElement('strong'), secondary = document.createElement('span'), languages = document.createElement('small')
      button.type = 'button'; button.className = 'catalog-row'; button.dataset.id = row.id
      primary.textContent = row.terms['zh-CN'] || row.terms['en-US'] || Object.values(row.terms)[0]
      secondary.textContent = row.terms[code || 'en-US'] || '官方原表未提供'
      languages.textContent = coverage(row) ? `${coverage(row)} 种小语种译法` : '原表仅提供中英文'
      button.append(primary, secondary, languages); button.setAttribute('aria-pressed', 'false')
      button.onclick = () => detail(row); $('catalogRows').append(button)
    }
    detail(slice.find(row => row.id === selected) || slice[0])
    $('catalogRows').scrollTop = 0
  }
  async function load() {
    if (busy) return
    busy = true; $('catalogReload').disabled = true; $('catalogStatus').textContent = '正在读取多语言术语…'
    try {
      const incoming = await callApi('GET', '/api/lexicon/catalog')
      if (!incoming?.entries?.length || !incoming?.languages?.length) throw Error('多语言资料未能载入。请点击“重新读取”；若仍为空，请在“关于”中校验软件完整性。')
      data = incoming
      const code = $('catalogLanguage').value
      $('catalogLanguage').replaceChildren(new Option('全部语言', ''), ...data.languages.map(lang => new Option(`${lang.name}（${lang.count} 条）`, lang.code)))
      if (data.languages.some(lang => lang.code === code)) $('catalogLanguage').value = code
      const available = data.entries.filter(row => coverage(row) > 0).length
      $('catalogStatus').textContent = `${data.source} · ${data.languages.length} 种语言 · 资料已载入：${data.entries.length} 条，其中 ${available} 条含小语种 · 仅供查阅`
      render()
    } catch (error) { $('catalogStatus').textContent = error.message; if (!data) { $('catalogRows').replaceChildren(); $('catalogDetail').textContent = '多语言资料读取失败，请重新读取。'; $('catalogCount').textContent = '尚未载入'; $('catalogPrev').disabled = $('catalogNext').disabled = true } }
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
