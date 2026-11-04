"""Canonical document-language identities; legacy Chinese/English policies stay intact."""

LANGUAGES = {'zh-CN':'简体中文', 'en-US':'英语', 'zh-Hant-TW':'繁体中文', 'ja-JP':'日语', 'ko':'韩语'}
LEGACY = {'zh-en':('zh-CN','en-US'), 'en-zh':('en-US','zh-CN')}
ALIASES = {'zh-TW':'zh-Hant-TW', 'zh-Hant':'zh-Hant-TW', 'ko-KR':'ko', 'zh':'zh-CN', 'en':'en-US'}
SUFFIXES = {'zh-CN':'Chinese', 'en-US':'English', 'zh-Hant-TW':'Traditional_Chinese', 'ja-JP':'Japanese', 'ko':'Korean'}


def canonical(code):
    return ALIASES.get(code,code) if isinstance(code,str) else code


def direction(src,dst):
    src,dst=canonical(src),canonical(dst)
    if not isinstance(src,str) or not isinstance(dst,str) or src not in LANGUAGES or dst not in LANGUAGES or src==dst:
        raise ValueError('请选择不同的文档源语言和目标语言。')
    return next((key for key,pair in LEGACY.items() if pair==(src,dst)),src+'>'+dst)


def pair(value='zh-en'):
    if not isinstance(value,str):raise ValueError('文档翻译方向不正确。')
    if value in LEGACY:return LEGACY[value]
    parts=value.split('>')
    if len(parts)!=2:raise ValueError('文档翻译方向不正确。')
    src,dst=map(canonical,parts);direction(src,dst)
    return src,dst


def normalize(data):
    """Accept old requests, explicit pairs and independent proofreading targets."""
    value=dict(data)
    if value.get('kind')=='check' and 'target_language' in value and 'source_language' not in value:
        dst=canonical(value['target_language'])
        if not isinstance(dst,str) or dst not in LANGUAGES:raise ValueError('请选择支持的校对语言。')
        src='en-US' if dst=='zh-CN' else 'zh-CN'
    elif 'source_language' in value or 'target_language' in value:
        src,dst=canonical(value.get('source_language')),canonical(value.get('target_language'))
    else:src,dst=pair(value.get('direction','zh-en'))
    value['direction']=direction(src,dst)
    # New language identity is already losslessly in direction. Retain old
    # history/cache shape for the two mature document policies.
    if value['direction'] not in LEGACY:
        value.update(source_language=src,target_language=dst)
    return value


def extended(value):
    return isinstance(value,str) and value not in LEGACY


def metadata():
    return {'languages':[{'code':code,'name':name} for code,name in LANGUAGES.items()],
            'workflows':['translate','check','translate_review','apply','save']}


def reference_identity():
    from .glossary.catalog import read
    from .checkpoints import digest
    return digest(read())
