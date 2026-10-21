"""Let long translated table bodies flow, preserving the form's cell grid."""
from docx.oxml.ns import qn


def fit_word_tables(document):
    # Word can move an entire minimum-height row to the next page before
    # splitting its text. A translated header can leave less room than that
    # minimum, producing a half-empty page even though the body is splittable.
    sections = document.sections
    if not sections: return []
    def effective(value, fallback): return fallback if value is None else value
    available = min((effective(s.page_height,10692130)-effective(s.top_margin,914400)-
                     effective(s.bottom_margin,914400))/635 for s in sections)  # twips
    adjustments = []
    for index, row in enumerate(document.element.body.iter(qn('w:tr'))):
        props = row.find(qn('w:trPr'))
        if props is None: continue
        height = props.find(qn('w:trHeight')); locked = props.find(qn('w:cantSplit'))
        if height is None or height.get(qn('w:hRule')) == 'exact': continue
        if locked is not None and locked.get(qn('w:val'), '1') not in {'0', 'false', 'off'}: continue
        paragraphs = list(row.iter(qn('w:p')))
        text = ''.join(t.text or '' for t in row.iter(qn('w:t')))
        if len(paragraphs) < 4 or len(text) < 600: continue
        try:minimum=int(height.get(qn('w:val'), '0'))
        except ValueError:continue
        if minimum < available*.35: continue
        props.remove(height)
        adjustments.append(dict(locator=f'word/table-row/{index}', reason='长正文表格行允许随内容跨页，不再保留会挤走正文的最小行高。'))
    return adjustments
