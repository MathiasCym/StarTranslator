/* The same plain-text editor is used by desktop and the owned LAN session. */
;(() => {
  window.StarTextTranslation = { mount({ button, request, prefix, ready = async () => {} }) {
    const dialog = document.createElement('dialog')
    dialog.className = 'text-translator'
    dialog.setAttribute('aria-labelledby', 'textTranslationTitle')
    dialog.innerHTML = `<header class="text-heading"><div><h2 id="textTranslationTitle">文本翻译</h2><p>使用当前模型与术语库，完整翻译并对照复核。</p></div><button type="button" data-close>关闭</button></header>
      <div class="text-toolbar"><label>翻译方向 <select data-direction aria-label="文本翻译方向"><option value="zh-en">中文 → 英文</option><option value="en-zh">英文 → 中文</option></select></label><button type="button" data-swap>交换原文与译文</button><button type="button" data-clear>清空</button></div>
      <div class="text-editors"><label><span class="text-editor-heading">原文 <span data-count>0 / 20,000 字符</span></span><textarea data-source maxlength="20000" placeholder="粘贴或输入需要翻译的文本…" spellcheck="false"></textarea></label><label><span class="text-editor-heading">译文</span><textarea data-target readonly placeholder="译文将在这里显示…" spellcheck="false"></textarea></label></div>
      <div class="text-feedback"><progress max="100" hidden aria-label="文本翻译进度"></progress><p data-status role="status" aria-live="polite">保留段落、数字、型号及网址；每次最多 20,000 字符。</p><p data-error role="alert" hidden></p></div>
      <footer class="text-actions"><button type="button" data-copy disabled>复制译文</button><button type="button" data-retry hidden>重试未完成段落</button><button type="button" data-cancel hidden>取消翻译</button><button type="button" data-start class="primary">开始翻译</button></footer>`
    document.body.append(dialog)
    const find = selector => dialog.querySelector(selector)
    const source = find('[data-source]'), target = find('[data-target]'), direction = find('[data-direction]')
    const status = find('[data-status]'), errorBox = find('[data-error]'), progress = find('progress')
    let active = null, busy = false, complete = false, submitting = false, polling = false, inputSnapshot = null
    function message(text, error = false) {
      if (error) { errorBox.textContent = text; errorBox.hidden = false }
      else { status.textContent = text; errorBox.hidden = true }
    }
    function controls() {
      const locked = busy || submitting
      source.disabled = direction.disabled = locked
      find('[data-start]').disabled = locked || !source.value.trim()
      find('[data-swap]').disabled = locked || !complete
      find('[data-clear]').disabled = locked
      find('[data-cancel]').hidden = !busy
      find('[data-copy]').disabled = !target.value || locked
      find('[data-retry]').hidden = locked || !active || complete || !inputSnapshot || source.value !== inputSnapshot.text || direction.value !== inputSnapshot.direction
      dialog.setAttribute('aria-busy', String(locked))
    }
    function show(job) {
      active = job.id; busy = ['queued', 'running'].includes(job.status)
      progress.hidden = !busy
      progress.value = job.percent || 0
      if (job.result) { target.value = job.result.translation; complete = job.result.complete === true }
      message((busy ? `${job.done} / ${job.total} 段 · ` : '') + job.message)
      if (job.error) message(job.error, true)
      else if (!busy && job.result && !complete) {
        const errors = job.result.blocks.filter(block => block.error).map(block => block.error)
        if (errors.length) message([...new Set(errors)].join('\n'), true)
      }
      controls()
    }
    async function poll() {
      if (polling) return
      polling = true
      try {
        while (busy && active) {
          await new Promise(resolve => setTimeout(resolve, 700))
          try { show(await request('GET', `${prefix}/${active}`)) }
          catch (error) {
            // A failed status request does not mean the accepted work stopped.
            message('暂时无法读取进度，将自动重连。' + error.message, true)
            await new Promise(resolve => setTimeout(resolve, 2500))
          }
        }
      } finally { polling = false }
    }
    async function start(retry) {
      if (busy || submitting) return
      submitting = true; controls(); message('正在提交文本翻译…')
      try {
        await ready()
        const body = { text: source.value, direction: direction.value, kind: 'text' }
        if (retry && active) body.retry_of = active
        const job = await request('POST', prefix, body)
        inputSnapshot = { text: body.text, direction: body.direction }
        target.value = ''; complete = false; show(job)
        poll()
      } catch (error) { message(error.message, true) }
      finally { submitting = false; controls() }
    }
    button.addEventListener('click', () => {
      if (!dialog.open) dialog.showModal()
      source.focus(); controls()
    })
    find('[data-close]').onclick = () => dialog.close()
    dialog.addEventListener('close', () => button.focus())
    find('[data-start]').onclick = () => start(false)
    find('[data-retry]').onclick = () => start(true)
    find('[data-cancel]').onclick = async () => {
      try { await request('POST', `${prefix}/${active}/cancel`, {}); message('正在结束当前请求，完成部分会保留。') }
      catch (error) { message(error.message, true) }
    }
    source.addEventListener('input', () => { find('[data-count]').textContent = `${source.value.length.toLocaleString()} / 20,000 字符`; controls() })
    direction.onchange = controls
    find('[data-clear]').onclick = () => {
      source.value = target.value = ''; complete = false; active = null; source.dispatchEvent(new Event('input'))
      message('保留段落、数字、型号及网址；每次最多 20,000 字符。'); source.focus()
    }
    find('[data-swap]').onclick = () => {
      const original = source.value; source.value = target.value; target.value = original
      direction.value = direction.value === 'zh-en' ? 'en-zh' : 'zh-en'
      complete = false; active = null; source.dispatchEvent(new Event('input')); source.focus()
      message('已交换文本，请点击“开始翻译”使用新的方向。')
    }
    find('[data-copy]').onclick = async () => {
      try { await navigator.clipboard.writeText(target.value); message('已复制' + (complete ? '译文。' : '当前结果；标记的未完成段落仍需重试。')) }
      catch { target.focus(); target.select(); message('已选中译文，请按 Ctrl+C 复制。') }
    }
    source.addEventListener('keydown', event => {
      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); start(false) }
    })
    controls()
    return { dialog }
  } }
})()
