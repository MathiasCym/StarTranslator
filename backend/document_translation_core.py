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


def salvage_untranslated_clauses(pending, paragraphs, src, dst, client, cancel, *, mode='faithful', notify=None):
    """Write verified clauses and retain only unresolved clauses in source form."""
    import re
    from .llm.client import LLMUnavailable, LLMResponseInvalid, LLMTruncated
    from .multilingual_documents import mapped, recover_paragraph
    from .multilingual_quality import LanguageReview
    from .replacer.styled_text import slice_groups, style_groups, write_styled
    from .text_integrity import prose, validate_identifiers
    from .text_languages import INLINE_CODE
    from .translation import check_cancel

    saved = []
    remaining = list(pending)
    for index,item in enumerate(remaining):
        check_cancel(cancel)
        paragraph = paragraphs.get(item['locator'])
        source = item.get('source_text')
        if not source or paragraph is None or paragraph.text.strip() != source.strip() or item.get('service_unavailable'):
            continue
        source = paragraph.text
        visible = INLINE_CODE.sub(lambda m: ' ' * len(m[0]), prose(source))
        boundaries = r'(?<=[。！？!?；;])|(?<=[a-z]\.)[ \t]+(?=[A-Z가-힣])|[\r\n\v]+|(?=[①-⑳㉑-㉟㊱-㊿])'
        breaks = [m.start() for m in re.finditer(boundaries, visible) if 0 < m.start() < len(source)]
        if not breaks:
            breaks = [m.start() for m in re.finditer(r'(?<=，)|(?<=,)[ \t]+(?=[A-Za-z])', visible)
                      if 0 < m.start() < len(source)]
        breaks = breaks[::max(1, (len(breaks) + 10) // 11)]
        if not breaks:
            continue
        groups = style_groups(paragraph)
        if not groups:
            continue
        if notify:
            notify('repair','正在逐句补译并保留可用译文',index,len(remaining))
        offsets = [0, *breaks, len(source)]
        runs, unresolved, style_warnings = [], [], []
        translated = 0
        verified_text_available = False
        quality = LanguageReview(src, dst)
        transport_failure = None
        for number,(start,end) in enumerate(zip(offsets, offsets[1:]),1):
            check_cancel(cancel)
            fragment = source[start:end]
            if not any(c.isalpha() for c in visible[start:end]):
                runs.extend(slice_groups(groups, start, end))
                continue
            first = start + len(fragment) - len(fragment.lstrip())
            last = start + len(fragment.rstrip())
            piece = source[first:last]
            runs.extend(slice_groups(groups, start, first))
            piece_groups = slice_groups(groups, first, last, visual_keys=True)
            try:
                if transport_failure:
                    raise transport_failure
                target = recover_paragraph(client, piece, src, dst, cancel, context=source,
                                           quality=quality, previous=item.get('reason',''))
                verified_text_available |= target != piece
                mapped_runs = mapped(client, piece, piece_groups, {}, src, dst, cancel, source, mode,
                                     initial_target=target, quality=quality, style_warnings=style_warnings)
                if (dst in ('en-US','ko') and runs and runs[-1]['text'].endswith(('.', '!', '?', ';'))
                        and mapped_runs and not mapped_runs[0]['text'][:1].isspace()):
                    mapped_runs[0] = {**mapped_runs[0], 'text':' '+mapped_runs[0]['text']}
                runs.extend(mapped_runs)
                translated += target != piece
            except (ValueError, LLMUnavailable) as error:
                if isinstance(error, LLMUnavailable) and not isinstance(error, (LLMResponseInvalid, LLMTruncated)):
                    transport_failure = error
                runs.extend(piece_groups)
                unresolved.append({'source_text':piece, 'reason':str(error), 'fragment':number})
            runs.extend(slice_groups(groups, last, end))
        if not translated:
            if unresolved and not verified_text_available:
                item['unresolved_fragments'] = unresolved
            continue
        target = ''.join(run['text'] for run in runs)
        try:
            validate_identifiers(source, target)
        except ValueError:
            continue
        from copy import deepcopy
        saved_xml = deepcopy(paragraph._p)
        try:
            write_styled(paragraph, groups, runs)
        except (ValueError, KeyError, AttributeError, TypeError):
            node = paragraph._p
            node.clear()
            node.attrib.update(saved_xml.attrib)
            node.tail = saved_xml.tail
            node.extend(deepcopy(child) for child in saved_xml)
            continue
        if unresolved:
            item.update(translation=paragraph.text, unresolved_fragments=unresolved, partial_translation=True)
        else:
            pending.remove(item)
        saved.append((item['locator'], source, paragraph.text, bool(unresolved), style_warnings))
    return saved


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
