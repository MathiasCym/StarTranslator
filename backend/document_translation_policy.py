"""Standalone translation is glossary-free; combined work shares review standards."""
from copy import copy
from .glossary.loader import Glossary
from contextlib import contextmanager
from contextvars import ContextVar

_mode=ContextVar('star_combined_document_policy',default=None)

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
