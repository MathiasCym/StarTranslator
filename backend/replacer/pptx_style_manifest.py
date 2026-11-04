"""Source style ledger, independent of model output and fitting decisions."""
from .styled_text import _style_key
from .text_runs import text_runs,BreakRun


def run_key(run):
    rpr=next((c for c in run._r if c.tag.rsplit('}',1)[-1]=='rPr'),None)
    return _style_key(rpr)


def _stable(key):
    if not key:return ()
    tag,attrs,text,children=key
    attrs=tuple((k,v) for k,v in attrs if k not in {'sz','spc'})
    children=tuple(_stable(c) for c in children)
    return (tag,attrs,text,children) if attrs or text or children else ()


def capture_styles(paragraphs):
    return {loc:{run_key(r) for r in text_runs(p) if not isinstance(r,BreakRun) and any(c.isalnum() for c in r.text)}
            for loc,p,*_ in paragraphs}


def verify_styles(document,paragraphs,manifest,changed,script_font=None):
    """Typography may fit, but color/font/weight and source style coverage must hold."""
    origins=getattr(document,'_star_run_styles',{})
    warnings=[]
    for loc,paragraph,_,slide,number in paragraphs:
        if loc not in changed or loc not in manifest:continue
        represented=set();mutated=False
        sizes=[]
        for run in text_runs(paragraph):
            if isinstance(run,BreakRun) or not any(c.isalnum() for c in run.text):continue
            actual=run_key(run);original=origins.get(run._r,actual)
            represented.add(original)
            def stable(value):
                if script_font and value:
                    tag,attrs,text,children=value
                    children=tuple(c for c in children if c[0].rsplit('}',1)[-1]!='ea')
                    value=(tag,attrs,text,children)
                return _stable(value)
            mutated|=stable(actual)!=stable(original)
            if script_font:
                ea=next((c for c in actual[3] if c[0].rsplit('}',1)[-1]=='ea'),None) if actual else None
                if ea and dict(ea[1]).get('typeface')!=script_font:mutated=True
            source_style=getattr(document,'_star_cohort_origins',{}).get(run._r)
            if source_style and run.font.size is not None:sizes.append((source_style[1],run.font.size.pt))
        flattened=any(a>b+.5 and x+.1<y*a/b*.9 for a,x in sizes for b,y in sizes)
        covered=manifest[loc]<=represented
        if script_font or getattr(document,'_star_target_language',None):
            def without_ea(value):
                if not value:return value
                tag,attrs,text,children=value
                return _stable((tag,attrs,text,tuple(c for c in children if not script_font or c[0].rsplit('}',1)[-1]!='ea')))
            covered={without_ea(k) for k in manifest[loc]}<={without_ea(k) for k in represented}
        if mutated or flattened or not covered:
            warnings.append({'slide':slide,'locator':loc,'text':f'第 {number} 段',
                             'reason':'该处字体、强调样式或字号层级尚未完整对应，请结合原稿确认。'})
    return warnings
