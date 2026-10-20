"""Readable Han text and opaque identifiers have different translation rules."""
import re
from collections import Counter

# Unified ideographs, compatibility forms, extensions B–I and ideographic zero.
HAN = r'\u3007\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f\U00030000-\U000323af'
CHINESE = re.compile('[' + HAN + ']')
PHRASES = re.compile('[' + HAN + ']+(?:[、，：·][' + HAN + ']+)*')
IDENTIFIERS = re.compile(
    r'(?:[a-z][a-z0-9+.-]*://|mailto:|www\.)[^\s<>"\'，。；！？、（）]+'
    r'|(?:[A-Za-z]:[\\/]|\\\\)[^\s<>"\'，。；！？、（）]+'
    r'|[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', re.I)


def prose(text):
    """Keep offsets stable while excluding addresses and paths, never labels."""
    return IDENTIFIERS.sub(lambda m: ' ' * len(m[0]), text)


def contains_chinese(text):
    return bool(CHINESE.search(prose(text)))


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
