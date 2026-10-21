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
from ..text_integrity import contains_chinese
from ..replacer.text_runs import BreakRun

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


class WordTextRun:
    """Edit only a w:t child, leaving sibling objects and field controls intact."""
    def __init__(self, node, parent):
        self.node, self._r, self._parent = node, node.getparent(), parent

    @property
    def text(self): return self.node.text or ''

    @text.setter
    def text(self, value):
        self.node.text = value
        self.node.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')


class WordTextSpan(WordSpan):
    def __init__(self, paragraph, node, reason=''):
        self.node = node
        super().__init__(paragraph, [node.getparent()], reason)

    @property
    def runs(self): return [WordTextRun(self.node, self)]

    def write_styled(self, groups, runs):
        self.runs[0].text = ''.join(item['text'] for item in runs)


class DrawingBreak(BreakRun):
    @BreakRun.text.setter
    def text(self,value):
        a='http://schemas.openxmlformats.org/drawingml/2006/main'
        node=etree.Element('{'+a+'}r')
        rpr=self._r.find('{'+a+'}rPr')
        if rpr is not None:node.append(deepcopy(rpr))
        etree.SubElement(node,'{'+a+'}t').text=value
        self._r.getparent().replace(self._r,node)


class DrawingParagraph:
    """DrawingML inside a Word XML tree has no python-pptx element classes."""
    _star_xml_runs = True
    def __init__(self, node): self._p = node

    @property
    def runs(self):
        a='http://schemas.openxmlformats.org/drawingml/2006/main'
        result=[]
        for r in self._p:
            if r.tag=='{'+a+'}br':result.append(DrawingBreak(r,self))
            elif r.tag=='{'+a+'}r':result.extend(WordTextRun(t,self) for t in r if t.tag=='{'+a+'}t')
        return result

    @property
    def text(self):
        a='http://schemas.openxmlformats.org/drawingml/2006/main'
        return ''.join('\v' if r.tag=='{'+a+'}br' else ''.join(t.text or '' for t in r if t.tag=='{'+a+'}t')
                       for r in self._p if r.tag in {'{'+a+'}r','{'+a+'}br','{'+a+'}fld'})

    def write_styled(self, groups, runs):
        a='http://schemas.openxmlformats.org/drawingml/2006/main'
        templates={g['id']:g['prototype']._r for g in groups}
        children=[r for r in self._p if r.tag in {'{'+a+'}r','{'+a+'}br'}]
        position=self._p.index(children[0])
        for r in children:self._p.remove(r)
        for item in runs:
            if not item['text']:continue
            import re
            for value in re.split(r'([\n\v])',item['text']):
                if not value:continue
                node=deepcopy(templates[item['id']])
                if value in {'\n','\v'}:
                    node.tag='{'+a+'}br'
                    for t in list(node):
                        if t.tag!='{'+a+'}rPr':node.remove(t)
                else:node.find('{'+a+'}t').text=value
                self._p.insert(position,node);position+=1


