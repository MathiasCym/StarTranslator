"""Measure real Windows fonts and fit whole frames without moving slide objects."""
from collections import Counter
from contextlib import AbstractContextManager
import ctypes
from ctypes import wintypes
import os
import re
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.util import Pt
from types import SimpleNamespace

A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
C = 'http://schemas.openxmlformats.org/drawingml/2006/chart'
EMU_PT = 12700


class Metrics(AbstractContextManager):
    """GDI works offline on Windows, including fallback fonts and bold faces."""
    def __init__(self):
        if os.name != 'nt':
            raise OSError('此环境暂不支持字体测量。')
        self.gdi = ctypes.WinDLL('gdi32', use_last_error=True)
        self.gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self.gdi.CreateCompatibleDC.restype = wintypes.HDC
        self.gdi.CreateFontW.argtypes = [ctypes.c_int]*5 + [wintypes.DWORD]*8 + [wintypes.LPCWSTR]
        self.gdi.CreateFontW.restype = wintypes.HANDLE
        self.gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
        self.gdi.SelectObject.restype = wintypes.HANDLE
        self.gdi.DeleteObject.argtypes = [wintypes.HANDLE]
        self.gdi.DeleteDC.argtypes = [wintypes.HDC]
        self.gdi.GetTextExtentPoint32W.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.SIZE)]
        self.gdi.GetTextFaceW.argtypes = [wintypes.HDC, ctypes.c_int, wintypes.LPWSTR]
        self.dc = self.gdi.CreateCompatibleDC(None)
        if not self.dc: raise OSError('无法初始化字体测量。')
        self.fonts, self.cache, self.initial, self.available = {}, {}, None, {}

    def measure(self, text, style, scale=1):
        name, size, bold, italic, tracking = style
        pixels = max(1, round(size * scale * 8))
        key = (name, pixels, bold, italic)
        cache_key = (text, key, tracking, round(scale, 4))
        if cache_key in self.cache: return self.cache[cache_key]
        if key not in self.fonts:
            self.fonts[key] = self.gdi.CreateFontW(-pixels, 0, 0, 0, 700 if bold else 400,
                int(italic), 0, 0, 1, 0, 0, 4, 0, name)
            if not self.fonts[key]: raise OSError('无法加载字体。')
        previous = self.gdi.SelectObject(self.dc, self.fonts[key])
        if self.initial is None: self.initial = previous
        extent = wintypes.SIZE()
        length = len(text.encode('utf-16-le')) // 2
        if not self.gdi.GetTextExtentPoint32W(self.dc, text or ' ', length or 1, ctypes.byref(extent)):
            raise OSError('无法测量文字。')
        value = (extent.cx / 8 + max(0, len(text)-1) * tracking * scale,
                 max(size * scale, extent.cy / 8) * 1.025)
        self.cache[cache_key] = value
        return value

    def has_font(self, name):
        if name in self.available:return self.available[name]
        self.measure('Display', (name,12,False,False,0))
        self.gdi.SelectObject(self.dc,self.fonts[(name,96,False,False)])
        face=ctypes.create_unicode_buffer(128)
        self.gdi.GetTextFaceW(self.dc,128,face)
        self.available[name]=face.value.casefold()==name.casefold()
        return self.available[name]

    def __exit__(self, *args):
        if self.initial: self.gdi.SelectObject(self.dc, self.initial)
        for font in self.fonts.values(): self.gdi.DeleteObject(font)
        self.gdi.DeleteDC(self.dc)


def _node(parent, tag):
    return None if parent is None else parent.find(f'{{{A}}}{tag}')


def _placeholder_chain(shape, slide):
    result = []
    if shape is None or not getattr(shape, 'is_placeholder', False): return result
    idx = shape.placeholder_format.idx
    kind = shape.placeholder_format.type
    for owner in (slide.slide_layout, slide.slide_layout.slide_master):
        candidates = list(owner.placeholders)
        match = next((p for p in candidates if p.placeholder_format.idx == idx), None)
        if match is None: match = next((p for p in candidates if p.placeholder_format.type == kind), None)
        if match is not None and match.has_text_frame: result.append(match.text_frame._txBody)
    return result


