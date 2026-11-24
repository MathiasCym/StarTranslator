"""East-Asian script fonts only for the additional document policies."""
import re
from functools import lru_cache
from .replacer.text_runs import text_runs, BreakRun

CJK=re.compile(r'[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]')
FONTS={'zh-CN':('Microsoft YaHei','SimSun'), 'zh-Hant-TW':('Microsoft JhengHei','PMingLiU'),
       'ja-JP':('Yu Gothic','Meiryo','MS Gothic'), 'ko':('Malgun Gothic','Gulim')}
LOCALES={'zh-CN':'zh-CN','zh-Hant-TW':'zh-TW','ja-JP':'ja-JP','ko':'ko-KR','en-US':'en-US'}


@lru_cache(maxsize=512)
def replacement_face(source, characters, language):
    if not source or source.startswith('+'):
        return None
    from .replacer.pptx_layout import Metrics
    try:
        with Metrics() as metrics:
            if metrics.missing_glyphs(source,characters) is not True:
                return None
            return next((face for face in FONTS[language] if metrics.missing_glyphs(face,characters) is False),None)
    except OSError:
        return None


def apply(document,paragraphs,locators,language):
    """Keep original font resources unless a concrete face lacks target glyphs."""
    overrides = getattr(document,'_star_script_font_overrides',{})
    document._star_script_font_overrides = overrides
    locale=LOCALES[language]
    for locator,paragraph,*_ in paragraphs:
        if locator not in locators:continue
        for run in text_runs(paragraph):
            if isinstance(run,BreakRun) or not run.text:continue
            element=run._r;ns=element.tag.split('}')[0][1:]
            characters = ''.join(sorted(set(CJK.findall(run.text)))) if language in FONTS else ''
            is_word=ns=='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
            if is_word:
                from docx.oxml import OxmlElement
                from docx.oxml.ns import qn
                props=element.find(qn('w:rPr'))
                if props is None:props=OxmlElement('w:rPr');element.insert(0,props)
                lang=props.find(qn('w:lang'))
                if lang is None:lang=OxmlElement('w:lang');props.append(lang)
                lang.set(qn('w:val'),locale);lang.set(qn('w:eastAsia'),locale)
                fonts=props.find(qn('w:rFonts'))
                if characters and fonts is not None and not fonts.get(qn('w:eastAsiaTheme')):
                    face = replacement_face(fonts.get(qn('w:eastAsia')),characters,language)
                    if face:
                        fonts.set(qn('w:eastAsia'),face)
            elif ns=='http://schemas.openxmlformats.org/drawingml/2006/main':
                from lxml import etree
                props=element.find('{'+ns+'}rPr')
                if props is None:props=etree.Element('{'+ns+'}rPr');element.insert(0,props)
                props.set('lang',locale)
                ea=props.find('{'+ns+'}ea')
                if characters and ea is not None:
                    face = replacement_face(ea.get('typeface'),characters,language)
                    if face:
                        from .replacer.pptx_style_manifest import run_key
                        overrides[element] = (run_key(run),face)
                        ea.set('typeface',face)
    document._star_target_language=language
