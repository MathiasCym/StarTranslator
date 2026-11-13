"""Shared document coverage and bounded recovery, independent of language.

Language and format adapters retain content, numeral and style validators.
Workers return data; the owner alone writes Office objects.
"""
from .document_parallel import ordered_pages


class IncompleteTranslation(Exception):
    """The resumable work is retained internally, without publishing a file."""


def verify_translation_delivery(path, direction, *, untranslated=0, audit=None, source=None):
    """Only a reread, complete translation may leave the private staging area."""
    from . import document_languages
    from .text_integrity import CHINESE, HAN, prose
    from .text_languages import INLINE_CODE
    from .multilingual_quality import chinese_script, copied_simplified_glyphs
    from .reverse_validation import english_clauses
    from .extract import extract
    import re
    import unicodedata

    blocking = {'untranslated', 'chinese', 'text', 'image'}
    if untranslated or any(issue.get('kind') in blocking for issue in (audit or {}).get('issues', [])):
        raise IncompleteTranslation()
    source_language, target = document_languages.pair(direction)
    if target == 'en-US':
        if direction == 'zh-en':
            from .translation_audit import saved_residuals
            if any(item['editable'] or item['source'] in ('numbering', 'package_text') for item in saved_residuals(path)):
                raise IncompleteTranslation()
            return
        forbidden = re.compile(r'[\u3040-\u30ff\uac00-\ud7af' + HAN + ']')
    elif target == 'ko':
        forbidden = CHINESE
    elif target in ('zh-CN', 'zh-Hant-TW'):
        forbidden = re.compile(r'[\u3041-\u30fa\uac00-\ud7af]')
    else:
        forbidden = None
    originals = ({segment.locator:segment.text for segment in extract(str(source)) if segment.editable}
        if source and target in ('ja-JP', 'zh-Hant-TW', 'ko') else {})
    for segment in extract(str(path)):
        if not segment.editable:
            continue
        visible = unicodedata.normalize('NFKC', INLINE_CODE.sub(' ', prose(segment.text)))
        original = unicodedata.normalize('NFKC', INLINE_CODE.sub(' ', prose(originals.get(segment.locator, ''))))
        if target == 'ko':
            # A Korean name can be followed by its original written form.
            visible = re.sub(r'(?<=[가-힣])\s*\(\s*([' + HAN + r']{1,20})\s*\)',
                lambda match: ' ' if match[1] in original else match[0], visible)
        if forbidden is not None and forbidden.search(visible):
            raise IncompleteTranslation()
        if target != 'en-US' and english_clauses(visible):
            raise IncompleteTranslation()
        if source_language in ('zh-CN', 'zh-Hant-TW') and target in ('ja-JP', 'zh-Hant-TW') and original and copied_simplified_glyphs(original,visible,target):
            raise IncompleteTranslation()
        if source_language in ('zh-CN', 'zh-Hant-TW') and visible.strip() == original.strip():
            if target == 'ja-JP' and len(CHINESE.findall(original)) >= 12 and re.search(r'[，。！？；,!?;]', original):
                raise IncompleteTranslation()
            if target == 'zh-Hant-TW':
                mapped = chinese_script(visible, target)
                if mapped is not None and mapped != visible:
                    raise IncompleteTranslation()


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
