"""English-to-Chinese equivalents; never alter shared Word/PDF/PPT writers."""
import re
from .text_integrity import prose


def fact_view(text):
    """Normalize explicit fiscal periods and N-in-M labels for comparison only."""
    # M is months only in an explicit fiscal results label, not a length/model.
    def fiscal(match):
        if re.search(r'(?:model|code|version|type|part|型号|代码)\s*[:：]?\s*$',text[max(0,match.start()-30):match.start()],re.I):
            return match[0]
        return match[1]+'个月 '+match[2]+'财年'
    text=re.sub(r'(?<![A-Za-z0-9])([1-9]\d?)M\s+FY\s*(\d{4})\b',fiscal,text,flags=re.I)
    text=re.sub(r'(?<![A-Za-z0-9])(\d+)\s*-\s*in\s*-\s*(\d+)(?![A-Za-z0-9])',r'\1合\2',text,flags=re.I)
    digits={char:str(number) for number,char in enumerate('零一二三四五六七八九')}
    text=re.sub(r'([一二三四五六七八九])合([一二三四五六七八九])',
        lambda m:digits[m[1]]+'合'+digits[m[2]],text)
    return text


def english_clauses(text):
    """Flag readable clauses, retaining names, product labels, units and URLs."""
    verbs={'is','are','was','were','has','have','had','can','will','must','should','shall',
        'does','did','supports','provides','includes','requires','contains','applies',
        'raised','organized','forwarded','reported','sent'}
    found=[]
    for match in re.finditer(r"[A-Za-z]+(?:[-'][A-Za-z]+)*(?:[ \t]+[A-Za-z]+(?:[-'][A-Za-z]+)*){3,}",prose(text)):
        words=re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*",match[0])
        lower=[w.lower() for w in words]
        if sum(w.islower() for w in words)>=2 and any(w in verbs for w in lower):
            found.append(match[0])
    return found
