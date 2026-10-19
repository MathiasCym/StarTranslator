"""Visible Word text separated from immutable field and object boundaries.

Never remove a field, link, drawing or bookmark to translate its surrounding
prose. A span owns only contiguous text-only runs in one XML container.
"""
from copy import deepcopy
from lxml import etree
from docx.oxml.ns import qn
from docx.oxml import parse_xml
from docx.text.paragraph import Paragraph
from docx.text.run import Run

TEXT = {qn('w:t'), qn('w:tab'), qn('w:br'), qn('w:cr')}
WRAPPERS = {qn('w:hyperlink'), qn('w:smartTag'), qn('w:customXml'),
            qn('w:sdtContent'), qn('w:ins'), qn('w:moveTo')}


class WordSpan:
    def __init__(self, paragraph, elements, reason=''):
        self._p, self._parent = paragraph._p, paragraph._parent
        self.elements = list(elements)
        self.not_editable_reason = reason
        self.original_text = self.text

    @property
    def runs(self):
        return [Run(node, self) for node in self.elements]

    @property
    def text(self):
        return ''.join(r.text for r in self.runs)

    @property
    def part(self):
        return self._parent.part

    def write_styled(self, groups, runs):
        prototypes = {g['id']: g['prototype']._r for g in groups}
        parent = self.elements[0].getparent()
        if any(n.getparent() is not parent for n in self.elements):
            raise ValueError('Word 文字边界改变，已保留原段落。')
        position = parent.index(self.elements[0])
        replacement = []
        for item in runs:
            if not item['text']:
                continue
            node = deepcopy(prototypes[item['id']])
            # Templates are text-only: field instructions and objects can never
            # be copied into translated runs, duplicated or deleted here.
            Run(node, self).text = item['text']
            replacement.append(node)
        for node in self.elements:
            parent.remove(node)
        for node in replacement:
            parent.insert(position, node)
            position += 1
        self.elements = replacement


def _paragraph_spans(paragraph, fields):
    groups, current, group_parent, group_reason = [], [], None, ''

    def flush():
        nonlocal current
        if current:
            groups.append(WordSpan(paragraph, current, group_reason))
            current = []

    def visit(container):
        nonlocal group_parent, group_reason
        for node in container:
            if node.tag == qn('w:r'):
                structural = [n for n in node if n.tag not in TEXT | {qn('w:rPr')}]
                if structural:
                    flush()
                    for child in node:
                        if child.tag == qn('w:fldChar'):
                            kind = child.get(qn('w:fldCharType'))
                            if kind == 'begin':
                                fields.append({'instruction': '', 'result': False})
                            elif kind == 'separate' and fields:
                                fields[-1]['result'] = True
                            elif kind == 'end' and fields:
                                fields.pop()
                        elif child.tag == qn('w:instrText') and fields:
                            fields[-1]['instruction'] += child.text or ''
                    # A mixed run is uncommon, but deleting its text would also
                    # delete its object/control. Report just that run truthfully.
                    if any(n.tag in TEXT for n in node):
                        groups.append(WordSpan(paragraph, [node],
                            '文字与域控件或嵌入对象共用同一文字节点，需人工确认。'))
                    continue
                if not any(n.tag in TEXT for n in node):
                    flush()
                    continue
                reason = ''
                for field in fields:
                    command = field['instruction'].strip().split(None, 1)
                    if not field['result'] or not command or command[0].upper() != 'HYPERLINK':
                        reason = '动态域结果由 Word 生成，已保护域指令和结果；周围正文仍可翻译。'
                        break
                if node.getparent() is not group_parent or reason != group_reason:
                    flush()
                group_parent, group_reason = node.getparent(), reason
                current.append(node)
            elif node.tag in WRAPPERS:
                flush(); visit(node); flush()
            elif node.tag == qn('w:sdt'):
                flush()
                content = node.find(qn('w:sdtContent'))
                if content is not None: visit(content)
                flush()
            else:
                # Bookmarks and proofing markers must keep their exact positions.
                flush()
    visit(paragraph._p)
    flush()
    return groups


