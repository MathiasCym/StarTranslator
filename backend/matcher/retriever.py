"""检索器：从文本中召回「可能涉及哪些术语」。

**它不判错。** 这一点是这次重构的核心——字面匹配在原理上分不清
「另一种正确说法」和「错译」：`COB screen` 与 `COB LED display`
同义，`Tianquan series` 与 `Tianquan distributed system` 是简称与
全称，`color depth` 与 `bit depth` 都是「色深」。规则层一命中就报错，
在人工校对过的语料上产出了 35 条假阳性、真错误 0 条。

所以这里只负责缩小范围：把段落里出现过的术语、以及段落里那些
「看起来像术语但没匹配上」的片段捞出来，交给判决器（judge.py）
让模型去判断。

历史包袱说明：本模块由 rule_match.py 改造而来。原来的
exact/case/variant/fuzzy 判错逻辑已全部删除，只保留召回能力，
并修复了原来的词边界 bug（`sms` 曾匹配到 mecha·nisms 内部）。
"""
import re
from difflib import SequenceMatcher

from ..glossary.loader import Glossary
from ..models import Candidate, GlossaryEntry

MIN_TOKEN_LEN = 3

# 英文术语切分。保留连字符和点号（point-by-point、HDMI 2.1）
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9.\-]*(?:\s+[A-Za-z0-9.\-]+)*")


def _normalize(s: str) -> str:
    s = s.lower().strip()
    if s.endswith("s") and not s.endswith("ss") and len(s) > 4:
        s = s[:-1]
    return s.replace("-", " ")


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _form_pattern(form: str) -> re.Pattern:
    """带词边界的模式。

    词边界是必须的：原实现直接 re.escape(form) 匹配，导致
    `sms` 命中 `mechanisms` 内部，产出一条纯 bug 型假阳性。
    术语两端要么是词边界，要么是非字母数字字符。
    """
    escaped = re.escape(form)
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)


def recall_terms(text: str, glossary: Glossary) -> list[GlossaryEntry]:
    """召回文本中出现过的术语（去重，按首次出现位置排序）。

    只回答「这段涉及哪些术语」，不回答「是否用错了」。
    """
    if not text.strip():
        return []

    forms: list[tuple[str, GlossaryEntry]] = []
    for entry in glossary.entries:
        for form in entry.all_forms():
            if len(form) >= MIN_TOKEN_LEN:
                forms.append((form, entry))
    forms.sort(key=lambda x: -len(x[0]))       # 长词优先，避免 card 抢 receiving card

    found: dict[str, GlossaryEntry] = {}
    first_pos: dict[str, int] = {}
    occupied: list[tuple[int, int]] = []

    def overlaps(s: int, e: int) -> bool:
        return any(not (e <= a or s >= b) for a, b in occupied)

    for form, entry in forms:
        for m in _form_pattern(form).finditer(text):
            s, e = m.start(), m.end()
            if overlaps(s, e):
                continue
            occupied.append((s, e))
            if entry.zh not in found:
                found[entry.zh] = entry
                first_pos[entry.zh] = s
            break

    return sorted(found.values(), key=lambda e: first_pos[e.zh])


def recall_fragments(text: str, glossary: Glossary,
                     threshold: float = 0.86) -> list[str]:
    """召回「像术语但没完全匹配上」的片段，供判决器重点看。

    典型价值：`point pitch`（应为 pixel pitch）这类语义域误译，
    字面差异大、规则层抓不到，但作为「疑似片段」送给模型就能判出来。
    """
    if not text.strip():
        return []

    occupied: list[tuple[int, int]] = []
    for entry in glossary.entries:
        for form in entry.all_forms():
            if len(form) >= MIN_TOKEN_LEN:
                for m in _form_pattern(form).finditer(text):
                    occupied.append((m.start(), m.end()))

    def overlaps(s: int, e: int) -> bool:
        return any(not (e <= a or s >= b) for a, b in occupied)

    out: list[str] = []
    for m in _TOKEN_RE.finditer(text):
        s, e = m.start(), m.end()
        token = m.group(0)
        if len(token) < MIN_TOKEN_LEN or overlaps(s, e):
            continue
        for entry in glossary.entries:
            for form in entry.all_forms():
                if abs(len(form) - len(token)) > max(4, len(form) * 0.4):
                    continue
                if _similarity(token, form) >= threshold:
                    out.append(token)
                    break
            else:
                continue
            break
    return out


def rank_candidates(text: str, glossary: Glossary, limit: int = 3) -> list[Candidate]:
    """给一个词找最接近的若干术语，供人工/模型选择。

    兑现最初的需求：「确定不了与哪个词汇更匹配时，把最匹配的三个
    以内的词汇提交给用户进行手动选择」。
    """
    scored: list[Candidate] = []
    for entry in glossary.entries:
        best = 0.0
        for form in entry.all_forms():
            best = max(best, _similarity(text, form))
        boost = 0.08 if entry.priority == 1 else 0.0
        scored.append(Candidate(
            en=entry.en, zh=entry.zh,
            score=round(min(best + boost, 1.0), 3),
            reason=f"字面相似度 {best:.2f}" + ("（已确认标准）" if boost else ""),
            priority=entry.priority,
        ))
    scored.sort(key=lambda c: (-c.score, c.priority))
    return scored[:limit]


def select_relevant_terms(text: str, glossary: Glossary,
                          limit: int | None = None) -> list[GlossaryEntry]:
    """挑出与文本相关的术语送模型，避免把整库塞进 prompt。

    先放召回命中的（强相关），再用词重叠度补足到 limit。

    limit 默认按段落长度自适应——短段落塞 80 条术语纯属浪费 token，
    而网关单次调用延迟随 prompt 增长。长段落才需要更大的术语面。
    """
    if limit is None:
        # 约每 12 字符给 1 条术语名额，夹在 20~60 之间
        limit = max(20, min(60, len(text) // 12 + 20))

    hit = recall_terms(text, glossary)
    if len(hit) >= limit:
        return hit[:limit]

    hit_zh = {e.zh for e in hit}
    tokens = {w.lower() for w in re.split(r"[^A-Za-z0-9\-]+", text) if w}
    scored = []
    for e in glossary.entries:
        if e.zh in hit_zh:
            continue
        words = {w.lower() for w in e.en.replace("-", " ").split()}
        overlap = len(tokens & words) + (20 if e.zh in text else 0)
        bonus = 1 if e.priority == 1 else 0
        scored.append((overlap * 2 + bonus, e))
    scored.sort(key=lambda x: -x[0])
    return hit + [e for _, e in scored[:limit - len(hit)]]
