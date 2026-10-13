"""Visible master/layout text and chart labels with their embedded workbook."""
from io import BytesIO
from pathlib import PurePosixPath
import posixpath
from zipfile import ZipFile
from lxml import etree
from pptx.text.text import TextFrame

A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
C = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
NS = {'a':A, 'c':C, 'p':P}


class Owner:
    def __init__(self, part):
        self.part = part


class XmlRun:
    def __init__(self, element, parent):
        self._r, self._parent = element, parent

    @property
    def text(self):
        return self._r.text or ''

    @text.setter
    def text(self, value):
        self._r.text = value


class XmlParagraph:
    def __init__(self, node):
        self.node, self._p = node, node.getparent()
        self.original = node.text or ''

    @property
    def runs(self):
        # write_styled replaces the original node, so always locate its successor.
        return [XmlRun(self._p.find(f'{{{C}}}v'), self)]

    @property
    def text(self):
        return self.runs[0].text


def extra_paragraphs(path, document):
    paragraphs, parts, workbooks, blocked = [], {}, {}, []
    package = {str(part.partname).lstrip('/'):part for part in document.part.package.iter_parts()}
    with ZipFile(path) as archive:
        names = set(archive.namelist())
        for name in sorted(names):
            if not name.endswith('.xml') or not name.startswith(('ppt/slideMasters/', 'ppt/slideLayouts/', 'ppt/charts/')):
                continue
            if '/_rels/' in name or name not in package:
                continue
            part = package[name]
            root = getattr(part, '_element', None)
            if root is None:
                root = etree.fromstring(archive.read(name))
            parts[name] = root
            source = 'chart' if name.startswith('ppt/charts/') else 'template'
            if source == 'template':
                nodes = root.xpath('.//p:sp[not(p:nvSpPr/p:nvPr/p:ph)]/p:txBody', namespaces=NS) if type(root) is etree._Element else root.xpath('.//p:sp[not(p:nvSpPr/p:nvPr/p:ph)]/p:txBody')
            else:
                nodes = root.xpath('.//a:txBody | .//c:rich', namespaces=NS) if type(root) is etree._Element else root.xpath('.//a:txBody | .//c:rich')
            for i, body in enumerate(nodes):
                for j, paragraph in enumerate(TextFrame(body, Owner(part)).paragraphs):
                    paragraphs.append((f'part:{name}/body{i}/p{j}', paragraph, source, None, j+1))
            if source != 'chart':
                continue
            rel_name = posixpath.join(posixpath.dirname(name), '_rels', PurePosixPath(name).name + '.rels')
            workbook = None
            if rel_name in names:
                relationships = etree.fromstring(archive.read(rel_name))
                for rel in relationships:
                    if rel.get('Type', '').endswith('/package') and rel.get('TargetMode') != 'External':
                        target = posixpath.normpath(posixpath.join(posixpath.dirname(name), rel.get('Target', '')))
                        if target.startswith('ppt/embeddings/') and target.endswith('.xlsx') and target in names:
                            workbook = target
                            break
            labels = []
            for node in root.iter(f'{{{C}}}v'):
                parent = node.getparent()
                # Never touch numeric caches or formula/axis references.
                ancestors = {ancestor.tag for ancestor in node.iterancestors()}
                if f'{{{C}}}strLit' not in ancestors and not (workbook and f'{{{C}}}strCache' in ancestors):
                    if f'{{{C}}}strCache' in ancestors:
                        import re
                        if re.search(r'[\u3400-\u9fff]',node.text or ''):
                            blocked.append((f'part:{name}/linked-label{len(blocked)}',node.text,'chart',None,
                                '该图表关联外部数据，需更新关联数据中的中文标签。'))
                    continue
                proxy = XmlParagraph(node)
                labels.append(proxy)
                paragraphs.append((f'part:{name}/label{len(labels)-1}', proxy, 'chart', None, len(labels)))
            if workbook:
                workbooks.setdefault(workbook, []).extend(labels)
    document._star_extra_parts = parts
    document._star_workbooks = workbooks
    document._star_extra_blocked = blocked
    return paragraphs


def changed_extra_parts(document, changed, original):
    result = {}
    names = set()
    for locator in changed:
        if locator.startswith('part:'):
            names.add(locator[5:].split('.xml/',1)[0] + '.xml')
    for name in names:
        root = document._star_extra_parts[name]
        result[name] = etree.tostring(root, encoding='UTF-8', xml_declaration=True, standalone=True)
    for name, paragraphs in getattr(document, '_star_workbooks', {}).items():
        replacements = {}
        for paragraph in paragraphs:
            if paragraph.text != paragraph.original:
                existing = replacements.get(paragraph.original)
                if existing is not None and existing != paragraph.text:
                    raise ValueError('同一图表标签出现不同译法，未导出，请重试。')
                replacements[paragraph.original] = paragraph.text
        if not replacements:
            continue
        target = BytesIO()
        with ZipFile(BytesIO(original.read(name))) as workbook, ZipFile(target, 'w') as output:
            output.comment = workbook.comment
            for info in workbook.infolist():
                data = workbook.read(info.filename)
                if info.filename == 'xl/sharedStrings.xml' or info.filename.startswith('xl/worksheets/') and info.filename.endswith('.xml'):
                    root = etree.fromstring(data)
                    edited = False
                    for container in root.iter(f'{{{S}}}si', f'{{{S}}}is'):
                        texts = list(container.iter(f'{{{S}}}t'))
                        old = ''.join(node.text or '' for node in texts)
                        if old in replacements and texts:
                            texts[0].text = replacements[old]
                            for node in texts[1:]: node.text = ''
                            edited = True
                    if edited:
                        data = etree.tostring(root, encoding='UTF-8', xml_declaration=True, standalone=True)
                output.writestr(info, data)
        result[name] = target.getvalue()
    return result
