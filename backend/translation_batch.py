"""Bounded same-page requests; each returned paragraph is still validated separately."""
import json
from .llm.client import LLMUnavailable, LLMResponseInvalid, LLMTruncated
from .matcher.judge import _build_glossary_text
from .matcher.retriever import select_relevant_terms

MAX_ITEMS = 8
MAX_CHARACTERS = 1800


def batch_candidates(items, start, prepared, memory, cached=()):
    selected, size = [], 0
    for index, segment in items[start:]:
        text = segment.text
        if segment.locator in cached: break
        # Manual breaks/long paragraphs keep the established chunking path.
        if len(text) > 600 or any(c in text for c in '\n\v'):
            break
        if memory.counts[memory.key(segment, text)] > 1:
            break  # Let document memory own shared phrases, including failures.
        if len(selected) >= MAX_ITEMS or size + len(text) > MAX_CHARACTERS:
            break
        selected.append((index, segment, prepared[segment.locator]))
        size += len(text)
    return selected if len(selected) > 1 else []


def translate_batch(client, entries, glossary, references, segments, page_context, system):
    from .translation import check_cancel
    check_cancel(getattr(client, 'cancel', None))
    refs, terms, contexts, items = [], [], [], []
    def index_of(values,text):
        if text not in values:values.append(text)
        return values.index(text)
    for index,segment,groups in entries:
        # Preserve exactly the individual paragraph's glossary/reference recall.
        # Shared indexes remove duplicates without cutting later items' context.
        term=index_of(terms,_build_glossary_text(select_relevant_terms(segment.text,glossary,limit=24)))
        reference=index_of(refs,references.context(segment,segments.index(segment)) if references else '')
        context=index_of(contexts,page_context.prompt(segment))
        items.append({'id':str(index),'text':segment.text,'glossary_id':term,'reference_id':reference,'context_id':context,
            'runs':[{'id':group['id'],'text':group['text']} for group in groups]})
    prompt = ('【术语数据索引，从0开始】\n'+json.dumps(terms,ensure_ascii=False)+
        '\n【参考材料索引，从0开始】\n'+json.dumps(refs,ensure_ascii=False)+'\n'+
        '【各段版面语境索引，从0开始】\n'+json.dumps(contexts,ensure_ascii=False)+'\n【本批待译段落】\n'+json.dumps(items, ensure_ascii=False)+
        '\n每段 glossary_id、reference_id、context_id 对应上面的资料索引；量词与当前文本框关系只适用于对应段落。每个 id 必须独立翻译，不得合并、遗漏、交换或重复相邻段落的信息；保留各自的数字和样式。')
    if len(prompt)+len(system)>36000:return {}  # Keep the original individual path; never trim its data.
    instruction = ('\n【本次为批量请求，输出格式以此为准】只返回 '
        '{"items":[{"id":"原段落id","translation":"完整英文",'
        '"runs":[{"id":"原样式id","text":"对应英文片段"}]}]}。'
        '所有段落 id 各出现一次；每段 runs 拼接等于该段 translation。')
    try:
        result = client.chat_json(prompt, system=system+instruction, max_tokens=8000)
    except (LLMResponseInvalid, LLMTruncated):
        return {}  # Regenerate separately; partial batch JSON is never accepted.
    except LLMUnavailable as error:
        return {index: error for index, _, _ in entries}
    rows = result.get('items') if isinstance(result, dict) else None
    if not isinstance(rows, list):
        return {}
    expected = {str(index): index for index, _, _ in entries}
    found, duplicates = {}, set()
    for row in rows:
        if not isinstance(row, dict): continue
        key = row.get('id')
        if not isinstance(key, str) or key not in expected: continue
        if key in found: duplicates.add(key)
        found[key] = row
    # Missing/duplicate IDs fall back only at those paragraphs. Every accepted
    # item still passes residual/numeric/style checks in mapped_translation.
    return {expected[key]: row for key, row in found.items() if key not in duplicates}
