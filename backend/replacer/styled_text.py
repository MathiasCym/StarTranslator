"""Keep inline emphasis instead of flattening translations into the first run."""
from copy import deepcopy
from difflib import SequenceMatcher
import unicodedata
import re
from .text_runs import text_runs, BreakRun


class StyleMappingError(ValueError):
    """Valid translation content needs a separate inline-style mapping."""


def _style_key(rpr):
    if rpr is None:
        return ()
    # Proofing/language metadata creates extra runs without changing their look.
    ignored = {'lang', 'altLang', 'dirty', 'smtClean', 'smtId'}
    def node_key(node):
        attrs = tuple(sorted((name, value) for name, value in node.attrib.items()
                             if name.rsplit('}', 1)[-1] not in ignored))
        children = tuple(node_key(child) for child in node
                         if child.tag.rsplit('}', 1)[-1] not in {'lang', 'noProof'})
        return (node.tag, attrs, node.text or '', children)
    return node_key(rpr)


def style_groups(paragraph):
    groups = []
    leading = ''
    for run in text_runs(paragraph):
        if not run.text:
            continue
        if isinstance(run, BreakRun):
            if groups:
                groups[-1]['text'] += '\v'
            else:
                leading += '\v'
            continue
        rpr = next((c for c in run._r if c.tag.rsplit('}', 1)[-1] == 'rPr'), None)
        key = _style_key(rpr)
        if groups and groups[-1]['key'] == key:
            groups[-1]['text'] += run.text
        else:
            groups.append({'id': len(groups), 'text': leading + run.text, 'key': key, 'prototype': run})
            leading = ''
    return groups


def slice_groups(groups, start, end, visual_keys=False):
    result, offset = [], 0
    for group in groups:
        stop = offset + len(group['text'])
        text = group['text'][max(0, start-offset):max(0, min(stop, end)-offset)] if stop > start and offset < end else ''
        if text:
            result.append({'id': group['id'], 'text': text, **({'key': group['key']} if visual_keys else {})})
        offset = stop
    return result


def response_runs(result, text, groups):
    if not groups:
        raise StyleMappingError('原文样式不可定位。')
    if len(groups) == 1:
        return [{'id': groups[0]['id'], 'text': text}]
    runs = result.get('runs') if isinstance(result, dict) else None
    allowed = {g['id'] for g in groups}
    if not isinstance(runs, list) or not runs or len(runs) > 500:
        raise StyleMappingError('模型未返回文字样式对应关系。')
    for item in runs:
        if (not isinstance(item, dict) or type(item.get('id')) is not int or item['id'] not in allowed
                or not isinstance(item.get('text'), str)):
            raise StyleMappingError('模型返回的文字样式对应关系无效。')
    runs = [{'id': r['id'], 'text': r['text']} for r in runs]
    if ''.join(r['text'] for r in runs) != text:
        runs = _align_runs(runs, text)
    by_id = {g['id']: g for g in groups}
    # Repeated runs may share the same visual style. Require each distinct
    # meaningful style, not every incidental run ID created by PowerPoint.
    meaningful = {g.get('key', g['id']) for g in groups if any(c.isalnum() for c in g['text'])}
    used = {by_id[r['id']].get('key', r['id']) for r in runs if any(c.isalnum() for c in r['text'])}
    if not meaningful <= used:
        raise StyleMappingError('译文中的局部强调样式尚未对应。')
    labels=[r['id'] for r in runs for _ in r['text']]
    for a,b,label in _numeric_style_spans(text,groups):
        expected=by_id[label].get('key',label)
        if any(by_id[v].get('key',v)!=expected for v in labels[a:b]):
            raise StyleMappingError('换算后的数字必须保留原数字的字体、字号与强调样式。')
    return runs


def _numeric_style_spans(text,groups):
    """Only unambiguous numeric-only groups; Chinese scales compare by value."""
    from ..writing_policy import numeric_tokens
    normalized,target=numeric_tokens(text)
    if len(normalized)!=len(text):return []
    spans=[]
    for group in groups:
        source,values=numeric_tokens(group['text'])
        if not values:continue
        residue=source
        for _,a,b in reversed(values):residue=residue[:a]+residue[b:]
        if residue.strip(' \t\r\n\v,，.。%％+-–—()（）'):continue
        for value,_,_ in values:
            matches=[(a,b) for v,a,b in target if v==value]
            # A duplicated value in either language cannot safely identify emphasis.
            source_count=sum(v==value for g in groups for v,_,_ in numeric_tokens(g['text'])[1])
            if len(matches)==1 and source_count==1:
                a,b=matches[0];spans.append((a,b,group['id']))
    return spans


def _align_runs(runs, text):
    source = ''.join(r['text'] for r in runs)
    content = lambda s: ''.join(c for c in unicodedata.normalize('NFKC', s).casefold() if c.isalnum())
    if not source or content(source) != content(text):
        raise StyleMappingError('样式片段需要重新对应到完整译文。')
    labels = [r['id'] for r in runs for _ in r['text']]
    result = []
    def append(label, value):
        if not value:
            return
        if result and result[-1]['id'] == label:
            result[-1]['text'] += value
        else:
            result.append({'id': label, 'text': value})
    for op, a, b, c, d in SequenceMatcher(None, source, text, autojunk=False).get_opcodes():
        if op == 'equal':
            for offset, char in enumerate(text[c:d]):
                append(labels[a+offset], char)
        elif op != 'delete':
            append(labels[min(a, len(labels)-1)] if a < b else labels[max(0, a-1)], text[c:d])
    return result


