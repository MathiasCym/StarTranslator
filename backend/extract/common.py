"""提取层的公共工具。"""
import re

# Word 会把一个词拆进多个 run（拼写检查、格式变更都会触发）。
# 判断"相邻 run 是否需要合并"的依据：无空白相接。
_WHITESPACE = re.compile(r"\s")


def needs_merge(texts: list[str]) -> bool:
    """相邻 run 无空白相接 → 说明原本可能是一个词被拆开了。"""
    for a, b in zip(texts, texts[1:]):
        if not a or not b:
            continue
        if not _WHITESPACE.match(a[-1]) and not _WHITESPACE.match(b[0]):
            return True
    return False


def is_meaningful(text: str) -> bool:
    """跳过纯空白/纯符号的段落——它们没有检验价值。"""
    stripped = text.strip()
    if not stripped:
        return False
    # 至少含一个拉丁字母或中日韩字符
    return bool(re.search(r"[A-Za-z一-鿿぀-ヿ가-힯]", stripped))


def context_of(text: str, needle: str, width: int = 60) -> str:
    """截取 needle 周围的上下文，帮人工判断。"""
    idx = text.lower().find(needle.lower())
    if idx == -1:
        return text[:width * 2]
    start = max(0, idx - width)
    end = min(len(text), idx + len(needle) + width)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"
