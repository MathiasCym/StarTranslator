const byId = id => document.getElementById(id)
let setupInfo, setupScope = 'current', installing = false, finished = false
function selectScope(value) { setupScope = value; for (const [id, scope] of [['scopeCurrent', 'current'], ['scopeAll', 'all']]) { byId(id).classList.toggle('selected', scope === value); byId(id).setAttribute('aria-pressed', String(scope === value)) } }
function failure(error) { byId('setupMessage').textContent = error.message || String(error) }
function setStatus(value) {
  if (value.phase === 'verifying') {
    byId('setupProgress').hidden = false; byId('setupOptions').hidden = true
    byId('setupStep').textContent = '校验安装完整性'; byId('setupPhase').textContent = `校验安装完整性 · ${value.percent || 0}%${value.total ? `（${value.checked || 0} / ${value.total} 项）` : ''}`
    byId('setupBar').style.width = (80 + (value.percent || 0) / 5) + '%'; byId('setupMeter').setAttribute('aria-valuenow', String(80 + (value.percent || 0) / 5))
    for (const id of ['phaseChecking', 'phaseFiles', 'phaseRegistering']) { byId(id).classList.add('done'); byId(id).classList.remove('active') }
    byId('phaseVerifying').classList.add('active'); byId('phaseVerifying').classList.remove('done')
    byId('setupWorking').textContent = '进行中'; byId('setupBar').classList.add('running')
    byId('setupAction').disabled = byId('setupClose').disabled = true; byId('setupAction').textContent = '正在校验…'
    return
  }
  if (value.phase === 'error') {
    installing = false; byId('setupBar').classList.remove('running'); byId('setupWorking').textContent = '未完成'; byId('setupOptions').hidden = false; byId('setupAction').disabled = false; byId('setupClose').disabled = false
    byId('setupProgress').hidden = true
    byId('setupAction').innerHTML = setupInfo.uninstall ? '重新卸载<span aria-hidden="true">↗</span>' : '重新安装<span aria-hidden="true">↗</span>'; byId('setupStep').textContent = '等待重试'; failure(value.message); return
  }
  const order = ['checking', 'files', 'registering', 'complete'], index = order.indexOf(value.phase)
  if (index < 0) return
  byId('setupMessage').textContent = ''; byId('setupOptions').hidden = true; byId('setupProgress').hidden = false; byId('setupAction').disabled = value.phase !== 'complete'; byId('setupClose').disabled = value.phase !== 'complete'
  byId('setupStep').textContent = setupInfo.uninstall ? '正在卸载' : '正在安装'
  byId('setupPhase').textContent = (setupInfo.uninstall ? ['确认卸载环境', '正在移除程序文件', '正在清理快捷方式与设置'] : ['确认安装环境', '正在写入程序文件', '正在创建快捷方式与设置'])[index] || '完成'
  byId('setupBar').style.width = [10, 45, 80, 100][index] + '%'; byId('setupMeter').setAttribute('aria-valuenow', String([10, 45, 80, 100][index])); byId('setupBar').classList.toggle('running', value.phase !== 'complete')
  byId('setupWorking').textContent = value.phase === 'complete' ? '已完成' : '进行中'
  for (const [i, id] of ['phaseChecking', 'phaseFiles', 'phaseRegistering'].entries()) { byId(id).classList.toggle('done', i < index); byId(id).classList.toggle('active', i === index) }
  byId('phaseVerifying').classList.remove('active', 'done')
  byId('setupAction').textContent = setupInfo.uninstall ? '正在卸载…' : '正在安装…'
  if (value.phase === 'complete') {
    installing = false; finished = true; byId('setupDone').hidden = false; byId('setupStep').textContent = '已完成'; byId('setupTitle').textContent = setupInfo.uninstall ? '期待下一次相遇' : '星译官，准备就绪'; byId('setupDescription').textContent = setupInfo.uninstall ? '星译官已从此电脑移除。' : '安装完成，程序文件完整性校验通过。'; byId('setupMascot').src = 'assets/happy.png'
    if (!setupInfo.uninstall) { byId('phaseVerifying').classList.add('done'); byId('setupPhase').textContent = `完整性校验通过${value.checked ? ` · ${value.checked} 项` : ''}` }
    byId('setupDoneTitle').textContent = setupInfo.uninstall ? '卸载完成' : '校验通过'; byId('setupDoneDescription').textContent = setupInfo.uninstall ? '原文、导出文档和个人词库已保留。' : '可以放心启动星译官。'; byId('setupDonePath').textContent = setupInfo.uninstall ? '' : value.directory
    byId('setupAction').innerHTML = setupInfo.uninstall ? '完成<span aria-hidden="true">✓</span>' : '启动星译官<span aria-hidden="true">↗</span>'; byId('setupExit').hidden = setupInfo.uninstall
  }
}
byId('setupMin').onclick = () => window.setup.minimize()
byId('setupClose').onclick = byId('setupExit').onclick = () => window.setup.close()
byId('scopeCurrent').onclick = () => selectScope('current'); byId('scopeAll').onclick = () => selectScope('all')
byId('setupBrowse').onclick = async () => { try { const dir = await window.setup.pickDirectory(); if (dir) byId('setupPath').value = dir } catch (error) { failure(error) } }
byId('setupAction').onclick = async () => {
  if (installing) return
  try {
    if (finished) { await (setupInfo.uninstall ? window.setup.close() : window.setup.launch()); return }
    installing = true; byId('setupAction').disabled = true; byId('setupMessage').textContent = ''
    const result = await window.setup.start({ directory: byId('setupPath').value.trim(), scope: setupScope })
    if (!result.started) { installing = false; byId('setupAction').disabled = false }
  } catch (error) { installing = false; byId('setupAction').disabled = false; failure(error) }
}
window.setup.onStatus(setStatus)
;(async () => {
  setupInfo = await window.setup.info(); selectScope(setupInfo.scope); byId('setupPath').value = setupInfo.directory; byId('setupVersion').textContent = 'v' + setupInfo.version
  if (setupInfo.upgrade) { byId('scopeCurrent').disabled = byId('scopeAll').disabled = true; byId('setupPathHint').textContent = '发现已安装的星译官。更新将保留模型配置与本机词库。' }
  if (setupInfo.uninstall) {
    document.title = '星译官 · 卸载'; byId('setupStep').textContent = '准备卸载'; byId('setupTitle').textContent = '暂时说声再见'; byId('setupDescription').textContent = '移除程序，保留你的文档和个人词库。'; byId('setupPath').readOnly = true; byId('setupBrowse').hidden = true; document.querySelector('.scope').hidden = true; byId('setupAction').innerHTML = '确认卸载<span aria-hidden="true">↗</span>'
    byId('phaseChecking').textContent = '确认卸载环境'; byId('phaseFiles').textContent = '移除程序文件'; byId('phaseRegistering').textContent = '清理快捷方式与设置'
    byId('phaseVerifying').hidden = true
  }
})().catch(failure)
