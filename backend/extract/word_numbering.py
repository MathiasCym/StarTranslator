"""Visible list labels are document content, not field instructions or links."""
from copy import deepcopy
import re
from collections import Counter
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

EAST_ASIAN = {'chineseCounting', 'chineseCountingThousand', 'chineseLegalSimplified',
    'taiwaneseCounting', 'taiwaneseCountingThousand', 'taiwaneseDigital',
    'ideographDigital', 'ideographTraditional', 'ideographLegalTraditional'}


def used_levels(document):
    part = next((p for p in document.part.package.parts
                 if str(p.partname) == '/word/numbering.xml'), None)
    if part is None: return None, []
    root = part.element
    styles = {s.get(qn('w:styleId')): s for s in document.styles.element}
    used = set()
    for owner in document.part.package.parts:
        element = getattr(owner, '_element', None)
        if element is None: continue
        for paragraph in element.iter(qn('w:p')):
            props = paragraph.find(qn('w:pPr'))
            sid = props.find(qn('w:pStyle')) if props is not None else None
            chain = [props] if props is not None else []
            visited = set()
            while sid is not None and sid.get(qn('w:val')) not in visited:
                key = sid.get(qn('w:val')); visited.add(key)
                style = styles.get(key)
                if style is None: break
                chain.append(style.find(qn('w:pPr')))
                sid = style.find(qn('w:basedOn'))
            for prop in chain:
                number = prop.find('w:numPr/w:numId', prop.nsmap) if prop is not None else None
                if number is not None:
                    if number.get(qn('w:val')) != '0': used.add(number.get(qn('w:val')))
                    break
    abstracts = {n.get(qn('w:abstractNumId')): n for n in root.findall(qn('w:abstractNum'))}
    result, seen = [], set()
    for num in root.findall(qn('w:num')):
        if num.get(qn('w:numId')) not in used: continue
        abstract = num.find(qn('w:abstractNumId'))
        base = abstracts.get(abstract.get(qn('w:val'))) if abstract is not None else None
        levels = {n.get(qn('w:ilvl')): n for n in base.findall(qn('w:lvl'))} if base is not None else {}
        for override in num.findall(qn('w:lvlOverride')):
            level = override.find(qn('w:lvl'))
            if level is not None: levels[override.get(qn('w:ilvl'))] = level
        for level in levels.values():
            if level not in seen: seen.add(level); result.append(level)
    return part, result


class LabelRun:
    def __init__(self, paragraph): self.owner, self._r = paragraph, paragraph._p[0]
    @property
    def text(self): return self.owner.node.get(qn('w:val'), '')
    @text.setter
    def text(self, value):
        if Counter(re.findall(r'%[1-9]', value)) != Counter(re.findall(r'%[1-9]', self.owner.original_text)):
            raise ValueError('自动编号占位符必须保持不变。')
        self.owner.node.set(qn('w:val'), value)


class NumberingLabel(Paragraph):
    def __init__(self, node, document):
        self.node = node; self.original_text = node.get(qn('w:val'), '')
        paragraph = OxmlElement('w:p'); run = OxmlElement('w:r'); paragraph.append(run)
        props = node.getparent().find(qn('w:rPr'))
        if props is not None: run.append(deepcopy(props))
        super().__init__(paragraph, document)
    @property
    def text(self): return self.node.get(qn('w:val'), '')
    @property
    def runs(self): return [LabelRun(self)]
    def write_styled(self, groups, runs): self.runs[0].text = ''.join(v['text'] for v in runs)


def english_numbering(document):
    part, levels = used_levels(document)
    changed = False
    for level in levels:
        fmt = level.find(qn('w:numFmt')); label = level.find(qn('w:lvlText'))
        if fmt is not None and fmt.get(qn('w:val')) in EAST_ASIAN:
            fmt.set(qn('w:val'), 'decimal'); changed = True
        if label is not None:
            old = label.get(qn('w:val'), '')
            new = old.replace('、', '. ').replace('（', '(').replace('）', ')')
            if new != old: label.set(qn('w:val'), new); changed = True
    if changed:
        document._star_word_text_parts.add(str(part.partname).lstrip('/'))