def _defaults(paragraph, frame, shape, slide, document):
    direct = paragraph._p.find(f'{{{A}}}pPr')
    level = int(direct.get('lvl','0')) if direct is not None else 0
    sources = [direct]
    for body in [frame._txBody, *_placeholder_chain(shape, slide)]:
        lst = _node(body, 'lstStyle')
        sources.append(_node(lst, f'lvl{level+1}pPr'))
        if body is not frame._txBody:
            paras = body.findall(f'{{{A}}}p')
            if paras: sources.append(_node(paras[min(level, len(paras)-1)], 'pPr'))
    if slide is not None:
        master = slide.slide_layout.slide_master
        txstyles = master._element.find(f'{{{P}}}txStyles')
        kind = 'otherStyle'
        if shape is not None and getattr(shape, 'is_placeholder', False):
            kind = 'titleStyle' if int(shape.placeholder_format.type) in {1, 3} else 'bodyStyle'
        textstyle = None if txstyles is None else txstyles.find(f'{{{P}}}{kind}')
        sources.append(_node(textstyle, f'lvl{level+1}pPr'))
    default = document._element.find(f'{{{P}}}defaultTextStyle')
    sources.append(_node(default, f'lvl{level+1}pPr'))
    return [s for s in sources if s is not None]


def _font_name(value, slide, document):
    if not value or not value.startswith('+'): return value or 'Arial'
    part = slide.slide_layout.slide_master.part if slide is not None else document.part
    try:
        theme = next(rel.target_part for rel in part.rels.values() if rel.reltype.endswith('/theme'))
        from lxml import etree
        root = etree.fromstring(theme.blob)
        kind = 'majorFont' if value.startswith('+mj') else 'minorFont'
        name = root.find(f'.//{{{A}}}{kind}/{{{A}}}latin').get('typeface')
        return name or 'Arial'
    except (StopIteration, AttributeError): return 'Arial'


def _style(run, defaults, slide, document, font_scale):
    sources = [_node(run._r, 'endParaRPr' if run._r.tag == f'{{{A}}}p' else 'rPr'), *[_node(p, 'defRPr') for p in defaults]]
    sources = [s for s in sources if s is not None]
    def attr(name, fallback):
        return next((s.get(name) for s in sources if s.get(name) is not None), fallback)
    name = next((n.get('typeface') for s in sources for n in [_node(s,'latin')] if n is not None), '+mn-lt')
    return (_font_name(name, slide, document), float(attr('sz',1800))/100 * font_scale,
            attr('b','0') == '1', attr('i','0') == '1', float(attr('spc',0))/1000)


def _paragraph_data(frame, shape, slide, document):
    from .text_runs import text_runs, BreakRun
    norm = _node(frame._txBody.bodyPr, 'normAutofit')
    font_scale = float(norm.get('fontScale','100000')) / 100000 if norm is not None else 1
    result = []
    class BlankRun:
        def __init__(self,paragraph): self._r,self.paragraph=paragraph._p,paragraph
        text=' '
        @property
        def font(self):
            from pptx.text.text import Font
            return Font(self.paragraph._p.get_or_add_endParaRPr())
    for paragraph in frame.paragraphs:
        defaults = _defaults(paragraph, frame, shape, slide, document)
        def attr(name, fallback=0):
            return float(next((p.get(name) for p in defaults if p.get(name) is not None), fallback)) / EMU_PT
        pieces = []
        last_style = None
        for run in text_runs(paragraph):
            if isinstance(run,BreakRun) and _node(run._r,'rPr') is None and last_style is not None:
                style = last_style
            else:
                style = _style(run,defaults,slide,document,font_scale)
            pieces.append((run, style)); last_style = style
        if not pieces:
            run=BlankRun(paragraph)
            pieces.append((run,_style(run,defaults,slide,document,font_scale)))
        spacing = {}
        for name in ['lnSpc','spcBef','spcAft']:
            node = next((node for p in defaults for node in [_node(p,name)] if node is not None), None)
            if node is not None and len(node):
                child = node[0]
                spacing[name] = (child.tag.rsplit('}',1)[-1], float(child.get('val','0')))
        bullet = any(_node(p, 'buChar') is not None or _node(p,'buAutoNum') is not None for p in defaults)
        result.append((paragraph, pieces, attr('marL'), attr('marR'), attr('indent'), spacing, bullet))
    return result


