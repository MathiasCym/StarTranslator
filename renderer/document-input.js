// Shared by the custom picker and document import UI.
;(function (root) {
  const isTemporaryOfficeFile = value => String(value || '').split(/[\\/]/).pop().startsWith('~$')
  const temporaryFileMessage = '这是 Office 临时锁文件，请选择不带“~$”前缀的原始文档。'
  const policy = { isTemporaryOfficeFile, temporaryFileMessage }
  if (typeof module === 'object' && module.exports) module.exports = policy
  else root.DocumentInput = policy
})(typeof globalThis !== 'undefined' ? globalThis : this)
