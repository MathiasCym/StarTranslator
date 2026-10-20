"""Patch only Word text parts; preserve relationships, fields and media."""
from io import BytesIO
from zipfile import ZipFile
from lxml import etree

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'


def signature(raw):
    root=etree.fromstring(raw,etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False))
    result=[];drawing_links=set()
    for node in root.iter():
        if node.tag in {f'{{{W}}}{name}' for name in ('fldChar','instrText','fldSimple','hyperlink','bookmarkStart','bookmarkEnd')}:
            result.append((node.tag,tuple(sorted(node.attrib.items())),node.text if node.tag==f'{{{W}}}instrText' else None))
        elif node.tag in {f'{{{A}}}hlinkClick',f'{{{A}}}hlinkMouseOver'}:
            drawing_links.add((node.tag,tuple(sorted(node.attrib.items())),None))
        elif node.tag in {f'{{{W}}}drawing',f'{{{W}}}pict',f'{{{W}}}object'}:
            from copy import deepcopy
            shape=deepcopy(node)
            for child in list(shape.iter()):
                if child.tag in {f'{{{W}}}txbxContent',f'{{{A}}}p'}:
                    # Geometry and embedded data remain immutable; text may change.
                    child.clear()
            result.append((node.tag,etree.tostring(shape,method='c14n')))
    return result,sorted(drawing_links)


def save_word(source, document, destination):
    buffer=BytesIO();document.save(buffer);buffer.seek(0)
    allowed=getattr(document,'_star_word_text_parts',{'word/document.xml'})
    with ZipFile(source) as before, ZipFile(buffer) as generated, ZipFile(destination,'w') as output:
        output.comment=before.comment
        names=set(generated.namelist())
        for info in before.infolist():
            original=before.read(info.filename)
            data=generated.read(info.filename) if info.filename in allowed and info.filename in names else original
            if data!=original and signature(data)!=signature(original):
                raise ValueError('Word 链接、域控件或嵌入对象发生变化，已阻止覆盖原有信息。')
            output.writestr(info,data)