def estimate(data, width, metrics, scale=1, wrap=True):
    height, widest, clipped = 0, 0, False
    for paragraph, pieces, left, right, indent, spacing, bullet in data:
        chars = [(char, style) for run, style in pieces for char in run.text]
        if not chars: continue
        available = max(1, width-left-right)
        first = max(0, indent) + (max(style[1] for _,style in chars)*scale*.65 if bullet and not left else 0)
        used, line_height, lines = first, 0, []
        text = ''.join(char for char,_ in chars)
        for token in re.finditer(r'[\v\n]|[^\S\v\n]+|[^\s]+', text):
            value = token.group()
            if value in {'\v','\n'}:
                lines.append(line_height or max(style[1] for _,style in chars)*scale*1.2)
                widest = max(widest, used); used, line_height = 0, 0
                continue
            fragments = []
            for char, style in chars[token.start():token.end()]:
                if fragments and fragments[-1][1] == style:
                    fragments[-1] = (fragments[-1][0]+char,style)
                else: fragments.append((char,style))
            widths = [metrics.measure(s.replace('\t','    '),style,scale) for s,style in fragments]
            token_width, token_height = sum(w for w,h in widths), max(h for w,h in widths)
            if value.isspace():
                if used: used += token_width
                continue
            if wrap and used and used+token_width > available:
                lines.append(line_height or token_height)
                widest = max(widest, min(used,available)); used, line_height = 0, 0
            if wrap and token_width > available:
                # PowerPoint can break a long word; measure the actual fragments.
                for char,style in chars[token.start():token.end()]:
                    cw,ch = metrics.measure(char,style,scale)
                    if used and used+cw > available:
                        lines.append(line_height); widest=max(widest,used); used,line_height=0,0
                    used += cw; line_height=max(line_height,ch)
            else:
                used += token_width; line_height=max(line_height,token_height)
        lines.append(line_height or max(style[1] for _,style in chars)*scale*1.2)
        widest=max(widest,used)
        clipped |= used > available+.2
        kind, value = spacing.get('lnSpc',('spcPct',100000))
        line_heights = [max(h, value/100*scale) if kind == 'spcPts' else h*value/100000 for h in lines]
        height += sum(line_heights)
        for name in ['spcBef','spcAft']:
            kind,value = spacing.get(name,('spcPts',0))
            height += value/100 if kind == 'spcPts' else max(line_heights)*value/100000
    return height, widest, clipped


