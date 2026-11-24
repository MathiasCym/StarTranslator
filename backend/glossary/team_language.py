"""Share maintained entries for one language over the bundled glossary."""
import copy

from . import catalog, language_pairs as pairs, store


DEFAULT = 'en-US'
NAMES = {DEFAULT: '英语', **pairs.LANGUAGES}


def supported(language):
    if not isinstance(language, str) or language not in NAMES:
        raise ValueError('团队词库仅支持英语、繁体中文、日语和韩语。')
    return language


def remote_path(language):
    return 'glossary/team.json' if language == DEFAULT else f'glossary/team-languages/{supported(language)}.json'


def validate(entries):
    if not isinstance(entries, list) or len(entries) > 20000:
        raise ValueError('团队语种维护记录须为列表，最多 20000 条。')
    result = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('团队术语条目格式不正确。')
        zh = entry.get('zh')
        english = entry.get('english', '')
        if not isinstance(zh, str) or not zh.strip() or len(zh) > 12000 or not isinstance(english, str) or len(english) > 12000:
            raise ValueError('团队术语的中文或英文参考格式不正确。')
        item = {'zh': zh.strip(), 'english': english.strip()}
        key = pairs.identity(item['zh'], item['english'])
        if key in seen:
            raise ValueError('团队术语有重复的中文及英文参考。')
        seen.add(key)
        if entry.get('deleted') is True:
            result.append({**item, 'deleted': True})
            continue
        for field in ('translation', 'note'):
            value = entry.get(field, '')
            if not isinstance(value, str) or len(value) > 12000:
                raise ValueError('团队术语的译法或备注格式不正确。')
            item[field] = value.strip()
        for field in pairs.LISTS:
            values = entry.get(field, [])
            if not isinstance(values, list) or len(values) > 100 or any(not isinstance(v, str) or len(v) > 300 for v in values):
                raise ValueError('团队术语的别名或错译格式不正确。')
            item[field] = list(dict.fromkeys(v.strip() for v in values if v.strip()))
        priority = entry.get('priority', 2)
        category = entry.get('category', 'term')
        if type(priority) is not int or priority not in (1, 2, 3) or category not in ('term', 'person'):
            raise ValueError('团队术语的确认状态或分类不正确。')
        result.append({**item, 'priority': priority, 'category': category})
    return result


def decode(language, value):
    if language == DEFAULT:
        return store.validate(value)
    if not isinstance(value, dict) or value.get('schema') != 1 or value.get('language') != language:
        raise ValueError('团队词库的语种或格式不匹配。')
    return validate(value.get('entries'))


def encode(language, entries):
    if language == DEFAULT:
        return store.validate(entries)
    return {'schema': 1, 'language': language, 'entries': validate(entries)}


def groups(entries):
    return {pairs.identity(item['zh'], item['english']): [copy.deepcopy(item)] for item in entries}


def snapshot(language):
    if language == DEFAULT:
        return store.read()
    with pairs.LOCK:
        source, reference, english, data, fingerprint = pairs.context(language)
        saved = pairs.records(data, source, language)
        bases = pairs.bases(reference, english['entries'], language)
        return {'path': source, 'fingerprint': fingerprint, 'entries': validate(list(saved.values())), 'bases': bases}


def common_ancestors(before, local, remote):
    """Compare two first-time overrides against their shared bundled term."""
    known = groups(before)
    ours = groups(local['entries'])
    theirs = groups(remote)
    found = []
    for key in (ours.keys() & theirs.keys()) - known.keys():
        if key in local['bases']:
            found.append(pairs.base_value(local['bases'][key]))
    return [*before, *validate(found)]


def save(language, entries, current):
    """Persist overrides while the caller holds the language-store write lock."""
    source, _, _, data, fingerprint = pairs.context(language)
    if source != current['path'] or fingerprint != current['fingerprint']:
        raise store.FileChanged('本机词库已变化，请重新获取差异。')
    update_data(language,entries,current,data)
    pairs.write_data(data)
    return snapshot(language)


def update_data(language, entries, current, data):
    source = current['path']
    old = pairs.records(data, source, language)
    bases = current['bases']
    output = {}
    for item in entries:
        key = pairs.identity(item['zh'], item['english'])
        previous = old.get(key)
        if previous and validate([previous])[0] == item:
            output[key] = previous
        elif item.get('deleted'):
            output[key] = item
        else:
            output[key] = {**item, 'source': '团队维护', 'baseline': bases.get(key, {}).get('official', [])}
    data['sources'].setdefault(source, {})[language] = output
