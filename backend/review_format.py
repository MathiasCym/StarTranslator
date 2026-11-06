"""Shared authored-format evidence for all document proofreading languages."""
import json
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path


def script_positions(groups):
    result=[];offset=0
    for group in groups:
        def find(node):
            if not isinstance(node,(tuple,list)) or len(node)!=4:return None
            tag,attributes,_,children=node
            if not isinstance(tag,str):return None
            attributes=dict(attributes)
            if 'baseline' in attributes and int(attributes['baseline']):return {'baseline':attributes['baseline']}
            if tag.rsplit('}',1)[-1]=='vertAlign':return {'vertical_align':next(iter(attributes.values()),'')}
            return next((value for child in children if (value:=find(child))),None)
        position=find(group.get('key'))
        if position:result.append({'start':offset,'end':offset+len(group['text']),'text':group['text'],**position})
        offset+=len(group['text'])
    return result


def attach(segments):
    """Read exact current Office paragraphs once; no document or cache writes."""
    from .extract.office import open_office
    from .replacer.styled_text import style_groups
    files={}
    for segment in segments:
        segment._script_positions=[]
        path=segment.file_path
        if path and Path(path).suffix.lower() in {'.docx','.pptx'}:files.setdefault(path,[]).append(segment)
    for path,members in files.items():
        if not Path(path).is_file():continue
        try:
            _,paragraphs,_=open_office(path)
            values={loc:(p.text,script_positions(style_groups(p))) for loc,p,*_ in paragraphs}
        except Exception:
            # Format evidence is optional for callers that already supply text.
            # Missing/unreadable packages cannot invalidate semantic review or
            # be treated as proof that a superscript is missing.
            continue
        for segment in members:
            text,positions=values.get(segment.locator,(None,[]))
            if text==segment.text:segment._script_positions=positions


def hints(segment):
    positions=getattr(segment,'_script_positions',[])
    if not positions:return {}
    return {'当前文字真实上下标':positions,'格式事实':'上下标已由文档字体样式实现，平面文本109可能显示为10的9次方。按给定位置判断，不得臆测丢失，也不要再换成Unicode上标重复改写；只提出仍然存在的真实问题。'}


def context(segment):
    data=hints(segment)
    return '\n【文档真实格式（非修改建议）】\n'+json.dumps(data,ensure_ascii=False) if data else ''


def normalize_suggestion(segment,old,new):
    """Remove only proven duplicate Unicode styling, never a genuine revision."""
    positions=getattr(segment,'_script_positions',[])
    if not positions or segment.text.count(old)!=1:return old,new
    source=segment.text;target=source.replace(old,new,1);styled={}
    for position in positions:
        direction=(1 if int(position.get('baseline',0))>0 else -1) if position.get('baseline') else (
            1 if position.get('vertical_align')=='superscript' else -1 if position.get('vertical_align')=='subscript' else 0)
        for offset in range(position['start'],position['end']):styled[offset]=direction
    edits=[]
    for op,a,b,c,d in SequenceMatcher(None,source,target,autojunk=False).get_opcodes():
        if op!='replace' or b-a!=d-c:continue
        for offset,(original,revised) in enumerate(zip(source[a:b],target[c:d])):
            direction=styled.get(a+offset,0);name=unicodedata.name(revised,'')
            if (direction and ('SUPERSCRIPT' in name if direction>0 else 'SUBSCRIPT' in name)
                    and unicodedata.normalize('NFKC',revised)==original):edits.append((c+offset,original))
    if not edits:return old,new
    characters=list(target)
    for index,value in edits:characters[index]=value
    corrected=''.join(characters)
    return (source,corrected) if corrected!=source else (source,source)
