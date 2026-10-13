"""Only explicitly confirmed wrong translations can produce deterministic fixes.

这是「脚本先兜底、大模型做第二步」的第一步：命中**已确认错译变体**
（wrong_variants）就给出确定性替换建议，默认勾选、可取消，不等模型。
生效范围为 priority 1 与 2——已确认标准与待确认条目都参与，但歧义
（同一变体指向多个不同目标）与合法写法（变体本身是某条目的标准英文或
别名）一律放过，交模型判断。这是历史假阳性教训的硬约束，不得放宽。
"""
from ..models import Finding
from ..extract.common import context_of
from .retriever import _form_pattern

# 参与确定性替换确的确认等级。1=已确认标准，2=待确认。
AUTO_FIX_PRIORITIES = (1, 2)


def check_rules(segments, glossary):
    wrong = {}
    accepted = set()
    for entry in glossary.entries:
        accepted.update(v.casefold() for v in [entry.en, *entry.variants])
        if entry.priority in AUTO_FIX_PRIORITIES:
            for variant in entry.wrong_variants:
                wrong.setdefault(variant.casefold(), []).append(entry)
    findings = []
    for seg in segments:
        occupied = []
        for variant, entries in sorted(wrong.items(), key=lambda pair:-len(pair[0])):
            targets = {e.en.casefold() for e in entries}
            if len(targets) != 1 or variant in accepted:
                continue  # Ambiguous/acceptable phrases are left for model review.
            entry = entries[0]
            matches = [m for m in _form_pattern(variant).finditer(seg.text)
                       if not any(m.start()<end and m.end()>start for start,end in occupied)]
            if not matches:
                continue
            occupied.extend((m.start(),m.end()) for m in matches)
            found = matches[0].group()
            findings.append(Finding(segment_id=seg.id, file=seg.file, file_path=seg.file_path,
                slide=seg.slide, para=seg.para, source=seg.source, found_text=found,
                suggested=entry.en, concept_zh=entry.zh, confidence='high', method='rule',
                reason='命中词库中的已知机翻写法；建议统一为团队标准。',
                editable=seg.editable, not_editable_reason=seg.not_editable_reason,
                context=context_of(seg.text,found), occurrences=len(matches)))
    from ..bit_depth import check as check_bit_depth
    findings.extend(check_bit_depth(segments))
    return findings
