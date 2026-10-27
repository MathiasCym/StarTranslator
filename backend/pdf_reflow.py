"""Conservative text-layer recovery for PDF-to-Word only.

Position-based extraction is evidence for missing spaces, never a replacement
for the original text: it may omit characters or legitimate existing spaces.
"""
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from .text_integrity import IDENTIFIERS


def compact(text):
    return re.sub(r'\s+', '', text)


def _spaces(text):
    positions, offset = set(), 0
    for char in text.strip():
        if char.isspace(): positions.add(offset)
        else: offset += 1
    return positions


def restore_spaces(plain, layout):
    """Merge proven word gaps while retaining all source characters and order."""
    candidates = defaultdict(deque)
    for line in layout.splitlines():
        if line.strip(): candidates[compact(line)].append(line)
    lines = []
    for original in plain.splitlines():
        key = compact(original)
        if not key or not candidates[key]:
            lines.append(original.strip()); continue
        positioned = candidates[key].popleft()
        existing, additional = _spaces(original), _spaces(positioned)
        # Neither addresses nor technical IDs may gain character-level gaps.
        protected = set()
        for match in IDENTIFIERS.finditer(original):
            a, b = len(compact(original[:match.start()])), len(compact(original[:match.end()]))
            # A PDF may omit the gap after an email's sentence-ending period,
            # making the regex consume the following sentence as a TLD. Only a
            # gap independently present in positioned extraction can split it.
            if '@' in match[0] and '://' not in match[0]:
                end = re.match(r'(.+?@[A-Za-z0-9.-]+?\.[A-Za-z]{2,12})\.(?=[A-Z])',match[0])
                if end and a+len(compact(end[0])) in additional:
                    b=a+len(compact(end[1]))
            protected.update(range(a+1, b))
        for match in re.finditer(r'[A-Za-z0-9]+(?:[-_/][A-Za-z0-9]+)*', original):
            token = match[0]
            if re.search(r'\d', token) and (token.upper() == token or
                    re.fullmatch(r'\d+(?:K|M|G)?[xX]\d+(?:K|M|G)?', token)):
                a,b=len(compact(original[:match.start()])),len(compact(original[:match.end()]))
                protected.update(range(a+1, b))
        gaps = existing | (additional - protected)
        # The plain extractor can already supply useful spaces absent from layout.
        lines.append(''.join((' ' if i and i in gaps else '')+c for i, c in enumerate(key)))
    return '\n'.join(lines)


