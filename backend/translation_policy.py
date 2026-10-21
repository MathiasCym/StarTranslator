"""File-specific validation on top of the shared factual-content checks.

PDF text layers may join English words that were separate on the page. Word
and PowerPoint retain real run boundaries and must keep strict identifiers.
Never select this policy from the output extension: a PDF exports as DOCX.
"""
from pathlib import Path
from .writing_policy import validate_translation


def validate_for_file(path, source, target):
    return validate_translation(source, target,
        allow_reflow=Path(path).suffix.lower() == '.pdf' if path else False)
