"""Standalone translation is glossary-free; combined work shares review standards."""
from copy import copy
from .glossary.loader import Glossary
from contextlib import contextmanager
from contextvars import ContextVar

_mode=ContextVar('star_combined_document_policy',default=None)
REVIEW_SCOPE=('只检查适用的术语规范和格式，例如表格、标题、连接标点与明显破损的格式。'
    '普通正文的译义、数字、日期、单位、语法和表达不另做审校。只改命中的术语或格式，保留其他文字。'
    '保持链接目标、地址、代码和行内标记完整。')


def natural_writing(source):
    from .text_languages import humanizer_rules, natural_expression
    if not natural_expression(source):
        return ''
    return ('\n'+humanizer_rules()+
        '\n按 de-AI-writing 的保真原则在段内使用目标语言的自然语序和具体措辞。'
        '删去翻译时新增的空泛程度副词、讲义式过渡和重复收束，保留原稿口吻、时间、范围、推测、否定及确切信息。'
        '保持标题、段落、列表、表格、引用、刻意换行、代码和链接边界。只输出译文。')

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
