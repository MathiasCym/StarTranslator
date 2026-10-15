// Background checks never interrupt a document task or another dialog.
;(() => {
  const dialog = document.getElementById('updateNoticeDialog')
  let pending = null, finishing = false, seenManually = false
  function present() {
    if (!pending || dialog.open || document.hidden || !document.hasFocus() || state.busy || state.exportBusy || state.choosingOutput || integrityBusy || profileBusy) return
    if (document.querySelector('dialog[open],.modal:not([hidden])') || document.getElementById('workspace').hidden) return
    document.getElementById('updateNoticeIntro').textContent = `星译官 v${pending.version} 已发布，本次重点更新：`
    document.getElementById('updateNoticeHighlights').replaceChildren(...pending.highlights.map(text => {
      const item = document.createElement('li'); item.textContent = text; return item
    }))
    document.getElementById('ignoreUpdateVersion').checked = false
    document.getElementById('updateNoticeError').hidden = true
    dialog.showModal()
  }
  async function finish(view = false) {
    if (finishing) return
    finishing = true
    try {
      if (document.getElementById('ignoreUpdateVersion').checked) await window.api.ignoreUpdateNotice(pending.version)
      pending = null; dialog.close()
      if (view) {
        document.getElementById('updateDialog').showModal()
        document.getElementById('updateCheck').click()
      }
    } catch (error) {
      const message = document.getElementById('updateNoticeError')
      message.textContent = '未能保存提醒设置：' + error.message; message.hidden = false
    } finally { finishing = false }
  }
  for (const id of ['closeUpdateNotice', 'laterUpdateNotice']) document.getElementById(id).onclick = () => finish()
  document.getElementById('viewUpdateNotice').onclick = () => finish(true)
  document.getElementById('openUpdates').addEventListener('click', () => { seenManually = true; pending = null })
  dialog.addEventListener('cancel', event => { event.preventDefault(); finish() })
  window.addEventListener('focus', present)
  document.addEventListener('visibilitychange', present)
  new MutationObserver(present).observe(document.body, { subtree: true, attributes: true, attributeFilter: ['hidden', 'open', 'inert'] })
  setTimeout(() => window.api.startupUpdateNotice().then(value => { pending = seenManually ? null : value; present() }).catch(() => {}), 1800)
})()
