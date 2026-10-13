"""Application-specific embedded use of the bundled Humanizer/OfficeCLI skills."""
from collections import Counter
from functools import lru_cache
from pathlib import Path
import re
import unicodedata
from decimal import Decimal


NUMBER = re.compile(r'\d+(?:[.,]\d+)*')
SCALE = re.compile(r'\s*(万亿|亿|万|thousand|million|billion|trillion)(?![A-Za-z])', re.I)
SCALES = {'万': 10000, '亿': 100000000, '万亿': 1000000000000,
          'thousand': 1000, 'million': 1000000, 'billion': 1000000000, 'trillion': 1000000000000}
QUANTITY_UNIT = re.compile(r'\s*(nits?|尼特|millimeters?|mm|毫米|centimeters?|cm|厘米|meters?|m|米|'
    r'Hz|赫兹|fps|帧/秒|bits?|位|pixels?|像素|screens?|块|panels?)(?![A-Za-z])', re.I)
UNITS = {'nits':'nit', '尼特':'nit', 'millimeter':'mm', 'millimeters':'mm', '毫米':'mm',
    'centimeter':'cm', 'centimeters':'cm', '厘米':'cm', 'meter':'m', 'meters':'m', '米':'m',
    '赫兹':'hz', '帧/秒':'fps', 'bits':'bit', '位':'bit', 'pixels':'pixel', '像素':'pixel',
    'screens':'screen', '块':'screen', 'panels':'screen', 'panel':'screen'}


def numeric_tokens(text):
    """Compare actual values, including Chinese/English quantity scales."""
    text = unicodedata.normalize('NFKC', text)
    result = []
    for match in NUMBER.finditer(text):
        raw = match.group().replace(',', '')
        # Multi-dot versions/IPs are identities, not decimal quantities.
        value = Decimal(raw) if raw.count('.') <= 1 else raw
        end = match.end()
        scale = SCALE.match(text, end)
        if scale and isinstance(value, Decimal):
            value *= SCALES[scale.group(1).lower()]
            end = scale.end()
        result.append((value, match.start(), end))
    return text, result


def numeric_values(text):
    return Counter(value for value, _, _ in numeric_tokens(text)[1])


def repair_numeric_translation(source, translation):
    """Correct one unambiguous quantity difference; never rewrite model codes."""
    text, target = numeric_tokens(translation)
    expected = numeric_values(source)
    actual = Counter(value for value, _, _ in target)
    missing, extra = expected - actual, actual - expected
    if sum(expected.values()) != sum(actual.values()) or sum(missing.values()) != 1 or sum(extra.values()) != 1:
        return translation
    old, new = next(iter(extra)), next(iter(missing))
    matches = [(start, end) for value, start, end in target if value == old]
    if len(matches) != 1 or not isinstance(new, Decimal):
        return translation
    start, end = matches[0]
    source_text, source_tokens = numeric_tokens(source)
    originals = [(a, b) for value, a, b in source_tokens if value == new]
    if len(originals) != 1:
        return translation
    def unit(text, offset):
        match = QUANTITY_UNIT.match(text, offset)
        value = match.group(1).lower() if match else ''
        return UNITS.get(value, value)
    expected_unit, actual_unit = unit(source_text, originals[0][1]), unit(text, end)
    if not expected_unit or expected_unit != actual_unit:
        return translation
    # Embedded digits in VX1000, 4K and similar identifiers require model review.
    if start and re.match(r'[A-Za-z0-9_.]', text[start-1]):
        return translation
    if end < len(text) and re.match(r'[A-Za-z]', text[end]) and not re.match(r'(?:nits?|mm|cm|m|Hz|fps|bits?|pixels?)(?![A-Za-z])', text[end:], re.I):
        return translation
    corrected = text[:start] + format(new, 'f') + text[end:]
    try:
        validate_translation(source, corrected)
    except ValueError:
        return translation
    return corrected


@lru_cache(maxsize=1)
def instructions():
    return (Path(__file__).parent / 'skills/translation-rules.md').read_text(encoding='utf-8')


def validate_translation(source, translation):
    if '```' in translation and '```' not in source:
        raise ValueError('译文包含说明或代码包装，请重新生成正文。')
    # Preserve factual tokens; Chinese units may be translated, values may not change.
    if numeric_values(source) != numeric_values(translation):
        raise ValueError('生成的英文与中文原稿存在数值差异，需要核对。')
    tokens = re.findall(r'(?<![A-Za-z0-9])(?:[A-Z]{2,}[A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*|'
        r'[A-Za-z]+[0-9][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*|[0-9]+[A-Z][A-Za-z0-9]*)(?![A-Za-z0-9])', source)
    for token in tokens:
        quantity = re.fullmatch(r'(\d+)(Hz|HZ|hz|FPS|fps|nits?|mm|cm|bits?|pixels?)',token,re.I)
        if quantity:
            # A space between a value and its unit is standard English formatting.
            value,unit = quantity.groups()
            separator=r'[-\s]*' if unit.lower()=='bit' else r'\s*'
            pattern = r'(?<![A-Za-z0-9])'+re.escape(value)+separator+re.escape(unit)+r'(?![A-Za-z0-9])'
            if len(re.findall(pattern,translation,re.I)) >= len(re.findall(pattern,source,re.I)):
                continue
        pattern = r'(?<![A-Za-z0-9])' + re.escape(token) + r'(?![A-Za-z0-9])'
        if len(re.findall(pattern, translation, re.I)) < len(re.findall(pattern, source, re.I)):
            raise ValueError(f'译文未保留原文中的型号或缩写 {token}，请重新生成。')