def word_paragraphs(document):
    paragraphs, blocked, seen, extra_parts, span_groups = [], [], set(), {}, []

    def story(element, parent, prefix, source, fields=None):
        fields = [] if fields is None else fields
        for index, child in enumerate(element):
            key = f'{prefix}/{index}'
            if child.tag == qn('w:p'):
                if child in seen: continue
                seen.add(child)
                paragraph = Paragraph(child, parent)
                simple = not fields and all(
                    n.tag in {qn('w:pPr'), qn('w:r')} and (
                        n.tag == qn('w:pPr') or all(c.tag in TEXT | {qn('w:rPr')} for c in n))
                    for n in child)
                spans = [paragraph] if simple else _paragraph_spans(paragraph, fields)
                if not simple: span_groups.append(spans)
                number = len(paragraphs) + 1
                for i, span in enumerate(spans):
                    locator = key if simple else f'{key}/span{i}'
                    paragraphs.append((locator, span, source, None, number))
                # Text boxes are editable Word text, not an image requiring OCR.
                for i, box in enumerate(child.iter(qn('w:txbxContent'))):
                    story(box, parent, f'{key}/textbox/{i}', 'textbox')
            elif child.tag == qn('w:tbl'):
                # Walk physical cells once; merged cells must not duplicate text.
                for r, row in enumerate(child.findall(qn('w:tr'))):
                    for c, cell in enumerate(row.findall(qn('w:tc'))):
                        story(cell, parent, f'{key}/table/{r}/{c}', 'table', fields)
            elif child.tag == qn('w:sdt'):
                content = child.find(qn('w:sdtContent'))
                if content is not None: story(content, parent, f'{key}/content', source, fields)
            elif child.tag in {qn('w:customXml'), qn('w:ins'), qn('w:moveTo')}:
                story(child, parent, key, source, fields)

    story(document.element.body, document, 'body', 'text')
    for i, section in enumerate(document.sections):
        for kind in ('header','footer','first_page_header','first_page_footer','even_page_header','even_page_footer'):
            part = getattr(section, kind)
            if not part.is_linked_to_previous:
                story(part._element, part, f'section/{i}/{kind}', 'header' if 'header' in kind else 'footer')
    # python-docx exposes these as generic package parts. Retain their complete
    # XML and only synchronize edited text before serializing the original part.
    for part in document.part.package.parts:
        name = str(part.partname).lstrip('/')
        if name not in {'word/footnotes.xml', 'word/endnotes.xml'}: continue
        root = parse_xml(part.blob)
        extra_parts[name] = (part, root)
        for i, note in enumerate(root):
            if note.get(qn('w:type')) in {'separator', 'continuationSeparator'}: continue
            story(note, document, f'part:{name}/note{i}', 'notes')
    document._star_word_parts = extra_parts
    document._star_word_span_groups = span_groups
    roots = [document.element.body]
    roots += [getattr(section, kind)._element for section in document.sections
              for kind in ('header','footer','first_page_header','first_page_footer','even_page_header','even_page_footer')
              if not getattr(section, kind).is_linked_to_previous]
    roots += [root for _, root in extra_parts.values()]
    covered = {node for _, para, *_ in paragraphs for run in para.runs
               for node in run._r if node.tag == qn('w:t')}
    import re
    for root in roots:
        for node in root.iter(qn('w:t')):
            if node in covered or not re.search(r'[\u3400-\u9fff]', node.text or ''): continue
            if any(a.tag in {qn('w:del'), qn('w:moveFrom')} for a in node.iterancestors()): continue
            blocked.append((f'word_other/{len(blocked)}', node.text, 'word_other', None,
                            '该文字所在 Word 结构尚不能安全写回，已保留并列出；其余正文继续处理。'))
    return paragraphs, blocked


def sync_word_parts(document):
    import re
    for spans in getattr(document, '_star_word_span_groups', []):
        visible = [span for span in spans if span.text]
        for left, right in zip(visible, visible[1:]):
            a, b = left.text, right.text
            if a == left.original_text and b == right.original_text: continue
            if left.not_editable_reason: continue
            # Translators trim standalone spans. Restore only new English word
            # boundaries at field/link seams; never split an original English
            # token across styled runs or alter a dynamic field's cached value.
            if re.search(r'[A-Za-z0-9][A-Za-z0-9]$', left.original_text[-1:] + right.original_text[:1]): continue
            if re.search(r'[A-Za-z0-9.,;:!?)]$', a) and re.match(r'[A-Za-z0-9(]', b):
                left.runs[-1].text += ' '
    for part, root in getattr(document, '_star_word_parts', {}).values():
        part._blob = etree.tostring(root, encoding='UTF-8', xml_declaration=True, standalone=True)
