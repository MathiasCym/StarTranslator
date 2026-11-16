"""Readable Han text and opaque identifiers have different translation rules."""
import re
import unicodedata
from collections import Counter

# Unified ideographs, compatibility forms, extensions B–I and ideographic zero.
HAN = r'\u3007\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f\U00030000-\U000323af'
CHINESE = re.compile('[' + HAN + ']')
KANA = r'\u3041-\u3096\u30a1-\u30fa'
HANGUL = r'\u1100-\u11ff\u3131-\u3163\uac00-\ud7af'
FOREIGN_SCRIPTS = {
    'en-US': re.compile('['+HAN+KANA+HANGUL+']+'),
    'zh-CN': re.compile('['+KANA+HANGUL+']+'),
    'zh-Hant-TW': re.compile('['+KANA+HANGUL+']+'),
    'ja-JP': re.compile('['+HANGUL+']+'),
    'ko': re.compile('['+KANA+']+'),
}
PHRASES = re.compile('[' + HAN + ']+(?:[、，：·][' + HAN + ']+)*')
IDENTIFIERS = re.compile(
    r'(?:[a-z][a-z0-9+.-]*://|mailto:|www\.)(?:[^\s<>"\'，。；！？、（）()]|\([^\s<>"\'()（）]*\))+'
    r'|(?:[A-Za-z]:[\\/]|\\\\)[^\s<>"\'，。；！？、（）]+'
    r'|[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', re.I)


def prose(text):
    """Keep offsets stable while excluding addresses and paths, never labels."""
    return IDENTIFIERS.sub(lambda m: ' ' * len(m[0]), text)


def contains_chinese(text):
    return bool(CHINESE.search(prose(text)))


def foreign_script_fragments(visible, target):
    pattern=FOREIGN_SCRIPTS.get(target)
    return tuple(dict.fromkeys(pattern.findall(unicodedata.normalize('NFKC',visible)))) if pattern else ()


def korean_han_fragments(original, translated):
    """A Korean name can carry its original spelling, while body text must be Korean."""
    original, translated = (unicodedata.normalize('NFKC', text) for text in (original, translated))
    gloss = r'(?<=[가-힣])\s*\(\s*([' + HAN + r']{1,20})\s*\)'
    visible = re.sub(gloss, lambda match: ' ' if match[1] in original else match[0], translated)
    return tuple(dict.fromkeys(re.findall('['+HAN+']+',visible)))


def bibliographic_product_label(value):
    """Recognize a numbered reference whose title consists of a technical name."""
    citation=re.fullmatch(
        r'\s*\[\d+\]\s+[A-Z0-9& -]{2,80}\.\s+'
        r'[A-Z][A-Z0-9-]{1,15}(?:\s+[A-Z][A-Za-z0-9+-]{0,30}){0,3}'
        r'\s*\[[A-Z]{1,3}(?:/[A-Z]{1,3})?\][\d.\s()\[\]-]+',prose(value))
    return citation is not None


def command_literal(value):
    """A complete shell example or qualified search expression."""
    line=value.strip()
    if not line.isascii() or '\n' in line or '\r' in line:
        return False
    if re.match(r'^[#$]\s*[A-Za-z][\w./-]*(?:\s+[^\n]+)?\s+-{1,2}[A-Za-z]\w*(?:\s|$)',line):
        return True
    operators=re.findall(r'(?:^|\s)(site|inurl|intitle|filetype):\S+',line)
    return bool(re.match(r'(?:site|inurl|intitle|filetype):\S+',line) and len(set(operators))>=2)


def document_clauses(value):
    """Expose original sentences and authored lines for bilingual review."""
    visible=prose(value)
    boundaries=r'(?<=[。！？!?；;])|(?<=[a-z]\.)\s+(?=[A-Z가-힣])|\r?\n'
    clauses=[part.strip() for part in re.split(boundaries,visible) if any(c.isalpha() for c in part)]
    return clauses if len(clauses)>1 else []

def chinese_phrases(text):
    return list(dict.fromkeys(PHRASES.findall(prose(text))))


def validate_identifiers(source, target):
    if Counter(IDENTIFIERS.findall(source)) != Counter(IDENTIFIERS.findall(target)):
        raise ValueError('译文改变了网址、邮箱或文件路径，请保留这些信息原样，仅翻译可读正文。')


def replace_prose(text, replacements):
    """A phrase repeated inside a URL must not be replaced inside that URL."""
    result, offset = [], 0
    def patch(value):
        for old, new in sorted(replacements.items(), key=lambda p: len(p[0]), reverse=True):
            value = value.replace(old, new)
        return value
    for match in IDENTIFIERS.finditer(text):
        result.extend((patch(text[offset:match.start()]), match[0]))
        offset = match.end()
    return ''.join(result) + patch(text[offset:])
