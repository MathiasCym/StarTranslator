// Shared by the custom picker and document import UI.
;(function (root) {
  const isTemporaryOfficeFile = value => String(value || '').split(/[\\/]/).pop().startsWith('~$')
  const temporaryFileMessage = '这是 Office 临时锁文件，请选择不带“~$”前缀的原始文档。'
  const extensions = ['docx', 'pptx', 'pdf', 'xlsx', 'txt', 'md', 'markdown', 'html', 'htm', 'json', 'epub', 'srt', 'ass']
  const policy = { isTemporaryOfficeFile, temporaryFileMessage, extensions,
    supported: value => extensions.includes(String(value || '').split('.').pop().toLowerCase()),
    formatsMessage: '支持 Word、PPT、PDF、Excel、文本、Markdown、HTML、JSON、EPUB 和字幕。PDF 文字层输出为 Word；扫描件需要先识别文字。' }
  if (typeof module === 'object' && module.exports) module.exports = policy
  else root.DocumentInput = policy
})(typeof globalThis !== 'undefined' ? globalThis : this)
