"""Two-stage checking: confirmed glossary rules, then optional model review."""
import re
import time
from concurrent.futures import ThreadPoolExecutor
from ..glossary.loader import Glossary
from ..llm.client import LLMClient, LLMUnavailable
from ..models import Finding, Segment
from ..extract.common import context_of
from .judge import judge_text, judge_text_ex, judge_segments
from .retriever import recall_terms
from .rules import check_rules
from ..document_context import DocumentContext
from ..writing_policy import numeric_values

# 单段判决的重试次数与退避（秒）。模型网关偶发超时/被限流是间歇性的，
# 重试即可恢复；因此不该让一段失败终止整份文档的复核。
MAX_ATTEMPTS = 3
RETRY_BACKOFF = (1.5, 3.0)

# 报告里最多逐条列出的未复核段落数，避免长文档把提示撑爆。
MAX_UNREVIEWED_LISTED = 10


def _judge_with_retry(seg, glossary, client, reference, rule_hits, cancel):
    """对单段判决，失败有限重试；重试仍失败才抛最后一个错误。"""
    last_error = None
    for attempt in range(MAX_ATTEMPTS):
        if cancel and cancel.is_set():
            raise LLMUnavailable('模型复核已取消。')
        try:
            return judge_text_ex(seg.text, glossary, client, reference=reference, rule_hits=rule_hits)
        except LLMUnavailable as error:
            last_error = error
            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
    raise last_error


def _describe_unreviewed(unreviewed):
    """把未复核段落拼成可读的清单（只列前若干段）。"""
    parts = []
    for seg in unreviewed[:MAX_UNREVIEWED_LISTED]:
        where = f'第 {seg.slide} 页' if seg.slide else (f'段 {seg.para}' if seg.para else '')
        parts.append(f'{seg.file}{" " + where if where else ""}'.strip())
    listed = '、'.join(parts)
    if len(unreviewed) > MAX_UNREVIEWED_LISTED:
        listed += f' 等 {len(unreviewed)} 段'
    return listed


