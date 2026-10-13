"""保格式替换的核心：run 级别的文本重写。

难点：Word/PowerPoint 会把一个词拆进多个 run（字体切换、拼写检查、
修订痕迹都会触发）。若直接在单个 run 上做 replace，会出现
  "COG packaging ha" | "s gained momentum"
→ 替换 "has" 会失败，替换 "ha" 会破坏另一个 run。

正确做法：
1. 把段落所有 run 的文本拼起来，在拼接结果上定位目标
2. 只改命中范围；跨 run 的替换沿用起始文字样式，保留范围外的格式。
"""
from difflib import SequenceMatcher


def replace_spans(runs, spans):
    """Apply non-overlapping original offsets right-to-left; keep unaffected runs."""
    for start,end,replacement in sorted(spans,reverse=True):
        text, bounds = concat_runs(runs)
        if start < 0 or end > len(text) or start >= end:
            raise ValueError('替换范围无效')
        for i,(a,b) in enumerate(bounds):
            if b <= start or a >= end:
                continue
            left = runs[i].text[:max(0,start-a)]
            right = runs[i].text[max(0,end-a):] if end < b else ''
            insert = replacement if a <= start < b else ''
            runs[i].text = left + insert + right


def concat_runs(runs) -> tuple[str, list[tuple[int, int]]]:
    """拼接 run 文本，返回 (全文, [(run起始, run结束), ...])。"""
    text = ""
    spans = []
    for r in runs:
        start = len(text)
        text += r.text
        spans.append((start, len(text)))
    return text, spans


def rewrite_runs(runs, new_text: str) -> None:
    """把 new_text 写入 runs：格式保留在第一个 run，其余置空。

    这是"保格式"的代价——若一个段落里有多种格式（如部分加粗），
    重写后统一为首个 run 的格式。仅在确实需要修改时才这样处理。
    """
    if not runs:
        return
    runs[0].text = new_text
    for r in runs[1:]:
        r.text = ""


def replace_in_runs(runs, old: str, new: str) -> bool:
    """在 run 组中替换文本，尽量少破坏格式。

    若 old 完整落在单个 run 内 → 只改那个 run（格式完全不受影响）。
    否则 → 只替换跨 run 的命中范围，保留其余文字样式。
    返回是否发生了替换。
    """
    if not runs or not old:
        return False
    text, spans = concat_runs(runs)

    # 大小写不敏感定位，但保留替换位置的准确性
    lower_text, lower_old = text.lower(), old.lower()
    idx = lower_text.find(lower_old)
    if idx == -1:
        return False

    end = idx + len(old)

    # 情况一：完整落在一个 run 内
    for i, (s, e) in enumerate(spans):
        if s <= idx and end <= e:
            run = runs[i]
            local_start = idx - s
            local_end = end - s
            run.text = run.text[:local_start] + new + run.text[local_end:]
            return True

    # Keep styles outside the replacement, even when the term spans runs.
    replace_spans(runs, [(idx, end, new)])
    return True


def apply_replacements(runs, replacements: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """批量替换。返回实际成功执行的 (old, new) 列表。

    replacements 需按在文中出现的顺序传入；每替换一次重新定位，
    避免偏移错乱。
    """
    done = []
    for old, new in replacements:
        if replace_in_runs(runs, old, new):
            done.append((old, new))
    return done
