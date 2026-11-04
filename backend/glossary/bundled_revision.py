"""Three-way official revisions; personal fields never become a second standard."""
import copy
from .bundled import key


def generated_only(entry):
    from ..models import GlossaryEntry
    from .store import generated_forms
    expected=generated_forms(GlossaryEntry(entry['zh'],entry['en']))
    return {key(v) for v in entry.get('machine_variants',[])}<={key(v) for v in expected}


def revise(entries,baseline,incoming,*,preserve_missing=False,previous_defaults=None):
    baseline=dict(baseline)
    for zh in incoming:
        if zh not in baseline and zh in (previous_defaults or {}):baseline[zh]=previous_defaults[zh]
    current={}
    for entry in entries:current.setdefault(key(entry['zh']),[]).append(entry)
    result=copy.deepcopy(entries)
    indexed={}
    for entry in result:indexed.setdefault(key(entry['zh']),[]).append(entry)
    report={'added':0,'updated':0,'removed':0,'merged':0,'preserved_deletions':0,'conflicts':[]}
    revised_pairs=set()
    for zh,candidates in incoming.items():
        existing=indexed.get(zh,[]);older=baseline.get(zh,[])
        if not existing:
            if older and (preserve_missing is True or isinstance(preserve_missing,set) and zh in preserve_missing):
                report['preserved_deletions']+=1;continue
            result.extend(copy.deepcopy(candidates));report['added']+=len(candidates);continue
        new_forms={key(e['en']) for e in candidates};old_forms={e['en'] for e in older}
        unchanged=old_forms=={e['en'] for e in candidates}
        for entry in existing:
            # A curated term that already differed from the old official file
            # is not a newly introduced conflict when the official value did
            # not change. Keep it; do not revive every historical disagreement.
            if unchanged:continue
            if len(candidates)==1 and entry['en'] in old_forms:
                new=candidates[0]
                if entry['en']!=new['en']:
                    entry['en']=new['en'];report['updated']+=1
                    revised_pairs.add((entry['zh'],entry['en']))
                if '公司官方术语库' in entry.get('source',''):
                    entry['source']=entry['source'].replace('公司官方术语库（英语）','公司官方术语库 TB（英语，2026-11-04）')
            elif key(entry['en']) not in new_forms and not new_forms.intersection(key(v) for v in entry.get('variants',[])):
                report['conflicts'].append({'zh':entry['zh'],'existing':[entry['en']],
                    'incoming':' / '.join(e['en'] for e in candidates),
                    'reason':'本机译法已被单独修改，保留个人版本；新版官方候选单独列出，未加入第二条标准。'})
    removed=set(baseline)-set(incoming)
    kept=[]
    for entry in result:
        zh=key(entry['zh'])
        if (zh in removed and entry['en'] in {e['en'] for e in baseline[zh]}
                and entry.get('source')=='公司官方术语库（英语）' and entry.get('priority',2)==1
                and not any(entry.get(k) for k in ('note','variants','wrong_variants')) and generated_only(entry)
                and entry.get('category','term')=='term'):
            report['removed']+=1
        else:kept.append(entry)
    # A new official spelling may converge with an already present standard.
    # Keep both provenances/notes/aliases in one row, rather than producing a
    # duplicate standard or discarding the other entry's personal fields.
    merged=[];seen={}
    for entry in kept:
        pair=(entry['zh'],entry['en'])
        previous=seen.get(pair)
        if previous is not None and pair in revised_pairs and previous.get('category','term')==entry.get('category','term'):
            combined=copy.deepcopy(previous)
            for field in ('variants','machine_variants','wrong_variants'):
                combined[field]=list(dict.fromkeys([*previous.get(field,[]),*entry.get(field,[])]))
            for field in ('note','source'):
                combined[field]=('\n\n' if field=='note' else '\n').join(dict.fromkeys(value for value in (previous.get(field,''),entry.get(field,'')) if value))
            combined['priority']=min(previous.get('priority',2),entry.get('priority',2))
            if max(len(combined.get(k,'')) for k in ('note','source'))<=12000 and all(len(combined.get(k,[]))<=100 for k in ('variants','machine_variants','wrong_variants')):
                previous.clear();previous.update(combined);report['merged']+=1;continue
            report['conflicts'].append({'zh':entry['zh'],'existing':[entry['en']],'incoming':entry['en'],
                'reason':'相同标准的备注或别名过长，未自动合并；两个原始记录均保留。'})
        merged.append(entry);seen.setdefault(pair,entry)
    return merged,report
