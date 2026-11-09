"""Curated usage guidance is labelled separately from the official workbook.

No language cell in the original catalog is changed. Personal standards and
deletions are applied afterwards by language_pairs.overlay.
"""
import copy,json
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=1)
def read():
    data=json.loads((Path(__file__).resolve().parents[2]/'glossary/technical-usage.json').read_text('utf-8'))
    if data.get('schema')!=1:raise ValueError('技术参数使用说明格式无效。')
    return data

def compose(reference):
    result=copy.deepcopy(reference);data=read()
    notes={(r['zh'],r['en']):r for r in data['annotations']}
    for row in result.get('entries',[]):
        terms=row.get('terms',{});item=notes.get((terms.get('zh-CN'),terms.get('en-US')))
        if item:row['guidance']={'note':item['note'],'source':data['source']}
    identities={(r.get('terms',{}).get('zh-CN'),r.get('terms',{}).get('en-US')) for r in result.get('entries',[])}
    for row in data['entries']:
        anchor=(row['terms']['zh-CN'],row['terms']['en-US'])
        if anchor not in identities:result['entries'].append(copy.deepcopy(row));identities.add(anchor)
    return result
