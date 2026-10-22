"""Fit translated Word text inside its existing frame, without moving objects."""
import math
import re
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

WPS = 'http://schemas.microsoft.com/office/word/2010/wordprocessingShape'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
V = 'urn:schemas-microsoft-com:vml'


def _value(sources, tag, attr='val', default=None):
    for source in sources:
        if source is None: continue
        node = source.find(qn('w:' + tag))
        if node is not None and node.get(qn('w:' + attr)) is not None: return node.get(qn('w:' + attr))
    return default


def _on(sources, tag):
    for source in sources:
        if source is None: continue
        node=source.find(qn('w:'+tag))
        if node is not None: return node.get(qn('w:val'),'1') not in {'0','false','off'}
    return False


def _properties(document, paragraph, run=None):
    styles = document.styles.element
    by_id = {s.get(qn('w:styleId')):s for s in styles.findall(qn('w:style'))}
    direct = paragraph.find(qn('w:pPr'))
    chain, seen = [], set()
    key = _value([direct], 'pStyle')
    if not key:
        key = next((k for k, s in by_id.items() if s.get(qn('w:type')) == 'paragraph' and s.get(qn('w:default')) == '1'), None)
    while key in by_id and key not in seen:
        seen.add(key); style = by_id[key]; chain.append(style)
        key = _value([style], 'basedOn')
    defaults = styles.find(qn('w:docDefaults'))
    pp = [direct, *[s.find(qn('w:pPr')) for s in chain]]
    rp = []
    if run is not None:
        rp.append(run.find(qn('w:rPr')))
        char = by_id.get(_value(rp, 'rStyle'))
        if char is not None: rp.append(char.find(qn('w:rPr')))
    rp.extend(s.find(qn('w:rPr')) for s in chain)
    if defaults is not None:
        pp.append(defaults.find(qn('w:pPrDefault')+'/'+qn('w:pPr')))
        rp.append(defaults.find(qn('w:rPrDefault')+'/'+qn('w:rPr')))
    return pp, rp


def _box_size(box):
    parent = box.getparent()
    if parent.tag == '{'+WPS+'}txbx':
        shape = parent.getparent(); body = shape.find('{'+WPS+'}bodyPr')
        ext = shape.find('{'+WPS+'}spPr/{'+A+'}xfrm/{'+A+'}ext')
        if ext is None or body is None or body.get('vert', 'horz') != 'horz' or body.get('numCol', '1') != '1': return None
        return ((int(ext.get('cx'))-int(body.get('lIns','91440'))-int(body.get('rIns','91440')))/12700,
                (int(ext.get('cy'))-int(body.get('tIns','45720'))-int(body.get('bIns','45720')))/12700)
    if parent.tag == '{'+V+'}textbox':
        shape = parent.getparent()
        style = dict(re.findall(r'(?:^|;)\s*([\w-]+)\s*:\s*([^;]+)', shape.get('style', '')))
        def points(value):
            match = re.fullmatch(r'([\d.]+)(pt|in|cm|mm)', value or '')
            return float(match[1])*{'pt':1,'in':72,'cm':72/2.54,'mm':72/25.4}[match[2]] if match else None
        width, height = points(style.get('width')), points(style.get('height'))
        if not width or not height: return None  # group-relative coordinates require a separate transform
        inset = parent.get('inset', '7.2pt,3.6pt,7.2pt,3.6pt').split(',')
        if len(inset) != 4: return None
        margins = [points(x.strip()) for x in inset]
        if any(x is None for x in margins): return None
        return width-margins[0]-margins[2], height-margins[1]-margins[3]
    return None


def _set(parent, tag, values):
    node = parent.find(qn('w:'+tag))
    if node is None: node = OxmlElement('w:'+tag); parent.append(node)
    for key, value in values.items(): node.set(qn('w:'+key),str(value))
    return node


def _ppr(para):
    props = para.find(qn('w:pPr'))
    if props is None: props = OxmlElement('w:pPr'); para.insert(0, props)
    return props


def _font(document, sources):
    for source in sources:
        node=None if source is None else source.find(qn('w:rFonts'))
        if node is None: continue
        theme=node.get(qn('w:asciiTheme')) or node.get(qn('w:hAnsiTheme'))
        if theme:
            try:
                from lxml import etree
                part=next(r.target_part for r in document.part.rels.values() if r.reltype.endswith('/theme'))
                key='majorFont' if theme.startswith('major') else 'minorFont'
                family=etree.fromstring(part.blob).find('.//{'+A+'}'+key+'/{'+A+'}latin')
                if family is not None and family.get('typeface'):return family.get('typeface')
            except (StopIteration,AttributeError,ValueError):pass
        family=node.get(qn('w:ascii')) or node.get(qn('w:hAnsi'))
        if family:return family
    return 'Times New Roman'


