"""Context-bound bit-depth style, never packet counts, rates or identifiers."""
import re
from .models import Finding
from .extract.common import context_of

LABEL=re.compile(r'色深|位深|(?:colou?r|bit)\s+depth',re.I)
VALUE=re.compile(r'(?<![\w-])([1-9]\d?)[ \t]*bit(?![\w/-])',re.I)
VALUES=re.compile(r'^\s*\d{1,2}[ \t]*(?:-?[ \t]*bit)(?:\s*/\s*\d{1,2}[ \t]*(?:-?[ \t]*bit))*\s*$',re.I)

def is_depth_field(segment,segments):
    # Header and value must belong to the same table column.
    match=re.match(r'^(.*?/table/)(\d+)/(\d+)/',segment.locator)
    if match:
        prefix,row,column=match.groups()
        for other in segments:
            header=re.match(r'^(.*?/table/)(\d+)/(\d+)/',other.locator)
            if other.file_path==segment.file_path and header and header.group(1)==prefix and header.group(3)==column and int(header.group(2))<int(row) and LABEL.search(other.text):
                return True
        return False
    if VALUES.fullmatch(segment.text):
        neighbors=[s for s in segments if s.file_path==segment.file_path and s.slide==segment.slide]
        if segment.slide is None:
            if segment not in neighbors: return False
            index=neighbors.index(segment);neighbors=neighbors[max(0,index-2):index+1]
        return any(LABEL.search(s.text) for s in neighbors)
    return False

def replacements(text,segment,segments):
    field=is_depth_field(segment,segments)
    result=[]
    for match in VALUE.finditer(text):
        if int(match.group(1))>64: continue
        adjective=re.match(r'\s+(?:colou?r|alpha|input|output|signal|gr[ae]yscale|depth|video|RGB|per-channel)\b',text[match.end():],re.I)
        if field or adjective: result.append((match.start(),match.end(),match.group(1)+'-bit'))
    return result

def check(segments):
    result=[]
    for seg in segments:
        grouped={}
        for start,end,target in replacements(seg.text,seg,segments):
            if not is_depth_field(seg,segments):
                # The replacement engine changes every occurrence of found_text.
                # Include the modifier so a separate bit count is not caught too.
                adjective=re.match(r'\s+(?:colou?r|alpha|input|output|signal|gr[ae]yscale|depth|video|RGB|per-channel)\b',seg.text[end:],re.I)
                if adjective:
                    target+=adjective.group();end+=adjective.end()
            grouped.setdefault((seg.text[start:end],target),[]).append((start,end))
        for (found,target),matches in grouped.items():
            result.append(Finding(segment_id=seg.id,file=seg.file,file_path=seg.file_path,slide=seg.slide,para=seg.para,
                source=seg.source,found_text=found,suggested=target,concept_zh='位深参数格式',confidence='high',method='rule',
                reason='位深参数统一采用数字加连字符的写法，例如 8-bit、10-bit / 12-bit；不改变数值。',
                editable=seg.editable,not_editable_reason=seg.not_editable_reason,context=context_of(seg.text,found),occurrences=len(matches)))
    return result
