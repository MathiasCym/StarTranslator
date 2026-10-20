"""Document-scoped translation reuse and advisory consistency checks; no model calls."""
import re
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import Future, TimeoutError
from dataclasses import replace
from threading import Lock
from .models import Finding
from .document_context import DocumentContext
from .matcher.retriever import _form_pattern
from .writing_policy import validate_translation

from .text_integrity import CHINESE
WORDS = re.compile(r'[A-Za-z0-9]+')
PERIOD_TITLE = re.compile(r'(?<![A-Za-z0-9])(?P<period>H[12]|[12]H|(?:first|second)[\s-]+half(?:\s+of\s+(?:the\s+)?year)?)\s+(?P<noun>strateg(?:y|ies)|plans?|outlook|review|summary|results?|performance|priorities|objectives?|goals?)(?![A-Za-z0-9])', re.I)


def signature(text):
    return tuple(WORDS.findall(unicodedata.normalize('NFKC', text).casefold()))


def ambiguous_sources(glossary):
    values = defaultdict(set)
    for entry in glossary.entries:
        values[entry.zh.strip()].add(signature(entry.en))
    return {zh for zh, forms in values.items() if zh and len(forms) > 1}


def reusable_source(text, ambiguous):
    text = text.strip()
    return bool(text and len(text) <= 300 and
        (len(CHINESE.findall(text)) >= 4 or text in ('上半年', '下半年', '第一季度', '第二季度', '第三季度', '第四季度')) and
        not any(zh in text for zh in ambiguous))


class DocumentTranslationMemory:
    """One request owns a repeated complete phrase; concurrent pages reuse its text.

    Only single-style phrases are reused. Run IDs and styles remain owned by the
    receiving paragraph; ambiguous short words and different counted objects
    never share a key. Failed requests are not kept as accepted translations.
    """
    def __init__(self, segments, glossary):
        self.context = DocumentContext(segments)
        self.ambiguous = ambiguous_sources(glossary)
        self.counts = Counter(self.key(seg, piece) for seg in segments if seg.editable
            for piece in re.split(r'[\v\n]', seg.text) if reusable_source(piece, self.ambiguous))
        self.lock, self.values = Lock(), {}

    def key(self, segment, piece):
        noun = self.context.object_name(segment)
        # An unresolved counted object must stay local rather than borrowing a
        # screen/cabinet translation from another page.
        scope = segment.locator if '块' in piece and not noun else noun
        return (segment.file_path or segment.file, segment.source, scope, piece.strip())

    def translate(self, segment, piece, groups, operation, check_cancel):
        key = self.key(segment, piece)
        if len(groups) != 1 or not reusable_source(piece, self.ambiguous) or self.counts[key] < 2:
            return operation()
        with self.lock:
            future = self.values.get(key)
            owner = future is None
            if owner: future = self.values[key] = Future()
        if owner:
            try:
                runs, warning = operation()
                future.set_result((''.join(run['text'] for run in runs), warning))
            except BaseException as error:
                future.set_exception(error)
                with self.lock:
                    if self.values.get(key) is future: self.values.pop(key)
                raise
        while True:
            check_cancel()
            try:
                text, warning = future.result(timeout=.1)
                return [{'id': groups[0]['id'], 'text': text}], warning
            except TimeoutError:
                if future.done(): raise  # A model timeout must not become an endless wait.


def _source_map(segments, references):
    if references is None: return {}
    if hasattr(references, 'aligned_sources'): return references.aligned_sources(segments)
    if hasattr(references, 'aligned_text'): return {seg.id: references.aligned_text(seg) for seg in segments}
    return {}


def _abbreviation(entry):
    return bool(re.fullmatch(r'[A-Z][A-Z0-9.+-]{1,10}', entry.en) and not re.fullmatch(r'H[12]|Q[1-4]', entry.en))


def _acronym_forms(entry):
    short = signature(entry.en)
    forms = {signature(f) for f in [entry.en, *entry.variants]}
    return forms | {short + form for form in forms} | {form + short for form in forms}


def _safe(source, target):
    if CHINESE.search(target) or not WORDS.search(target): return False
    try: validate_translation(source, target)
    except ValueError: return False
    return True


