// Native modal top layer: help never changes the task panel's height.
(() => {
  for (const options of document.querySelectorAll('[data-translation-options]')) {
    const button = options.querySelector('.translation-help-button')
    const help = document.getElementById(button.getAttribute('aria-controls'))
    const close = () => { if (help.open) help.close() }
    button.addEventListener('click', () => {
      if (help.open) { close(); return }
      help.hidden = false; help.showModal(); button.setAttribute('aria-expanded', 'true')
    })
    help.querySelector('[data-close-help]').addEventListener('click', close)
    help.addEventListener('close', () => {
      help.hidden = true; button.setAttribute('aria-expanded', 'false')
      if (!options.hidden && !options.disabled) button.focus({ preventScroll: true })
    })
    help.addEventListener('click', event => {
      const rect = help.getBoundingClientRect()
      if (event.target === help && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) close()
    })
    new MutationObserver(() => { if (options.hidden || options.disabled || help.hidden) close() })
      .observe(options, { attributes: true, attributeFilter: ['hidden', 'disabled'], subtree: true })
  }
})()
