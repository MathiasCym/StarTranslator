"""Contain broken input references without inventing destinations or page numbers."""
import re
from zipfile import ZipFile
from lxml import etree

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
Q = '{'+W+'}'
ERROR = re.compile(r'(?:错误[!！]\s*(?:未定义书签|未找到引用源)[。.]?|Error!\s*(?:Bookmark not defined|Reference source not found)\.?)(?:\s*)$', re.I)
REFERENCE = re.compile(r'^\s*(PAGEREF|REF|NOTEREF)\s+("[^"]+"|[^\s\\]+)', re.I)


def printed_toc(text):
    """Only a numbered TOC row with leaders, not prose discussing this error."""
    error=ERROR.search(text)
    if not error or not re.match(r'^\s*\d+(?:\.\d+)*[.、)]?\s+\S',text):return text
    prefix=text[:error.start()]
    if not re.search(r'(?:\t|\.{4,}|…{2,}|·{4,})\s*$',prefix):return text
    return prefix+'—'


def warning(locator, target='', cached='', page=None, printed=False):
    return {'locator':locator,'slide':page,'text':cached or target,
        'reason':('原稿目录中已包含书签错误，保留目录标题并将无法确认的页码标为“—”；未编造目标或页码。'
                  if printed else '原稿引用的目标书签不存在，已锁定该失效引用并保留可用缓存，防止刷新成书签报错；缓存页码未重新核实，请确认原稿目录目标。')}


def _fields(root):
    stack=[];found=[]
    for node in root.iter():
        if node.tag==Q+'fldSimple':
            found.append((node,node.get(Q+'instr',''),list(node.iter(Q+'t'))))
        elif node.tag==Q+'fldChar':
            kind=node.get(Q+'fldCharType')
            if kind=='begin':stack.append({'node':node,'instruction':'','texts':[],'result':False})
            elif kind=='separate' and stack:stack[-1]['result']=True
            elif kind=='end' and stack:
                item=stack.pop();found.append((item['node'],item['instruction'],item['texts']))
        elif node.tag==Q+'instrText' and stack:stack[-1]['instruction']+=node.text or ''
        elif node.tag==Q+'t':
            for item in stack:
                if item['result']:item['texts'].append(node)
    return found


def _replace_tail(nodes, start, value):
    offset=0;inserted=False
    for node in nodes:
        text=node.text or '';end=offset+len(text)
        if end>start:
            keep=max(0,start-offset)
            node.text=text[:keep]+(value if not inserted else '')
            inserted=True
        offset=end


def protect_parts(parts):
    """Return only safe XML changes, plus non-fatal input-quality warnings."""
    parser=etree.XMLParser(resolve_entities=False,no_network=True,load_dtd=False)
    roots={name:etree.fromstring(raw,parser) for name,raw in parts.items()
           if name.startswith('word/') and name.endswith('.xml')}
    bookmarks={n.get(Q+'name') for root in roots.values() for n in root.iter(Q+'bookmarkStart')}
    changed={};warnings=[]
    for name,root in roots.items():
        dirty=False;field_nodes=set()
        for index,(begin,instruction,texts) in enumerate(_fields(root)):
            field_nodes.update(texts)
            match=REFERENCE.match(instruction)
            if not match:continue
            target=match[2].strip('"')
            if target in bookmarks:continue
            cached=''.join(n.text or '' for n in texts)
            paragraph=next((p for p in begin.iterancestors() if p.tag==Q+'p'),None)
            context=''.join(n.text or '' for n in paragraph.iter(Q+'t')) if paragraph is not None else cached
            warnings.append(warning(f'{name}/reference/{index}',target,context))
            for key,value in [('fldLock','true'),('dirty','false')]:
                if begin.get(Q+key)!=value:begin.set(Q+key,value);dirty=True
            # Never preserve an already baked error as the supposed page value.
            if ERROR.fullmatch(cached.strip()) and texts:
                _replace_tail(texts,0,'—');dirty=True
        for index,paragraph in enumerate(root.iter(Q+'p')):
            # Field results are handled above; never alter a valid live field.
            nodes=[n for n in paragraph.iter(Q+'t') if n not in field_nodes]
            if not nodes or any(n in field_nodes for n in paragraph.iter(Q+'t')):continue
            stream=[];positions=[];offset=0
            for node in paragraph.iter():
                if node.tag==Q+'t':positions.append((node,offset));stream.append(node.text or '');offset+=len(node.text or '')
                elif node.tag==Q+'tab':stream.append('\t');offset+=1
            text=''.join(stream);fixed=printed_toc(text)
            if fixed==text:continue
            error=ERROR.search(text);inserted=False
            for node,start in positions:
                value=node.text or ''
                if start+len(value)>error.start():
                    node.text=value[:max(0,error.start()-start)]+('—' if not inserted else '')
                    inserted=True
            warnings.append(warning(f'{name}/toc/{index}',cached=text,printed=True));dirty=True
        if dirty:changed[name]=etree.tostring(root,encoding='UTF-8',xml_declaration=True,standalone=True)
    return changed,warnings


def inspect_file(path):
    with ZipFile(path) as source:
        parts={name:source.read(name) for name in source.namelist() if name.startswith('word/') and name.endswith('.xml')}
    return protect_parts(parts)