def _paragraph_spans(paragraph, fields):
    groups, current, group_parent, group_reason = [], [], None, ''

    def flush():
        nonlocal current
        if current:
            groups.append(WordSpan(paragraph, current, group_reason))
            current = []

    def field_reason():
        for field in fields:
            command = field['instruction'].strip().split(None, 1)
            # TOC display labels are cached prose, not instructions or page
            # references. Nested PAGEREF fields remain protected by this loop.
            if not field['result'] or not command or command[0].upper() not in {'HYPERLINK','TOC'}:
                return '动态域结果由 Word 生成，已保护域指令和结果；周围正文仍可翻译。'
        return ''

    def visit(container):
        nonlocal group_parent, group_reason
        for node in container:
            if node.tag == qn('w:r'):
                structural = [n for n in node if n.tag not in TEXT | {qn('w:rPr')} or n.tag==qn('w:tab')]
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
                        elif child.tag == qn('w:t'):
                            groups.append(WordTextSpan(paragraph, child, field_reason()))
                    continue
                if not any(n.tag in TEXT for n in node):
                    flush()
                    continue
                reason = field_reason()
                if node.getparent() is not group_parent or reason != group_reason:
                    flush()
                group_parent, group_reason = node.getparent(), reason
                current.append(node)
            elif node.tag in WRAPPERS:
                flush(); visit(node); flush()
            elif node.tag == qn('w:fldSimple'):
                flush()
                fields.append({'instruction':node.get(qn('w:instr'), ''), 'result':True})
                visit(node); flush(); fields.pop()
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
                        n.tag == qn('w:pPr') or all(c.tag in TEXT | {qn('w:rPr')} and c.tag!=qn('w:tab') for c in n))
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
        if name not in {'word/footnotes.xml', 'word/endnotes.xml', 'word/comments.xml'}: continue
        root = parse_xml(part.blob)
        extra_parts[name] = (part, root)
        for i, note in enumerate(root):
            if note.get(qn('w:type')) in {'separator', 'continuationSeparator'}: continue
            story(note, document, f'part:{name}/note{i}', 'comments' if name.endswith('comments.xml') else 'notes')
    document._star_word_parts = extra_parts
    document._star_word_span_groups = span_groups
    roots = [document.element.body]
    roots += [getattr(section, kind)._element for section in document.sections
              for kind in ('header','footer','first_page_header','first_page_footer','even_page_header','even_page_footer')
              if not getattr(section, kind).is_linked_to_previous]
    roots += [root for _, root in extra_parts.values()]
    text_parts={'word/document.xml',*extra_parts}
    for section in document.sections:
        for kind in ('header','footer','first_page_header','first_page_footer','even_page_header','even_page_footer'):
            part=getattr(section,kind)
            if not part.is_linked_to_previous:text_parts.add(str(part.part.partname).lstrip('/'))
    # Producers can wrap valid paragraphs in alternate-content or other XML
    # containers. Their w:p text remains safe to edit; deleted revisions do not.
    for root_index, root in enumerate(roots):
        for index, node in enumerate(root.iter(qn('w:p'))):
            if node in seen or any(a.tag in {qn('w:del'),qn('w:moveFrom')} for a in node.iterancestors()): continue
            # Traverse the original node, without moving it out of its container.
            parent = node.getparent()
            story(parent, document, f'other/{root_index}/{index}', 'text')
    # DrawingML text is used by some Word shapes and diagrams. Keep its XML
    # owner and links intact, changing only ordinary a:r text inside each a:p.
    a = 'http://schemas.openxmlformats.org/drawingml/2006/main'
    known = {id(root) for root in roots}
    for part in document.part.package.parts:
        name = str(part.partname).lstrip('/')
        if not name.startswith(('word/diagrams/', 'word/charts/', 'word/drawings/')) or not name.endswith('.xml'): continue
        root = getattr(part, '_element', None)
        if root is None: root = parse_xml(part.blob)
        if id(root) not in known:
            roots.append(root); known.add(id(root)); extra_parts[name] = (part, root)
            text_parts.add(name)
    for root_index, root in enumerate(roots):
        for index, node in enumerate(list(root.iter('{'+a+'}p'))):
            paragraphs.append((f'drawing/{root_index}/{index}', DrawingParagraph(node), 'drawing', None, index+1))
    covered = {node for _, para, *_ in paragraphs for run in para.runs
               for node in run._r if node.tag == qn('w:t')}
    for root in roots:
        for node in root.iter(qn('w:t')):
            if node in covered or not contains_chinese(node.text or ''): continue
            if any(a.tag in {qn('w:del'), qn('w:moveFrom')} for a in node.iterancestors()): continue
            blocked.append((f'word_other/{len(blocked)}', node.text, 'word_other', None,
                            '该文字所在 Word 结构尚不能安全写回，已保留并列出；其余正文继续处理。'))
    c='http://schemas.openxmlformats.org/drawingml/2006/chart'
    for root in roots:
        for node in root.iter('{'+c+'}v'):
            if contains_chinese(node.text or '') and any(p.tag in {'{'+c+'}strCache','{'+c+'}strLit','{'+c+'}tx'} for p in node.iterancestors()):
                blocked.append((f'word_chart/{len(blocked)}',node.text,'chart',None,'Word 图表关联的文字仍需处理，已保留原数据与图表关系。'))
    document._star_word_text_parts=text_parts
    from .word_numbering import used_levels, NumberingLabel
    numbering, levels = used_levels(document)
    for index, level in enumerate(levels):
        label = level.find(qn('w:lvlText'))
        if label is not None and contains_chinese(label.get(qn('w:val'), '')):
            paragraphs.append((f'numbering/{index}/label', NumberingLabel(label, document), 'numbering', None, index+1))
            text_parts.add(str(numbering.partname).lstrip('/'))
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
