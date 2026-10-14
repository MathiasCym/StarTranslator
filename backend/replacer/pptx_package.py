"""Preserve untouched Office package parts byte-for-byte, including extensions."""
from pathlib import Path
import re
from zipfile import ZipFile
def save_office(source, document, destination, changed):
    if Path(source).suffix.lower() != '.pptx':
        document.save(str(destination))
        return
    parts = {}
    for locator in changed:
        if locator.startswith('part:'):
            continue
        match = re.match(r'^slide(\d+)/(.*)', locator)
        if not match:
            raise ValueError('幻灯片文字位置无效，未导出。')
        slide = document.slides[int(match[1])-1]
        part = slide.notes_slide.part if match[2].startswith('notes/') else slide.part
        parts[str(part.partname).lstrip('/')] = part
    with ZipFile(source, 'r') as original, ZipFile(destination, 'w') as output:
        from ..extract.pptx_extra import changed_extra_parts
        extras = changed_extra_parts(document, changed, original)
        output.comment = original.comment
        for info in original.infolist():
            data = extras.get(info.filename) if info.filename in extras else parts[info.filename].blob if info.filename in parts else original.read(info.filename)
            if info.filename in parts or info.filename in extras:
                _guard_part(info.filename, original.read(info.filename), data)
            output.writestr(info, data)


def _guard_part(name, before, after):
    """Reject geometry/animation/table changes before writing the original package."""
    if not name.endswith('.xml') or not name.startswith(('ppt/slides/','ppt/notesSlides/','ppt/slideMasters/','ppt/slideLayouts/')):
        return
    from lxml import etree
    a='http://schemas.openxmlformats.org/drawingml/2006/main'
    p='http://schemas.openxmlformats.org/presentationml/2006/main'
    def skeleton(raw):
        root=etree.fromstring(raw)
        for body in root.xpath('.//p:txBody | .//a:txBody',namespaces={'p':p,'a':a}):
            # Text and typography are editable. Fields and list semantics are not.
            paragraphs=body.findall(f'{{{a}}}p')
            signatures=[]
            for para in paragraphs:
                ppr=para.find(f'{{{a}}}pPr')
                signatures.append((dict(ppr.attrib) if ppr is not None else {},
                    [(n.tag,etree.tostring(n,method='c14n')) for n in para.iter()
                     if n.tag in {f'{{{a}}}fld',f'{{{a}}}buChar',f'{{{a}}}buAutoNum',f'{{{a}}}buNone'}]))
            bodypr=body.find(f'{{{a}}}bodyPr')
            layout={k:v for k,v in bodypr.attrib.items() if k!='wrap'} if bodypr is not None else {}
            body.clear()
            body.text=repr((layout,signatures))
        return etree.tostring(root,method='c14n')
    if skeleton(before)!=skeleton(after):
        raise ValueError('原稿对象结构发生变化，已停止导出以保护原有格式。')