def check_segments(segments, glossary, use_llm=True, client=None, progress=None,
                   references=None, cancel=None, on_finding=None, workers=3):
    checked = [s for s in segments if s.source not in ('image','group') and s.text.strip()]
    findings = check_rules(checked, glossary)
    from ..consistency import check_consistency
    consistency = check_consistency(checked, glossary, references=references)
    rule_count = len(findings)
    findings.extend(consistency)
    consistency_by_segment = {}
    for finding in consistency:
        consistency_by_segment.setdefault(finding.segment_id, []).append(finding)
    stats = {'segments':len(checked),'rule_hits':rule_count,'consistency_hits':len(consistency),'llm_hits':0,'judged':0,
             'errors':0,'unreviewed':0,'truncated':0,'model_status':'not_requested','warnings':[],
             'unsupported':sum(not s.editable for s in segments), 'discarded_context_hits':0}
    file_totals, file_judged, incomplete_files = {}, {}, set()
    for segment in checked:
        file_totals[segment.file_path] = file_totals.get(segment.file_path, 0) + 1
    if progress:
        progress(0,len(checked),'术语规则检查完成，正在准备模型复核' if use_llm else '术语规则检查完成')
    if use_llm:
        page_context = DocumentContext(segments)
        client = client or LLMClient()
        stats['model_status'] = 'complete'
        file_counts = {}
        unreviewed = []
        def review_one(seg, ordinal):
            reference = references.context(seg,ordinal) if references else ''
            reference += '\n' + page_context.prompt(seg)
            advice = consistency_by_segment.get(seg.id, [])
            if advice:
                reference += '\n【全文用语统一建议；仅供风格参考，不代表原写法错误】\n' + '\n'.join(f'{f.found_text} → {f.suggested}' for f in advice[:6])[:1800]
            return _judge_with_retry(seg,glossary,client,reference,
                rules_by_segment.get(seg.id, []),cancel)
        # Build page flow caches before threads start; only the merger writes findings.
        for seg in checked: page_context.prompt(seg)
        rules_by_segment = {}
        for finding in findings:
            if finding.method == 'rule': rules_by_segment.setdefault(finding.segment_id, []).append(finding)
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='star-review') as pool:
            pending = []
            for seg in checked:
                ordinal = file_counts.get(seg.file_path,0)
                file_counts[seg.file_path] = ordinal + 1
                pending.append(pool.submit(review_one, seg, ordinal))
            for index,seg in enumerate(checked):
                if cancel and cancel.is_set():
                    for future in pending: future.cancel()
                    stats['model_status'] = 'cancelled'
                    stats['warnings'].append('模型复核已取消；以下仅包含已完成部分。')
                    break
                new_hits = []
                try:
                    hits, truncated = pending[index].result()
                    stats['judged'] += 1
                    file_judged[seg.file_path] = file_judged.get(seg.file_path, 0) + 1
                    if truncated:
                        stats['truncated'] += 1
                        incomplete_files.add(seg.file_path)
                    for hit in hits:
                        added = numeric_values(hit['suggested']) - numeric_values(hit['found'])
                        aligned = references.aligned_text(seg) if references and hasattr(references,'aligned_text') else ''
                        verified = bool(added and aligned and not (added - numeric_values(aligned)))
                        if not verified and page_context.duplicates_neighbor_number(seg, hit['found'], hit['suggested']):
                            stats['discarded_context_hits'] += 1
                            continue
                        if any(f.segment_id==seg.id and f.found_text.casefold()==hit['found'].casefold() for f in findings):
                            continue
                        finding = Finding(segment_id=seg.id,file=seg.file,file_path=seg.file_path,
                            slide=seg.slide,para=seg.para,source=seg.source,found_text=hit['found'],
                            suggested=hit['suggested'],concept_zh=hit.get('concept_zh',''),
                            confidence=hit.get('confidence','medium'),method='llm',kind=hit.get('kind','term'),
                            reason=hit.get('reason',''),editable=seg.editable,not_editable_reason=seg.not_editable_reason,
                            context=page_context.report_context(seg), numeric_addition_verified=verified,
                            occurrences=len(list(re.finditer(re.escape(hit['found']),seg.text,re.I))))
                        findings.append(finding)
                        new_hits.append(finding)
                        stats['llm_hits'] += 1
                except Exception as error:
                    # 单段失败不再终止整份文档：记下来，跳过，继续下一段。
                    stats['errors'] += 1
                    incomplete_files.add(seg.file_path)
                    unreviewed.append(seg)
                    stats['warnings'].append(
                        f'{seg.file} 有 1 段未能完成模型复核（{error}），已跳过，请人工复核该段。')
                if on_finding and new_hits:
                    on_finding([f.to_dict() for f in new_hits])
                if progress:
                    progress(index+1,len(checked),'模型复核中')
        if stats['model_status'] == 'complete':
            stats['unreviewed'] = len(unreviewed)
            if stats['judged'] == 0 and stats['errors']:
                # 一段都没跑通，说明多半是模型/网络整体不可用，而非个别段落。
                stats['model_status'] = 'unavailable'
            elif unreviewed or stats['truncated']:
                stats['model_status'] = 'partial'
        if stats['model_status'] in ('partial','unavailable'):
            summary = '模型复核未完成或部分未完成；已保留术语规则结果与已完成部分，不能视为全文校对通过。'
            if unreviewed:
                summary += f'未复核段落：{_describe_unreviewed(unreviewed)}。请对上述段落人工复核。'
            stats['warnings'].insert(0,summary)
    stats['findings'] = len(findings)
    stats['completed_files'] = [path for path, count in file_totals.items()
        if not use_llm or (file_judged.get(path, 0) == count and path not in incomplete_files)]
    return findings, stats


def dedupe_findings(findings):
    seen, result = set(), []
    for finding in findings:
        key = (finding.segment_id,finding.found_text.casefold(),finding.suggested.casefold())
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return result
