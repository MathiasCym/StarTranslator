"""Document translation never consumes glossary choices; review owns them."""
from copy import copy
from .glossary.loader import Glossary


def without_glossary(references):
    glossary=Glossary([])
    glossary.document_translation=True
    if references is not None and hasattr(references,'glossary'):
        references=copy(references)
        references.glossary=glossary
    return glossary,references