def dominant_runs(text, groups):
    weights = {}
    counts = {}
    for group in groups:
        key = group.get('key', group['id'])
        weights[key] = weights.get(key, 0) + len(group['text'])
        counts[key] = counts.get(key, 0) + 1
    def ordinary(key):
        attrs = dict(key[1]) if isinstance(key,tuple) and len(key)>1 else {}
        return attrs.get('b','0') != '1' and attrs.get('u','none') in {'none','0'}
    candidates = [key for key in weights if ordinary(key)] or list(weights)
    key = max(candidates,key=lambda k:(counts[k],weights[k]))
    group = next(g for g in groups if g.get('key', g['id']) == key)
    return [{'id': group['id'], 'text': text}]


def anchored_runs(text, groups, glossary=None):
    """Restore only verifiable emphasis anchors; never color arbitrary words."""
    base = dominant_runs(text, groups)[0]['id']
    base_key = next(g.get('key', g['id']) for g in groups if g['id'] == base)
    labels, unresolved = [base] * len(text), False
    numeric_spans=_numeric_style_spans(text,groups)
    entries = getattr(glossary, 'entries', []) if glossary else []
    for group in groups:
        if group.get('key', group['id']) == base_key or not any(c.isalnum() for c in group['text']):
            continue
        source = group['text'].strip()
        anchors = [source] if source and not re.search(r'[\u3400-\u9fff]', source) else []
        for entry in entries:
            if entry.priority == 1 and entry.zh and entry.zh in source:
                anchors.extend([entry.en, *entry.variants])
        found = False
        for a,b,label in numeric_spans:
            if label==group['id'] and not any(v!=base for v in labels[a:b]):
                labels[a:b]=[label]*(b-a);found=True
        if found:continue
        for anchor in sorted(set(anchors), key=len, reverse=True):
            matches = list(re.finditer(r'(?<![A-Za-z0-9])' + re.escape(anchor) + r'(?![A-Za-z0-9])', text, re.I))
            if len(matches) != 1:
                continue
            a, b = matches[0].span()
            if any(label != base for label in labels[a:b]):
                continue
            labels[a:b] = [group['id']] * (b-a)
            found = True
            break
        unresolved |= not found
    result = []
    for label, char in zip(labels, text):
        if result and result[-1]['id'] == label:
            result[-1]['text'] += char
        else:
            result.append({'id':label, 'text':char})
    return result, unresolved


def best_effort_runs(text,groups,glossary=None):
    """Keep anchors first, then retain unplaced source styles on whole word spans.

    This final fallback never drops text, fonts, emphasis prototypes or numbers.
    Semantic mapping remains preferred; uncertain placement is recorded privately.
    """
    runs,unresolved=anchored_runs(text,groups,glossary)
    if not unresolved:return runs,False
    labels=[r['id'] for r in runs for _ in r['text']]
    by_id={g['id']:g for g in groups}
    base=dominant_runs(text,groups)[0]['id']
    used={by_id[v].get('key',v) for v,c in zip(labels,text) if c.isalnum()}
    source_total=sum(len(g['text']) for g in groups) or 1
    offset=0
    words=list(re.finditer(r'[A-Za-z]+(?:[-\u2019\'][A-Za-z]+)*',text))
    for group in groups:
        key=group.get('key',group['id']);length=len(group['text'])
        center=(offset+length/2)/source_total*len(text);offset+=length
        if key in used or not any(c.isalnum() for c in group['text']):continue
        available=[m for m in words if all(v==base for v in labels[m.start():m.end()])]
        if not available:continue
        word=min(available,key=lambda m:abs((m.start()+m.end())/2-center))
        labels[word.start():word.end()]=[group['id']]*(word.end()-word.start());used.add(key)
    result=[]
    for label,char in zip(labels,text):
        if result and result[-1]['id']==label:result[-1]['text']+=char
        else:result.append({'id':label,'text':char})
    return result,True


def write_styled(paragraph, groups, runs):
    templates = {g['id']: g['prototype'] for g in groups}
    old_runs = text_runs(paragraph)
    position = paragraph._p.index(old_runs[0]._r)
    for old in old_runs:
        paragraph._p.remove(old._r)
    for item in runs:
        if not item['text']:
            continue
        template = templates[item['id']]
        is_ppt = paragraph._p.tag == '{http://schemas.openxmlformats.org/drawingml/2006/main}p'
        for value in re.split(r'([\n\v])', item['text']) if is_ppt else [item['text']]:
            if not value:
                continue
            if is_ppt and value in {'\n', '\v'}:
                from pptx.oxml.xmlchemy import OxmlElement
                element = OxmlElement('a:br')
                rpr = next((c for c in template._r if c.tag.rsplit('}', 1)[-1] == 'rPr'), None)
                if rpr is not None:
                    element.append(deepcopy(rpr))
            else:
                element = deepcopy(template._r)
                new_run = type(template)(element, paragraph)
                new_run.text = value
            paragraph._p.insert(position, element)
            position += 1