def join_link_wraps(text, uris):
    """Only join physical URL wraps when an annotation proves the exact URI."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = re.search(r'https?://\S+$', line)
        if not match: continue
        value = match[0]
        options = [u for u in uris if u.startswith(value) and u != value]
        if not options: continue
        tail = ''
        for j in range(i+1, min(i+5, len(lines))):
            part = lines[j].strip()
            if not part or re.search(r'\s', part): break
            tail += part
            if value+tail in options:
                lines[i] = line+tail
                lines[i+1:j+1] = ['']*(j-i)
                break
            if not any(u.startswith(value+tail) for u in options): break
    return '\n'.join(lines)


@dataclass(frozen=True)
class Block:
    text: str
    kind: str = 'body'


FOOTER = re.compile(r'^[-–—]\s*\d+\s*[-–—]$')
TOC = re.compile(r'\.{4,}|…{2,}|·{4,}')
HEADING = re.compile(r'^(?:\d+(?:\.\d+){0,4}[.、]?\s*\D|[一二三四五六七八九十]+[、.])')


def page_blocks(text, repeated_headers=()):
    """Separate headings/TOC/references without splitting wrapped body clauses."""
    lines = text.splitlines()
    blocks, current, kind = [], [], 'body'
    def flush():
        nonlocal current
        value = '\n'.join(current).strip()
        if value: blocks.append(Block(value, kind))
        current = []
    for index, raw in enumerate(lines):
        line = raw.strip()
        if not line: flush(); kind = 'body'; continue
        key = compact(line)
        special = ('header' if key in repeated_headers and index < 4 else
            'footer' if FOOTER.fullmatch(line) else
            'toc' if TOC.search(line) else
            'heading' if len(line) <= 75 and (key in {'目录','摘要','参考资料','参考文献'} or
                HEADING.match(line) and not re.fullmatch(r'[\d\s./-]+',line)
                and not re.search(r'[，。；！？,;!?]', line)) else None)
        if special:
            flush(); blocks.append(Block(line, special)); kind = 'body'; continue
        if re.match(r'^\[\d+\]', line):
            flush(); kind = 'reference'
        elif kind != 'reference' and current and re.search(r'[。！？](?:\[\d+\])*[”」"]?$', current[-1]):
            flush(); kind = 'body'
        current.append(line)
    flush()
    return blocks


def extract_page(page):
    plain = page.extract_text() or ''
    if not plain.strip(): return plain
    try:
        positioned = page.extract_text(extraction_mode='layout', layout_mode_space_vertically=False) or ''
    except Exception:
        # Position recovery is optional; plain text remains the authoritative
        # fallback for unsupported fonts/operators or broken positioning data.
        return plain
    return restore_spaces(plain, positioned)


def fit_contents(document, paragraphs):
    """Replace extracted dot runs with Word leaders, preserving labels/numbers."""
    from docx.shared import Pt
    from docx.enum.text import WD_TAB_ALIGNMENT, WD_TAB_LEADER
    from .replacer.text_runs import text_runs
    from .replacer.run_utils import replace_spans
    section=document.sections[0]
    width=(section.page_width-section.left_margin-section.right_margin)/12700
    for paragraph in paragraphs:
        matches=list(re.finditer(r'\s*(?:\.{4,}|…{2,}|·{4,})\s*',paragraph.text))
        if len(matches)!=1:continue
        match=matches[0]
        replace_spans(text_runs(paragraph),[(match.start(),match.end(),'\t')])
        stops=paragraph.paragraph_format.tab_stops
        stops.clear_all();stops.add_tab_stop(Pt(width),WD_TAB_ALIGNMENT.RIGHT,WD_TAB_LEADER.DOTS)


def recover_chinese(client, source, groups, glossary, check_cancel):
    """A rejected English rewrite must not roll a Chinese header back with it."""
    from .translation_residual import repair_residual
    from .translation_policy import validate_for_file
    from .text_integrity import contains_chinese
    from .replacer.styled_text import response_runs
    result = repair_residual(client, source, {'translation':source}, glossary,
        allow_source=True, check_cancel=check_cancel)
    target = result['translation']
    mappings=result.get('_residual_replacements',{})
    if mappings:
        # Chinese normally touches model IDs/quantities without spaces. English
        # fragments need boundaries; opaque URLs and paths remain untouched.
        pattern=re.compile('|'.join(re.escape(k) for k in sorted(mappings,key=len,reverse=True)))
        def patch_prose(value,offset):
            def replace(match):
                text=mappings[match[0]]
                a,b=offset+match.start(),offset+match.end()
                if a and source[a-1].isascii() and source[a-1].isalnum() and text[0].isalnum():text=' '+text
                if b<len(source) and source[b].isascii() and source[b].isalnum() and text[-1].isalnum():text+=' '
                return text
            return pattern.sub(replace,value)
        parts=[];offset=0
        for match in IDENTIFIERS.finditer(source):
            parts.extend([patch_prose(source[offset:match.start()],offset),match[0]]);offset=match.end()
        target=''.join(parts)+patch_prose(source[offset:],offset)
        result={**result,'translation':target}
    if contains_chinese(target): raise ValueError('PDF 局部补译仍有未译中文。')
    validate_for_file('source.pdf', source, target)
    return result, response_runs(result, target, groups)
