const test = require('node:test'), assert = require('node:assert/strict')
const { rankTermRows } = require('../renderer/term-search')

test('exact LED standard outranks many incidental matches and reaches the first page', () => {
  const rows = Array.from({ length: 70 }, (_, i) => ['相关术语' + i, 'MLED module', 'LED industry', ''])
  rows.push(['发光二极管', 'LED', '', 'Light-emitting diode'])
  const columns = ['zh', 'en', 'note', 'variants']
  for (const query of ['LED', 'led', 'ＬＥＤ', ' LED ']) {
    const matches = rankTermRows(rows, columns, query)
    assert.equal(matches[0].row[1], 'LED')
    assert.equal(matches.length, 71)
  }
  assert.equal(rankTermRows(rows, columns, 'diode')[0].row[1], 'LED')
})

test('reordered columns and aliases remain searchable; metadata does not create matches', () => {
  const columns = ['source', 'variants', 'en', 'zh', 'priority', null]
  const rows = [['secret-source', 'Printed Circuit Board', 'PCB', '线路板', 'secret-priority', 'Team tag'],
    ['', '', 'PCB assembly', '装配', '', '']]
  assert.equal(rankTermRows(rows, columns, 'Printed Circuit Board')[0].index, 0)
  assert.equal(rankTermRows(rows, columns, 'PCB')[0].index, 0)
  assert.equal(rankTermRows(rows, columns, 'Team tag')[0].index, 0)
  assert.equal(rankTermRows(rows, columns, 'secret').length, 0)
  assert.deepEqual(rankTermRows(rows, columns, '').map(r => r.index), [0, 1])
  assert.equal(rankTermRows(rows, columns, '[unknown]').length, 0)
})
