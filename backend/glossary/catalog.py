"""Read-only multilingual reference; free text can use its supplied language pairs.

It remains independent of the editable bilingual glossary and document writers.
"""
import json
from pathlib import Path
from .loader import DEFAULT_PATH


def effective():
    """Local maintained standards for proofreading/free text only."""
    from .language_pairs import overlay
    return overlay(reference())


def reference():
    from .technical_usage import compose
    return compose(read())


def read():
    path = Path(DEFAULT_PATH).parent / 'multilingual.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as error:
        raise ValueError('多语言术语资料暂时无法读取；中英词库仍可正常使用。请检查安装完整性。') from error
    if not isinstance(data, dict) or data.get('schema') != 1 or data.get('readOnly') is not True or not isinstance(data.get('entries'), list):
        raise ValueError('多语言术语资料格式不正确；中英词库仍可正常使用。')
    return data


def merge_lookup(reference, additions):
    """Add imported reference cells without replacing supplied translations."""
    if not additions:
        return reference
    from .language_pairs import identity
    import copy
    from collections import Counter
    result = copy.deepcopy(reference)
    anchors = {}
    for row in result['entries']:
        terms = row['terms']
        anchors.setdefault(identity(terms.get('zh-CN',''),terms.get('en-US','')),row)
    for key, record in additions.items():
        row = anchors.get(key)
        if row is None:
            row = {'id':'imported-'+key,'terms':{'zh-CN':record['zh'],'en-US':record['english']},'source':'本机导入'}
            result['entries'].append(row)
        for code, value in record['terms'].items():
            if not row['terms'].get(code):
                row['terms'][code] = value
    counts = Counter(code for row in result['entries'] for code,value in row['terms'].items() if value)
    for language in result['languages']:
        language['count'] = counts[language['code']]
    return result


def lookup():
    from . import language_pairs as pairs
    reference = read()
    if not pairs.path().exists():
        return reference
    try:
        source = pairs.scope()
    except (ValueError, OSError):
        return reference
    imported = pairs.read_data().get('lookup',{}).get(source,{})
    return merge_lookup(reference,imported)