def fit_textboxes(document, changed, metrics=None):
    paragraphs = getattr(document, '_star_word_layout_paragraphs', [])
    selected = {loc for loc in changed}
    boxes = {}
    for locator, paragraph, *_ in paragraphs:
        if locator not in selected: continue
        node = getattr(paragraph, '_p', None)
        if node is None: continue
        box = next((p for p in node.iterancestors() if p.tag == qn('w:txbxContent')), None)
        if box is not None: boxes.setdefault(box, (locator, set()))[1].add(node)
    if not boxes: return [], []
    if metrics is None:
        from .pptx_layout import Metrics
        try:
            with Metrics() as actual: return fit_textboxes(document, changed, actual)
        except OSError: return [], [{'slide':None,'locator':'word/textboxes','reason':'文本框字体测量不可用，未擅自缩小文字。'}]
    adjustments, warnings = [], []
    for box, (locator, targets) in boxes.items():
        size = _box_size(box)
        if not size or min(size) < 5: continue
        width, height = size[0]*.97, size[1]*.97
        data = []
        for para in box.findall(qn('w:p')):
            pp, _ = _properties(document, para)
            pieces = []
            for run in para.findall(qn('w:r')):
                _, rp = _properties(document, para, run)
                text = ''.join(n.text or '' if n.tag == qn('w:t') else '\n' if n.tag in {qn('w:br'),qn('w:cr')} else '\t' if n.tag == qn('w:tab') else '' for n in run)
                style = (_font(document,rp),
                    float(_value(rp,'sz',default='22'))/2,
                    _on(rp,'b'),_on(rp,'i'),float(_value(rp,'spacing',default='0'))/20)
                pieces.append([run, text, style])
            data.append((para, pp, pieces))
        def measure(compact=False, factors=None):
            total, widest = 0, 0
            for para, pp, pieces in data:
                factor = (factors or {}).get(para,1)
                fs = max((s[1]*factor for _, text, s in pieces if text),default=11)
                line, count, line_height = 0, 1, fs*1.2
                for _, text, style in pieces:
                    for token in re.findall(r'\n|[^\S\n]+|[^\s]+',text):
                        if token == '\n': line=0;count+=1;continue
                        token_width, token_height = metrics.measure(token, style, factor)
                        line_height = max(line_height,token_height)
                        if line and line+token_width>width: line=0;count+=1
                        widest=max(widest,token_width);line+=token_width
                text = ''.join(t for _,t,_ in pieces)
                if not text.strip() and compact: total+=1;continue
                before=float(_value(pp,'spacing','before','0'))/20
                after=float(_value(pp,'spacing','after','0'))/20
                before_lines=_value(pp,'spacing','beforeLines');after_lines=_value(pp,'spacing','afterLines')
                if before_lines is not None:before=float(before_lines)/100*line_height
                if after_lines is not None:after=float(after_lines)/100*line_height
                if compact:before=min(before,6);after=min(after,6)
                total+=count*line_height+before+after
            return total,widest
        current, widest = measure()
        if current<=height and widest<=width: continue
        factors = {}
        # A short English title slightly wider than its Chinese frame should
        # stay legible on one line when a modest (<=20%) adjustment suffices.
        for para, pp, pieces in data:
            if para not in targets: continue
            text=''.join(t for _,t,_ in pieces)
            span=sum(metrics.measure(t,s)[0] for _,t,s in pieces)
            if width<span<=width/0.8 and '\n' not in text:
                factors[para]=math.floor(width/span*100)/100
        compact_height, widest = measure(True,factors)
        if compact_height>height:
            factor=max(.8,height/compact_height*.97)
            factors={p:min(factors.get(p,1),factor) for p,_,_ in data}
        final_height,widest=measure(True,factors)
        if final_height>height or widest>width:
            warnings.append({'slide':None,'locator':locator,'reason':'译文文本框仍可能裁切，已保留可读字号，请在 Word/WPS 中核对。'})
        for para, pp, pieces in data:
            props=_ppr(para); text=''.join(t for _,t,_ in pieces)
            _set(props,'spacing',{'before':0,'after':round(min(float(_value(pp,'spacing','after','0'))/20,6)*20),
                'beforeLines':0,'afterLines':0,'line':240,'lineRule':'auto'})
            # Inherited Chinese justification spreads a wrapped English title
            # across the box. Only translated paragraphs receive this override.
            if para in targets and _value(pp,'jc',default='left') in {'both','distribute','thaiDistribute'}:
                _set(props,'jc',{'val':'left'})
            if not text.strip():
                _set(props,'spacing',{'before':0,'after':0,'line':20,'lineRule':'exact'})
                continue
            factor=factors.get(para,1)
            if factor<1:
                for run,_,style in pieces:
                    rp=run.find(qn('w:rPr'))
                    if rp is None:rp=OxmlElement('w:rPr');run.insert(0,rp)
                    point=max(min(style[1],12),math.floor(style[1]*factor*2)/2)
                    _set(rp,'sz',{'val':round(point*2)});_set(rp,'szCs',{'val':round(point*2)})
        adjustments.append({'slide':None,'locator':locator,'reason':'适配译文文本框的换行、继承对齐与段落间距，保留文本、颜色、加粗及对象尺寸。'})
    return adjustments,warnings
