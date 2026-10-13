function rankTermRows(rows, columns, query) {
  const normalize = value => String(value ?? '').normalize('NFKC').trim().replace(/\s+/g, ' ').toLocaleLowerCase()
  query = normalize(query)
  const mapped = rows.map((row, index) => ({ row, index }))
  if (!query) return mapped
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const word = new RegExp('(^|[^\\p{L}\\p{N}])' + escaped + '(?=$|[^\\p{L}\\p{N}])', 'u')
  return mapped.map(item => {
    let score = Infinity
    columns.forEach((field, index) => {
      if (['priority', 'source'].includes(field)) return
      const value = normalize(item.row[index])
      if (!value.includes(query)) return
      const primary = ['zh', 'en'].includes(field)
      const alias = field === 'variants'
      const exact = primary ? value === query : alias && String(item.row[index] ?? '').split(/\r?\n/).some(v => normalize(v) === query)
      const rank = primary ? (exact ? 0 : word.test(value) ? 2 : value.startsWith(query) ? 3 : 6)
        : alias ? (exact ? 1 : word.test(value) ? 4 : 7)
        : ['machine_variants', 'wrong_variants'].includes(field) ? 8 : 9
      score = Math.min(score, rank)
    })
    return { ...item, score }
  }).filter(item => Number.isFinite(item.score)).sort((a, b) => a.score - b.score || a.index - b.index)
}

if (typeof module !== 'undefined' && module.exports) module.exports = { rankTermRows }
