"""Preserve untouched Office package parts byte-for-byte, including extensions."""
from pathlib import Path
import re
from zipfile import ZipFile
def save_office(source, document, destination, changed):
    if Path(source).suffix.lower() != '.pptx':
        if Path(source).suffix.lower() == '.docx':
            from .word_textboxes import fit_textboxes
            try: adjustments,warnings=fit_textboxes(document,changed)
            except (ValueError,TypeError,ArithmeticError,OSError):
                adjustments=[]
                warnings=[{'slide':None,'locator':'word/textboxes','reason':'该文档的文本框排版参数无法安全测量，已保留内容，请在 Word/WPS 中核对。'}]
            document._star_word_layout_result=(adjustments,warnings)
            from ..extract.word import sync_word_parts
            sync_word_parts(document)
            from .word_package import save_word
            save_word(source,document,destination)
            return
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
                _guard_part(info.filename, original.read(info.filename), data,
                    getattr(document,'_star_visual_geometry',{}).get(info.filename,{}))
            output.writestr(info, data)


def _guard_part(name, before, after, approved_geometry=None):
    """Reject geometry/animation/table changes before writing the original package."""
    if not name.endswith('.xml') or not name.startswith(('ppt/slides/','ppt/notesSlides/','ppt/slideMasters/','ppt/slideLayouts/')):
        return
    from lxml import etree
    a='http://schemas.openxmlformats.org/drawingml/2006/main'
    p='http://schemas.openxmlformats.org/presentationml/2006/main'
    def skeleton(raw,output=False):
        root=etree.fromstring(raw)
        for sid,value in (approved_geometry or {}).items():
            shapes=root.xpath('.//p:sp[p:nvSpPr/p:cNvPr/@id=$id]',namespaces={'p':p},id=str(sid))
            if len(shapes)!=1:raise ValueError('版式调整对象无法验证，未导出。')
            ext=shapes[0].find(f'{{{p}}}spPr/{{{a}}}xfrm/{{{a}}}ext')
            expected=value['after' if output else 'before']
            if ext is None or tuple(int(ext.get(k)) for k in ('cx','cy'))!=tuple(expected):
                raise ValueError('版式调整尺寸无法验证，未导出。')
            ext.set('cx',str(value['before'][0]));ext.set('cy',str(value['before'][1]))
            if 'before_offset' in value:
                off=shapes[0].find(f'{{{p}}}spPr/{{{a}}}xfrm/{{{a}}}off')
                expected_offset=value['after_offset' if output else 'before_offset']
                if off is None or tuple(int(off.get(k)) for k in ('x','y'))!=tuple(expected_offset):
                    raise ValueError('版式调整位置无法验证，未导出。')
                off.set('x',str(value['before_offset'][0]));off.set('y',str(value['before_offset'][1]))
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
    if skeleton(before)!=skeleton(after,True):
        raise ValueError('原稿对象结构发生变化，已停止导出以保护原有格式。')
