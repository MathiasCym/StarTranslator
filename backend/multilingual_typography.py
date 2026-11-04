"""East-Asian script fonts only for the additional document policies."""
import re
from functools import lru_cache
from .replacer.text_runs import text_runs, BreakRun

CJK=re.compile(r'[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]')
FONTS={'zh-CN':('Microsoft YaHei','SimSun'), 'zh-Hant-TW':('Microsoft JhengHei','PMingLiU'),
       'ja-JP':('Yu Gothic','Meiryo','MS Gothic'), 'ko':('Malgun Gothic','Gulim')}
LOCALES={'zh-CN':'zh-CN','zh-Hant-TW':'zh-TW','ja-JP':'ja-JP','ko':'ko-KR','en-US':'en-US'}


@lru_cache(maxsize=5)
def font_for(language):
    if language not in FONTS:return None
    from .replacer.pptx_layout import Metrics
    try:
        with Metrics() as metrics:
            return next((name for name in FONTS[language] if metrics.has_font(name)),None)
    except OSError:return None


def apply(document,paragraphs,locators,language):
    """Keep Latin fonts, size, color, bold, links and all non-text objects."""
    font=font_for(language);warnings=[]
    locale=LOCALES[language]
    for locator,paragraph,*_ in paragraphs:
        if locator not in locators:continue
        for run in text_runs(paragraph):
            if isinstance(run,BreakRun) or not run.text:continue
            element=run._r;ns=element.tag.split('}')[0][1:]
            is_word=ns=='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
            if is_word:
                from docx.oxml import OxmlElement
                from docx.oxml.ns import qn
                props=element.find(qn('w:rPr'))
                if props is None:props=OxmlElement('w:rPr');element.insert(0,props)
                lang=props.find(qn('w:lang'))
                if lang is None:lang=OxmlElement('w:lang');props.append(lang)
                lang.set(qn('w:val'),locale);lang.set(qn('w:eastAsia'),locale)
                if font and CJK.search(run.text):
                    fonts=props.find(qn('w:rFonts'))
                    if fonts is None:
                        fonts=OxmlElement('w:rFonts');props.insert(1 if len(props) and props[0].tag==qn('w:rStyle') else 0,fonts)
                    fonts.set(qn('w:eastAsia'),font)
                    # Explicit script face wins over a source-language theme.
                    fonts.attrib.pop(qn('w:eastAsiaTheme'),None)
            elif ns=='http://schemas.openxmlformats.org/drawingml/2006/main':
                from lxml import etree
                props=element.find('{'+ns+'}rPr')
                if props is None:props=etree.Element('{'+ns+'}rPr');element.insert(0,props)
                props.set('lang',locale)
                if font and CJK.search(run.text):
                    ea=props.find('{'+ns+'}ea')
                    if ea is None:
                        ea=etree.Element('{'+ns+'}ea')
                        # rPr schema: latin, ea, cs, sym, hyperlink...
                        after=props.find('{'+ns+'}latin')
                        index=list(props).index(after)+1 if after is not None else next((i for i,c in enumerate(props) if c.tag.rsplit('}',1)[-1] in {'cs','sym','hlinkClick','hlinkMouseOver','rtl','extLst'}),len(props))
                        props.insert(index,ea)
                    ea.set('typeface',font)
        if language in FONTS and not font and CJK.search(paragraph.text):
            warnings.append({'locator':locator,'reason':'本机未找到已确认的目标语言字体，保留原字体；请在 Office 中核对字体替代效果。'})
    document._star_target_language=language
    return warnings
