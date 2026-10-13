// Leave space around the window inside the available desktop (excluding taskbars).
function defaultWindowSize(workArea) {
  const width = Math.max(1, Math.min(1440, workArea.width - 80))
  const height = Math.max(1, Math.min(960, workArea.height - 80))
  return { width, height, minWidth: Math.min(1000, width), minHeight: Math.min(700, height) }
}
module.exports = { defaultWindowSize }
