"""Make untranslated visible text actionable without changing the document."""
from ..models import Finding
from ..translation_residual import CHINESE, PHRASES, repair_residual
from ..llm.client import LLMUnavailable


def residual_findings(segment, glossary, client=None, existing=(), cancel=None):
    phrases=list(dict.fromkeys(PHRASES.findall(segment.text)))
    phrases=[p for p in phrases if not any(p in f.found_text and f.suggested and not CHINESE.search(f.suggested) for f in existing)]
    if not phrases:return [],False
    replacements,error={},''
    def check():
        if cancel and cancel.is_set():raise LLMUnavailable('补译已取消。')
    if client and segment.editable:
        try:
            check()
            result=repair_residual(client,segment.text,{'translation':segment.text},glossary,
                allow_source=True,check_cancel=check)
            replacements=result.get('_residual_replacements',{})
        except (ValueError,LLMUnavailable) as failure:
            error=str(failure)
            replacements=getattr(failure,'partial_result',{}).get('_residual_replacements',{})
    found=[]
    for phrase in phrases:
        value=replacements.get(phrase,'')
        found.append(Finding(segment_id=segment.id,file=segment.file,file_path=segment.file_path,
            slide=segment.slide,para=segment.para,source=segment.source,found_text=phrase,
            suggested=value,method='llm' if value else 'rule',kind='grammar',confidence='medium',
            reason='未译中文：'+('建议补译为英文，原有英文、数字和型号保持不变。' if value else '补译尚未完成，已保留原文。'),
            editable=bool(value and segment.editable),
            not_editable_reason='' if value and segment.editable else segment.not_editable_reason or error[:180] or '连接模型后可补译该处中文。',
            context=segment.text))
    return found,any(not f.suggested for f in found)