def _frames(document, changed):
    def shapes(items,prefix,slide):
        for index,shape in enumerate(items):
            key=f'{prefix}/shape{index}'
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                yield from shapes(shape.shapes,key,slide)
            elif shape.has_table:
                table=shape.table
                for r,row in enumerate(table.rows):
                    for c,cell in enumerate(row.cells):
                        loc=f'{key}/table/{r}/{c}/'
                        if cell.is_spanned or not any(v.startswith(loc) for v in changed): continue
                        width=sum(table.columns[k].width for k in range(c,c+cell.span_width))
                        height=sum(table.rows[k].height for k in range(r,r+cell.span_height))
                        margins=(cell.margin_left,cell.margin_right,cell.margin_top,cell.margin_bottom)
                        yield loc,cell.text_frame,None,slide,width,height,margins
            elif shape.has_text_frame and any(v.startswith(key+'/p') for v in changed):
                frame=shape.text_frame
                yield key,frame,shape,slide,shape.width,shape.height,(frame.margin_left,frame.margin_right,frame.margin_top,frame.margin_bottom)
            elif shape.has_chart:
                name=str(shape.chart.part.partname).lstrip('/')
                root=getattr(document,'_star_extra_parts',{}).get(name)
                if root is None: continue
                from pptx.text.text import TextFrame
                from ..extract.pptx_extra import Owner
                for i,body in enumerate(root.xpath('.//a:txBody | .//c:rich')):
                    loc=f'part:{name}/body{i}/'
                    if not any(v.startswith(loc) for v in changed): continue
                    owner=next((p for p in body.iterancestors() if p.tag in
                        {f'{{{C}}}dLbl',f'{{{C}}}title'}),None)
                    if owner is None: continue
                    layout=owner.find(f'{{{C}}}layout/{{{C}}}manualLayout')
                    if layout is None:
                        # Office/WPS stores point-label bounds in the c15 extension.
                        layout=next(iter(owner.findall(f'.//{{{C}}}manualLayout')),None)
                    def dimension(tag):
                        value=layout.find(f'{{{C}}}{tag}') if layout is not None else None
                        try: return float(value.get('val')) if value is not None else None
                        except (TypeError,ValueError): return None
                    w,h=dimension('w'),dimension('h')
                    title=owner.tag==f'{{{C}}}title'
                    if not w or not 0<w<=1:
                        count=max((len(cat.findall(f'.//{{{C}}}pt')) for cat in root.findall(f'.//{{{C}}}cat')),default=5)
                        w=.9 if title else .78/max(1,count)
                    if not h or not 0<h<=1: h=.19 if title else .14
                    frame=TextFrame(body,Owner(shape.chart.part))
                    yield loc,frame,shape,slide,round(shape.width*w),round(shape.height*h),(frame.margin_left,frame.margin_right,frame.margin_top,frame.margin_bottom)
    for index,slide in enumerate(document.slides,1):
        yield from shapes(slide.shapes,f'slide{index}',slide)
    # Shared template objects are measured once; their geometry is retained.
    for name,root in getattr(document,'_star_extra_parts',{}).items():
        if not name.startswith(('ppt/slideMasters/','ppt/slideLayouts/')): continue
        for index,body in enumerate(root.xpath('.//p:sp[not(p:nvSpPr/p:nvPr/p:ph)]/p:txBody')):
            key=f'part:{name}/body{index}/'
            if not any(v.startswith(key) for v in changed): continue
            from pptx.text.text import TextFrame
            from ..extract.pptx_extra import Owner
            frame=TextFrame(body,Owner(None))
            ext=body.getparent().find(f'{{{P}}}spPr/{{{A}}}xfrm/{{{A}}}ext')
            if ext is not None:
                yield key,frame,None,None,int(ext.get('cx')),int(ext.get('cy')),(frame.margin_left,frame.margin_right,frame.margin_top,frame.margin_bottom)


def capture_layout(document, locators):
    """Snapshot original text and typography before translation/replacement mutates runs."""
    snapshots={}
    for key,frame,shape,slide,width,height,margins in _frames(document,locators):
        data=_paragraph_data(frame,shape,slide,document)
        frozen=[(None,[(SimpleNamespace(text=run.text),style) for run,style in pieces],left,right,indent,dict(spacing),bullet)
                for _,pieces,left,right,indent,spacing,bullet in data]
        snapshots[key]={'data':frozen,'wrap':frame.word_wrap is not False,'auto_size':frame.auto_size,
                        'width':width,'height':height,'margins':margins}
    return snapshots


def _variant(data, compact=False, font=None):
    result=[]
    for paragraph,pieces,left,right,indent,spacing,bullet in data:
        spacing=dict(spacing)
        if compact:
            kind,value=spacing.get('lnSpc',('spcPct',100000))
            # Keep a full glyph-height baseline; remove excess leading only.
            spacing['lnSpc']=('spcPct',100000) if kind=='spcPts' else ('spcPct',min(value,100000))
            for name in ['spcBef','spcAft']:
                kind,value=spacing.get(name,('spcPts',0))
                spacing[name]=(kind,value*.6)
        if font:
            pieces=[(run,(font,*style[1:])) for run,style in pieces]
        result.append((paragraph,pieces,left,right,indent,spacing,bullet))
    return result


