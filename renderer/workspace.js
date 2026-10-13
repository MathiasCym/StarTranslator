// Keep keyboard navigation inside the current dialog and return to its opener.
;(() => {
  const dialogs = [...document.querySelectorAll('.modal[id]')]
  const page = [...document.querySelectorAll('body > header, body > main')]
  const settings = {
    lexiconModal: { initial: 'termSearch', close: 'closeLexicon', opener: 'openLexicon' },
    modelModal: { initial: 'modelProfileName', close: 'modelClose', opener: 'openModel' },
    aboutModal: { initial: 'closeAbout', close: 'closeAbout', opener: 'openAbout' },
    historyModal: { initial: 'historyPreset', close: 'closeHistory', opener: 'openHistory' },
    reportModal: { initial: 'reportStatus', close: 'backBtn', opener: 'viewReport' },
    confirmationModal: { initial: 'confirmationCancel', close: 'confirmationCancel' },
    combinedOutputModal: { initial: 'combinedOutputStart', close: 'combinedOutputCancel' }
  }
  let current = null, lastExternalFocus = null, initialized = false
  const openers = new Map()
  document.addEventListener('focusin', event => {
    if (!event.target.closest('.modal') && event.target !== document.body) lastExternalFocus = event.target
  })
  const controls = dialog => [...dialog.querySelectorAll('button, input, select, textarea, summary, [tabindex]')]
    .filter(el => !el.disabled && el.tabIndex >= 0 && el.getClientRects().length && !el.closest('[hidden]'))
  function sync() {
    const next = dialogs.filter(dialog => !dialog.hidden).at(-1) || null
    if (initialized && next === current) return
    initialized = true
    const previous = current
    current = next
    let returning = previous?.hidden ? openers.get(previous) : null
    const visited = new Set()
    while (returning?.closest('.modal')?.hidden) {
      const parent = returning.closest('.modal')
      if (visited.has(parent)) { returning = lastExternalFocus; break }
      visited.add(parent); returning = openers.get(parent)
    }
    if (next && !openers.has(next)) {
      const active = document.activeElement
      openers.set(next, active !== document.body && !next.contains(active) ? active : lastExternalFocus || document.getElementById(settings[next.id]?.opener))
    }
    dialogs.forEach(dialog => { dialog.inert = dialog !== next })
    page.forEach(el => { el.inert = !!next })
    if (next) {
      const target = returning && next.contains(returning) ? returning : document.getElementById(settings[next.id]?.initial) || controls(next)[0]
      target?.focus({ preventScroll: true })
    } else {
      if (returning?.isConnected) returning.focus({ preventScroll: true })
    }
    dialogs.filter(dialog => dialog.hidden).forEach(dialog => openers.delete(dialog))
  }
  const observer = new MutationObserver(sync)
  dialogs.forEach(dialog => observer.observe(dialog, { attributes: true, attributeFilter: ['hidden'] }))
  document.addEventListener('keydown', event => {
    if (document.querySelector('dialog[open]')) return
    if (!current) return
    if (event.key === 'Escape') {
      event.preventDefault()
      document.getElementById(settings[current.id]?.close)?.click()
    } else if (event.key === 'Tab') {
      const items = controls(current)
      if (!items.length) { event.preventDefault(); return }
      const first = items[0], last = items[items.length - 1]
      if (!current.contains(document.activeElement) || (event.shiftKey && document.activeElement === first)) {
        event.preventDefault(); (event.shiftKey ? last : first).focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus()
      }
    }
  })
  // The brand image opens About; give it the same keyboard behavior as a button.
  const brand = document.getElementById('aboutOpen')
  brand.setAttribute('role', 'button'); brand.setAttribute('aria-label', '关于星译官'); brand.tabIndex = 0
  brand.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); brand.click() }
  })
  sync()
})()
