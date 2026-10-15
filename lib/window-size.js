// Match the approved 1520×980 reference in screen pixels, including Windows DPI.
// Electron bounds are DIP, while web zoom must keep the same reference text size.
const REFERENCE_SCALE = 1.1875
function referenceZoom(scaleFactor = 1, workArea) {
  const dpi = scaleFactor > 0 ? scaleFactor : 1
  const scale = workArea ? Math.max(1, Math.min(REFERENCE_SCALE, (workArea.width * dpi - 64) / 960, (workArea.height * dpi - 64) / 540)) : REFERENCE_SCALE
  return scale / dpi
}
function defaultWindowSize(workArea, scaleFactor = 1) {
  const dpi = scaleFactor > 0 ? scaleFactor : 1, zoom = referenceZoom(dpi, workArea)
  const width = Math.max(1, Math.floor(Math.min(1520 / dpi, workArea.width - 64 / dpi)))
  const height = Math.max(1, Math.floor(Math.min(980 / dpi, workArea.height - 64 / dpi)))
  return { width, height, minWidth: Math.min(Math.floor(960 * zoom), width), minHeight: Math.min(Math.floor(540 * zoom), height) }
}
function fitBounds(workArea, bounds, scaleFactor = 1) {
  const size = defaultWindowSize(workArea, scaleFactor)
  const width = Math.min(bounds.width, size.width), height = Math.min(bounds.height, size.height)
  return {
    width, height,
    x: Math.round(Math.max(workArea.x, Math.min(bounds.x, workArea.x + workArea.width - width))),
    y: Math.round(Math.max(workArea.y, Math.min(bounds.y, workArea.y + workArea.height - height)))
  }
}
function installDisplaySizing(window, screen, initialDisplay) {
  let displayId = initialDisplay.id, areaKey = JSON.stringify(initialDisplay.workArea), scale = initialDisplay.scaleFactor || 1, needsFit = false, needsDefault = false, timer
  const applyZoom = display => {
    const zoom = referenceZoom(display.scaleFactor, display.workArea)
    if (Math.abs(window.webContents.getZoomFactor() - zoom) > .0001) window.webContents.setZoomFactor(zoom)
  }
  applyZoom(initialDisplay)
  window.webContents.on('did-finish-load', () => { if (!window.isDestroyed()) applyZoom(screen.getDisplayMatching(window.getBounds())) })
  const adapt = () => {
    if (window.isDestroyed()) return
    const bounds = window.getBounds(), display = screen.getDisplayMatching(bounds)
    const changed = display.id !== displayId || (display.scaleFactor || 1) !== scale
    displayId = display.id
    scale = display.scaleFactor || 1
    applyZoom(display)
    const nextKey = JSON.stringify(display.workArea)
    needsFit ||= changed || nextKey !== areaKey
    needsDefault ||= changed
    areaKey = nextKey
    const size = defaultWindowSize(display.workArea, display.scaleFactor)
    window.setMinimumSize(size.minWidth, size.minHeight)
    if (window.isMaximized() || window.isMinimized() || window.isFullScreen()) return
    if (!needsFit) return
    const next = fitBounds(display.workArea, needsDefault ? { ...bounds, width: size.width, height: size.height } : bounds, display.scaleFactor)
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
module.exports = { defaultWindowSize, fitBounds, installDisplaySizing, referenceZoom }
