"""Bounded bilingual reference retrieval; pairing is explicit, never guessed by filename."""
import os
import re
from pathlib import Path
from .extract import extract
from .models import Segment
from .matcher.retriever import _form_pattern
from .document_input import validate_document_input


def concepts(text, glossary):
    return {e.zh for e in glossary.entries if e.zh in text or
            any(len(v) >= 3 and _form_pattern(v).search(text) for v in e.all_forms())}


class ReferenceIndex:
    def __init__(self, paths, glossary, pairs=None):
        self.glossary = glossary
        self.items = []
        self.by_path = {}
        self.pairs = {os.path.abspath(k): os.path.abspath(v) for k,v in (pairs or {}).items() if v}
        for path in dict.fromkeys(paths or []):
            validate_document_input(path)
            if Path(path).suffix.lower() == '.txt':
                text = Path(path).read_text(encoding='utf-8-sig')
                segments = [Segment(id=str(i), file=Path(path).name, text=t, locator=str(i))
                            for i,t in enumerate(text.splitlines()) if t.strip()]
            else:
                segments = [s for s in extract(path) if s.source not in ('image', 'group')]
            self.by_path[os.path.abspath(path)] = segments
            for s in segments:
                self.items.append((s, concepts(s.text, glossary), set(re.findall(r'[a-z0-9]{3,}', s.text.lower()))))

    def aligned_text(self, segment):
        paired = self.by_path.get(self.pairs.get(os.path.abspath(segment.file_path), ''))
        return next((s.text for s in (paired or []) if s.locator == segment.locator), '')

    def context(self, segment, ordinal=0):
        related = concepts(segment.text, self.glossary)
        tokens = set(re.findall(r'[a-z0-9]{3,}', segment.text.lower()))
        selected = []
        paired = self.by_path.get(self.pairs.get(os.path.abspath(segment.file_path), ''))
        if paired:
            exact = next((s for s in paired if s.locator == segment.locator), None)
            if segment.slide:
                selected = [s for s in paired if s.slide == segment.slide][:100]
            elif ordinal < len(paired):
                selected = paired[max(0, ordinal-1):ordinal+2]
            if exact:
                selected = [exact] + [s for s in selected if s is not exact][:99 if segment.slide else 3]
        scored = sorted(((len(related & terms)*10 + len(tokens & words), i, s)
                         for i,(s,terms,words) in enumerate(self.items)), key=lambda x:(-x[0],x[1]))
        for score, _, s in scored:
            if score > 0 and s not in selected and len(selected) < 5:
                selected.append(s)
        if not selected and self.items:
            # Useful for small bilingual samples without shared words; label as
            # background only, not evidence of one-to-one correspondence.
            selected = [self.items[0][0]]
        parts, used = [], 0
        for s in selected:
            text = s.text[:1600]
            if used + len(text) > 5000:
                break
            aligned = paired and s.locator == segment.locator
            parts.append(f'{"对应原稿位置；" if aligned else ""}来源：{s.file}；页：{s.slide or "—"}\n{text}')
            used += len(text)
        return '\n\n'.join(parts)
