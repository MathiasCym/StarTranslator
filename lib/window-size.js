// Electron work areas already use device-independent pixels; do not scale twice.
function defaultWindowSize(workArea) {
  // Leave desktop space on smaller/scaled screens; large monitors need no extra UI enlargement.
  const width = Math.max(1, Math.min(1280, Math.max(960, Math.round(workArea.width * .86)), workArea.width - 40))
  const height = Math.max(1, Math.min(820, Math.max(580, Math.round(workArea.height * .86)), workArea.height - 40))
  return { width, height, minWidth: Math.min(960, width), minHeight: Math.min(580, height) }
}
function fitBounds(workArea, bounds) {
  const size = defaultWindowSize(workArea)
  const width = Math.min(bounds.width, size.width), height = Math.min(bounds.height, size.height)
  return {
    width, height,
    x: Math.round(Math.max(workArea.x, Math.min(bounds.x, workArea.x + workArea.width - width))),
    y: Math.round(Math.max(workArea.y, Math.min(bounds.y, workArea.y + workArea.height - height)))
  }
}
function installDisplaySizing(window, screen, initialDisplay) {
  let displayId = initialDisplay.id, areaKey = JSON.stringify(initialDisplay.workArea), needsFit = false, needsDefault = false, timer
  const adapt = () => {
    if (window.isDestroyed()) return
    const bounds = window.getBounds(), display = screen.getDisplayMatching(bounds)
    const changed = display.id !== displayId
    displayId = display.id
    const nextKey = JSON.stringify(display.workArea)
    needsFit ||= changed || nextKey !== areaKey
    needsDefault ||= changed
    areaKey = nextKey
    const size = defaultWindowSize(display.workArea)
    window.setMinimumSize(size.minWidth, size.minHeight)
    if (window.isMaximized() || window.isMinimized() || window.isFullScreen()) return
    if (!needsFit) return
    const next = fitBounds(display.workArea, needsDefault ? { ...bounds, width: size.width, height: size.height } : bounds)
    needsFit = needsDefault = false
    if (Object.keys(next).some(key => bounds[key] !== next[key])) window.setBounds(next)
  }
  const schedule = () => { clearTimeout(timer); timer = setTimeout(adapt, 180) }
  window.on('move', schedule)
  window.on('unmaximize', schedule)
  screen.on('display-metrics-changed', schedule)
  screen.on('display-removed', schedule)
  window.once('closed', () => {
    clearTimeout(timer)
    screen.removeListener('display-metrics-changed', schedule)
    screen.removeListener('display-removed', schedule)
  })
}
module.exports = { defaultWindowSize, fitBounds, installDisplaySizing }
