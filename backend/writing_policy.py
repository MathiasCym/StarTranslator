"""Application-specific embedded use of the bundled Humanizer/OfficeCLI skills."""
from collections import Counter
from functools import lru_cache
from pathlib import Path
import re
import unicodedata
from decimal import Decimal
from datetime import date


# A comma groups exactly three digits. A model followed by a comma and year
# ("A8,2023") contains two facts, never the number 82,023.
NUMBER = re.compile(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d,])|\d+(?:\.\d+)*')
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


def _calendar_numeric_tokens(text, *, bare_months=False):
    """Keep dates as complete facts, without treating decimals/versions as dates.

    Numeric month shorthand requires calendar context. In particular a dated
    notice heading may use 2025.6; a brightness of 2025.6 nits may not. Ordinary
    quantity/style matching continues to use numeric_tokens unchanged.
    """
    text, tokens = numeric_tokens(text)
    dates = []
    def add_dates(match, values):
        normalized=[];calendar=[]
        try:
            for year,month,day in values:
                year=int(year) if year is not None else None
                month=int(month);day=int(day) if day else None
                calendar.append(date(year if year is not None else 2000,month,day or 1))
                normalized.append('date:'+(f'{year:04d}' if year is not None else '-')+f'-{month:02d}'+(f'-{day:02d}' if day else ''))
        except (ValueError,TypeError):return
        if len(calendar)>1 and calendar[-1]<calendar[0]:return
        if any(match.start()<end and match.end()>start for _,start,end in dates):return
        dates.extend((value,match.start(),match.end()) for value in normalized)
    def add(match, year, month, day=None):
        add_dates(match,[(year,month,day)])
    # Shared month/year ranges represent two dates, not a date plus a quantity.
    for m in re.finditer(r'(?<!\d)([1-9]\d{3})\s*年\s*(\d{1,2})\s*月\s*(?:至|到|[-–—~])\s*(\d{1,2})\s*月',text):
        add_dates(m,[(m[1],m[2],None),(m[1],m[3],None)])
    for m in re.finditer(r'(?<!\d)([1-9]\d{3})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?\s*(?:至|到|[-–—~])\s*(\d{1,2})\s*[日号]',text):
        add_dates(m,[(m[1],m[2],m[3]),(m[1],m[2],m[4])])
    for m in re.finditer(r'(?<![A-Za-z0-9_.])([1-9]\d{3})\s*年\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*[日号])?',text):
        add(m,*m.groups())
    months='January February March April May June July August September October November December'.split()
    names={name.casefold():n for n,name in enumerate(months,1)}
    names.update({name[:3].casefold():n for n,name in enumerate(months,1)})
    names['sept']=9
    month=r'('+'|'.join(sorted(names,key=len,reverse=True))+r')\.?'
    # Longer forms first, so a day is never silently reduced to month precision.
    for m in re.finditer(r'\b'+month+r'\s*(?:[-–—]|to|through|and)\s*'+month+r'\s*,?\s*([1-9]\d{3})\b',text,re.I):
        add_dates(m,[(m[3],names[m[1].casefold()],None),(m[3],names[m[2].casefold()],None)])
    for m in re.finditer(r'\b'+month+r'\s+(\d{1,2})(?:st|nd|rd|th)?\s*[-–—]\s*(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*([1-9]\d{3})\b',text,re.I):
        add_dates(m,[(m[4],names[m[1].casefold()],m[2]),(m[4],names[m[1].casefold()],m[3])])
    for m in re.finditer(r'\b(\d{1,2})(?:st|nd|rd|th)?\s*[-–—]\s*(\d{1,2})(?:st|nd|rd|th)?\s+'+month+r'\s*,?\s*([1-9]\d{3})\b',text,re.I):
        add_dates(m,[(m[4],names[m[3].casefold()],m[1]),(m[4],names[m[3].casefold()],m[2])])
    for m in re.finditer(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+'+month+r'\s*,?\s*([1-9]\d{3})\b',text,re.I):
        add(m,m[3],names[m[2].casefold()],m[1])
    for m in re.finditer(r'\b'+month+r'[\s,]+(?:(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*)?([1-9]\d{3})\b',text,re.I):
        add(m,m[3],names[m[1].casefold()],m[2])
    # No year in the source means no invented year in the translation.
    for m in re.finditer(r'(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]',text):
        add(m,None,*m.groups())
    for m in re.finditer(r'\b'+month+r'\s+(\d{1,2})(?:st|nd|rd|th)?\b',text,re.I):
        add(m,None,names[m[1].casefold()],m[2])
    for m in re.finditer(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+'+month+r'\b',text,re.I):
        add(m,None,names[m[2].casefold()],m[1])
    for m in re.finditer(r'(?<!\d)(\d{1,2})\s*月(?!\s*\d)',text):
        add(m,None,m[1])
    if bare_months:
        # Only a source month fact enables standalone English month names.
        # Lowercase "may" remains a modal unless preceded by calendar wording.
        for m in re.finditer(r'\b'+month+r'\b',text,re.I):
            if m[1]=='may' and not re.search(r'\b(?:in|by|during|until|through|of|early|late)\s*$',text[:m.start()],re.I):continue
            add(m,None,names[m[1].casefold()])
    compact=re.compile(r'(?<![A-Za-z0-9_.])([1-9]\d{3})([./-])(\d{1,2})(?:\2(\d{1,2}))?(?!\d|[./-]\d)')
    for m in compact.finditer(text):
        before,after=text[max(0,m.start()-24):m.start()],text[m.end():]
        # Explicit quantities, identifiers and version labels stay numeric.
        if re.search(r'(?:版本|型号|价格|数值|version|model|price|value|\bv)\s*[:：]?\s*$',before,re.I):continue
        if re.match(r'\s*(?:%|元|美元|人民币|万元|亿元|万|亿)',after):continue
        if m[4] is None and re.match(r'\s*[A-Za-z0-9_]',after):
            # An English dated heading is allowed only with a known event noun.
            if not re.match(r'\s+(?:[A-Za-z-]+\s+){0,3}(?:notice|plan|policy|report|release|update|meeting|conference)\b',after,re.I):continue
        if QUANTITY_UNIT.match(after):continue
        calendar_context=(m[4] is not None
            or re.search(r'(?:日期|时间|发布于|截至|于|自|至|\bdated|\bin|\bsince|\buntil|\bas of)\s*[:：]?\s*$',before,re.I)
            or re.match(r'\s*(?:[月年]|[^\d\n:：]{0,16}(?:通知|方案|规划|计划|报告|会议|发布|公告))',after)
            or (not text[:m.start()].strip(' \t\r\n•·—-:：')
                and re.match(r'\s+(?:[A-Za-z-]+\s+){0,3}(?:notice|plan|policy|report|release|update|meeting|conference)\b',after,re.I)))
        if calendar_context:add(m,m[1],m[3],m[4])
    # Numeric day/month order is accepted only when unambiguous. For 05/09/2025
    # neither a US nor a European interpretation may be guessed from language.
    for m in re.finditer(r'(?<![A-Za-z0-9_.])(\d{1,2})([./-])(\d{1,2})\2([1-9]\d{3})(?!\d|[./-]\d)',text):
        before=text[max(0,m.start()-24):m.start()]
        if re.search(r'(?:版本|型号|version|model|\bv)\s*[:：]?\s*$',before,re.I):continue
        first,second=int(m[1]),int(m[3])
        if first>12 and second<=12:add(m,m[4],second,first)
        elif second>12 and first<=12:add(m,m[4],first,second)
        elif first==second:add(m,m[4],first,second)
        elif 1<=first<=12 and 1<=second<=12 and not any(m.start()<end and m.end()>start for _,start,end in dates):
            dates.append((f'ambiguous-date:{m[4]}-{first:02d}-{second:02d}',m.start(),m.end()))
    tokens=[(value,start,end) for value,start,end in tokens
        if not any(start>=a and end<=b for _,a,b in dates)]
    return text, sorted(tokens+dates,key=lambda token:token[1])


def _translation_numeric_values(text):
    return Counter(value for value,_,_ in _calendar_numeric_tokens(text)[1])


def _written_quantity_digits(source, translation):
    """Recognize spelled quantities backed by a numeric source fact.

    This is an analysis copy only: never rewrite English, identifiers or runs.
    Match a whole compound number so 'twenty-four' cannot count as four.
    """
    from .text_integrity import prose
    small='zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split()
    tens='twenty thirty forty fifty sixty seventy eighty ninety'.split()
    values={word:i for i,word in enumerate(small)}
    values.update({word:(i+2)*10 for i,word in enumerate(tens)})
    unit='(?:'+'|'.join(small[1:10])+')'
    below='(?:'+'|'.join(tens)+')(?:[- ]'+unit+')?|(?:'+'|'.join(small)+')'
    compound='(?:(?:'+unit+'|a) hundred(?: (?:and )?(?:'+below+'))?|'+below+')'
    pattern=re.compile(r'(?<![A-Za-z0-9_-])('+compound+r')(?: (thousand|million|billion|trillion))?(?![A-Za-z0-9_-])',re.I)
    expected=_translation_numeric_values(source)
    replacements=[]
    for match in pattern.finditer(prose(translation)):
        value=0
        for word in re.split(r'[- ]+',match[1].lower()):
            if word=='hundred':value=(value or 1)*100
            elif word not in {'and','a'}:value+=values[word]
        value=Decimal(value)*SCALES.get((match[2] or '').lower(),1)
        if value in expected:replacements.append((match.start(),match.end(),format(value,'f')))
    for start,end,value in reversed(replacements):translation=translation[:start]+value+translation[end:]
    return translation


def translation_numeric_tokens(source, translation):
    """Calendar shorthand adds a label digit, not a factual quantity.

    Only explicit Chinese calendar labels permit it. Existing source identifiers
    remain counted, and codes embedded in model names/versions are never removed.
    """
    text, tokens = _calendar_numeric_tokens(_written_quantity_digits(source,translation),
        bare_months=bool(re.search(r'\d\s*月',source)))
    ignored = []
    for label,number in [('二维','2'),('三维','3'),('四维','4')]:
        allowed=source.count(label)
        matches=list(re.finditer(r'(?<![A-Za-z0-9_])'+number+r'[- ]?D(?![A-Za-z0-9_])',text,re.I))
        ignored.extend((m.start(),m.end()) for m in matches[:allowed])
    # An explicitly named Chinese five-year plan already encodes its ordinal.
    # Ignore only the exact equivalent English name, never arbitrary new digits.
    chinese = {11:'十一',12:'十二',13:'十三',14:'十四',15:'十五',16:'十六',17:'十七',18:'十八',19:'十九',20:'二十'}
    for number,label in chinese.items():
        if not re.search(re.escape(label)+r'五["”’》]*\s*(?:规划|计划)',source):continue
        suffix='th' if number not in (21,22,23) else {21:'st',22:'nd',23:'rd'}[number]
        pattern=re.compile(r'\b'+str(number)+suffix+r'\s*[-–]?\s*(?:Five|5)[-\s]+Year\s+Plan\b',re.I)
        ignored.extend((m.start(),m.end()) for m in pattern.finditer(text))
    for labels, forms in [(['上半年'], ['H1', '1H']), (['下半年'], ['H2', '2H']),
            (['第一季度', '一季度'], ['Q1', '1Q']), (['第二季度', '二季度'], ['Q2', '2Q']),
            (['第三季度', '三季度'], ['Q3', '3Q']), (['第四季度', '四季度'], ['Q4', '4Q'])]:
        allowed = len(re.findall('|'.join(sorted(map(re.escape, labels), key=len, reverse=True)), source))
        if not allowed: continue
        pattern = re.compile(r'(?<![A-Za-z0-9_.])(?:'+'|'.join(forms)+r')(?![A-Za-z0-9_.])', re.I)
        matches = list(pattern.finditer(text))
        extra = max(0, len(matches) - len(list(pattern.finditer(source))))
        ignored.extend((m.start(), m.end()) for m in matches[:min(allowed, extra)])
    # Written Chinese counters can become Arabic digits in English. Account
    # only for extra target digits, so original numeric identifiers still count.
    counters=Counter()
    digits={c:n for n,chars in enumerate(['零〇','一','二两','三','四','五','六','七','八','九']) for c in chars}
    for match in re.finditer(r'([零〇一二两三四五六七八九十百千]+)(?=个|台|套|座|块|条|位|家|项|组|对|种|次)',source):
        # Approximate ranges such as 一两台 / 两三套 are not exact counts.
        if len(match[1])>1 and not any(c in match[1] for c in '十百千'):continue
        value,current=0,0
        for char in match[1]:
            if char in digits:current=digits[char]
            else:value+=(current or 1)*{'十':10,'百':100,'千':1000}[char];current=0
        counters[Decimal(value+current)]+=1
    eligible=[token for token in tokens if not any(token[1]>=a and token[2]<=b for a,b in ignored)]
    extra=Counter(v for v,_,_ in eligible)-_translation_numeric_values(source)
    for value,count in counters.items():
        matches=[(a,b) for v,a,b in eligible if v==value]
        ignored.extend(matches[:min(count,extra[value])])
    return text, [(value, start, end) for value, start, end in tokens if not any(start >= a and end <= b for a, b in ignored)]


def quantity_units(text):
    """Bind explicit physical units to their values, including shared dimensions.

    Chinese counters such as 位/块 depend on context and are deliberately excluded.
    A trailing unit in 500 x 600 mm applies to both dimensions.
    """
    text, tokens = _calendar_numeric_tokens(text)
    values = {}
    physical = {'nit', 'mm', 'cm', 'm', 'hz', 'fps', 'bit', 'pixel'}
    joined = re.compile(r'\s*(?:[x×*~–—-]|by|to|至|到|/)\s*', re.I)
    def quantity(index):
        value, start, end = tokens[index]
        embedded = start and re.match(r'[A-Za-z0-9_]', text[start-1])
        dimension = index and joined.fullmatch(text[tokens[index-1][2]:start])
        return isinstance(value, Decimal) and (not embedded or dimension)
    for index, (value, start, end) in enumerate(tokens):
        if not quantity(index):
            continue
        unit = QUANTITY_UNIT.match(text, end)
        if unit is None and re.match(r'-bits?\b', text[end:], re.I):
            unit = QUANTITY_UNIT.match(text, end+1)
        if unit is None or unit.group(1) in ('位', '块'):
            continue
        label = unit.group(1).lower()
        label = UNITS.get(label, label)
        if label not in physical:
            continue
        values[index] = (value, label)
        previous = index-1
        while previous >= 0:
            prior, a, b = tokens[previous]
            if (not quantity(previous) or previous in values
                    or not joined.fullmatch(text[b:tokens[previous+1][1]])):
                break
            values[previous] = (prior, label)
            previous -= 1
    return Counter(values.values())


def repair_numeric_translation(source, translation):
    """Correct one unambiguous quantity difference; never rewrite model codes."""
    text, target = translation_numeric_tokens(source, translation)
    expected = _translation_numeric_values(source)
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


def validate_translation(source, translation, *, allow_reflow=False):
    from .text_integrity import validate_identifiers
    validate_identifiers(source, translation)
    if '```' in translation and '```' not in source:
        raise ValueError('译文包含说明或代码包装，请重新生成正文。')
    # Preserve factual tokens; Chinese units may be translated, values may not change.
    expected = _translation_numeric_values(source)
    actual = Counter(value for value, _, _ in translation_numeric_tokens(source, translation)[1])
    if expected != actual:
        def describe(values):
            def label(value):
                if isinstance(value,str) and value.startswith('ambiguous-date:'):return value.replace('ambiguous-date:','月日顺序待确认的日期 ')
                return value.replace('date:','日期 ') if isinstance(value,str) and value.startswith('date:') else str(value)
            return '、'.join(label(value)+(f'（{count}处）' if count>1 else '') for value,count in values.items()) or '无'
        raise ValueError('生成的英文与中文原稿存在数值差异，需要核对。'
            +' 原稿需保留：'+describe(expected-actual)+'；译文多出：'+describe(actual-expected)+'。')
    missing_units = quantity_units(source) - quantity_units(_written_quantity_digits(source,translation))
    if missing_units:
        required = '、'.join(f'{value} {unit}' for value, unit in missing_units)
        raise ValueError('译文未保留与原数值对应的单位，需要修正：'+required+'。')
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
        if allow_reflow:
            # PDF text layers frequently omit spaces between separate English
            # words. Accept only whitespace insertion: every original letter,
            # digit and punctuation mark must remain, in the same order.
            inner=r'\s*'.join(re.escape(char) for char in token)
            if any(token.endswith(a) for a in {'GPU','CPU','LED','LCD','OLED','API','SDK','IC','FPGA','PCB'}):
                inner+=r'(?:s|[’\']s)?'
            pattern=r'(?<![A-Za-z0-9])'+inner+r'(?![A-Za-z0-9])'
            # A storage quantity joined to a brand is two facts, not one model
            # code. English may put the brand before its capacity or in brackets.
            joined=re.fullmatch(r'(\d+(?:KB|MB|GB|TB|Kbit|Mbit|Gbit))([A-Z][a-z].*)',token)
            parts=list(joined.groups()) if joined else token.split('.') if '.' in token and not re.search(r'\d\.\d',token) else []
            if len(parts)>1:
                needed=len(re.findall(re.escape(token),source,re.I))
                if all(len(re.findall(r'(?<![A-Za-z0-9])'+r'\s*'.join(re.escape(c) for c in part)+r'(?![A-Za-z0-9])',translation,re.I))>=needed for part in parts if part):
                    continue
        if token in {'GPU','CPU','LED','LCD','OLED','API','SDK','IC','FPGA','PCB','PM'}:
            pattern=r'(?<![A-Za-z0-9])'+re.escape(token)+r'(?:s|[’\']s)?(?![A-Za-z0-9])'
        if len(re.findall(pattern, translation, re.I)) < len(re.findall(pattern, source, re.I)):
            raise ValueError(f'译文未保留原文中的型号或缩写 {token}，请重新生成。')
