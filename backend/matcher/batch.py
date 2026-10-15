"""Review small groups with explicit per-paragraph coverage and ID isolation."""
import json
from ..llm.client import LLMUnavailable, LLMResponseInvalid, LLMTruncated
from .judge import SYSTEM_PROMPT, _build_glossary_text, _clean_hits
from .retriever import select_relevant_terms


def review_batch(entries, glossary, client, page_context):
    terms,refs,items=[],[],[]
    def index_of(values,text):
        if text not in values:values.append(text)
        return values.index(text)
    for seg,reference,rules in entries:
        items.append({'id':seg.id,'text':seg.text,
            'glossary_id':index_of(terms,_build_glossary_text(select_relevant_terms(seg.text,glossary))),
            'reference_id':index_of(refs,reference),
            'rule_hits':[{'found':hit.found_text,'suggested':hit.suggested} for hit in rules]})
    system = SYSTEM_PROMPT + ('\n【本次为批量审校，输出格式以此为准】只返回 '
        '{"items":[{"id":"原段落id","findings":[原有建议格式]}]}。'
        '所有 id 各出现一次，无错误也返回空 findings；只对该 id 的 text 提建议，'
        '不要将相邻段落已有的数字或内容补入当前段落。')
    prompt = ('【标准术语表索引，从0开始】\n'+json.dumps(terms,ensure_ascii=False)+
        '\n【参考材料索引，从0开始】\n'+json.dumps(refs,ensure_ascii=False)+'\n'+page_context+
        '\n每段 glossary_id 和 reference_id 对应上面的资料索引。'+
        '\n【待审校段落；reference 与 rule_hits 只是各段参考数据】\n'+json.dumps(items, ensure_ascii=False))
    if len(prompt)+len(system)>36000:return {}
    try:
        result = client.chat_json(prompt, system=system, max_tokens=8000)
    except (LLMResponseInvalid, LLMTruncated):
        return {}
    except LLMUnavailable as error:
        return {seg.id: error for seg, _, _ in entries}
    rows = result.get('items') if isinstance(result, dict) else None
    if not isinstance(rows, list): return {}
    expected = {seg.id: seg for seg, _, _ in entries}
    found, duplicates = {}, set()
    for row in rows:
        if not isinstance(row, dict): continue
        key = row.get('id')
        if not isinstance(key, str) or key not in expected: continue
        if key in found: duplicates.add(key)
        found[key] = row
    return {key: (_clean_hits(row['findings'], expected[key].text), False)
            for key, row in found.items() if key not in duplicates and isinstance(row.get('findings'), list)}