def check_consistency(segments, glossary, references=None, aligned_sources=None):
    sources = aligned_sources if aligned_sources is not None else _source_map(segments, references)
    ambiguous = ambiguous_sources(glossary)
    by_zh = defaultdict(list)
    for entry in glossary.entries: by_zh[entry.zh.strip()].append(entry)
    findings, occupied = [], defaultdict(list)
    original_context = DocumentContext([replace(seg, text=sources.get(seg.id) or seg.text) for seg in segments])

    def add(seg, found, preferred, zh, reason, matches):
        if signature(found) == signature(preferred): return
        matches = [m for m in matches if not any(m.start() < end and m.end() > start for start, end in occupied[seg.id])]
        if not matches: return
        occupied[seg.id].extend((m.start(), m.end()) for m in matches)
        findings.append(Finding(segment_id=seg.id, file=seg.file, file_path=seg.file_path,
            slide=seg.slide, para=seg.para, source=seg.source, found_text=matches[0].group(), suggested=preferred,
            concept_zh=zh, confidence='medium', method='consistency', kind='consistency',
            reason=reason+'这是全文用语统一建议，不代表原写法一定错误，请确认后应用。',
            editable=seg.editable, not_editable_reason=seg.not_editable_reason,
            context=(('对应原稿：'+sources[seg.id]+'\n') if sources.get(seg.id) else '')+seg.text,
            occurrences=len(matches)))

    # Exact, explicitly aligned originals also cover repeated terms absent from the glossary.
    repeated = defaultdict(list)
    for seg in segments:
        source = sources.get(seg.id, '').strip()
        original = replace(seg, text=source)
        noun = original_context.object_name(original)
        if '块' in source and not noun: continue
        if reusable_source(source, ambiguous) and len(seg.text) <= 900 and _safe(source, seg.text):
            repeated[(seg.file_path or seg.file, seg.source, noun, source)].append(seg)
    for (_, _, _, source), group in repeated.items():
        if len({signature(seg.text) for seg in group}) < 2: continue
        entries = by_zh.get(source, [])
        if any(_abbreviation(e) and all(signature(seg.text) in _acronym_forms(e) for seg in group) for e in entries):
            continue  # First-use expansions and the acronym itself are both legitimate.
        standard = next((e.en for e in entries if e.priority == 1 and _safe(source, e.en)), '')
        preferred = standard or group[0].text
        where = f'第 {group[0].slide} 页' if group[0].slide else f'段 {group[0].para}'
        for seg in group:
            add(seg, seg.text, preferred, source, '同一中文原文出现不同译法；'+('优先采用已确认的词库标准。' if standard else f'参考本文件{where}已经采用的译法。'), list(re.finditer(re.escape(seg.text), seg.text)))

    # Index forms by their first token instead of scanning every glossary form for every paragraph.
    indexed = defaultdict(list)
    form_owners = defaultdict(set)
    for entry in glossary.entries:
        for form in [entry.en, *entry.variants]: form_owners[signature(form)].add(entry.zh)
    for index, entry in enumerate(glossary.entries):
        if entry.zh in ambiguous or _abbreviation(entry) or '块' in entry.zh: continue
        for form in dict.fromkeys([entry.en, *entry.variants]):
            words = WORDS.findall(form.casefold())
            if words and len(form) >= 3 and len(form_owners[signature(form)]) == 1:
                indexed[words[0]].append((index, entry, _form_pattern(form)))
    hits = defaultdict(list)
    for seg in segments:
        source = sources.get(seg.id, '')
        if not source: continue  # Without a paired original, don't guess a technical concept.
        candidates = [value for token in set(WORDS.findall(seg.text.casefold())) for value in indexed.get(token, [])]
        local = defaultdict(list)
        for index, entry, pattern in candidates:
            if entry.zh not in source: continue
            local[index].extend((entry, match) for match in pattern.finditer(seg.text))
        for index, matches in local.items():
            accepted, spans = [], []
            for entry, match in sorted(matches, key=lambda value: -(value[1].end()-value[1].start())):
                if any(match.start() < end and match.end() > start for start, end in spans): continue
                spans.append((match.start(), match.end()))
                accepted.append((entry, match))
            by_form = defaultdict(list)
            for entry, match in accepted: by_form[signature(match.group())].append(match)
            for matches in by_form.values():
                hits[(seg.file_path or seg.file, index)].append((seg, entry, matches))
    for values in hits.values():
        forms = {signature(matches[0].group()) for _, _, matches in values}
        if len(forms) < 2 or len({seg.id for seg, _, _ in values}) < 2: continue
        entry = values[0][1]
        preferred = entry.en if entry.priority == 1 else values[0][2][0].group()
        for seg, _, matches in values:
            if not _safe(entry.zh, preferred): continue
            add(seg, matches[0].group(), preferred, entry.zh, '对应同一中文术语的已认可写法在本文件中混用；建议统一。', matches)

    # Business-period titles provide a narrow, explicit equivalence even without a Chinese reference.
    periods = defaultdict(list)
    for seg in segments:
        for match in PERIOD_TITLE.finditer(seg.text):
            if any(match.start() < end and match.end() > start for start, end in occupied[seg.id]): continue
            label = match['period'].casefold()
            half = 1 if label in ('h1', '1h') or label.startswith('first') else 2
            periods[(seg.file_path or seg.file, half, match['noun'].casefold())].append((seg, match))
    for (_, half, _), values in periods.items():
        if len({signature(match.group()) for _, match in values}) < 2: continue
        preferred = values[0][1].group()
        for seg, match in values:
            add(seg, match.group(), preferred, '上半年' if half == 1 else '下半年',
                '同一时期和业务标题混用了时间简称与完整写法；建议沿用本文件首先采用的写法。', [match])
    return findings
