// Shared confirmation surface; never invoke the browser's system dialogs.
window.AppDialogs = (() => {
  const box = document.getElementById('confirmationModal')
  const title = document.getElementById('confirmationTitle')
  const message = document.getElementById('confirmationMessage')
  const accept = document.getElementById('confirmationAccept')
  const cancel = document.getElementById('confirmationCancel')
  let pending = null
  function finish(value) {
    if (!pending) return
    const resolve = pending; pending = null
    box.hidden = true
    resolve(value)
  }
  accept.onclick = () => finish(true)
  cancel.onclick = () => finish(false)
  return {
    ask({ title: heading, message: body, accept: label = '放弃修改', cancel: back = '继续编辑', danger = false }) {
      // A second request must not replace a decision already being reviewed.
      if (pending) return Promise.resolve(false)
      title.textContent = heading; message.textContent = body
      accept.textContent = label; cancel.textContent = back
      accept.classList.toggle('danger', danger)
      box.hidden = false
      return new Promise(resolve => { pending = resolve })
    },
    get isOpen() { return !!pending }
  }
})()
