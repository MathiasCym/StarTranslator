"""One traversal shared by extraction and export, including tables and groups."""
from pathlib import Path
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from .common import is_meaningful
from ..models import Segment, RunInfo
from ..document_input import validate_document_input
from ..replacer.text_runs import text_runs, editable_paragraph


def open_office(path):
    validate_document_input(path)
    if Path(path).suffix.lower() not in {'.docx', '.pptx'}:
        from ..formats import open_text_document
        return open_text_document(path)
    paragraphs, blocked, seen, layouts = [], [], set(), {}
    if Path(path).suffix.lower() == '.docx':
        document = Document(path)
        def blocks(element, parent, locator, source):
            for i, child in enumerate(element.iterchildren()):
                key = f'{locator}/{i}'
                if child.tag == qn('w:p'):
                    if child in seen:
                        continue
                    seen.add(child)
                    paragraphs.append((key, Paragraph(child, parent), source, None, len(paragraphs)+1))
                elif child.tag == qn('w:tbl'):
                    table = Table(child, parent)
                    for r,row in enumerate(table.rows):
                        for c,cell in enumerate(row.cells):
                            blocks(cell._tc, cell, f'{key}/table/{r}/{c}', 'table')
        blocks(document.element.body, document, 'body', 'text')
        for i, section in enumerate(document.sections):
            for kind in ('header','footer','first_page_header','first_page_footer','even_page_header','even_page_footer'):
                part = getattr(section,kind)
                if part.is_linked_to_previous:
                    continue
                blocks(part._element,part,f'section/{i}/{kind}', 'header' if 'header' in kind else 'footer')
        for i,node in enumerate(document.element.body.iter(qn('w:txbxContent'))):
            text = ''.join(t.text or '' for t in node.iter(qn('w:t')))
            if text:
                blocked.append((f'textbox/{i}', text, 'textbox', None, 'Word 文本框暂不自动改写，请手动处理。'))
        images = len(document.element.body.findall('.//' + qn('w:drawing')))
        if images:
            blocked.append(('drawings', f'[{images} 个图片/绘图对象]', 'image', None, '图片内文字未做 OCR，需人工检查。'))
    else:
        document = Presentation(path)
        def shapes(items, prefix, slide):
            for i,shape in enumerate(items):
                key = f'{prefix}/shape{i}'
                if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                    shapes(shape.shapes,key,slide)
                elif shape.has_table:
                    for r,row in enumerate(shape.table.rows):
                        for c,cell in enumerate(row.cells):
                            if cell.is_spanned:
                                continue
                            for p,para in enumerate(cell.text_frame.paragraphs):
                                paragraphs.append((f'{key}/table/{r}/{c}/{p}',para,'table',slide,p+1))
                elif shape.has_text_frame:
                    for p,para in enumerate(shape.text_frame.paragraphs):
                        locator = f'{key}/p{p}'
                        paragraphs.append((locator,para,'text',slide,p+1))
                        layouts[locator] = dict(container=prefix, x=shape.left/12700, y=shape.top/12700,
                                               width=shape.width/12700, height=shape.height/12700)
                elif shape.has_chart:
                    blocked.append((key,'[图表对象]','image',slide,'可编辑的图表文字已纳入检查，图形内其他标注需人工检查。'))
                elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                    blocked.append((key,'[图片/图表]','image',slide,'图片或图表内文字需人工检查。'))
                else:
                    # Preserve unsupported embedded diagrams without claiming coverage.
                    if 'graphicFrame' in shape._element.tag:
                        blocked.append((key,'[嵌入图示]','image',slide,'嵌入图示内文字暂不支持自动处理。'))
        for s,slide in enumerate(document.slides,1):
            shapes(slide.shapes,f'slide{s}',s)
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                for p,para in enumerate(slide.notes_slide.notes_text_frame.paragraphs):
                    paragraphs.append((f'slide{s}/notes/p{p}',para,'notes',s,p+1))
        from .pptx_extra import extra_paragraphs
        paragraphs.extend(extra_paragraphs(path, document))
        blocked.extend(document._star_extra_blocked)
    if Path(path).suffix.lower() == '.pptx': document._star_text_layouts = layouts
    return document, paragraphs, blocked


def extract_office(path):
    document, paragraphs, blocked = open_office(path)
    result = []
    for locator,para,source,slide,number in paragraphs:
        text = para.text
        if not is_meaningful(text):
            continue
        runs = [RunInfo(r.text,i) for i,r in enumerate(text_runs(para))]
        editable = editable_paragraph(para)
        if Path(path).suffix.lower() == '.docx' and any(
                node.tag in {qn('w:drawing'), qn('w:pict'), qn('w:object'), qn('w:fldChar'), qn('w:instrText')}
                for node in para._p.iter()):
            editable = False
        result.append(Segment(id=str(len(result)),file=Path(path).name,text=text,locator=locator,
            source=source,slide=slide,para=number,runs=runs,editable=editable,
            layout=getattr(document,'_star_text_layouts',{}).get(locator,{}),
            not_editable_reason='' if editable else '含动态域、嵌入对象或特殊文字结构，需人工处理。'))
    for locator,text,source,slide,reason in blocked:
        result.append(Segment(id=str(len(result)),file=Path(path).name,text=text,locator=locator,
            source=source,slide=slide,editable=False,not_editable_reason=reason))
    return result