def _find_scale(data,width,height,metrics,wrap):
    sizes=Counter()
    for _,pieces,*_ in data:
        for run,style in pieces: sizes[style[1]]+=len(run.text.strip()) or 1
    dominant=max(sizes,key=sizes.get)
    floor=min(1,max(6,min(9,dominant*.65))/dominant)
    def fits(scale):
        h,_,clipped=estimate(data,width,metrics,scale,wrap)
        return h<=height and not clipped
    if fits(1): return 1,True,dominant
    if not fits(floor): return floor,False,dominant
    lo,hi=floor,1
    for _ in range(12):
        mid=(lo+hi)/2
        if fits(mid): lo=mid
        else: hi=mid
    return max(floor,lo-.004),True,dominant


def _write_typography(data,scale,font_changed,spacing_changed,padding,baked_scale):
    from pptx.oxml.xmlchemy import OxmlElement
    for paragraph,pieces,_,_,_,spacing,_ in data:
        for run,style in pieces:
            size=round(style[1]*scale,2)
            if not hasattr(run,'font'):
                rpr=_node(run._r,'rPr')
                if rpr is None:
                    rpr=OxmlElement('a:rPr'); run._r.insert(0,rpr)
                rpr.set('sz',str(round(size*100)))
                if font_changed:
                    latin=_node(rpr,'latin')
                    if latin is None: latin=OxmlElement('a:latin'); rpr.append(latin)
                    latin.set('typeface',style[0])
                continue
            explicit=run.font.size.pt if run.font.size is not None else None
            if scale<.999 or baked_scale or explicit is not None and abs(explicit-size)>.005:
                run.font.size=Pt(size)
            if font_changed: run.font.name=style[0]
        if spacing_changed or scale<.999:
            if 'lnSpc' in spacing:
                kind,value=spacing['lnSpc']
                paragraph.line_spacing=Pt(value/100*scale) if kind=='spcPts' else value/100000
            if spacing_changed:
                for name,attr in [('spcBef','space_before'),('spcAft','space_after')]:
                    kind,value=spacing.get(name,('spcPts',0))
                    if kind=='spcPts': setattr(paragraph,attr,Pt(value/100))
                    else:
                        ppr=paragraph._p.get_or_add_pPr(); old=_node(ppr,name)
                        if old is not None:ppr.remove(old)
                        node=OxmlElement('a:'+name); child=OxmlElement('a:spcPct');child.set('val',str(round(value)));node.append(child);ppr.append(node)
        if padding>.05:
            old=paragraph.space_after.pt if paragraph.space_after is not None else 0
            paragraph.space_after=Pt(old+padding)
        ppr=_node(paragraph._p,'pPr')
        if ppr is not None and paragraph._p.index(ppr):
            paragraph._p.remove(ppr); paragraph._p.insert(0,ppr)


