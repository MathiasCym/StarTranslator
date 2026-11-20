"""Standalone translation is glossary-free; combined work shares review standards."""
from copy import copy
from .glossary.loader import Glossary
from contextlib import contextmanager
from contextvars import ContextVar

_mode=ContextVar('star_combined_document_policy',default=None)
REVIEW_SEVERITY=('只有能从原文指出的实质性漏译、事实或条件改变、明确未译正文、技术参数错误才设为 critical。'
    '正常的措辞、符号、等值数字或单位写法、语言中省略不定量词，以及无法证实的问题均为 minor，不应要求重译。'
    '编号与数值是两个语义单位，如①、②紧贴电压或尺寸也不能拼成一个数字。'
    '发现真实的数值、单位或日期错误时，按原文修正该处，保留其余正确译文。'
    '存在问题时附上 severity:"critical" 或 severity:"minor"；minor 直接保留现有译文。'
    '已要求核对目标字形或原样专名的，应同时返回原样片段的判断。')


def keep_minor_review(answer):
    if (isinstance(answer,dict) and type(answer.get('ok')) is bool and isinstance(answer.get('issues'),list)
            and answer.get('severity')=='minor'):
        return {**answer,'ok':True,'issues':[]}
    return answer


def preserve_values_without_source(before, after):
    """A standalone review has no original to justify a new numeric value."""
    from .writing_policy import numeric_values
    if numeric_values(before) != numeric_values(after):
        raise ValueError('缺少原文依据，校对建议不能改变已有数值。')

@contextmanager
def combined_processing(enabled):
    token=_mode.set({'enabled':bool(enabled),'reference':None})
    try:yield
    finally:_mode.reset(token)

def automatic():return bool((_mode.get() or {}).get('enabled'))

def reference():
    state=_mode.get()
    if not state or not state['enabled']:return {}
    if state['reference'] is None:
        from .glossary import catalog
        try:
            state['reference']=catalog.effective()
        except (OSError,ValueError):
            # Proofreading reports the unavailable catalog. Still produce a draft.
            state['reference']={}
    return state['reference']


def without_glossary(references):
    if automatic() and references is not None and hasattr(references,'glossary'):
        glossary=copy(references.glossary);glossary.document_translation=False
        references=copy(references);references.glossary=glossary
        reference()  # Freeze maintained standards before page workers start.
        return glossary,references
    glossary=Glossary([])
    glossary.document_translation=True
    if references is not None and hasattr(references,'glossary'):
        references=copy(references)
        references.glossary=glossary
    return glossary,references
