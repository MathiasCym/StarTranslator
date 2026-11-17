"""Shared document coverage and bounded recovery, independent of language.

Language and format adapters retain content, numeral and style validators.
Workers return data; the owner alone writes Office objects.
"""
from collections import Counter
from pathlib import Path
from .document_parallel import ordered_pages


class IncompleteTranslation(Exception):
    """The resumable work is retained internally, without publishing a file."""


def verify_translation_delivery(path, direction, *, untranslated=0, audit=None, source=None, allow_incomplete=False):
    """Reread the saved artifact. Only explicitly labelled drafts may contain untranslated text."""
    from . import document_languages
    from .text_integrity import CHINESE, prose, korean_han_fragments, foreign_script_fragments, command_literal
    from .text_languages import INLINE_CODE
    from .multilingual_quality import chinese_script, copied_simplified_glyphs
    from .reverse_validation import english_clauses
    from .extract import extract
    import re
    import unicodedata

    blocking = {'untranslated', 'chinese', 'text', 'image'}
    if not allow_incomplete and (untranslated or any(issue.get('kind') in blocking for issue in (audit or {}).get('issues', []))):
        counts=Counter(issue['kind'] for issue in (audit or {}).get('issues',[]) if issue.get('kind') in blocking)
        raise IncompleteTranslation(f'unresolved={untranslated}, audit={dict(counts)}')
    source_language, target = document_languages.pair(direction)
    native=source and Path(source).suffix.lower()==Path(path).suffix.lower() and Path(source).suffix.lower() in ('.docx','.pptx')
    saved=None
    originals={}
    if native or source and target in ('ja-JP','zh-Hant-TW','ko'):
        originals={segment.locator:segment.text for segment in extract(str(source)) if segment.editable}
    if native:
        saved=[segment for segment in extract(str(path)) if segment.editable]
        locations={segment.locator for segment in saved}
        missing=set(originals)-locations
        if missing:
            raise IncompleteTranslation(f'{len(missing)} missing editable locations in saved output; first: {min(missing)}')
    if direction == 'zh-en' and not allow_incomplete:
        from .translation_audit import saved_residuals
        if any(item['editable'] or item['source'] in ('numbering', 'package_text') for item in saved_residuals(path)):
            raise IncompleteTranslation('visible Chinese in saved English output')
    for segment in saved if saved is not None else extract(str(path)):
        if not segment.editable:
            continue
        source_text = originals.get(segment.locator, '')
        if command_literal(source_text):
            if segment.text.strip() != source_text.strip():
                raise IncompleteTranslation(f'altered command in saved output at {segment.locator}')
            continue
        if allow_incomplete:
            continue
        visible = unicodedata.normalize('NFKC', INLINE_CODE.sub(' ', prose(segment.text)))
        original = unicodedata.normalize('NFKC', INLINE_CODE.sub(' ', prose(source_text)))
        if foreign_script_fragments(visible,target) or target == 'ko' and korean_han_fragments(original,visible):
            raise IncompleteTranslation(f'source script in saved output at {segment.locator}')
        if target != 'en-US' and english_clauses(visible):
            raise IncompleteTranslation(f'English clause in saved output at {segment.locator}')
        if source_language in ('zh-CN', 'zh-Hant-TW') and target in ('ja-JP', 'zh-Hant-TW') and original and copied_simplified_glyphs(original,visible,target):
            raise IncompleteTranslation(f'copied source script in saved output at {segment.locator}')
        if source_language in ('zh-CN', 'zh-Hant-TW') and visible.strip() == original.strip():
            if target == 'ja-JP' and len(CHINESE.findall(original)) >= 12 and re.search(r'[，。！？；,!?;]', original):
                raise IncompleteTranslation(f'unchanged source paragraph at {segment.locator}')
            if target == 'zh-Hant-TW':
                mapped = chinese_script(visible, target)
                if mapped is not None and mapped != visible:
                    raise IncompleteTranslation(f'unchanged simplified characters at {segment.locator}')


def transport_epoch(error):
    seen=set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        value=getattr(error,'transport_epoch',None)
        if type(value) is int:return value
        error=getattr(error,'__cause__',None)
    return None


def transport_recovered(client,error):
    epoch=error if type(error) is int else transport_epoch(error)
    judge=getattr(client,'transport_recovered',None)
    return epoch is not None and callable(judge) and judge(epoch) is True


def may_recover_transport(client,error):
    epoch=error if type(error) is int else transport_epoch(error)
    judge=getattr(client,'can_recover_transport',None)
    return epoch is not None and callable(judge) and judge(epoch) is True


def repair_plan(expected,pending,needs_repair=None):
    unresolved={row['locator'] for row in pending}
    return [s for s in expected if s.locator in unresolved or needs_repair is not None and needs_repair(s)]


def interruption_summary(outputs):
    pending={(output.get('source') or output.get('path'),item.get('locator'))
             for output in outputs for item in output.get('review_items',[]) if item.get('service_unavailable')}
    if not pending:return None
    return {'pending':len(pending),'message':f'模型连接中断，仍有 {len(pending)} 处未完成翻译；已完成译文与断点已保留。请恢复连接后从断点继续，这些位置尚未进入正常校对。'}


def publish_new_file(temporary,target,guard):
    """One atomic publish policy; transient Windows locks never erase a file."""
    from pathlib import Path
    from .atomic_file import replace_checked
    def checked():
        guard()
        if Path(target).exists():raise ValueError('输出位置已有新文件，请重新选择位置；现有文件未覆盖。')
    replace_checked(temporary,target,checked)


def ensure_coverage(expected,completed,pending,paragraphs):
    """Every requested location must be validated or explicitly unfinished."""
    completed=set(completed);unresolved={row['locator'] for row in pending};result=list(pending)
    for segment in expected:
        if segment.locator in completed or segment.locator in unresolved:continue
        paragraph=paragraphs.get(segment.locator)
        result.append({'locator':segment.locator,'slide':segment.slide,'para':segment.para,
            'source_text':segment.text,'translation':paragraph.text if paragraph is not None else segment.text,
            'reason':'该位置未取得通过完整性与样式检查的译文，已保留原文；不能视为翻译完成。',
            'retained_source':True,'service_unavailable':False})
        unresolved.add(segment.locator)
    return result


def repaired_pages(items,compute,workers,cancel,page_key,on_retry=None,client=None):
    """Repair content once; exhausted transport only after proven recovery."""
    from .translation import check_cancel
    failed=[]
    for result in ordered_pages(items,compute,workers,cancel,page_key):
        item,_,_,error=result
        if (isinstance(error,ValueError) and not getattr(error,'retry_exhausted',False)
                or transport_epoch(error) is not None):failed.append((item,error,result))
        else:yield result
    eligible=[]
    for item,error,result in failed:
        if (isinstance(error,ValueError) and not getattr(error,'retry_exhausted',False)
                or may_recover_transport(client,error)):
            eligible.append((item,error))
            if on_retry:on_retry(item,error)
        else:yield result
    if not eligible:return
    check_cancel(cancel)
    def repair(pair):
        item,error=pair
        return compute(item,repair_error=str(error))
    yield from ordered_pages(eligible,repair,workers,cancel,lambda pair:page_key(pair[0]))