def fit_document(document, changed, snapshots=None):
    warnings, adjustments = [], []
    try:
        with Metrics() as metrics:
            for key,frame,shape,slide,width,height,margins in _frames(document,changed):
                if '/table/' in key:
                    cell=key.split('/table/',1)[1].strip('/').split('/')
                    label=f'表格第 {int(cell[0])+1} 行、第 {int(cell[1])+1} 列'
                else:
                    label=('图表文字' if key.startswith('part:ppt/charts/') else f'文本框 {shape.shape_id}') if shape is not None else '共享版式文字'
                location={'slide':document.slides.index(slide)+1 if slide is not None else None,'text':label,'locator':key}
                props=frame._txBody.bodyPr
                if props.get('vert','horz') != 'horz' or int(props.get('numCol','1'))>1:
                    warnings.append({**location,'reason':'竖排或多栏文本保留原有布局，请检查显示。'}); continue
                width=(width-margins[0]-margins[1])/EMU_PT*.975
                height=(height-margins[2]-margins[3])/EMU_PT*.97
                original=(snapshots or {}).get(key)
                natural_bounds=False
                wrap=frame.word_wrap is not False
                if (width<=0 or height<=0) and original and original['auto_size']==MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT:
                    # Zero-size auto-growing source objects use their original ink bounds.
                    # Retain every coordinate/dimension and the source stretch setting.
                    natural_bounds=True
                    if width<=0:
                        _,width,_=estimate(original['data'],10000,metrics,wrap=False)
                        width+=max((left+right for _,_,left,right,*_ in original['data']),default=0)+.5
                        wrap=False
                    if height<=0:
                        height=estimate(original['data'],width,metrics,wrap=wrap)[0]+.5
                if width <= 0 or height <= 0:
                    warnings.append({**location,'reason':'原稿文本框尺寸过小，保留原有伸展设置，请检查该处显示。'})
                    continue
                data=_paragraph_data(frame,shape,slide,document)
                norm=_node(props,'normAutofit')
                baked_scale=norm is not None and norm.get('fontScale','100000')!='100000'
                wrapped=False
                # Preserve explicit no-wrap where possible, especially auto-growing titles.
                budgets=None
                if original and len(original['data'])==len(data) and len(data)>1:
                    budgets=[estimate([item],width,metrics,wrap=wrap)[0] for item in original['data']]
                    total=sum(budgets)
                    if total>height: budgets=[b*height/total for b in budgets]
                    else:
                        last=max((i for i,item in enumerate(original['data']) if any(r.text.strip() for r,_ in item[1])),default=len(data)-1)
                        budgets[last]+=height-total
                units=[[item] for item in data] if budgets else [data]
                for index,unit in enumerate(units):
                    budget=budgets[index] if budgets else height
                    scale,ok,dominant=_find_scale(unit,width,budget,metrics,wrap)
                    chosen,compact,font=unit,False,None
                    if scale<.82 or not ok:
                        candidate=_variant(unit,compact=True)
                        alt,alt_ok,_=_find_scale(candidate,width,budget,metrics,wrap)
                        if alt>scale+.025 or alt_ok and not ok:
                            chosen,scale,ok,compact=candidate,alt,alt_ok,True
                    if scale<.75 or not ok:
                        for family in ['Arial Narrow','Aptos Narrow','Calibri']:
                            if not metrics.has_font(family):continue
                            candidate=_variant(unit,compact=compact,font=family)
                            alt,alt_ok,_=_find_scale(candidate,width,budget,metrics,wrap)
                            if alt>scale+.04 or alt_ok and not ok:
                                chosen,scale,ok,font=candidate,alt,alt_ok,family
                    # Ordinary no-wrap boxes can use word wrapping if shrinking alone fails.
                    if not ok and not wrap and not natural_bounds:
                        wrap=True;wrapped=True;frame.word_wrap=True
                        chosen=_variant(unit,compact=compact,font=font)
                        scale,ok,_=_find_scale(chosen,width,budget,metrics,wrap)
                    measured=estimate(chosen,width,metrics,scale,wrap)[0]
                    padding=max(0,budget-measured-.1) if budgets and index<len(units)-1 and ok else 0
                    _write_typography(chosen,scale,bool(font),compact,padding,baked_scale)
                    if not ok:
                        warnings.append({**location,'reason':f'第 {index+1} 段已缩小字号；原有空间仍较紧，请检查该处显示。'})
                    if scale<.999 or wrapped or compact or font:
                        adjustments.append({**location,'paragraph':index+1,'scale':round(scale,3),'font_size':round(dominant*scale,2),
                                            'wrapped':wrapped,'font':font,'spacing_compacted':compact,'original_bounds':natural_bounds})
                if not natural_bounds: frame.auto_size=MSO_AUTO_SIZE.NONE
                if key.startswith('part:ppt/charts/'):
                    # Never replace a forecast value with an ellipsis at display time.
                    # The measured font fits the retained chart-label bounds.
                    props.set('vertOverflow','overflow'); props.set('horzOverflow','overflow')
    except OSError as error:
        warnings.append({'slide':None,'text':'','reason':'文字测量未完成，保留原有字号：'+str(error)})
    return adjustments,warnings
